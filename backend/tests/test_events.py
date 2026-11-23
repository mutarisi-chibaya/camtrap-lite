from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.models import Camera, Event, Image, ImageStatus
from app.services.events import TimedImage, group_by_gap, group_events

T0 = datetime(2018, 1, 5, 0, 0, 0)


def _t(seconds: float) -> datetime:
    return T0 + timedelta(seconds=seconds)


def _ids(groups: list[list[TimedImage]]) -> list[list[int]]:
    return [[i.id for i in g] for g in groups]


def test_gap_splits_events() -> None:
    imgs = [TimedImage(1, _t(0)), TimedImage(2, _t(30)), TimedImage(3, _t(200))]
    assert _ids(group_by_gap(imgs, 60)) == [[1, 2], [3]]


def test_gap_equal_to_threshold_stays_in_event() -> None:
    imgs = [TimedImage(1, _t(0)), TimedImage(2, _t(60)), TimedImage(3, _t(120.5))]
    assert _ids(group_by_gap(imgs, 60)) == [[1, 2], [3]]


def test_gap_measured_to_previous_image_not_event_start() -> None:
    imgs = [TimedImage(i, _t(i * 50)) for i in range(5)]  # 200 s span, 50 s steps
    assert _ids(group_by_gap(imgs, 60)) == [[0, 1, 2, 3, 4]]


def test_unsorted_input_is_sorted_by_time() -> None:
    imgs = [TimedImage(3, _t(500)), TimedImage(1, _t(0)), TimedImage(2, _t(10))]
    assert _ids(group_by_gap(imgs, 60)) == [[1, 2], [3]]


def test_missing_timestamps_become_single_image_events() -> None:
    imgs = [TimedImage(1, _t(0)), TimedImage(5, None), TimedImage(2, _t(5)), TimedImage(4, None)]
    assert _ids(group_by_gap(imgs, 60)) == [[1, 2], [4], [5]]


def test_empty_input() -> None:
    assert group_by_gap([], 60) == []


def test_group_events_assigns_only_unassigned_processed_images(db: Session) -> None:
    cam = Camera(name="c")
    db.add(cam)
    db.flush()

    def img(n: int, ts: datetime | None, status: ImageStatus = ImageStatus.processed) -> Image:
        return Image(
            camera_id=cam.id,
            original_filename=f"{n}.jpg",
            storage_key=f"{n}",
            timestamp=ts,
            status=status,
        )

    a, b, c = img(1, _t(0)), img(2, _t(20)), img(3, None)
    failed = img(4, _t(10), ImageStatus.failed)
    db.add_all([a, b, c, failed])
    db.flush()

    events = group_events(db, cam.id)
    assert len(events) == 2
    assert a.event_id == b.event_id == events[0].id
    assert (events[0].start_time, events[0].end_time) == (_t(0), _t(20))
    assert c.event_id == events[1].id and events[1].start_time is None
    assert failed.event_id is None

    # Re-running does not touch images that already belong to an event.
    assert group_events(db, cam.id) == []
    assert db.query(Event).count() == 2
