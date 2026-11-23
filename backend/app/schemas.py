"""Pydantic request/response schemas."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models import ImageStatus, TimestampSource


class CameraCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    site_name: str = ""
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)


class CameraOut(CameraCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    image_count: int = 0


class ImageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    camera_id: int
    original_filename: str
    width: int | None
    height: int | None
    timestamp: datetime | None
    timestamp_source: TimestampSource
    status: ImageStatus


class RejectedFile(BaseModel):
    filename: str
    reason: str


class UploadResult(BaseModel):
    images: list[ImageOut]
    rejected: list[RejectedFile]
    job_ids: list[int]


class Thresholds(BaseModel):
    event_gap_seconds: int
    auto_accept_conf: float
    auto_empty_conf: float
    static_min_conf: float
    static_iou: float
    static_min_fraction: float
    static_min_count: int


class ReviewStats(BaseModel):
    reviewed_events: int
    remaining_events: int
    median_review_ms: float | None
    # Derived from the median review time, so idle time between sessions doesn't count.
    events_per_minute: float | None


class Stats(BaseModel):
    cameras: int
    total_images: int
    images_by_status: dict[str, int]
    processing_progress: float  # 0-1, processed or failed / total
    total_events: int
    events_by_triage: dict[str, int]
    images_by_triage: dict[str, int]
    pct_images_auto_handled: float  # images in auto-triaged events: no human looked at them
    pct_events_auto_handled: float
    static_clusters_by_status: dict[str, int]
    review: ReviewStats
    thresholds: Thresholds
