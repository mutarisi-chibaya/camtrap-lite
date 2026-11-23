"""Importer tests with a tiny hand-written MegaDetector batch-output JSON."""

import pytest
from sqlalchemy.orm import Session

from app.models import Camera, Detection, Image, ImageStatus
from app.services import md_import

RESULTS = {
    "info": {"format_version": "1.3", "detector": "md_v5a.0.0.pt"},
    "detection_categories": {"1": "animal", "2": "person", "3": "vehicle"},
    "images": [
        {  # exact relative path
            "file": "KAR_S1/A01/A01_R1/IMG1.JPG",
            "detections": [
                {"category": "1", "conf": 0.93, "bbox": [0.1, 0.2, 0.3, 0.4]},
                {"category": "2", "conf": 0.40, "bbox": [0.5, 0.5, 0.1, 0.2]},
                {"category": "1", "conf": 0.01, "bbox": [0.0, 0.0, 0.1, 0.1]},  # dropped
            ],
        },
        # absolute Colab path -> suffix match
        {"file": "/content/images/KAR_S1/A01/A01_R1/IMG2.JPG", "detections": []},
        {"file": "IMG3.JPG", "failure": "Failure image access"},  # bare-name match
        {"file": "KAR_S1/A01/A01_R1/NOT_IN_DB.JPG", "detections": []},
    ],
}


@pytest.fixture
def images(db: Session) -> list[Image]:
    cam = Camera(name="A01", site_name="Karoo")
    db.add(cam)
    db.flush()
    imgs = [
        Image(
            camera_id=cam.id,
            original_filename=f"KAR_S1/A01/A01_R1/IMG{i}.JPG",
            storage_key=f"k{i}",
            status=ImageStatus.uploaded,
        )
        for i in (1, 2, 3)
    ]
    db.add_all(imgs)
    db.commit()
    return imgs


def test_import_saves_detections_and_reports_missing(
    db: Session, images: list[Image], monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[int] = []
    monkeypatch.setattr(md_import, "finalize_cameras_if_done", lambda _db, ids: calls.extend(ids))

    report = md_import.import_md_results(db, RESULTS)

    assert report.matched == 2
    assert report.failed == 1
    assert report.detections == 2
    assert report.missing_from_db == ["KAR_S1/A01/A01_R1/NOT_IN_DB.JPG"]
    assert [i.status for i in images] == [
        ImageStatus.processed,
        ImageStatus.processed,
        ImageStatus.failed,
    ]
    dets = db.query(Detection).order_by(Detection.confidence.desc()).all()
    assert [(d.category, d.confidence) for d in dets] == [("animal", 0.93), ("person", 0.40)]
    assert (dets[0].bbox_x, dets[0].bbox_y, dets[0].bbox_w, dets[0].bbox_h) == (0.1, 0.2, 0.3, 0.4)
    assert calls == [images[0].camera_id]


def test_reimport_replaces_detections(db: Session, images: list[Image]) -> None:
    md_import.import_md_results(db, RESULTS)
    md_import.import_md_results(db, RESULTS)
    assert db.query(Detection).count() == 2


def test_camera_finalized_only_when_all_images_done(db: Session, images: list[Image]) -> None:
    partial = {**RESULTS, "images": RESULTS["images"][:1]}
    assert md_import.import_md_results(db, partial).finalized_cameras == []
    assert md_import.import_md_results(db, RESULTS).finalized_cameras == [images[0].camera_id]


def test_camera_filter(db: Session, images: list[Image]) -> None:
    report = md_import.import_md_results(db, RESULTS, camera_id=images[0].camera_id + 1)
    assert report.matched == 0
    assert len(report.missing_from_db) == 4
