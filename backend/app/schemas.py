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
