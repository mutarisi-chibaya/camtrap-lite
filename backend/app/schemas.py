"""Pydantic request/response schemas."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models import (
    AnnotationLabel,
    ImageStatus,
    StaticClusterStatus,
    TimestampSource,
    TriageStatus,
)


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


class DetectionOut(BaseModel):
    id: int
    category: str
    confidence: float
    bbox: tuple[float, float, float, float]  # normalised x, y, w, h
    is_static_candidate: bool
    is_masked: bool = False


class ReviewImage(BaseModel):
    id: int
    original_filename: str
    width: int | None
    height: int | None
    timestamp: datetime | None
    timestamp_source: TimestampSource
    detections: list[DetectionOut]


class ReviewEvent(BaseModel):
    id: int
    camera_id: int
    camera_name: str
    start_time: datetime | None
    end_time: datetime | None
    max_animal_conf: float | None
    images: list[ReviewImage]


class ReviewQueue(BaseModel):
    events: list[ReviewEvent]
    remaining: int  # all events still needing review (for the given camera filter)


class ReviewDecision(BaseModel):
    label: AnnotationLabel
    review_duration_ms: int | None = Field(default=None, ge=0)


class ReviewResult(BaseModel):
    event_id: int
    triage_status: TriageStatus
    label: AnnotationLabel | None
    remaining: int


class StaticSample(BaseModel):
    image_id: int
    detection_id: int
    bbox: tuple[float, float, float, float]
    confidence: float
    category: str
    timestamp: datetime | None
    width: int | None
    height: int | None


class StaticClusterOut(BaseModel):
    id: int
    camera_id: int
    camera_name: str
    bbox: tuple[float, float, float, float]  # representative box, normalised
    occurrence_count: int
    occurrence_fraction: float
    status: StaticClusterStatus
    samples: list[StaticSample]


class StaticClusterUpdate(BaseModel):
    status: StaticClusterStatus


class MaskCreate(BaseModel):
    name: str = Field(default="", max_length=200)
    polygon: list[tuple[float, float]] = Field(min_length=3, max_length=200)

    @field_validator("polygon")
    @classmethod
    def _normalised(cls, v: list[tuple[float, float]]) -> list[tuple[float, float]]:
        if any(not (0 <= x <= 1 and 0 <= y <= 1) for x, y in v):
            raise ValueError("polygon points must be normalised to 0-1")
        return v


class MaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    camera_id: int
    name: str
    polygon: list[tuple[float, float]]
    created_at: datetime


class CameraBox(BaseModel):
    image_id: int
    category: str
    confidence: float
    bbox: tuple[float, float, float, float]
    is_masked: bool
