"""Group a camera's images into trigger events.

Camera traps fire in bursts: one animal walking past produces several images seconds apart.
Reviewing per event instead of per image is what makes human review fast, and triage is
decided per event so one confident frame covers the blurry ones around it.
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Event, Image, ImageStatus, TriageStatus


@dataclass(frozen=True)
class TimedImage:
    id: int
    timestamp: datetime | None


def group_by_gap(images: list[TimedImage], gap_seconds: float) -> list[list[TimedImage]]:
    """Split images into events wherever consecutive timestamps are > `gap_seconds` apart.

    The gap is measured to the *previous* image, so a long burst with small gaps stays one
    event. Images without a timestamp can't be placed in time, so each becomes its own
    single-image event (the UI flags these).
    """
    timed = sorted(
        ((i.timestamp, i) for i in images if i.timestamp is not None), key=lambda t: (t[0], t[1].id)
    )
    groups: list[list[TimedImage]] = []
    prev_ts: datetime | None = None
    for ts, img in timed:
        if prev_ts is not None and (ts - prev_ts).total_seconds() <= gap_seconds:
            groups[-1].append(img)
        else:
            groups.append([img])
        prev_ts = ts
    untimed = sorted((i for i in images if i.timestamp is None), key=lambda i: i.id)
    groups.extend([i] for i in untimed)
    return groups


def group_events(db: Session, camera_id: int) -> list[Event]:
    """Create events for the camera's processed images that are not in an event yet.

    Grouping is incremental so it never discards events that already have human reviews.
    Trade-off: images uploaded later that fall inside an existing event's time window form
    a new event instead of joining the old one.
    """
    images = list(
        db.scalars(
            select(Image).where(
                Image.camera_id == camera_id,
                Image.status == ImageStatus.processed,
                Image.event_id.is_(None),
            )
        )
    )
    by_id = {i.id: i for i in images}
    groups = group_by_gap(
        [TimedImage(i.id, i.timestamp) for i in images], get_settings().event_gap_seconds
    )

    events = []
    for group in groups:
        event = Event(
            camera_id=camera_id,
            start_time=group[0].timestamp,
            end_time=group[-1].timestamp,
            triage_status=TriageStatus.needs_review,
        )
        db.add(event)
        db.flush()
        for member in group:
            by_id[member.id].event_id = event.id
        events.append(event)
    return events


def release_untimed_events(db: Session, camera_id: int) -> int:
    """Dissolve the camera's timestamp-less events that no human has reviewed.

    Used after OCR fills in timestamps: those images were single-image events only because
    their time was unknown. Their images are detached so `group_events` can regroup them.
    Returns the number of events removed.
    """
    events = list(
        db.scalars(
            select(Event).where(
                Event.camera_id == camera_id,
                Event.start_time.is_(None),
                Event.triage_status != TriageStatus.reviewed,
            )
        )
    )
    for event in events:
        for img in event.images:
            img.event_id = None
        db.delete(event)  # cascades to its AI annotations
    db.flush()
    return len(events)
