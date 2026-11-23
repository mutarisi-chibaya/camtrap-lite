from datetime import datetime

import pytest

from app.services.timestamp_ocr import OcrCheck, is_plausible, parse_banner

NOW = datetime(2026, 11, 23, 12, 0, 0)
CHECK = OcrCheck(now=NOW)


@pytest.mark.parametrize(
    ("texts", "expected"),
    [
        (["12/9/2017   1:40 AM"], datetime(2017, 12, 9, 1, 40)),  # Cuddeback, MDY
        (["12/9/2017", "1:40 PM"], datetime(2017, 12, 9, 13, 40)),  # split into two boxes
        (["2017-10-04 01:01:44"], datetime(2017, 10, 4, 1, 1, 44)),  # ISO
        (["TEMP 23C  10-04-17 21:05:13"], datetime(2017, 10, 4, 21, 5, 13)),  # 2-digit year
        (["12:00 AM 01/02/2018"], datetime(2018, 1, 2, 0, 0)),  # time before date, midnight
        (["l2/9/2Ol7 1:4O AM"], datetime(2017, 12, 9, 1, 40)),  # OCR letter/digit confusions
    ],
)
def test_parses_common_banners(texts: list[str], expected: datetime) -> None:
    assert parse_banner(texts, CHECK) == expected


def test_falls_back_to_other_date_order_when_preferred_is_impossible() -> None:
    # 25/10/2017 cannot be MDY (month 25), so DMY is used.
    assert parse_banner(["25/10/2017 06:30"], CHECK) == datetime(2017, 10, 25, 6, 30)


def test_dmy_preference() -> None:
    check = OcrCheck(now=NOW, date_order="DMY")
    assert parse_banner(["04/10/2017 06:30"], check) == datetime(2017, 10, 4, 6, 30)
    assert parse_banner(["04/10/2017 06:30"], CHECK) == datetime(2017, 4, 10, 6, 30)


@pytest.mark.parametrize(
    "texts",
    [
        ["13/13/2017 01:00"],  # no valid month in either order
        ["02/30/2017 01:00"],  # 30 February
        ["12/9/2017 25:40"],  # hour 25
        ["12/9/2017 13:40 PM"],  # 13 PM
        ["12/9/1999 01:00"],  # before min year (clock reset)
        ["12/9/2031 01:00"],  # in the future
        ["Cuddeback"],  # no timestamp at all
        ["12/9/2017"],  # date without time
        [],
    ],
)
def test_rejects_impossible_or_missing(texts: list[str]) -> None:
    assert parse_banner(texts, CHECK) is None


def test_camera_range_check() -> None:
    rng = (datetime(2017, 10, 1), datetime(2018, 1, 31))
    check = OcrCheck(now=NOW, camera_range=rng, max_days_from_camera=30)
    assert is_plausible(datetime(2017, 12, 9), check)
    assert is_plausible(datetime(2018, 2, 20), check)  # within 30 days of the range
    assert not is_plausible(datetime(2019, 6, 1), check)
    # e.g. a camera whose clock reset to its factory date
    assert parse_banner(["01/01/2016 00:00"], check) is None
