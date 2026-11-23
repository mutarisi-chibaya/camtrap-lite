"""OCR integration with a fake reader (no EasyOCR model needed)."""

import io
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from PIL import Image as PILImage
from sqlalchemy.orm import Session, sessionmaker

from app.ml.ocr import BannerReader, read_banner_timestamp, strips
from app.ml.types import DetectionResult
from app.models import Camera, Event, Image, ImageStatus, TimestampSource, TriageStatus
from app.queue import QueuedJob
from app.services.events import group_events, release_untimed_events
from app.services.ocr_fill import camera_check, fill_timestamp
from app.storage import LocalStorage
from tests.helpers import make_jpeg
from worker.run import process_job


class FakeReader(BannerReader):
    """Returns canned text per strip (bottom, then top) and counts calls."""

    def __init__(self, bottom: list[str], top: list[str] | None = None) -> None:
        self.texts = [bottom, top or []]
        self.calls = 0

    def read_strip(self, strip: PILImage.Image) -> list[str]:
        self.calls += 1
        return self.texts[(self.calls - 1) % 2]


def _camera(db: Session) -> Camera:
    cam = Camera(name="c")
    db.add(cam)
    db.flush()
    return cam


def test_strips_are_bottom_then_top() -> None:
    img = PILImage.new("RGB", (100, 200), (0, 0, 0))
    img.paste((255, 255, 255), (0, 180, 100, 200))  # white bottom band
    bottom, top = strips(img, 0.1)
    assert bottom.size == top.size == (100, 20)
    assert bottom.getpixel((5, 5)) == (255, 255, 255)
    assert top.getpixel((5, 5)) == (0, 0, 0)


def test_reads_top_strip_when_bottom_has_nothing() -> None:
    reader = FakeReader(["8a.pa6"], ["2018-01-05 06:00:00"])
    ts = read_banner_timestamp(reader, PILImage.new("RGB", (100, 100)))
    assert ts == datetime(2018, 1, 5, 6, 0, 0)
    assert reader.calls == 2


def test_fill_timestamp_and_camera_range(db: Session) -> None:
    cam = _camera(db)
    db.add(
        Image(
            camera_id=cam.id,
            original_filename="exif.jpg",
            storage_key="e",
            timestamp=datetime(2017, 12, 1),
            timestamp_source=TimestampSource.exif,
        )
    )
    img = Image(camera_id=cam.id, original_filename="x.jpg", storage_key="x")
    db.add(img)
    db.flush()

    assert camera_check(db, cam.id).camera_range == (datetime(2017, 12, 1), datetime(2017, 12, 1))
    # A reset camera clock (far outside the camera's range) is rejected.
    assert not fill_timestamp(db, FakeReader(["01/01/2016 00:00"]), img, make_jpeg())
    assert img.timestamp is None
    assert fill_timestamp(db, FakeReader(["12/9/2017 1:40 AM"]), img, make_jpeg())
    assert (img.timestamp, img.timestamp_source) == (datetime(2017, 12, 9, 1, 40), "ocr")
    # Images that already have a timestamp are never OCR'd again.
    assert not fill_timestamp(db, FakeReader(["12/9/2017 2:00 AM"]), img, make_jpeg())


def test_release_and_regroup_untimed_events(db: Session) -> None:
    cam = _camera(db)
    imgs = [
        Image(
            camera_id=cam.id,
            original_filename=f"{i}.jpg",
            storage_key=str(i),
            status=ImageStatus.processed,
        )
        for i in range(3)
    ]
    db.add_all(imgs)
    db.flush()
    assert len(group_events(db, cam.id)) == 3  # no timestamps: one event each
    reviewed = db.get_one(Event, imgs[2].event_id)
    reviewed.triage_status = TriageStatus.reviewed

    t0 = datetime(2018, 1, 5, 6, 0, 0)
    for i, img in enumerate(imgs):  # as if OCR filled them, 10 s apart
        img.timestamp = t0 + timedelta(seconds=10 * i)
        img.timestamp_source = TimestampSource.ocr
    assert release_untimed_events(db, cam.id) == 2  # the human-reviewed one is kept
    (event,) = group_events(db, cam.id)
    assert imgs[0].event_id == imgs[1].event_id == event.id
    assert imgs[2].event_id == reviewed.id
    assert (event.start_time, event.end_time) == (t0, t0 + timedelta(seconds=10))


class _Detector:
    def detect(self, image: object, image_id: str = "x") -> list[DetectionResult]:
        return [DetectionResult("animal", 0.9, (0.1, 0.1, 0.1, 0.1))]


def test_worker_ocrs_only_images_without_timestamp(
    db: Session, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("worker.run.finalize_cameras_if_done", lambda *_: None)
    storage = LocalStorage(tmp_path)
    storage.put("a.jpg", io.BytesIO(make_jpeg()))
    storage.put("b.jpg", io.BytesIO(make_jpeg()))
    cam = _camera(db)
    no_ts = Image(
        camera_id=cam.id, original_filename="a", storage_key="a.jpg", status=ImageStatus.queued
    )
    has_ts = Image(
        camera_id=cam.id,
        original_filename="b",
        storage_key="b.jpg",
        status=ImageStatus.queued,
        timestamp=datetime(2018, 1, 1),
        timestamp_source=TimestampSource.exif,
    )
    db.add_all([no_ts, has_ts])
    db.commit()

    reader = FakeReader(["1/2/2018 3:04 PM"])
    sessions = sessionmaker(bind=db.get_bind(), expire_on_commit=False)
    job = QueuedJob(1, "detect", {"image_ids": [no_ts.id, has_ts.id]}, 1)
    process_job(job, _Detector(), storage, sessions, ocr=lambda: reader)  # type: ignore[arg-type]

    db.expire_all()
    filled = db.get_one(Image, no_ts.id)
    assert (filled.timestamp, filled.timestamp_source) == (datetime(2018, 1, 2, 15, 4), "ocr")
    assert filled.status == ImageStatus.processed
    assert db.get_one(Image, has_ts.id).timestamp_source == TimestampSource.exif
    assert reader.calls == 1
