"""End to end: import results -> events -> static -> triage -> /stats."""

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import (
    Annotation,
    AnnotationLabel,
    AnnotationSource,
    Camera,
    Event,
    Image,
    TriageStatus,
)
from app.services.md_import import import_md_results

T0 = datetime(2018, 1, 5, 6, 0, 0)


def test_pipeline_and_stats(client: TestClient, db: Session) -> None:
    cam = Camera(name="A01")
    db.add(cam)
    db.flush()
    # 4 events of 2 images each, 10 minutes apart; one image without a timestamp.
    files = []
    for e in range(4):
        for k in range(2):
            name = f"e{e}_{k}.jpg"
            files.append(name)
            db.add(
                Image(
                    camera_id=cam.id,
                    original_filename=name,
                    storage_key=name,
                    timestamp=T0 + timedelta(minutes=10 * e, seconds=5 * k),
                )
            )
    db.add(Image(camera_id=cam.id, original_filename="nots.jpg", storage_key="nots.jpg"))
    db.commit()

    confs = {"e0_0.jpg": 0.95, "e1_1.jpg": 0.5, "e2_0.jpg": 0.03}  # e3: person
    entries = []
    for name in files + ["nots.jpg"]:
        dets = []
        if name in confs:
            dets.append({"category": "1", "conf": confs[name], "bbox": [0.1, 0.1, 0.2, 0.2]})
        if name == "e3_0.jpg":
            dets.append({"category": "2", "conf": 0.9, "bbox": [0.5, 0.5, 0.1, 0.3]})
        entries.append({"file": name, "detections": dets})
    report = import_md_results(db, {"images": entries})
    assert report.finalized_cameras == [cam.id]

    status = {e.start_time: e.triage_status for e in db.query(Event)}
    assert status == {
        T0: TriageStatus.auto_animal,
        T0 + timedelta(minutes=10): TriageStatus.needs_review,
        T0 + timedelta(minutes=20): TriageStatus.auto_empty,
        T0 + timedelta(minutes=30): TriageStatus.auto_person,
        None: TriageStatus.auto_empty,
    }

    review_ev = db.query(Event).filter_by(triage_status=TriageStatus.needs_review).one()
    review_ev.triage_status = TriageStatus.reviewed
    db.add(
        Annotation(
            event_id=review_ev.id,
            label=AnnotationLabel.animal,
            source=AnnotationSource.human,
            review_duration_ms=2000,
        )
    )
    db.commit()

    s = client.get("/stats").json()
    assert s["total_images"] == 9
    assert s["processing_progress"] == 1.0
    assert s["total_events"] == 5
    assert s["events_by_triage"] == {
        "auto_animal": 1,
        "auto_empty": 2,
        "auto_person": 1,
        "reviewed": 1,
    }
    assert s["pct_images_auto_handled"] == pytest.approx(100 * 7 / 9)
    assert s["pct_events_auto_handled"] == 80.0
    assert s["review"] == {
        "reviewed_events": 1,
        "remaining_events": 0,
        "median_review_ms": 2000,
        "events_per_minute": 30.0,
    }
    assert s["thresholds"]["auto_accept_conf"] == 0.8

    assert client.get("/stats", params={"camera_id": cam.id + 1}).json()["total_images"] == 0
