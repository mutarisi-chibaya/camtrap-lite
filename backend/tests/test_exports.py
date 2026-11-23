import csv
import io
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import (
    Annotation,
    AnnotationLabel,
    AnnotationSource,
    Camera,
    Detection,
    DetectionCategory,
    Event,
    Image,
    ImageStatus,
    StaticCluster,
    StaticClusterStatus,
    TriageStatus,
)
from app.services.export_coco import to_pixel_bbox
from app.services.labels import final_labels


def test_to_pixel_bbox() -> None:
    assert to_pixel_bbox((0.1, 0.2, 0.3, 0.4), 2592, 2000) == [259.2, 400.0, 777.6, 800.0]
    assert to_pixel_bbox((0.0, 0.0, 1.0, 1.0), 640, 480) == [0.0, 0.0, 640.0, 480.0]
    # rounding to 2 decimals
    assert to_pixel_bbox((1 / 3, 1 / 3, 1 / 3, 1 / 3), 100, 100) == [33.33, 33.33, 33.33, 33.33]


def _det(cat: str, conf: float, cluster: StaticCluster | None = None) -> Detection:
    return Detection(
        category=DetectionCategory(cat),
        confidence=conf,
        bbox_x=0.1,
        bbox_y=0.2,
        bbox_w=0.3,
        bbox_h=0.4,
        static_cluster_id=cluster.id if cluster else None,
        is_static_candidate=cluster is not None,
    )


@pytest.fixture
def data(db: Session) -> dict[str, int]:
    """Three events: AI animal, AI animal overridden to empty by a human, needs review.

    Image a1 also has a low-confidence box and a box in a confirmed static cluster.
    """
    cam = Camera(name="A01", site_name="Karoo", latitude=-32.2, longitude=22.5)
    db.add(cam)
    db.flush()
    rock = StaticCluster(
        camera_id=cam.id,
        bbox_x=0.1,
        bbox_y=0.2,
        bbox_w=0.3,
        bbox_h=0.4,
        occurrence_count=5,
        occurrence_fraction=0.5,
        status=StaticClusterStatus.confirmed_static,
    )
    db.add(rock)
    db.flush()
    ids: dict[str, int] = {}
    for name, status in [
        ("ai", TriageStatus.auto_animal),
        ("human", TriageStatus.reviewed),
        ("open", TriageStatus.needs_review),
    ]:
        ev = Event(camera_id=cam.id, start_time=datetime(2018, 1, 1), triage_status=status)
        db.add(ev)
        db.flush()
        img = Image(
            camera_id=cam.id,
            original_filename=f"{name}.jpg",
            storage_key=name,
            width=2000,
            height=1000,
            status=ImageStatus.processed,
            event_id=ev.id,
            timestamp=datetime(2018, 1, 1, 6, 0, 0),
        )
        img.detections.append(_det("animal", 0.9))
        if name == "ai":
            img.detections += [_det("animal", 0.1), _det("animal", 0.95, rock)]
        db.add(img)
        db.flush()
        ids[name] = img.id
        ids[f"{name}_event"] = ev.id
    db.add(
        Annotation(
            event_id=ids["ai_event"], label=AnnotationLabel.animal, source=AnnotationSource.ai
        )
    )
    db.add(
        Annotation(
            event_id=ids["human_event"], label=AnnotationLabel.animal, source=AnnotationSource.ai
        )
    )
    db.add(
        Annotation(
            event_id=ids["human_event"],
            label=AnnotationLabel.empty,
            source=AnnotationSource.human,
            review_duration_ms=1200,
        )
    )
    db.add(
        Image(
            camera_id=cam.id,
            original_filename="queued.jpg",
            storage_key="q",
            status=ImageStatus.queued,
        )
    )
    db.commit()
    return ids


def test_human_label_overrides_ai(db: Session, data: dict[str, int]) -> None:
    labels = final_labels(db)
    assert labels[data["ai_event"]].label == "animal"
    assert labels[data["human_event"]] == labels[data["human_event"]].__class__("empty", "human")
    assert data["open_event"] not in labels


def test_csv_export(client: TestClient, data: dict[str, int]) -> None:
    r = client.get("/exports/csv")
    assert r.status_code == 200
    assert "attachment" in r.headers["content-disposition"]
    rows = {row["filename"]: row for row in csv.DictReader(io.StringIO(r.text))}
    assert len(rows) == 4

    ai = rows["ai.jpg"]
    assert (ai["camera"], ai["site"], ai["latitude"]) == ("A01", "Karoo", "-32.2")
    assert (ai["final_label"], ai["label_source"]) == ("animal", "ai")
    # 0.9 counts, 0.1 is below min_conf, the 0.95 box is a confirmed static rock
    assert ai["n_animal_detections"] == "1"
    assert ai["max_animal_confidence"] == "0.9000"
    assert ai["timestamp"] == "2018-01-01T06:00:00"

    assert (rows["human.jpg"]["final_label"], rows["human.jpg"]["label_source"]) == (
        "empty",
        "human",
    )
    assert rows["open.jpg"]["final_label"] == "" and rows["open.jpg"]["triage_status"] == (
        "needs_review"
    )
    assert rows["queued.jpg"]["event_id"] == "" and rows["queued.jpg"]["triage_status"] == "queued"

    lower = list(csv.DictReader(io.StringIO(client.get("/exports/csv?min_conf=0.05").text)))
    assert next(r for r in lower if r["filename"] == "ai.jpg")["n_animal_detections"] == "2"


def test_coco_export(client: TestClient, data: dict[str, int]) -> None:
    coco = client.get("/exports/coco").json()
    assert [c["name"] for c in coco["categories"]] == ["animal", "person", "vehicle"]
    assert len(coco["images"]) == 4
    by_image: dict[int, list[dict]] = {}
    for a in coco["annotations"]:
        by_image.setdefault(a["image_id"], []).append(a)

    # ai image: only the 0.9 box (0.1 below min_conf, 0.95 confirmed static)
    (ann,) = by_image[data["ai"]]
    assert ann["bbox"] == [200.0, 200.0, 600.0, 400.0]  # 2000 x 1000 px image
    assert ann["area"] == 240000.0
    assert ann["category_id"] == 1 and ann["score"] == 0.9
    # human said empty -> its boxes are false positives and are dropped
    assert data["human"] not in by_image
    # not reviewed yet -> boxes kept
    assert len(by_image[data["open"]]) == 1

    img = next(i for i in coco["images"] if i["id"] == data["human"])
    assert (img["final_label"], img["label_source"]) == ("empty", "human")
    assert (img["width"], img["height"], img["location"]) == (2000, 1000, "A01")


def test_export_camera_filter(client: TestClient, data: dict[str, int]) -> None:
    assert client.get("/exports/coco?camera_id=999").json()["images"] == []
    assert client.get("/exports/csv?camera_id=999").text.count("\n") == 1  # header only
