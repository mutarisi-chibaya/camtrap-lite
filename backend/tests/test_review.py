from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import (
    Annotation,
    AnnotationSource,
    Camera,
    Detection,
    DetectionCategory,
    Event,
    Image,
    ImageStatus,
    TriageStatus,
)

T0 = datetime(2018, 1, 5, 6, 0, 0)


@pytest.fixture
def events(db: Session) -> list[Event]:
    """Three uncertain events (conf 0.5) and one confident one on a single camera."""
    cam = Camera(name="A01")
    db.add(cam)
    db.flush()
    out = []
    for n, conf in enumerate([0.5, 0.5, 0.5, 0.95]):
        ev = Event(camera_id=cam.id, start_time=T0 + timedelta(hours=n))
        db.add(ev)
        db.flush()
        for k in (1, 0):  # inserted out of time order on purpose
            img = Image(
                camera_id=cam.id,
                original_filename=f"{n}_{k}.jpg",
                storage_key=f"{n}_{k}",
                status=ImageStatus.processed,
                event_id=ev.id,
                timestamp=T0 + timedelta(hours=n, seconds=k),
                width=100,
                height=80,
            )
            img.detections.append(
                Detection(
                    category=DetectionCategory.animal,
                    confidence=conf,
                    bbox_x=0.1,
                    bbox_y=0.2,
                    bbox_w=0.3,
                    bbox_h=0.4,
                )
            )
            db.add(img)
        out.append(ev)
    db.flush()
    from app.services.triage import triage_events

    triage_events(db, out)
    db.commit()
    return out


def test_next_returns_uncertain_events_in_time_order(
    client: TestClient, events: list[Event]
) -> None:
    body = client.get("/review/next", params={"limit": 2}).json()
    assert body["remaining"] == 3
    assert [e["id"] for e in body["events"]] == [events[0].id, events[1].id]
    first = body["events"][0]
    assert first["camera_name"] == "A01"
    assert [i["original_filename"] for i in first["images"]] == ["0_0.jpg", "0_1.jpg"]
    det = first["images"][0]["detections"][0]
    assert det["bbox"] == [0.1, 0.2, 0.3, 0.4] and det["category"] == "animal"


def test_next_excludes_ids(client: TestClient, events: list[Event]) -> None:
    body = client.get("/review/next", params={"exclude": [events[0].id, events[1].id]}).json()
    assert [e["id"] for e in body["events"]] == [events[2].id]


def test_review_then_undo(client: TestClient, db: Session, events: list[Event]) -> None:
    ev = events[0]
    r = client.post(f"/review/{ev.id}", json={"label": "empty", "review_duration_ms": 1500})
    assert r.status_code == 200
    assert r.json() == {
        "event_id": ev.id,
        "triage_status": "reviewed",
        "label": "empty",
        "remaining": 2,
    }
    human = db.query(Annotation).filter_by(event_id=ev.id, source=AnnotationSource.human).one()
    assert (human.label, human.review_duration_ms) == ("empty", 1500)

    # Re-labelling replaces the previous human label.
    client.post(f"/review/{ev.id}", json={"label": "animal", "review_duration_ms": 900})
    assert db.query(Annotation).filter_by(event_id=ev.id).one().label == "animal"

    r = client.post(f"/review/{ev.id}/undo")
    assert r.json()["triage_status"] == "needs_review"
    assert r.json()["remaining"] == 3
    assert db.query(Annotation).filter_by(event_id=ev.id).count() == 0
    db.refresh(ev)
    assert ev.triage_status == TriageStatus.needs_review


def test_review_validation(client: TestClient, events: list[Event]) -> None:
    assert client.post("/review/9999", json={"label": "animal"}).status_code == 404
    assert client.post(f"/review/{events[0].id}", json={"label": "zebra"}).status_code == 422
    bad = {"label": "animal", "review_duration_ms": -1}
    assert client.post(f"/review/{events[0].id}", json=bad).status_code == 422
