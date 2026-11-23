"""Per-camera polygon masks that hide detections, e.g. grass that waves in the wind.

A detection is *masked* when the centre of its box lies inside any of its camera's mask
polygons. Using the centre, not full containment, means a box that spills a little out
of the grass is still caught, while an animal walking *in front of* the grass (its box
centre usually higher up) is not. Masked detections are ignored by triage, the static
finder and exports, exactly like detections in a confirmed static cluster. They stay in
the database, so deleting a mask brings them back.
"""

from collections import defaultdict
from collections.abc import Iterable, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CameraMask

Point = tuple[float, float]
Polygon = Sequence[Point]
BBox = tuple[float, float, float, float]


def point_in_polygon(x: float, y: float, polygon: Polygon) -> bool:
    """Ray casting: count how many polygon edges a ray to the right of (x, y) crosses."""
    inside = False
    n = len(polygon)
    for i in range(n):
        x1, y1 = polygon[i]
        x2, y2 = polygon[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            x_cross = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x < x_cross:
                inside = not inside
    return inside


def is_masked(bbox: BBox, polygons: Iterable[Polygon]) -> bool:
    x, y, w, h = bbox
    cx, cy = x + w / 2, y + h / 2
    return any(point_in_polygon(cx, cy, p) for p in polygons)


def load_masks(db: Session, camera_ids: Iterable[int] | None = None) -> dict[int, list[Polygon]]:
    """camera_id -> list of polygons."""
    q = select(CameraMask.camera_id, CameraMask.polygon)
    if camera_ids is not None:
        q = q.where(CameraMask.camera_id.in_(list(camera_ids)))
    out: dict[int, list[Polygon]] = defaultdict(list)
    for camera_id, polygon in db.execute(q):
        out[camera_id].append([(float(px), float(py)) for px, py in polygon])
    return out
