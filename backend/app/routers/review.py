"""Human review of uncertain events.

The frontend keeps a local queue and prefetches the next few events, so `GET /review/next`
takes `exclude` (ids already queued or with a decision still in flight) instead of
relying on server-side cursors.
"""

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, selectinload

from app.db import DbSession
from app.deps import WriteAuth
from app.models import (
    Annotation,
    AnnotationSource,
    Event,
    Image,
    TriageStatus,
)
from app.schemas import (
    DetectionOut,
    ReviewDecision,
    ReviewEvent,
    ReviewImage,
    ReviewQueue,
    ReviewResult,
)
from app.services.masks import Polygon, is_masked, load_masks
from app.services.triage import triage_events

router = APIRouter(prefix="/review", tags=["review"])


def _remaining(db: Session, camera_id: int | None = None) -> int:
    q = (
        select(func.count())
        .select_from(Event)
        .where(Event.triage_status == TriageStatus.needs_review)
    )
    if camera_id is not None:
        q = q.where(Event.camera_id == camera_id)
    return db.scalar(q) or 0


def _to_review_event(event: Event, polygons: list[Polygon]) -> ReviewEvent:
    images = sorted(event.images, key=lambda i: (i.timestamp is None, i.timestamp, i.id))
    return ReviewEvent(
        id=event.id,
        camera_id=event.camera_id,
        camera_name=images[0].camera.name if images else "",
        start_time=event.start_time,
        end_time=event.end_time,
        max_animal_conf=event.max_animal_conf,
        images=[
            ReviewImage(
                id=i.id,
                original_filename=i.original_filename,
                width=i.width,
                height=i.height,
                timestamp=i.timestamp,
                timestamp_source=i.timestamp_source,
                detections=[
                    DetectionOut(
                        id=d.id,
                        category=d.category.value,
                        confidence=d.confidence,
                        bbox=(d.bbox_x, d.bbox_y, d.bbox_w, d.bbox_h),
                        is_static_candidate=d.is_static_candidate,
                        is_masked=is_masked((d.bbox_x, d.bbox_y, d.bbox_w, d.bbox_h), polygons),
                    )
                    for d in sorted(i.detections, key=lambda d: -d.confidence)
                ],
            )
            for i in images
        ],
    )


@router.get("/next", response_model=ReviewQueue)
def next_events(
    db: DbSession,
    camera_id: int | None = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 5,
    exclude: Annotated[list[int] | None, Query()] = None,
) -> ReviewQueue:
    """The next events needing review, oldest first, with images and detections."""
    q = (
        select(Event)
        .where(Event.triage_status == TriageStatus.needs_review)
        .options(
            selectinload(Event.images).selectinload(Image.detections),
            selectinload(Event.images).selectinload(Image.camera),
        )
        .order_by(Event.camera_id, Event.start_time.is_(None), Event.start_time, Event.id)
        .limit(limit)
    )
    if camera_id is not None:
        q = q.where(Event.camera_id == camera_id)
    if exclude:
        q = q.where(Event.id.not_in(exclude))
    events = db.scalars(q).all()
    masks = load_masks(db, {e.camera_id for e in events})
    return ReviewQueue(
        events=[_to_review_event(e, masks.get(e.camera_id, [])) for e in events],
        remaining=_remaining(db, camera_id),
    )


def _get_event(db: Session, event_id: int) -> Event:
    event = db.get(Event, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="event not found")
    return event


@router.post("/{event_id}", response_model=ReviewResult, dependencies=[WriteAuth])
def review_event(
    event_id: int, body: ReviewDecision, db: DbSession, camera_id: int | None = None
) -> ReviewResult:
    """Record a human label. Re-labelling an already reviewed event replaces the old label."""
    event = _get_event(db, event_id)
    db.execute(
        delete(Annotation).where(
            Annotation.event_id == event_id, Annotation.source == AnnotationSource.human
        )
    )
    db.add(
        Annotation(
            event_id=event_id,
            label=body.label,
            source=AnnotationSource.human,
            review_duration_ms=body.review_duration_ms,
        )
    )
    event.triage_status = TriageStatus.reviewed
    db.commit()
    return ReviewResult(
        event_id=event_id,
        triage_status=event.triage_status,
        label=body.label,
        remaining=_remaining(db, camera_id),
    )


@router.post("/{event_id}/undo", response_model=ReviewResult, dependencies=[WriteAuth])
def undo_review(event_id: int, db: DbSession, camera_id: int | None = None) -> ReviewResult:
    """Remove the human label and re-triage the event (normally back to needs_review)."""
    event = _get_event(db, event_id)
    db.execute(
        delete(Annotation).where(
            Annotation.event_id == event_id, Annotation.source == AnnotationSource.human
        )
    )
    if event.triage_status == TriageStatus.reviewed:
        event.triage_status = TriageStatus.needs_review
    triage_events(db, [event])
    db.commit()
    return ReviewResult(
        event_id=event_id,
        triage_status=event.triage_status,
        label=None,
        remaining=_remaining(db, camera_id),
    )
