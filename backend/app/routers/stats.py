from statistics import median

from fastapi import APIRouter
from sqlalchemy import func, select

from app.config import get_settings
from app.db import DbSession
from app.models import (
    Annotation,
    AnnotationSource,
    Event,
    Image,
    ImageStatus,
    StaticCluster,
    TriageStatus,
)
from app.schemas import ReviewStats, Stats, Thresholds

router = APIRouter(prefix="/stats", tags=["stats"])

AUTO_STATUSES = (
    TriageStatus.auto_animal,
    TriageStatus.auto_empty,
    TriageStatus.auto_person,
    TriageStatus.auto_vehicle,
)


def _counts(db: DbSession, column, *where) -> dict[str, int]:  # type: ignore[no-untyped-def]
    rows = db.execute(select(column, func.count()).where(*where).group_by(column)).all()
    return {k.value if hasattr(k, "value") else str(k): n for k, n in rows}


@router.get("", response_model=Stats)
def get_stats(db: DbSession, camera_id: int | None = None) -> Stats:
    """Processing progress, triage outcomes, automation rate and review speed."""
    img_where = [Image.camera_id == camera_id] if camera_id is not None else []
    ev_where = [Event.camera_id == camera_id] if camera_id is not None else []

    images_by_status = _counts(db, Image.status, *img_where)
    events_by_triage = _counts(db, Event.triage_status, *ev_where)
    images_by_triage = dict(
        db.execute(
            select(Event.triage_status, func.count(Image.id))
            .join(Image, Image.event_id == Event.id)
            .where(*ev_where)
            .group_by(Event.triage_status)
        ).all()
    )
    total_images = sum(images_by_status.values())
    done = images_by_status.get(ImageStatus.processed, 0) + images_by_status.get(
        ImageStatus.failed, 0
    )
    images_in_events = sum(images_by_triage.values())
    auto_images = sum(images_by_triage.get(s, 0) for s in AUTO_STATUSES)
    total_events = sum(events_by_triage.values())
    auto_events = sum(events_by_triage.get(s.value, 0) for s in AUTO_STATUSES)

    durations = list(
        db.scalars(
            select(Annotation.review_duration_ms)
            .join(Event)
            .where(
                Annotation.source == AnnotationSource.human,
                Annotation.review_duration_ms.is_not(None),
                *ev_where,
            )
        )
    )
    median_ms = median(durations) if durations else None
    s = get_settings()

    return Stats(
        cameras=db.scalar(select(func.count(func.distinct(Image.camera_id))).where(*img_where))
        or 0,
        total_images=total_images,
        images_by_status=images_by_status,
        processing_progress=done / total_images if total_images else 0.0,
        total_events=total_events,
        events_by_triage=events_by_triage,
        images_by_triage={k.value: v for k, v in images_by_triage.items()},
        pct_images_auto_handled=100 * auto_images / images_in_events if images_in_events else 0.0,
        pct_events_auto_handled=100 * auto_events / total_events if total_events else 0.0,
        static_clusters_by_status=_counts(
            db,
            StaticCluster.status,
            *([StaticCluster.camera_id == camera_id] if camera_id is not None else []),
        ),
        review=ReviewStats(
            reviewed_events=events_by_triage.get(TriageStatus.reviewed.value, 0),
            remaining_events=events_by_triage.get(TriageStatus.needs_review.value, 0),
            median_review_ms=median_ms,
            events_per_minute=60_000 / median_ms if median_ms else None,
        ),
        thresholds=Thresholds(
            event_gap_seconds=s.event_gap_seconds,
            auto_accept_conf=s.auto_accept_conf,
            auto_empty_conf=s.auto_empty_conf,
            static_min_conf=s.static_min_conf,
            static_iou=s.static_iou,
            static_min_fraction=s.static_min_fraction,
            static_min_count=s.static_min_count,
        ),
    )
