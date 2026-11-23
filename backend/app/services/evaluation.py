"""Evaluation against ground-truth labels (LILA data), as pure functions over plain rows.

Ground truth in Snapshot Safari is labelled per *sequence*, so a sequence marked "animal"
can contain frames where the animal has already left. Event-level metrics (an event is
non-empty if any of its images is) are therefore the fairer measure; image-level numbers
are reported alongside them.
"""

from collections import defaultdict
from dataclasses import dataclass
from statistics import median

from app.models import TriageStatus
from app.services.triage import TriageDet, decide

AUTO = {
    TriageStatus.auto_animal.value,
    TriageStatus.auto_empty.value,
    TriageStatus.auto_person.value,
    TriageStatus.auto_vehicle.value,
}


@dataclass(frozen=True)
class ImageRow:
    image_id: int
    event_id: int
    triage_status: str
    gt: str | None  # "empty" | "animal" | "person" | None (no ground truth)
    final_label: str | None  # human over AI; None while waiting for review
    label_source: str | None


def is_empty(label: str | None) -> bool | None:
    return None if label is None else label == "empty"


def ratio(num: int, den: int) -> float | None:
    return num / den if den else None


@dataclass
class EventRow:
    event_id: int
    triage_status: str
    gt_empty: bool | None  # None if no image has ground truth
    final_label: str | None
    n_images: int


def to_events(images: list[ImageRow]) -> list[EventRow]:
    by_event: dict[int, list[ImageRow]] = defaultdict(list)
    for r in images:
        by_event[r.event_id].append(r)
    events = []
    for event_id, rows in by_event.items():
        gts = [is_empty(r.gt) for r in rows if r.gt is not None]
        events.append(
            EventRow(
                event_id=event_id,
                triage_status=rows[0].triage_status,
                gt_empty=None if not gts else all(gts),
                final_label=rows[0].final_label,
                n_images=len(rows),
            )
        )
    return events


@dataclass
class TriageMetrics:
    n: int
    auto_handled: float | None  # share needing no human
    empty_precision: float | None  # of auto-emptied, share truly empty
    empty_recall: float | None  # of truly empty, share auto-emptied
    animals_lost: int  # truly non-empty but auto-emptied (the costly error)
    animals_total: int
    auto_animal_precision: float | None  # of auto-animal, share truly non-empty
    final_accuracy: float | None  # empty vs non-empty, final label vs GT, where both exist
    final_n: int


def triage_metrics(rows: list[tuple[str, bool | None, str | None, int]]) -> TriageMetrics:
    """rows: (triage_status, gt_empty, final_label, weight). Weight = 1 per unit counted."""
    total = sum(w for *_, w in rows)
    auto = sum(w for s, _, _, w in rows if s in AUTO)
    with_gt = [(s, g, f, w) for s, g, f, w in rows if g is not None]
    auto_empty = [(g, w) for s, g, _, w in with_gt if s == "auto_empty"]
    true_empty = sum(w for _, g, _, w in with_gt if g)
    non_empty = sum(w for _, g, _, w in with_gt if not g)
    auto_animal = [(g, w) for s, g, _, w in with_gt if s == "auto_animal"]
    judged = [(g, f, w) for _, g, f, w in with_gt if f is not None]
    return TriageMetrics(
        n=total,
        auto_handled=ratio(auto, total),
        empty_precision=ratio(sum(w for g, w in auto_empty if g), sum(w for _, w in auto_empty)),
        empty_recall=ratio(sum(w for g, w in auto_empty if g), true_empty),
        animals_lost=sum(w for g, w in auto_empty if not g),
        animals_total=non_empty,
        auto_animal_precision=ratio(
            sum(w for g, w in auto_animal if not g), sum(w for _, w in auto_animal)
        ),
        final_accuracy=ratio(
            sum(w for g, f, w in judged if g == (f == "empty")), sum(w for *_, w in judged)
        ),
        final_n=sum(w for *_, w in judged),
    )


def image_metrics(images: list[ImageRow]) -> TriageMetrics:
    return triage_metrics([(r.triage_status, is_empty(r.gt), r.final_label, 1) for r in images])


def event_metrics(events: list[EventRow]) -> TriageMetrics:
    return triage_metrics([(e.triage_status, e.gt_empty, e.final_label, 1) for e in events])


@dataclass
class ReviewMetrics:
    reviewed_events: int
    median_ms: float | None
    events_per_minute: float | None
    total_minutes: float
    human_accuracy: float | None  # human label (empty vs not) vs event ground truth
    human_n: int


def review_metrics(durations_ms: list[int], human_vs_gt: list[tuple[str, bool]]) -> ReviewMetrics:
    """`human_vs_gt`: (human label, gt_empty) per reviewed event that has ground truth."""
    med = median(durations_ms) if durations_ms else None
    return ReviewMetrics(
        reviewed_events=len(durations_ms),
        median_ms=med,
        events_per_minute=60_000 / med if med else None,
        total_minutes=sum(durations_ms) / 60_000,
        human_accuracy=ratio(
            sum((lbl == "empty") == g for lbl, g in human_vs_gt), len(human_vs_gt)
        ),
        human_n=len(human_vs_gt),
    )


@dataclass
class SweepRow:
    accept: float
    empty: float
    pct_images_auto: float | None
    animal_images_lost: int
    animal_events_lost: int
    wrong_auto_animal_events: int  # auto-animal events that are truly empty


def threshold_sweep(
    event_dets: dict[int, list[TriageDet]],
    events: list[EventRow],
    accepts: list[float],
    empties: list[float],
    gt_nonempty_images: dict[int, int],
) -> list[SweepRow]:
    """Re-run the triage rule offline for other thresholds, to show the trade-off.

    Uses the same `decide` function as production, so the table matches what the app
    would do with those settings (before any human review).
    """
    rows = []
    total_images = sum(e.n_images for e in events)
    for a in accepts:
        for t in empties:
            auto_images = lost_images = lost_events = wrong_animal = 0
            for e in events:
                status = decide(event_dets.get(e.event_id, []), a, t).status.value
                if status in AUTO:
                    auto_images += e.n_images
                if status == "auto_empty" and e.gt_empty is False:
                    lost_events += 1
                    lost_images += gt_nonempty_images.get(e.event_id, 0)
                if status == "auto_animal" and e.gt_empty is True:
                    wrong_animal += 1
            rows.append(
                SweepRow(
                    a, t, ratio(auto_images, total_images), lost_images, lost_events, wrong_animal
                )
            )
    return rows
