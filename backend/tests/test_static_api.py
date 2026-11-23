from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import (
    Annotation,
    Camera,
    Detection,
    DetectionCategory,
    Event,
    Image,
    ImageStatus,
    StaticCluster,
    TriageStatus,
)
from app.routers.static_clusters import SAMPLES
from app.services.static import find_static_clusters
from app.services.triage import triage_camera

T0 = datetime(2018, 1, 1)
ROCK = (0.4, 0.5, 0.1, 0.08)


def _setup(db: Session, n_rock: int = 12) -> tuple[Camera, StaticCluster]:
    """A camera where a 'rock' fires at 0.85 in n_rock single-image events."""
    cam = Camera(name="E01")
    db.add(cam)
    db.flush()
    for i in range(20):
        ev = Event(camera_id=cam.id, start_time=T0 + timedelta(hours=i))
        db.add(ev)
        db.flush()
        img = Image(
            camera_id=cam.id,
            original_filename=f"{i}.jpg",
            storage_key=str(i),
            status=ImageStatus.processed,
            event_id=ev.id,
            width=100,
            height=100,
            timestamp=T0 + timedelta(hours=i),
        )
        if i < n_rock:
            x, y, w, h = ROCK
            img.detections.append(
                Detection(
                    category=DetectionCategory.animal,
                    confidence=0.85,
                    bbox_x=x,
                    bbox_y=y,
                    bbox_w=w,
                    bbox_h=h,
                )
            )
        db.add(img)
    db.flush()
    (cluster,) = find_static_clusters(db, cam.id)
    triage_camera(db, cam.id)
    db.commit()
    return cam, cluster


def _counts(db: Session) -> dict[str, int]:
    out: dict[str, int] = {}
    for ev in db.query(Event):
        out[ev.triage_status.value] = out.get(ev.triage_status.value, 0) + 1
    return out


def test_list_clusters_with_spread_samples(client: TestClient, db: Session) -> None:
    cam, cluster = _setup(db)
    body = client.get("/static-clusters", params={"status": "pending"}).json()
    assert len(body) == 1
    c = body[0]
    assert (c["id"], c["camera_name"], c["occurrence_count"]) == (cluster.id, "E01", 12)
    assert c["bbox"] == list(ROCK)
    assert len(c["samples"]) == SAMPLES
    times = [s["timestamp"] for s in c["samples"]]
    assert times == sorted(times) and times[0] != times[1]
    assert client.get("/static-clusters", params={"status": "rejected"}).json() == []
    assert client.get("/static-clusters", params={"camera_id": cam.id + 1}).json() == []


def test_confirm_and_reject_retriage(client: TestClient, db: Session) -> None:
    _, cluster = _setup(db)
    assert _counts(db) == {"auto_animal": 12, "auto_empty": 8}

    r = client.post(f"/static-clusters/{cluster.id}", json={"status": "confirmed_static"})
    assert r.status_code == 200 and r.json()["status"] == "confirmed_static"
    db.expire_all()
    assert _counts(db) == {"auto_empty": 20}
    assert {a.label.value for a in db.query(Annotation)} == {"empty"}

    client.post(f"/static-clusters/{cluster.id}", json={"status": "rejected"})
    db.expire_all()
    assert _counts(db) == {"auto_animal": 12, "auto_empty": 8}


def test_confirm_keeps_human_reviews(client: TestClient, db: Session) -> None:
    _, cluster = _setup(db)
    ev = db.query(Event).filter_by(triage_status=TriageStatus.auto_animal).first()
    assert ev is not None
    client.post(f"/review/{ev.id}", json={"label": "animal", "review_duration_ms": 500})
    client.post(f"/static-clusters/{cluster.id}", json={"status": "confirmed_static"})
    db.expire_all()
    assert db.get_one(Event, ev.id).triage_status == TriageStatus.reviewed


def test_bad_requests(client: TestClient, db: Session) -> None:
    _, cluster = _setup(db)
    assert client.post("/static-clusters/999", json={"status": "rejected"}).status_code == 404
    assert (
        client.post(f"/static-clusters/{cluster.id}", json={"status": "maybe"}).status_code == 422
    )
