"""Turn OCR'd banner text into a capture time, rejecting impossible dates.

Most camera traps print the date and time in a banner along the top or bottom edge
(Karoo's Cuddeback cameras print "12/9/2017   1:40 AM"). When EXIF is missing, this is
the only time we have, but OCR is noisy and camera clocks get reset, so every candidate is
checked before it is used:

- it must be a real calendar date and time (month 1-12, hour 0-23, ...);
- it must not be in the future, or before OCR_MIN_YEAR (default 2000);
- if the camera has other timestamps, it must fall within OCR_MAX_DAYS_FROM_CAMERA days
  of their range. A banner from a camera whose clock reset to 2000-01-01 is rejected.

Ambiguous dates like 04/10/2017 are read in OCR_DATE_ORDER (MDY by default, as on most
US-made cameras); the other order is used only if the preferred one is not a real date.
"""

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

# Common OCR confusions inside numbers.
_DIGIT_FIXES = str.maketrans(
    {"O": "0", "o": "0", "D": "0", "I": "1", "l": "1", "|": "1", "S": "5", "B": "8", "Z": "2"}
)

_DATE = re.compile(r"(?<!\d)(\d{1,4})[/\-.](\d{1,2})[/\-.](\d{2,4})(?!\d)")
_TIME = re.compile(
    r"(?<!\d)(\d{1,2})[:.](\d{2})(?:[:.](\d{2}))?\s*([AaPp])?\.?\s*[Mm]?\.?(?![A-Za-z])"
)


@dataclass(frozen=True)
class OcrCheck:
    min_year: int = 2000
    date_order: str = "MDY"  # or "DMY"
    max_days_from_camera: int = 30
    camera_range: tuple[datetime, datetime] | None = None  # other timestamps of the camera
    now: datetime | None = None


def _fix_digits(token: str) -> str:
    """Apply digit fixes only inside number-like tokens, so 'AM'/'PM' survive."""
    return re.sub(r"[0-9OoDIl|SBZ:/\-.]{4,}", lambda m: m.group(0).translate(_DIGIT_FIXES), token)


def _year(y: str) -> int:
    v = int(y)
    return v + 2000 if len(y) == 2 else v


def _date_candidates(a: str, b: str, c: str, order: str) -> list[tuple[int, int, int]]:
    """(year, month, day) readings of a date match, preferred order first."""
    if len(a) == 4:  # ISO-like: YYYY-MM-DD
        return [(int(a), int(b), int(c))]
    year = _year(c)
    mdy = (year, int(a), int(b))
    dmy = (year, int(b), int(a))
    return [mdy, dmy] if order.upper() == "MDY" else [dmy, mdy]


def _time(text: str) -> tuple[int, int, int] | None:
    m = _TIME.search(text)
    if not m:
        return None
    hour, minute, second = int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)
    ampm = (m.group(4) or "").upper()
    if ampm:
        if not 1 <= hour <= 12:
            return None
        hour = hour % 12 + (12 if ampm == "P" else 0)
    if hour > 23 or minute > 59 or second > 59:
        return None
    return hour, minute, second


def is_plausible(ts: datetime, check: OcrCheck) -> bool:
    now = check.now or datetime.now()
    if ts.year < check.min_year or ts > now + timedelta(days=1):
        return False
    if check.camera_range is not None:
        lo, hi = check.camera_range
        slack = timedelta(days=check.max_days_from_camera)
        if not lo - slack <= ts <= hi + slack:
            return False
    return True


def parse_banner(texts: list[str], check: OcrCheck | None = None) -> datetime | None:
    """First plausible timestamp found in the OCR text fragments, or None.

    Fragments are tried one by one and then joined, because OCR often splits the date and
    the time into separate boxes.
    """
    check = check or OcrCheck()
    for text in [*texts, " ".join(texts)]:
        text = _fix_digits(text)
        for m in _DATE.finditer(text):
            clock = _time(text[m.end() :]) or _time(text[: m.start()])
            if clock is None:
                continue
            for y, mo, d in _date_candidates(*m.groups(), check.date_order):
                try:
                    ts = datetime(y, mo, d, *clock)
                except ValueError:
                    continue  # not a real date in this order; try the other one
                if is_plausible(ts, check):
                    return ts
    return None
