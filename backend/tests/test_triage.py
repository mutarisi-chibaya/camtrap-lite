from datetime import datetime

import pytest
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
from app.services.triage import TriageDet, decide, triage_camera

ACCEPT, EMPTY = 0.80, 0.10


def _status(*dets: TriageDet) -> TriageStatus:
    return decide(list(dets), ACCEPT, EMPTY).status


@pytest.mark.parametrize(
    ("conf", "expected"),
    [
        (0.95, TriageStatus.auto_animal),
        (0.80, TriageStatus.auto_animal),  # boundary is inclusive
        (0.79, TriageStatus.needs_review),
        (0.10, TriageStatus.needs_review),  # not < AUTO_EMPTY_CONF
        (0.09, TriageStatus.auto_empty),
    ],
)
def test_animal_thresholds(conf: float, expected: TriageStatus) -> None:
    assert _status(TriageDet("animal", conf)) == expected


def test_no_detections_is_empty() -> None:
    d = decide([], ACCEPT, EMPTY)
    assert d.status == TriageStatus.auto_empty
    assert d.max_animal_conf is None


def test_uses_max_across_event_images() -> None:
    d = decide([TriageDet("animal", 0.3), TriageDet("animal", 0.85)], ACCEPT, EMPTY)
    assert d.status == TriageStatus.auto_animal
    assert d.max_animal_conf == 0.85


def test_uncertain_person_blocks_auto_empty() -> None:
    assert _status(TriageDet("animal", 0.02), TriageDet("person", 0.3)) == TriageStatus.needs_review
    assert _status(TriageDet("vehicle", 0.15)) == TriageStatus.needs_review


def test_confident_person_and_vehicle_are_auto_labelled() -> None:
    assert _status(TriageDet("person", 0.9)) == TriageStatus.auto_person
    assert _status(TriageDet("vehicle", 0.85)) == TriageStatus.auto_vehicle


def test_person_beats_animal_and_vehicle() -> None:
    dets = (TriageDet("animal", 0.99), TriageDet("vehicle", 0.9), TriageDet("person", 0.81))
    assert _status(*dets) == TriageStatus.auto_person


def test_confident_animal_with_uncertain_person_is_animal() -> None:
    assert _status(TriageDet("animal", 0.9), TriageDet("person", 0.4)) == TriageStatus.auto_animal


def test_confirmed_static_detections_are_ignored() -> None:
    rock = TriageDet("animal", 0.6, confirmed_static=True)
    assert _status(rock) == TriageStatus.auto_empty
    d = decide([rock, TriageDet("animal", 0.4)], ACCEPT, EMPTY)
    assert d.status == TriageStatus.needs_review
    assert d.max_animal_conf == 0.4


def _event_with(db: Session, conf: float, cluster: StaticCluster | None = None) -> Event:
    cam = db.query(Camera).first()
    if cam is None:
        cam = Camera(name="c")
        db.add(cam)
        db.flush()
    event = Event(camera_id=cam.id, start_time=datetime(2018, 1, 1))
    db.add(event)
    db.flush()
    img = Image(
        camera_id=cam.id,
        original_filename=f"e{event.id}",
        storage_key=f"e{event.id}",
        status=ImageStatus.processed,
        event_id=event.id,
    )
    img.detections.append(
        Detection(
            category=DetectionCategory.animal,
            confidence=conf,
            bbox_x=0.1,
            bbox_y=0.1,
            bbox_w=0.1,
            bbox_h=0.1,
            is_static_candidate=cluster is not None,
            static_cluster_id=cluster.id if cluster else None,
        )
    )
    db.add(img)
    db.flush()
    return event


def test_triage_camera_writes_status_and_ai_annotations(db: Session) -> None:
    sure, unsure = _event_with(db, 0.95), _event_with(db, 0.5)
    triage_camera(db, sure.camera_id)
    assert sure.triage_status == TriageStatus.auto_animal
    assert unsure.triage_status == TriageStatus.needs_review
    ann = db.query(Annotation).one()
    assert (ann.event_id, ann.label, ann.source) == (sure.id, "animal", "ai")

    triage_camera(db, sure.camera_id)  # idempotent: AI annotation replaced, not duplicated
    assert db.query(Annotation).count() == 1


def test_reviewed_events_are_left_alone(db: Session) -> None:
    ev = _event_with(db, 0.95)
    ev.triage_status = TriageStatus.reviewed
    db.add(Annotation(event_id=ev.id, label=AnnotationLabel.empty, source=AnnotationSource.human))
    db.flush()
    triage_camera(db, ev.camera_id)
    assert ev.triage_status == TriageStatus.reviewed
    assert [a.source for a in db.query(Annotation)] == ["human"]


def test_confirming_static_cluster_changes_triage(db: Session) -> None:
    cam = Camera(name="c")
    db.add(cam)
    db.flush()
    cluster = StaticCluster(
        camera_id=cam.id,
        bbox_x=0.1,
        bbox_y=0.1,
        bbox_w=0.1,
        bbox_h=0.1,
        occurrence_count=5,
        occurrence_fraction=0.5,
    )
    db.add(cluster)
    db.flush()
    ev = _event_with(db, 0.9, cluster)

    triage_camera(db, cam.id)
    assert ev.triage_status == TriageStatus.auto_animal  # pending: still counts

    cluster.status = StaticClusterStatus.confirmed_static
    db.flush()
    triage_camera(db, cam.id)
    assert ev.triage_status == TriageStatus.auto_empty
    assert db.query(Annotation).one().label == AnnotationLabel.empty
