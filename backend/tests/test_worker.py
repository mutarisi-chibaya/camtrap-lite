import io
from pathlib import Path
from typing import BinaryIO

from sqlalchemy.orm import Session, sessionmaker

from app.ml.detector import Detector
from app.ml.types import DetectionResult
from app.models import Camera, Detection, Image, ImageStatus
from app.queue import QueuedJob
from app.storage import LocalStorage
from worker.run import process_job


class FakeDetector(Detector):
    def detect(self, image: BinaryIO, image_id: str = "image") -> list[DetectionResult]:
        if image.read() == b"bad":
            raise ValueError("cannot decode")
        return [DetectionResult("animal", 0.9, (0.1, 0.1, 0.2, 0.2))]


def test_process_job_saves_detections_and_isolates_bad_images(
    db: Session, tmp_path: Path, monkeypatch
) -> None:
    calls: list[set[int]] = []
    monkeypatch.setattr("worker.run.finalize_cameras_if_done", lambda _db, ids: calls.append(ids))
    storage = LocalStorage(tmp_path)
    storage.put("good.jpg", io.BytesIO(b"good"))
    storage.put("bad.jpg", io.BytesIO(b"bad"))
    cam = Camera(name="c")
    db.add(cam)
    db.flush()
    good = Image(
        camera_id=cam.id, original_filename="g", storage_key="good.jpg", status=ImageStatus.queued
    )
    bad = Image(
        camera_id=cam.id, original_filename="b", storage_key="bad.jpg", status=ImageStatus.queued
    )
    missing = Image(
        camera_id=cam.id, original_filename="m", storage_key="nope.jpg", status=ImageStatus.queued
    )
    db.add_all([good, bad, missing])
    db.commit()

    job = QueuedJob(1, "detect", {"image_ids": [good.id, bad.id, missing.id]}, 1)
    sessions = sessionmaker(bind=db.get_bind(), expire_on_commit=False)
    assert process_job(job, FakeDetector(), storage, sessions) == 3

    for img in (good, bad, missing):
        db.refresh(img)
    assert good.status == ImageStatus.processed
    assert bad.status == ImageStatus.failed
    assert missing.status == ImageStatus.failed
    assert db.query(Detection).filter_by(image_id=good.id).count() == 1
    assert calls == [{cam.id}]
