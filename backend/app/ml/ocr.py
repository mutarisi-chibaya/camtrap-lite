"""Read the date/time banner printed on camera-trap images. Only this module imports easyocr.

Uses EasyOCR's documented API: ``easyocr.Reader(["en"], gpu=...)`` and
``reader.readtext(np_image, detail=0, allowlist=...)``, which returns the recognised strings.
Only thin strips along the bottom and top edges are read; that is where cameras print the
banner, and OCR on a strip is much faster than on the whole frame.
"""

from abc import ABC, abstractmethod
from datetime import datetime

from PIL import Image as PILImage

from app.services.timestamp_ocr import OcrCheck, parse_banner

STRIP_FRACTION = 0.08
ALLOWLIST = "0123456789/:-.APMapm "


class BannerReader(ABC):
    @abstractmethod
    def read_strip(self, strip: PILImage.Image) -> list[str]:
        """OCR one image strip, returning the text fragments found."""


class EasyOcrBannerReader(BannerReader):
    def __init__(self, gpu: bool = False) -> None:
        import easyocr  # lazy: pulls in torch, and only the worker/scripts need it

        self._reader = easyocr.Reader(["en"], gpu=gpu, verbose=False)

    def read_strip(self, strip: PILImage.Image) -> list[str]:
        import numpy as np

        return list(self._reader.readtext(np.array(strip), detail=0, allowlist=ALLOWLIST))


def strips(img: PILImage.Image, fraction: float = STRIP_FRACTION) -> list[PILImage.Image]:
    """Bottom strip first (the most common banner position), then top."""
    w, h = img.size
    band = max(1, int(h * fraction))
    return [img.crop((0, h - band, w, h)), img.crop((0, 0, w, band))]


def read_banner_timestamp(
    reader: BannerReader, img: PILImage.Image, check: OcrCheck | None = None
) -> datetime | None:
    """The first plausible timestamp in the banner strips, or None."""
    rgb = img.convert("RGB")
    for strip in strips(rgb):
        ts = parse_banner(reader.read_strip(strip), check)
        if ts is not None:
            return ts
    return None
