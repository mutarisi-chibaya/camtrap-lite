"""Load the downloaded LILA subset into the app (one Camera per LILA location).

    python scripts/ingest_lila_subset.py                 # then import_md_results.py
    python scripts/ingest_lila_subset.py --enqueue       # or let the worker run MegaDetector

Reads `manifest.csv` written by download_lila_subset.py, ingests every image (EXIF
timestamp, size) and sets `ground_truth_label` for evaluation.
"""

import argparse
import csv
from pathlib import Path

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Camera, Image
from app.queue import DbQueue
from app.services.ingest import enqueue_detection, ingest_image
from app.storage import get_storage

DEFAULT_DIR = Path(__file__).resolve().parents[2] / "data" / "lila"


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--dir", type=Path, default=DEFAULT_DIR, help="download_lila_subset output")
    p.add_argument("--enqueue", action="store_true", help="queue detect jobs for the worker")
    p.add_argument("--limit", type=int, help="only ingest the first N images (CPU smoke test)")
    args = p.parse_args()

    with (args.dir / "manifest.csv").open(newline="") as f:
        rows = list(csv.DictReader(f))
    if args.limit:
        rows = rows[: args.limit]

    storage = get_storage()
    with SessionLocal() as db:
        existing = set(db.scalars(select(Image.original_filename)))
        cameras: dict[str, Camera] = {c.name: c for c in db.scalars(select(Camera))}
        new_images: list[Image] = []
        for row in rows:
            if row["file"] in existing:
                continue
            name = f"KAR {row['camera']}"
            if name not in cameras:
                cameras[name] = Camera(name=name, site_name=row["site"])
                db.add(cameras[name])
                db.flush()
            data = (args.dir / "images" / row["file"]).read_bytes()
            new_images.append(
                ingest_image(db, storage, cameras[name], row["file"], data, row["ground_truth"])
            )
        db.commit()
        print(
            f"ingested {len(new_images)} new images ({len(rows) - len(new_images)} already present)"
        )
        for c in sorted(cameras.values(), key=lambda c: c.id):
            print(f"  camera {c.id}: {c.name}")
        if args.enqueue:
            jobs = enqueue_detection(db, DbQueue(SessionLocal), new_images)
            print(f"enqueued {len(jobs)} detect jobs")


if __name__ == "__main__":
    main()
