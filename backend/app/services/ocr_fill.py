"""Fill missing timestamps from the printed banner (OCR), used by the worker and a script."""

import io
import logging

from PIL import Image as PILImage
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.ml.ocr import BannerReader, read_banner_timestamp
from app.models import Image, TimestampSource
from app.services.timestamp_ocr import OcrCheck

log = logging.getLogger(__name__)


def camera_check(db: Session, camera_id: int) -> OcrCheck:
    """Plausibility settings, including the time range of the camera's trusted timestamps."""
    s = get_settings()
    lo, hi = db.execute(
        select(func.min(Image.timestamp), func.max(Image.timestamp)).where(
            Image.camera_id == camera_id,
            Image.timestamp_source.in_([TimestampSource.exif, TimestampSource.filename]),
        )
    ).one()
    return OcrCheck(
        min_year=s.ocr_min_year,
        date_order=s.ocr_date_order,
        max_days_from_camera=s.ocr_max_days_from_camera,
        camera_range=(lo, hi) if lo is not None and hi is not None else None,
    )


def fill_timestamp(
    db: Session, reader: BannerReader, image: Image, data: bytes, check: OcrCheck | None = None
) -> bool:
    """OCR the banner of an image that has no timestamp. Returns True if one was set."""
    if image.timestamp is not None:
        return False
    with PILImage.open(io.BytesIO(data)) as img:
        ts = read_banner_timestamp(reader, img, check or camera_check(db, image.camera_id))
    if ts is None:
        log.info("image %s: no plausible banner timestamp", image.id)
        return False
    image.timestamp = ts
    image.timestamp_source = TimestampSource.ocr
    return True
