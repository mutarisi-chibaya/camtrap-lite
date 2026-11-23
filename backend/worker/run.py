"""Detection worker: ``python -m worker.run``.

Loads MegaDetector once, then loops: claim a `detect` job -> read each image from
storage -> detect -> save detections (image becomes `processed`) -> when a camera has no
images left waiting, run event grouping / static finder / triage for it.

A job that raises is retried up to 3 times by the queue, then marked failed. Images that
cannot be decoded are marked `failed` individually so one bad file doesn't sink a batch.
"""

import argparse
import logging
import time

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.db import SessionLocal
from app.ml.detector import Detector, MegaDetector, gpu_available
from app.models import Image, ImageStatus
from app.queue import DbQueue, JobQueue, QueuedJob
from app.services.pipeline import finalize_cameras_if_done, save_detections
from app.storage import Storage, get_storage

log = logging.getLogger("worker")


def process_job(
    job: QueuedJob,
    detector: Detector,
    storage: Storage,
    sessions: sessionmaker[Session] = SessionLocal,
) -> int:
    """Run detection for one job's images. Returns the number of images processed."""
    image_ids = job.payload.get("image_ids", [])
    with sessions() as db:
        images = list(db.scalars(select(Image).where(Image.id.in_(image_ids))))
        for image in images:
            if image.status == ImageStatus.processed:
                continue  # already done in an earlier, partially failed attempt
            try:
                with storage.open_read(image.storage_key) as fh:
                    results = detector.detect(fh, image.original_filename)
            except (FileNotFoundError, OSError, ValueError) as e:
                log.warning("image %s failed: %s", image.id, e)
                image.status = ImageStatus.failed
                db.commit()
                continue
            save_detections(db, image, results)
            db.commit()  # per image, so progress is visible on the dashboard
        finalize_cameras_if_done(db, {i.camera_id for i in images})
    return len(images)


def run(queue: JobQueue, detector: Detector, storage: Storage, poll_seconds: float) -> None:
    total, started = 0, time.monotonic()
    while True:
        job = queue.claim()
        if job is None:
            time.sleep(poll_seconds)
            continue
        t0 = time.monotonic()
        try:
            n = process_job(job, detector, storage)
        except Exception as e:  # noqa: BLE001 - any failure goes back to the queue
            log.exception("job %s failed (attempt %s)", job.id, job.attempts)
            queue.fail(job.id, repr(e))
            continue
        queue.complete(job.id)
        total += n
        dt = time.monotonic() - t0
        log.info(
            "job %s: %d images in %.1fs (%.2f img/s; %.2f img/s overall, %d total)",
            job.id,
            n,
            dt,
            n / dt if dt else 0,
            total / (time.monotonic() - started),
            total,
        )


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        force=True,
    )


def main() -> None:
    p = argparse.ArgumentParser(description="CamTrap Lite detection worker")
    p.add_argument("--model", default="MDV5A", help="MegaDetector model name or .pt path")
    p.add_argument("--poll", type=float, default=2.0, help="seconds between empty polls")
    p.add_argument("--cpu", action="store_true", help="force CPU even if a GPU is available")
    args = p.parse_args()
    _configure_logging()

    settings = get_settings()
    log.info("loading %s (GPU available: %s)", args.model, gpu_available() and not args.cpu)
    detector = MegaDetector(args.model, settings.detection_min_conf, force_cpu=args.cpu)
    _configure_logging()  # megadetector adds its own root handlers on load; reset them
    log.info("model loaded; waiting for jobs")
    run(DbQueue(SessionLocal), detector, get_storage(), args.poll)


if __name__ == "__main__":
    main()
