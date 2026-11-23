"""CSV export: one row per image, with the final (human-over-AI) label of its event."""

import csv
import io
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import Detection, Image, StaticCluster, StaticClusterStatus
from app.services.labels import final_labels
from app.services.masks import is_masked, load_masks

COLUMNS = [
    "image_id",
    "filename",
    "camera",
    "site",
    "latitude",
    "longitude",
    "timestamp",
    "timestamp_source",
    "event_id",
    "final_label",
    "label_source",
    "triage_status",
    "n_animal_detections",
    "max_animal_confidence",
]


def countable_detections(db: Session, image_ids: list[int]) -> dict[int, list[Detection]]:
    """image_id -> detections, excluding confirmed-static clusters and camera masks."""
    if not image_ids:
        return {}
    rows = db.execute(
        select(Detection, Image.camera_id, StaticCluster.status)
        .join(Image, Detection.image_id == Image.id)
        .outerjoin(StaticCluster, Detection.static_cluster_id == StaticCluster.id)
        .where(Detection.image_id.in_(image_ids))
    ).all()
    masks = load_masks(db, {cam for _, cam, _ in rows})
    out: dict[int, list[Detection]] = defaultdict(list)
    for det, camera_id, cluster_status in rows:
        if cluster_status == StaticClusterStatus.confirmed_static:
            continue
        if is_masked((det.bbox_x, det.bbox_y, det.bbox_w, det.bbox_h), masks.get(camera_id, [])):
            continue
        out[det.image_id].append(det)
    return out


def export_csv(db: Session, camera_id: int | None = None, min_conf: float = 0.2) -> str:
    """Build the CSV. `n_animal_detections` counts animal boxes >= `min_conf` (MegaDetector's
    typical threshold is 0.2); `max_animal_confidence` uses all stored animal boxes."""
    q = select(Image).options(selectinload(Image.camera), selectinload(Image.event))
    if camera_id is not None:
        q = q.where(Image.camera_id == camera_id)
    images = list(db.scalars(q.order_by(Image.camera_id, Image.timestamp, Image.id)))
    labels = final_labels(db, camera_id)
    dets = countable_detections(db, [i.id for i in images])

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(COLUMNS)
    for img in images:
        animal = [d for d in dets.get(img.id, []) if d.category == "animal"]
        final = labels.get(img.event_id) if img.event_id is not None else None
        w.writerow(
            [
                img.id,
                img.original_filename,
                img.camera.name,
                img.camera.site_name,
                "" if img.camera.latitude is None else img.camera.latitude,
                "" if img.camera.longitude is None else img.camera.longitude,
                img.timestamp.isoformat() if img.timestamp else "",
                img.timestamp_source.value,
                img.event_id or "",
                final.label if final else "",
                final.source if final else "",
                img.event.triage_status.value if img.event else img.status.value,
                sum(d.confidence >= min_conf for d in animal),
                f"{max(d.confidence for d in animal):.4f}" if animal else "",
            ]
        )
    return buf.getvalue()
