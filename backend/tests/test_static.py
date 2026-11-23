import pytest
from sqlalchemy.orm import Session

from app.models import (
    Camera,
    Detection,
    DetectionCategory,
    Image,
    ImageStatus,
    StaticCluster,
    StaticClusterStatus,
)
from app.services.static import (
    Box,
    BoxCluster,
    cluster_boxes,
    find_static_clusters,
    iou,
    static_candidates,
)

ROCK = (0.40, 0.50, 0.10, 0.08)


def test_iou_basic_cases() -> None:
    assert iou((0, 0, 1, 1), (0, 0, 1, 1)) == pytest.approx(1.0)
    assert iou((0, 0, 0.5, 0.5), (0.5, 0.5, 0.5, 0.5)) == 0.0
    # half overlap: inter 0.5, union 1.5
    assert iou((0, 0, 1, 1), (0.5, 0, 1, 1)) == pytest.approx(1 / 3)
    assert iou((0, 0, 0, 0), (0, 0, 0, 0)) == 0.0


def test_cluster_groups_overlapping_boxes() -> None:
    boxes = [
        Box(1, 1, 0.5, ROCK),
        Box(2, 2, 0.3, (0.405, 0.50, 0.10, 0.08)),  # nearly the same place
        Box(3, 3, 0.9, (0.0, 0.0, 0.2, 0.2)),  # elsewhere
    ]
    clusters = cluster_boxes(boxes, 0.7)
    assert sorted(sorted(m.detection_id for m in c.members) for c in clusters) == [[1, 2], [3]]


def test_representative_is_highest_confidence_box() -> None:
    boxes = [Box(1, 1, 0.3, ROCK), Box(2, 2, 0.8, (0.41, 0.5, 0.1, 0.08))]
    (cluster,) = cluster_boxes(boxes, 0.7)
    assert cluster.representative == (0.41, 0.5, 0.1, 0.08)


def test_representative_is_fixed_so_clusters_do_not_drift() -> None:
    # Each box overlaps its neighbour enough, but the last is far from the first.
    boxes = [Box(i, i, 1.0 - i * 0.01, (0.02 * i, 0.0, 0.1, 0.1)) for i in range(6)]
    clusters = cluster_boxes(boxes, 0.7)
    assert len(clusters) > 1


def test_image_count_counts_distinct_images() -> None:
    c = BoxCluster(ROCK, [Box(1, 10, 0.5, ROCK), Box(2, 10, 0.4, ROCK), Box(3, 11, 0.4, ROCK)])
    assert c.image_count == 2


@pytest.mark.parametrize(
    ("count", "total", "expected"),
    [
        (5, 50, True),  # exactly 10 % and exactly 5 images
        (4, 20, False),  # 20 % but only 4 images
        (5, 51, False),  # 5 images but < 10 %
        (30, 100, True),
    ],
)
def test_candidate_needs_fraction_and_count(count: int, total: int, expected: bool) -> None:
    cluster = BoxCluster(ROCK, [Box(i, i, 0.5, ROCK) for i in range(count)])
    assert bool(static_candidates([cluster], total, 0.1, 5)) is expected


def test_no_images_no_candidates() -> None:
    assert static_candidates([BoxCluster(ROCK, [])], 0, 0.1, 5) == []


def _camera_with_rock(db: Session, n_images: int = 20, n_rock: int = 6) -> Camera:
    cam = Camera(name="c")
    db.add(cam)
    db.flush()
    for i in range(n_images):
        img = Image(
            camera_id=cam.id,
            original_filename=f"{i}.jpg",
            storage_key=f"{cam.id}/{i}",
            status=ImageStatus.processed,
        )
        if i < n_rock:
            x, y, w, h = ROCK
            img.detections.append(
                Detection(
                    category=DetectionCategory.animal,
                    confidence=0.3,
                    bbox_x=x,
                    bbox_y=y,
                    bbox_w=w,
                    bbox_h=h,
                )
            )
        if i == 0:  # a real animal elsewhere, and a low-confidence box below STATIC_MIN_CONF
            img.detections.append(
                Detection(
                    category=DetectionCategory.animal,
                    confidence=0.95,
                    bbox_x=0.0,
                    bbox_y=0.0,
                    bbox_w=0.3,
                    bbox_h=0.3,
                )
            )
        db.add(img)
    db.flush()
    return cam


def test_find_static_clusters_marks_members(db: Session) -> None:
    cam = _camera_with_rock(db)
    (cluster,) = find_static_clusters(db, cam.id)
    assert cluster.status == StaticClusterStatus.pending
    assert cluster.occurrence_count == 6
    assert cluster.occurrence_fraction == pytest.approx(0.3)
    flagged = db.query(Detection).filter_by(is_static_candidate=True).all()
    assert len(flagged) == 6 and {d.static_cluster_id for d in flagged} == {cluster.id}
    assert db.query(Detection).filter(Detection.confidence > 0.9).one().is_static_candidate is False


def test_rerun_keeps_human_decision(db: Session) -> None:
    cam = _camera_with_rock(db)
    (cluster,) = find_static_clusters(db, cam.id)
    cluster.status = StaticClusterStatus.confirmed_static
    db.flush()

    (again,) = find_static_clusters(db, cam.id)
    assert again.id == cluster.id
    assert again.status == StaticClusterStatus.confirmed_static
    assert db.query(StaticCluster).count() == 1


def test_pending_cluster_removed_when_no_longer_qualifying(db: Session) -> None:
    cam = _camera_with_rock(db, n_images=20, n_rock=6)
    find_static_clusters(db, cam.id)
    for i in range(41):  # 6 of 61 images: just below 10 %
        db.add(
            Image(
                camera_id=cam.id,
                original_filename=f"x{i}",
                storage_key=f"x{i}",
                status=ImageStatus.processed,
            )
        )
    db.flush()
    assert find_static_clusters(db, cam.id) == []
    assert db.query(StaticCluster).count() == 0
    assert db.query(Detection).filter_by(is_static_candidate=True).count() == 0
