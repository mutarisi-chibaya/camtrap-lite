"""Find static false detections: boxes that fire in the same place over and over.

A rock or branch that MegaDetector mistakes for an animal shows up at (almost) the same
box in a large share of a camera's images, while real animals move. We cluster boxes by
IoU and flag clusters that recur too often.

Clusters are only *suggestions*. Triage ignores their detections only after a human
confirms the cluster on the Static Check page, so we can afford to favour recall (loose
thresholds, all categories): a false suggestion costs one click, while a missed animal
hidden by an automatic rule would be lost.
"""

from dataclasses import dataclass, field

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import (
    Detection,
    Image,
    ImageStatus,
    StaticCluster,
    StaticClusterStatus,
)

BBox = tuple[float, float, float, float]  # normalised x, y, w, h


def iou(a: BBox, b: BBox) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ix = max(0.0, min(ax + aw, bx + bw) - max(ax, bx))
    iy = max(0.0, min(ay + ah, by + bh) - max(ay, by))
    inter = ix * iy
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0.0


@dataclass(frozen=True)
class Box:
    detection_id: int
    image_id: int
    confidence: float
    bbox: BBox


@dataclass
class BoxCluster:
    representative: BBox
    members: list[Box] = field(default_factory=list)

    @property
    def image_count(self) -> int:
        return len({m.image_id for m in self.members})


def cluster_boxes(boxes: list[Box], iou_threshold: float) -> list[BoxCluster]:
    """Greedy clustering against a fixed representative box per cluster.

    Boxes are visited highest-confidence first, so each cluster's representative is its
    clearest box. A box joins the cluster whose representative it overlaps most, if that
    IoU >= `iou_threshold`; otherwise it starts a new cluster. Comparing to a fixed
    representative (not a running mean) keeps clusters from drifting across the frame.
    """
    clusters: list[BoxCluster] = []
    for box in sorted(boxes, key=lambda b: (-b.confidence, b.detection_id)):
        best, best_iou = None, 0.0
        for c in clusters:
            score = iou(c.representative, box.bbox)
            if score > best_iou:
                best, best_iou = c, score
        if best is not None and best_iou >= iou_threshold:
            best.members.append(box)
        else:
            clusters.append(BoxCluster(box.bbox, [box]))
    return clusters


def static_candidates(
    clusters: list[BoxCluster], total_images: int, min_fraction: float, min_count: int
) -> list[BoxCluster]:
    """Clusters seen in >= min_fraction of the camera's images AND >= min_count images.

    The fraction catches cameras with many triggers; the absolute count stops a camera with
    only a handful of images from flagging every repeated box.
    """
    if total_images == 0:
        return []
    return [
        c
        for c in clusters
        if c.image_count >= min_count and c.image_count / total_images >= min_fraction
    ]


def _rep(cluster: StaticCluster) -> BBox:
    return (cluster.bbox_x, cluster.bbox_y, cluster.bbox_w, cluster.bbox_h)


def find_static_clusters(db: Session, camera_id: int) -> list[StaticCluster]:
    """Recompute the camera's static clusters, keeping earlier human decisions.

    A recomputed cluster that overlaps an existing one (IoU >= STATIC_IOU) reuses that row,
    so a confirmed/rejected status survives new uploads. Pending clusters that no longer
    qualify are deleted; decided ones are kept with a count of 0.
    """
    s = get_settings()
    total_images = (
        db.scalar(
            select(func.count())
            .select_from(Image)
            .where(Image.camera_id == camera_id, Image.status == ImageStatus.processed)
        )
        or 0
    )
    detections = list(
        db.scalars(
            select(Detection)
            .join(Image)
            .where(Image.camera_id == camera_id, Detection.confidence >= s.static_min_conf)
        )
    )
    boxes = [
        Box(d.id, d.image_id, d.confidence, (d.bbox_x, d.bbox_y, d.bbox_w, d.bbox_h))
        for d in detections
    ]
    candidates = static_candidates(
        cluster_boxes(boxes, s.static_iou), total_images, s.static_min_fraction, s.static_min_count
    )

    image_ids = select(Image.id).where(Image.camera_id == camera_id)
    db.execute(
        update(Detection)
        .where(Detection.image_id.in_(image_ids))
        .values(is_static_candidate=False, static_cluster_id=None)
    )
    existing = list(db.scalars(select(StaticCluster).where(StaticCluster.camera_id == camera_id)))
    unmatched = set(existing)
    by_id = {d.id: d for d in detections}

    result = []
    for cand in candidates:
        match = max(
            (c for c in unmatched if iou(_rep(c), cand.representative) >= s.static_iou),
            key=lambda c: iou(_rep(c), cand.representative),
            default=None,
        )
        if match is None:
            x, y, w, h = cand.representative
            match = StaticCluster(
                camera_id=camera_id,
                bbox_x=x,
                bbox_y=y,
                bbox_w=w,
                bbox_h=h,
                status=StaticClusterStatus.pending,
            )
            db.add(match)
        else:
            unmatched.discard(match)
        match.occurrence_count = cand.image_count
        match.occurrence_fraction = cand.image_count / total_images
        db.flush()
        for m in cand.members:
            by_id[m.detection_id].is_static_candidate = True
            by_id[m.detection_id].static_cluster_id = match.id
        result.append(match)

    for old in unmatched:
        if old.status == StaticClusterStatus.pending:
            db.delete(old)
        else:
            old.occurrence_count = 0
            old.occurrence_fraction = 0.0
    db.flush()
    return result
