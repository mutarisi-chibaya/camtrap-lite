"""Evaluate the pipeline against LILA ground truth and write docs/results.md.

    python scripts/evaluate.py                    # metrics + 10-image MegaDetector benchmark
    python scripts/evaluate.py --benchmark 0      # metrics only (no megadetector needed)

From the host (backend/ venv) against the docker-compose database, set
    DATABASE_URL=postgresql+psycopg://camtrap:camtrap@localhost:5432/camtrap
    STORAGE_DIR=../data/storage

Reports: share of images/events handled without a human, empty-filter precision/recall
(and how many real animals were auto-emptied), static clusters, human review speed and
accuracy, a threshold trade-off table, and detector throughput on this machine.
"""

import argparse
import os
import platform
import random
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import SessionLocal
from app.models import (
    Annotation,
    AnnotationSource,
    Camera,
    Detection,
    Event,
    Image,
    ImageStatus,
    StaticCluster,
    StaticClusterStatus,
)
from app.services.evaluation import (
    ImageRow,
    ReviewMetrics,
    SweepRow,
    TriageMetrics,
    event_metrics,
    image_metrics,
    is_empty,
    review_metrics,
    threshold_sweep,
    to_events,
)
from app.services.labels import final_labels
from app.services.triage import TriageDet
from app.storage import get_storage

DEFAULT_OUT = Path(__file__).resolve().parents[2] / "docs" / "results.md"


def pct(v: float | None, digits: int = 1) -> str:
    return "n/a" if v is None else f"{100 * v:.{digits}f}%"


def load_images(db: Session) -> list[ImageRow]:
    labels = final_labels(db)
    rows = db.execute(
        select(Image.id, Image.event_id, Event.triage_status, Image.ground_truth_label).join(
            Event, Image.event_id == Event.id
        )
    ).all()
    out = []
    for image_id, event_id, status, gt in rows:
        final = labels.get(event_id)
        out.append(
            ImageRow(
                image_id,
                event_id,
                status.value,
                gt,
                final.label if final else None,
                final.source if final else None,
            )
        )
    return out


def load_event_detections(db: Session) -> dict[int, list[TriageDet]]:
    rows = db.execute(
        select(Image.event_id, Detection.category, Detection.confidence, StaticCluster.status)
        .join(Image, Detection.image_id == Image.id)
        .outerjoin(StaticCluster, Detection.static_cluster_id == StaticCluster.id)
        .where(Image.event_id.is_not(None))
    ).all()
    out: dict[int, list[TriageDet]] = defaultdict(list)
    for event_id, cat, conf, cluster_status in rows:
        out[event_id].append(
            TriageDet(cat.value, conf, cluster_status == StaticClusterStatus.confirmed_static)
        )
    return out


def benchmark(db: Session, n: int) -> dict[str, str] | None:
    """Time MegaDetector on `n` stored images (after one warm-up image, model already loaded)."""
    try:
        from app.ml.detector import MegaDetector, gpu_available
    except ImportError:
        return None
    try:
        import megadetector  # noqa: F401
    except ImportError:
        print("megadetector not installed: skipping throughput benchmark")
        return None
    keys = list(db.scalars(select(Image.storage_key).where(Image.status == ImageStatus.processed)))
    if not keys:
        return None
    keys = random.Random(0).sample(keys, min(len(keys), n + 1))
    storage = get_storage()
    t0 = time.monotonic()
    detector = MegaDetector()
    load_s = time.monotonic() - t0
    with storage.open_read(keys[0]) as fh:  # warm-up
        detector.detect(fh)
    t0 = time.monotonic()
    for key in keys[1:]:
        with storage.open_read(key) as fh:
            detector.detect(fh)
    elapsed = time.monotonic() - t0
    gpu = gpu_available()
    device = "CPU"
    if gpu:
        import torch

        device = f"GPU ({torch.cuda.get_device_name(0)})"
    return {
        "images": str(len(keys) - 1),
        "seconds": f"{elapsed:.1f}",
        "images_per_sec": f"{(len(keys) - 1) / elapsed:.2f}",
        "sec_per_image": f"{elapsed / (len(keys) - 1):.2f}",
        "model_load_s": f"{load_s:.1f}",
        "device": device,
        "machine": f"{platform.processor() or platform.machine()}, {os.cpu_count()} logical CPUs, "
        f"{platform.system()} {platform.version()}",
    }


def triage_table(img: TriageMetrics, ev: TriageMetrics) -> list[str]:
    def row(name: str, a: str, b: str) -> str:
        return f"| {name} | {a} | {b} |"

    return [
        "| Metric | Images | Events |",
        "|---|---:|---:|",
        row("Total", str(img.n), str(ev.n)),
        row("Handled without a human", pct(img.auto_handled), pct(ev.auto_handled)),
        row("Empty filter precision", pct(img.empty_precision), pct(ev.empty_precision)),
        row("Empty filter recall", pct(img.empty_recall), pct(ev.empty_recall)),
        row(
            "**Real animals auto-emptied**",
            f"**{img.animals_lost} of {img.animals_total}**",
            f"**{ev.animals_lost} of {ev.animals_total}**",
        ),
        row("Auto-animal precision", pct(img.auto_animal_precision), pct(ev.auto_animal_precision)),
        row(
            "Final label accuracy (empty vs not)",
            f"{pct(img.final_accuracy)} (n={img.final_n})",
            f"{pct(ev.final_accuracy)} (n={ev.final_n})",
        ),
    ]


