"""Final per-event labels and the detections that count, shared by exports and evaluation."""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Annotation, AnnotationSource, Event


@dataclass(frozen=True)
class FinalLabel:
    label: str  # animal | empty | person | vehicle
    source: str  # human | ai


def final_labels(db: Session, camera_id: int | None = None) -> dict[int, FinalLabel]:
    """event_id -> final label. A human annotation always overrides the AI one.

    Events still waiting for review have no entry.
    """
    q = select(Annotation.event_id, Annotation.label, Annotation.source).join(Event)
    if camera_id is not None:
        q = q.where(Event.camera_id == camera_id)
    out: dict[int, FinalLabel] = {}
    for event_id, label, source in db.execute(q.order_by(Annotation.created_at, Annotation.id)):
        existing = out.get(event_id)
        if existing is None or source == AnnotationSource.human or existing.source != "human":
            out[event_id] = FinalLabel(label.value, source.value)
    return out
