"""SQLAlchemy models.

Enums are stored as VARCHAR (``native_enum=False``) so the same
schema works on Postgres and SQLite. Bounding boxes are normalised 0-1, top-left
x/y plus width/height (MegaDetector convention).
"""

import enum
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Enum, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class TimestampSource(enum.StrEnum):
    exif = "exif"
    filename = "filename"
    missing = "missing"


class ImageStatus(enum.StrEnum):
    uploaded = "uploaded"
    queued = "queued"
    processed = "processed"
    failed = "failed"


class DetectionCategory(enum.StrEnum):
    animal = "animal"
    person = "person"
    vehicle = "vehicle"


class TriageStatus(enum.StrEnum):
    auto_animal = "auto_animal"
    auto_empty = "auto_empty"
    auto_person = "auto_person"
    auto_vehicle = "auto_vehicle"
    needs_review = "needs_review"
    reviewed = "reviewed"


class AnnotationLabel(enum.StrEnum):
    animal = "animal"
    empty = "empty"
    person = "person"
    vehicle = "vehicle"


class AnnotationSource(enum.StrEnum):
    ai = "ai"
    human = "human"


class StaticClusterStatus(enum.StrEnum):
    pending = "pending"
    confirmed_static = "confirmed_static"
    rejected = "rejected"


class JobType(enum.StrEnum):
    detect = "detect"


class JobStatus(enum.StrEnum):
    pending = "pending"
    running = "running"
    done = "done"
    failed = "failed"


def _enum(e: type[enum.Enum], name: str) -> Enum:
    return Enum(
        e,
        name=name,
        native_enum=False,
        length=32,
        values_callable=lambda x: [m.value for m in x],
    )


class Camera(Base):
    __tablename__ = "cameras"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    site_name: Mapped[str] = mapped_column(String(200), default="")
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)

    images: Mapped[list["Image"]] = relationship(back_populates="camera")


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(primary_key=True)
    camera_id: Mapped[int] = mapped_column(ForeignKey("cameras.id"), index=True)
    start_time: Mapped[datetime | None] = mapped_column(DateTime)
    end_time: Mapped[datetime | None] = mapped_column(DateTime)
    triage_status: Mapped[TriageStatus] = mapped_column(
        _enum(TriageStatus, "triage_status"), default=TriageStatus.needs_review, index=True
    )
    max_animal_conf: Mapped[float | None] = mapped_column(Float)

    images: Mapped[list["Image"]] = relationship(back_populates="event")
    annotations: Mapped[list["Annotation"]] = relationship(
        back_populates="event", cascade="all, delete-orphan"
    )


class Image(Base):
    __tablename__ = "images"

    id: Mapped[int] = mapped_column(primary_key=True)
    camera_id: Mapped[int] = mapped_column(ForeignKey("cameras.id"), index=True)
    original_filename: Mapped[str] = mapped_column(String(500))
    storage_key: Mapped[str] = mapped_column(String(500), unique=True)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    timestamp: Mapped[datetime | None] = mapped_column(DateTime)
    timestamp_source: Mapped[TimestampSource] = mapped_column(
        _enum(TimestampSource, "timestamp_source"), default=TimestampSource.missing
    )
    event_id: Mapped[int | None] = mapped_column(ForeignKey("events.id"), index=True)
    status: Mapped[ImageStatus] = mapped_column(
        _enum(ImageStatus, "image_status"), default=ImageStatus.uploaded, index=True
    )
    ground_truth_label: Mapped[str | None] = mapped_column(String(50))

    camera: Mapped[Camera] = relationship(back_populates="images")
    event: Mapped[Event | None] = relationship(back_populates="images")
    detections: Mapped[list["Detection"]] = relationship(
        back_populates="image", cascade="all, delete-orphan"
    )


class StaticCluster(Base):
    __tablename__ = "static_clusters"

    id: Mapped[int] = mapped_column(primary_key=True)
    camera_id: Mapped[int] = mapped_column(ForeignKey("cameras.id"), index=True)
    # Representative box, normalised (same convention as Detection).
    bbox_x: Mapped[float] = mapped_column(Float)
    bbox_y: Mapped[float] = mapped_column(Float)
    bbox_w: Mapped[float] = mapped_column(Float)
    bbox_h: Mapped[float] = mapped_column(Float)
    occurrence_count: Mapped[int] = mapped_column(Integer)
    occurrence_fraction: Mapped[float] = mapped_column(Float)
    status: Mapped[StaticClusterStatus] = mapped_column(
        _enum(StaticClusterStatus, "static_cluster_status"), default=StaticClusterStatus.pending
    )

    detections: Mapped[list["Detection"]] = relationship(back_populates="static_cluster")


class Detection(Base):
    __tablename__ = "detections"

    id: Mapped[int] = mapped_column(primary_key=True)
    image_id: Mapped[int] = mapped_column(ForeignKey("images.id"), index=True)
    category: Mapped[DetectionCategory] = mapped_column(
        _enum(DetectionCategory, "detection_category")
    )
    confidence: Mapped[float] = mapped_column(Float)
    bbox_x: Mapped[float] = mapped_column(Float)
    bbox_y: Mapped[float] = mapped_column(Float)
    bbox_w: Mapped[float] = mapped_column(Float)
    bbox_h: Mapped[float] = mapped_column(Float)
    is_static_candidate: Mapped[bool] = mapped_column(default=False)
    static_cluster_id: Mapped[int | None] = mapped_column(
        ForeignKey("static_clusters.id"), index=True
    )

    image: Mapped[Image] = relationship(back_populates="detections")
    static_cluster: Mapped[StaticCluster | None] = relationship(back_populates="detections")


class Annotation(Base):
    __tablename__ = "annotations"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), index=True)
    label: Mapped[AnnotationLabel] = mapped_column(_enum(AnnotationLabel, "annotation_label"))
    source: Mapped[AnnotationSource] = mapped_column(_enum(AnnotationSource, "annotation_source"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    review_duration_ms: Mapped[int | None] = mapped_column(Integer)

    event: Mapped[Event] = relationship(back_populates="annotations")


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[JobType] = mapped_column(_enum(JobType, "job_type"))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[JobStatus] = mapped_column(
        _enum(JobStatus, "job_status"), default=JobStatus.pending, index=True
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
