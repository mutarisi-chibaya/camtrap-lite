from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import (
    Camera,
    Detection,
    DetectionCategory,
    Event,
    Image,
    ImageStatus,
    StaticCluster,
)
from app.services.masks import is_masked, point_in_polygon
from app.services.static import find_static_clusters
from app.services.triage import triage_camera

SQUARE = [(0.0, 0.6), (1.0, 0.6), (1.0, 1.0), (0.0, 1.0)]  # bottom 40 % of the frame
GRASS = (0.40, 0.75, 0.10, 0.08)  # box centre (0.45, 0.79): inside SQUARE
ANIMAL = (0.40, 0.20, 0.20, 0.30)  # centre (0.50, 0.35): outside


@pytest.mark.parametrize(
    ("x", "y", "inside"),
    [(0.5, 0.8, True), (0.5, 0.5, False), (1.2, 0.8, False), (0.01, 0.99, True)],
)
def test_point_in_polygon_square(x: float, y: float, inside: bool) -> None:
    assert point_in_polygon(x, y, SQUARE) is inside


def test_point_in_concave_polygon() -> None:
    # A "U" shape: the notch at the top middle is outside.
    u = [(0, 0), (0.3, 0), (0.3, 0.6), (0.7, 0.6), (0.7, 0), (1, 0), (1, 1), (0, 1)]
    assert point_in_polygon(0.1, 0.3, u)
    assert not point_in_polygon(0.5, 0.3, u)
    assert point_in_polygon(0.5, 0.8, u)


def test_is_masked_uses_box_centre() -> None:
    assert is_masked(GRASS, [SQUARE])
    assert not is_masked(ANIMAL, [SQUARE])
    # A box that mostly sticks out of the mask but has its centre inside is still masked.
    assert is_masked((0.0, 0.3, 0.2, 0.62), [SQUARE])
    assert not is_masked(GRASS, [])


@pytest.fixture
def camera(db: Session) -> Camera:
    """12 single-image events: grass fires at 0.85 in 6, a real animal (0.9) in 1."""
    cam = Camera(name="A02")
    db.add(cam)
    db.flush()
    for i in range(12):
        ev = Event(camera_id=cam.id, start_time=datetime(2018, 1, 1) + timedelta(hours=i))
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
        )
        box = GRASS if i < 6 else ANIMAL if i == 6 else None
        if box:
            x, y, w, h = box
            img.detections.append(
                Detection(
                    category=DetectionCategory.animal,
                    confidence=0.9 if i == 6 else 0.85,
                    bbox_x=x,
                    bbox_y=y,
                    bbox_w=w,
                    bbox_h=h,
                )
            )
        db.add(img)
    db.flush()
    find_static_clusters(db, cam.id)
    triage_camera(db, cam.id)
    db.commit()
    return cam


def _triage(db: Session) -> dict[str, int]:
    db.expire_all()
    out: dict[str, int] = {}
    for ev in db.query(Event):
        out[ev.triage_status.value] = out.get(ev.triage_status.value, 0) + 1
    return out


def test_mask_create_and_delete_retriage(client: TestClient, db: Session, camera: Camera) -> None:
    assert _triage(db) == {"auto_animal": 7, "auto_empty": 5}
    assert db.query(StaticCluster).count() == 1  # the grass also looks static

    r = client.post(
        f"/cameras/{camera.id}/masks", json={"name": "grass", "polygon": [list(p) for p in SQUARE]}
    )
    assert r.status_code == 201, r.text
    mask = r.json()
    assert mask["name"] == "grass" and len(mask["polygon"]) == 4
    assert _triage(db) == {"auto_animal": 1, "auto_empty": 11}
    assert db.query(StaticCluster).count() == 0  # masked boxes are not suggested as static

    boxes = client.get(f"/cameras/{camera.id}/boxes").json()
    assert sorted(b["is_masked"] for b in boxes) == [False] + [True] * 6
    assert client.get(f"/cameras/{camera.id}/masks").json()[0]["id"] == mask["id"]

    assert client.delete(f"/masks/{mask['id']}").status_code == 204
    assert _triage(db) == {"auto_animal": 7, "auto_empty": 5}
    assert client.get(f"/cameras/{camera.id}/masks").json() == []


def test_masked_detections_excluded_from_exports_and_flagged_in_review(
    client: TestClient, db: Session, camera: Camera
) -> None:
    client.post(f"/cameras/{camera.id}/masks", json={"polygon": [list(p) for p in SQUARE]})
    coco = client.get("/exports/coco").json()
    assert len(coco["annotations"]) == 1  # only the real animal

    # Put a masked box in an event that needs review and check the review payload flags it.
    ev = db.query(Event).first()
    assert ev is not None
    img = ev.images[0]
    img.detections.append(
        Detection(
            category=DetectionCategory.animal,
            confidence=0.5,
            bbox_x=0.4,
            bbox_y=0.2,
            bbox_w=0.2,
            bbox_h=0.3,
        )
    )
    db.flush()
    triage_camera(db, camera.id)
    db.commit()
    (event,) = client.get("/review/next").json()["events"]
    flags = {d["confidence"]: d["is_masked"] for d in event["images"][0]["detections"]}
    assert flags == {0.85: True, 0.5: False}


@pytest.mark.parametrize(
    "polygon",
    [
        [[0, 0], [1, 0]],  # fewer than 3 points
        [[0, 0], [1.5, 0], [1, 1]],  # outside 0-1
    ],
)
def test_mask_validation(client: TestClient, camera: Camera, polygon: list) -> None:
    r = client.post(f"/cameras/{camera.id}/masks", json={"polygon": polygon})
    assert r.status_code == 422


def test_not_found(client: TestClient, camera: Camera) -> None:
    assert client.post("/cameras/999/masks", json={"polygon": SQUARE}).status_code == 404
    assert client.delete("/masks/999").status_code == 404
    assert client.get("/cameras/999/images").status_code == 404


def test_camera_images(client: TestClient, camera: Camera) -> None:
    imgs = client.get(f"/cameras/{camera.id}/images", params={"limit": 5}).json()
    assert len(imgs) == 5 and imgs[0]["original_filename"] == "0.jpg"
