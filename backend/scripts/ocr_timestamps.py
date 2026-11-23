"""Fill missing timestamps by OCR-reading the date banner, then regroup and re-triage.

    python scripts/ocr_timestamps.py                # all cameras
    python scripts/ocr_timestamps.py --camera 3
    python scripts/ocr_timestamps.py --compare 30   # accuracy check on images WITH EXIF

The worker already does this for new uploads without EXIF. This script covers images that
came in through the results importer, and `--compare` measures OCR accuracy against EXIF.
"""

import argparse
import logging
import random
import time

from PIL import Image as PILImage
from sqlalchemy import select

from app.config import get_settings
from app.db import SessionLocal
from app.ml.detector import gpu_available
from app.ml.ocr import EasyOcrBannerReader, read_banner_timestamp
from app.models import Image, ImageStatus, TimestampSource
from app.services.events import group_events, release_untimed_events
from app.services.ocr_fill import camera_check, fill_timestamp
from app.services.triage import triage_camera
from app.storage import get_storage


def compare(n: int) -> None:
    """OCR `n` images that have EXIF timestamps and report how often the two agree."""
    storage = get_storage()
    reader = EasyOcrBannerReader(gpu=gpu_available())
    with SessionLocal() as db:
        imgs = list(db.scalars(select(Image).where(Image.timestamp_source == TimestampSource.exif)))
        sample = random.Random(0).sample(imgs, min(n, len(imgs)))
        same_minute = within_2min = none = 0
        t0 = time.monotonic()
        for img in sample:
            with storage.open_read(img.storage_key) as fh, PILImage.open(fh) as pil:
                ts = read_banner_timestamp(reader, pil, camera_check(db, img.camera_id))
            if ts is None or img.timestamp is None:
                none += 1
                continue
            # Banners usually show minutes only, so compare to the minute.
            diff = abs((ts - img.timestamp.replace(second=0)).total_seconds())
            same_minute += diff < 60
            within_2min += diff <= 120
        per_image = (time.monotonic() - t0) / max(1, len(sample))
    wrong = len(sample) - within_2min - none
    print(
        f"OCR vs EXIF on {len(sample)} images: same minute {same_minute}, within 2 min "
        f"{within_2min}, no plausible timestamp {none}, wrong {wrong} ({per_image:.1f} s/image)"
    )


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--camera", type=int)
    p.add_argument("--compare", type=int, default=0, help="accuracy check on N EXIF images")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if args.compare:
        compare(args.compare)
        return
    if not get_settings().ocr_enabled:
        print("OCR_ENABLED is false")
        return

    storage = get_storage()
    reader = EasyOcrBannerReader(gpu=gpu_available())
    with SessionLocal() as db:
        q = select(Image).where(Image.timestamp.is_(None), Image.status == ImageStatus.processed)
        if args.camera is not None:
            q = q.where(Image.camera_id == args.camera)
        images = list(db.scalars(q))
        filled: set[int] = set()
        for img in images:
            with storage.open_read(img.storage_key) as fh:
                if fill_timestamp(db, reader, img, fh.read()):
                    filled.add(img.camera_id)
        db.flush()
        for cid in sorted(filled):
            released = release_untimed_events(db, cid)
            created = group_events(db, cid)
            triage_camera(db, cid)
            print(f"camera {cid}: regrouped {released} untimed events into {len(created)} events")
        db.commit()
        n_filled = sum(1 for i in images if i.timestamp is not None)
        print(f"OCR filled {n_filled} of {len(images)} images without a timestamp")


if __name__ == "__main__":
    main()
