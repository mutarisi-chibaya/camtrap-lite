"""Test helpers: tiny in-memory JPEGs, optionally with an EXIF timestamp."""

import io
from datetime import datetime

from PIL import Image as PILImage

from app.services.ingest import EXIF_DATETIME_ORIGINAL, EXIF_IFD


def make_jpeg(size: tuple[int, int] = (64, 48), taken: datetime | None = None) -> bytes:
    img = PILImage.new("RGB", size, (90, 120, 60))
    exif = PILImage.Exif()
    if taken is not None:
        exif.get_ifd(EXIF_IFD)[EXIF_DATETIME_ORIGINAL] = taken.strftime("%Y:%m:%d %H:%M:%S")
    buf = io.BytesIO()
    img.save(buf, "JPEG", exif=exif.tobytes())
    return buf.getvalue()
