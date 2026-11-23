"""Decide per event whether a human needs to look at it.

Only confident cases are automated. Everything in the uncertain middle band goes to a
human, because a wrongly auto-emptied animal is lost for good while a needless review
costs a second or two. AUTO_EMPTY_CONF is therefore set low (favour recall of animals)
and AUTO_ACCEPT_CONF high (favour precision of automatic labels).
"""

from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import (
    Annotation,
    AnnotationLabel,
    AnnotationSource,
    Detection,
    Event,
    Image,
    StaticCluster,
    StaticClusterStatus,
    TriageStatus,
)

AUTO_LABELS = {
    TriageStatus.auto_animal: AnnotationLabel.animal,
    TriageStatus.auto_empty: AnnotationLabel.empty,
    TriageStatus.auto_person: AnnotationLabel.person,
    TriageStatus.auto_vehicle: AnnotationLabel.vehicle,
}


@dataclass(frozen=True)
class TriageDet:
    category: str
    confidence: float
    confirmed_static: bool = False


@dataclass(frozen=True)
class TriageDecision:
    status: TriageStatus
    max_animal_conf: float | None


def decide(dets: list[TriageDet], accept_conf: float, empty_conf: float) -> TriageDecision:
    """Triage one event from all detections across its images.

    Detections in a human-confirmed static cluster are ignored. Person beats vehicle beats
    animal when several are confident: images of people matter most (privacy) and are the
    rarest, so they should never be hidden inside an "animal" event.
    """
    best: dict[str, float] = defaultdict(float)
    for d in dets:
        if not d.confirmed_static:
            best[d.category] = max(best[d.category], d.confidence)
    animal = best.get("animal")
    top = {c: best.get(c, 0.0) for c in ("animal", "person", "vehicle")}

    if top["person"] >= accept_conf:
        status = TriageStatus.auto_person
    elif top["vehicle"] >= accept_conf:
        status = TriageStatus.auto_vehicle
    elif top["animal"] >= accept_conf:
        status = TriageStatus.auto_animal
    elif max(top.values()) < empty_conf:
        status = TriageStatus.auto_empty
    else:
        status = TriageStatus.needs_review
    return TriageDecision(status, animal)


def triage_events(db: Session, events: list[Event]) -> None:
    """(Re)triage events. Human-reviewed events keep their status and annotations."""
    if not events:
        return
    s = get_settings()
    ids = [e.id for e in events]
    rows = db.execute(
        select(Image.event_id, Detection.category, Detection.confidence, StaticCluster.status)
        .join(Image, Detection.image_id == Image.id)
        .outerjoin(StaticCluster, Detection.static_cluster_id == StaticCluster.id)
        .where(Image.event_id.in_(ids))
    ).all()
    dets: dict[int, list[TriageDet]] = defaultdict(list)
    for event_id, category, conf, cluster_status in rows:
        dets[event_id].append(
            TriageDet(category.value, conf, cluster_status == StaticClusterStatus.confirmed_static)
        )

    open_ids = [e.id for e in events if e.triage_status != TriageStatus.reviewed]
    db.execute(
        delete(Annotation).where(
            Annotation.event_id.in_(open_ids), Annotation.source == AnnotationSource.ai
        )
    )
    for event in events:
        decision = decide(dets[event.id], s.auto_accept_conf, s.auto_empty_conf)
        event.max_animal_conf = decision.max_animal_conf
        if event.triage_status == TriageStatus.reviewed:
            continue
        event.triage_status = decision.status
        label = AUTO_LABELS.get(decision.status)
        if label is not None:
            db.add(Annotation(event_id=event.id, label=label, source=AnnotationSource.ai))
    db.flush()


def triage_camera(db: Session, camera_id: int) -> None:
    events = list(db.scalars(select(Event).where(Event.camera_id == camera_id)))
    triage_events(db, events)