def sweep_table(rows: list[SweepRow], accept: float, empty: float) -> list[str]:
    out = [
        "| AUTO_ACCEPT_CONF | AUTO_EMPTY_CONF | Images auto-handled | Animal events auto-emptied "
        "(images) | Empty events auto-labelled animal |",
        "|---:|---:|---:|---:|---:|",
    ]
    for r in rows:
        current = " **(current)**" if (r.accept, r.empty) == (accept, empty) else ""
        out.append(
            f"| {r.accept:.2f} | {r.empty:.2f}{current} | {pct(r.pct_images_auto)} | "
            f"{r.animal_events_lost} ({r.animal_images_lost}) | {r.wrong_auto_animal_events} |"
        )
    return out


def review_lines(r: ReviewMetrics) -> list[str]:
    if r.reviewed_events == 0:
        return [
            "No human reviews recorded yet. Review the `needs_review` events on the Review page "
            "and re-run this script.",
        ]
    return [
        "| Metric | Value |",
        "|---|---:|",
        f"| Events reviewed by a human | {r.reviewed_events} |",
        f"| Median review time per event | {r.median_ms / 1000:.2f} s |" if r.median_ms else "",
        f"| Throughput (from median) | {r.events_per_minute:.1f} events/min |"
        if r.events_per_minute
        else "",
        f"| Total review time | {r.total_minutes:.1f} min |",
        f"| Human label vs ground truth (empty vs not) | {pct(r.human_accuracy)} (n={r.human_n}) |",
    ]


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    p.add_argument("--benchmark", type=int, default=10, help="images to time (0 = skip)")
    args = p.parse_args()
    s = get_settings()

    with SessionLocal() as db:
        images = load_images(db)
        events = to_events(images)
        img_m, ev_m = image_metrics(images), event_metrics(events)

        human = db.execute(
            select(Annotation.event_id, Annotation.label, Annotation.review_duration_ms).where(
                Annotation.source == AnnotationSource.human
            )
        ).all()
        gt_by_event = {e.event_id: e.gt_empty for e in events}
        rev = review_metrics(
            [ms for _, _, ms in human if ms is not None],
            [
                (lbl.value, gt_by_event[eid])
                for eid, lbl, _ in human
                if gt_by_event.get(eid) is not None
            ],
        )

        nonempty_imgs: dict[int, int] = Counter(
            r.event_id for r in images if is_empty(r.gt) is False
        )
        sweep = threshold_sweep(
            load_event_detections(db), events, [0.7, 0.8, 0.9], [0.05, 0.1, 0.2], nonempty_imgs
        )
        clusters = Counter(c.value for c in db.scalars(select(StaticCluster.status)))
        n_cameras = db.query(Camera).count()
        gt_counts = Counter(r.gt or "none" for r in images)
        bench = benchmark(db, args.benchmark) if args.benchmark > 0 else None

    lines = [
        "# Results",
        "",
        f"Generated by `scripts/evaluate.py` on {datetime.now():%Y-%m-%d %H:%M}.",
        "",
        f"**Data:** {len(images)} images, {len(events)} trigger events, {n_cameras} cameras from "
        f"Snapshot Karoo (LILA BC). Ground truth: "
        + ", ".join(f"{k} {v}" for k, v in sorted(gt_counts.items()))
        + " images (labels are per sequence).",
        "",
        f"**Thresholds:** auto-accept ≥ {s.auto_accept_conf}, auto-empty < {s.auto_empty_conf}, "
        f"event gap {s.event_gap_seconds} s, static IoU {s.static_iou}, "
        f"static share ≥ {s.static_min_fraction:.0%} and ≥ {s.static_min_count} images.",
        "",
        "## Triage vs ground truth",
        "",
        *triage_table(img_m, ev_m),
        "",
        "*Empty filter* = events auto-labelled empty. Precision: share of them that really are "
        "empty. Recall: share of all truly empty images/events it removed. *Real animals "
        "auto-emptied* is the error that matters most, since nobody ever looks at those images "
        "again. *Final label* uses the human label when there is one, otherwise the AI label.",
        "",
        "## Threshold trade-off",
        "",
        "The same triage rule re-run offline with other thresholds (before human review):",
        "",
        *sweep_table(sweep, s.auto_accept_conf, s.auto_empty_conf),
        "",
        "## Static false detections",
        "",
        f"Clusters found: {sum(clusters.values())} "
        f"(pending {clusters.get('pending', 0)}, confirmed static "
        f"{clusters.get('confirmed_static', 0)}, rejected {clusters.get('rejected', 0)}).",
        "",
        "## Human review",
        "",
        *[line for line in review_lines(rev) if line],
        "",
        "## Detector throughput",
        "",
    ]
    if bench:
        lines += [
            "| Metric | Value |",
            "|---|---:|",
            f"| Device | {bench['device']} |",
            f"| Machine | {bench['machine']} |",
            f"| Images timed | {bench['images']} |",
            f"| Throughput | {bench['images_per_sec']} images/s "
            f"({bench['sec_per_image']} s/image) |",
            f"| Model load (once per worker) | {bench['model_load_s']} s |",
        ]
    else:
        lines.append("Not measured in this run (`--benchmark 0` or megadetector not installed).")
    text = "\n".join(lines) + "\n"

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text, encoding="utf-8")
    sys.stdout.reconfigure(errors="replace")  # type: ignore[union-attr]  # Windows consoles
    print(text)
    print(f"written to {args.out}")


if __name__ == "__main__":
    main()
