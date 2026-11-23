import pytest

from app.services.evaluation import (
    ImageRow,
    event_metrics,
    image_metrics,
    review_metrics,
    threshold_sweep,
    to_events,
)
from app.services.triage import TriageDet

# event 1: auto_empty, truly empty (2 images)
# event 2: auto_empty, but one frame has an animal -> a lost animal
# event 3: auto_animal, truly animal
# event 4: reviewed by a human as animal, truly animal
# event 5: needs review, truly empty
IMAGES = [
    ImageRow(1, 1, "auto_empty", "empty", "empty", "ai"),
    ImageRow(2, 1, "auto_empty", "empty", "empty", "ai"),
    ImageRow(3, 2, "auto_empty", "animal", "empty", "ai"),
    ImageRow(4, 2, "auto_empty", "empty", "empty", "ai"),
    ImageRow(5, 3, "auto_animal", "animal", "animal", "ai"),
    ImageRow(6, 4, "reviewed", "animal", "animal", "human"),
    ImageRow(7, 5, "needs_review", "empty", None, None),
]


def test_image_level_metrics() -> None:
    m = image_metrics(IMAGES)
    assert m.n == 7
    assert m.auto_handled == pytest.approx(5 / 7)
    assert m.empty_precision == pytest.approx(3 / 4)  # images 1, 2, 4 of 1-4
    assert m.empty_recall == pytest.approx(3 / 4)  # truly empty: 1, 2, 4, 7
    assert (m.animals_lost, m.animals_total) == (1, 3)
    assert m.auto_animal_precision == 1.0
    assert m.final_n == 6
    assert m.final_accuracy == pytest.approx(5 / 6)  # image 3 is wrong


def test_event_level_metrics() -> None:
    events = to_events(IMAGES)
    by_id = {e.event_id: e for e in events}
    assert by_id[2].gt_empty is False  # any non-empty frame makes the event non-empty
    assert by_id[1].n_images == 2
    m = event_metrics(events)
    assert m.n == 5
    assert m.auto_handled == pytest.approx(3 / 5)
    assert m.empty_precision == pytest.approx(1 / 2)
    assert (m.animals_lost, m.animals_total) == (1, 3)


def test_missing_ground_truth_is_ignored() -> None:
    rows = [ImageRow(1, 1, "auto_empty", None, "empty", "ai")]
    m = image_metrics(rows)
    assert m.auto_handled == 1.0
    assert m.empty_precision is None and m.final_accuracy is None
    assert to_events(rows)[0].gt_empty is None


def test_review_metrics() -> None:
    r = review_metrics([1000, 3000, 2000], [("animal", False), ("empty", False)])
    assert r.reviewed_events == 3
    assert r.median_ms == 2000
    assert r.events_per_minute == 30.0
    assert r.total_minutes == pytest.approx(0.1)
    assert r.human_accuracy == 0.5
    empty = review_metrics([], [])
    assert empty.median_ms is None and empty.events_per_minute is None


def test_threshold_sweep() -> None:
    events = to_events(IMAGES)
    dets = {
        2: [TriageDet("animal", 0.08)],  # weak detection of the real animal
        3: [TriageDet("animal", 0.85)],
        4: [TriageDet("animal", 0.9)],
        5: [TriageDet("animal", 0.3)],
    }
    nonempty = {2: 1, 3: 1, 4: 1}
    rows = {
        (r.accept, r.empty): r for r in threshold_sweep(dets, events, [0.8], [0.05, 0.1], nonempty)
    }
    # Lower empty threshold: event 2 (conf 0.08) is no longer auto-emptied.
    assert rows[(0.8, 0.05)].animal_events_lost == 0
    assert rows[(0.8, 0.1)].animal_events_lost == 1
    assert rows[(0.8, 0.1)].animal_images_lost == 1
    # 0.05: events 1, 3, 4 automated (4 images); events 2 and 5 need review.
    assert rows[(0.8, 0.05)].pct_images_auto == pytest.approx(4 / 7)
    assert rows[(0.8, 0.1)].pct_images_auto == pytest.approx(6 / 7)
    assert rows[(0.8, 0.1)].wrong_auto_animal_events == 0
