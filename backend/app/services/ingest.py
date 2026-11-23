"""Register uploaded image files: store them, read size + timestamp, create Image rows."""

import io
import re
import uuid
from datetime import datetime
from pathlib import PurePosixPath

from PIL import Image as PILImage
from PIL import UnidentifiedImageError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Camera, Image, ImageStatus, JobType, TimestampSource
from app.queue.base import JobQueue
from app.storage.base import Storage

EXIF_IFD = 0x8769
EXIF_DATETIME_ORIGINAL = 36867
EXIF_DATETIME_DIGITIZED = 36868
TIFF_DATETIME = 306

# e.g. 20171004_010144, 2017-10-04 01-01-44, 2017-10-04T01:01:44
_FILENAME_TS = re.compile(
    r"(?<!\d)(\d{4})[-_.]?(\d{2})[-_.]?(\d{2})[ _T-]?(\d{2})[-_.:]?(\d{2})[-_.:]?(\d{2})(?!\d)"
)
_MIN_YEAR, _MAX_YEAR = 1990, 2100


class InvalidImageError(ValueError):
    pass


def _parse_exif_datetime(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        ts = datetime.strptime(value.strip().rstrip("\x00"), "%Y:%m:%d %H:%M:%S")
    except ValueError:
        return None
    return ts if _MIN_YEAR <= ts.year <= _MAX_YEAR else None


def timestamp_from_exif(img: PILImage.Image) -> datetime | None:
    """Prefer DateTimeOriginal (shutter time); fall back to Digitized, then TIFF DateTime."""
    exif = img.getexif()
    sub = exif.get_ifd(EXIF_IFD)
    for value in (
        sub.get(EXIF_DATETIME_ORIGINAL),
        sub.get(EXIF_DATETIME_DIGITIZED),
        exif.get(TIFF_DATETIME),
    ):
        ts = _parse_exif_datetime(value)
        if ts is not None:
            return ts
    return None


def timestamp_from_filename(name: str) -> datetime | None:
    """Many camera/renaming tools embed the capture time in the filename."""
    m = _FILENAME_TS.search(PurePosixPath(name).name)
    if not m:
        return None
    try:
        ts = datetime(*(int(g) for g in m.groups()))
    except ValueError:  # e.g. month 13: not a timestamp after all
        return None
    return ts if _MIN_YEAR <= ts.year <= _MAX_YEAR else None


def read_image_info(
    data: bytes, filename: str
) -> tuple[int, int, datetime | None, TimestampSource]:
    """Return (width, height, timestamp, timestamp_source) for raw image bytes."""
    try:
        with PILImage.open(io.BytesIO(data)) as img:
            width, height = img.size
            ts = timestamp_from_exif(img)
    except (UnidentifiedImageError, OSError) as e:
        raise InvalidImageError(f"{filename}: not a readable image") from e
    if ts is not None:
        return width, height, ts, TimestampSource.exif
    ts = timestamp_from_filename(filename)
    if ts is not None:
        return width, height, ts, TimestampSource.filename
    return width, height, None, TimestampSource.missing


def _storage_key(camera_id: int, filename: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", PurePosixPath(filename.replace("\\", "/")).name)
    return f"cameras/{camera_id}/{uuid.uuid4().hex[:12]}_{safe}"


def ingest_image(
    db: Session,
    storage: Storage,
    camera: Camera,
    filename: str,
    data: bytes,
    ground_truth_label: str | None = None,
) -> Image:
    """Store one file and add (not commit) its Image row.

    `filename` is kept as given (it may be a relative path such as
    ``KAR_S1/A01/A01_R1/x.JPG``) so MegaDetector results files can be matched to it later.
    """
    width, height, ts, source = read_image_info(data, filename)
    key = _storage_key(camera.id, filename)
    storage.put(key, io.BytesIO(data))
    image = Image(
        camera_id=camera.id,
        original_filename=filename.replace("\\", "/"),
        storage_key=key,
        width=width,
        height=height,
        timestamp=ts,
        timestamp_source=source,
        status=ImageStatus.uploaded,
        ground_truth_label=ground_truth_label,
    )
    db.add(image)
    return image


def enqueue_detection(db: Session, queue: JobQueue, images: list[Image]) -> list[int]:
    """Create one `detect` job per BATCH_SIZE images and mark those images queued."""
    db.flush()
    batch_size = get_settings().batch_size
    job_ids = []
    for start in range(0, len(images), batch_size):
        batch = images[start : start + batch_size]
        for img in batch:
            img.status = ImageStatus.queued
        db.commit()
        job_ids.append(queue.enqueue(JobType.detect.value, {"image_ids": [i.id for i in batch]}))
    return job_ids
