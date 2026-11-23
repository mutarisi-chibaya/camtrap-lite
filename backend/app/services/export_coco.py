"""COCO JSON export: images, detection boxes in pixels, and the three MegaDetector categories.

Boxes are only exported for images whose event's final label is not `empty`: if a human (or
triage) decided the event is empty, its boxes are false positives. Boxes in confirmed static
clusters and boxes below `min_conf` are left out for the same reason.
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import Image
from app.services.export_csv import countable_detections
from app.services.labels import final_labels

CATEGORIES = [
    {"id": 1, "name": "animal"},
    {"id": 2, "name": "person"},
    {"id": 3, "name": "vehicle"},
]
CATEGORY_IDS = {c["name"]: c["id"] for c in CATEGORIES}


def to_pixel_bbox(bbox: tuple[float, float, float, float], width: int, height: int) -> list[float]:
    """Normalised [x, y, w, h] (top-left origin, 0-1) -> COCO pixels [x, y, w, h]."""
    x, y, w, h = bbox
    return [round(x * width, 2), round(y * height, 2), round(w * width, 2), round(h * height, 2)]


def export_coco(db: Session, camera_id: int | None = None, min_conf: float = 0.2) -> dict[str, Any]:
    q = select(Image).options(selectinload(Image.camera))
    if camera_id is not None:
        q = q.where(Image.camera_id == camera_id)
    images = list(db.scalars(q.order_by(Image.id)))
    labels = final_labels(db, camera_id)
    dets = countable_detections(db, [i.id for i in images])

    coco_images, annotations = [], []
    for img in images:
        final = labels.get(img.event_id) if img.event_id is not None else None
        coco_images.append(
            {
                "id": img.id,
                "file_name": img.original_filename,
                "width": img.width,
                "height": img.height,
                "date_captured": img.timestamp.isoformat() if img.timestamp else None,
                "location": img.camera.name,
                "seq_id": img.event_id,
                "final_label": final.label if final else None,
                "label_source": final.source if final else None,
            }
        )
        if (final and final.label == "empty") or not img.width or not img.height:
            continue
        for d in dets.get(img.id, []):
            if d.confidence < min_conf:
                continue
            box = to_pixel_bbox((d.bbox_x, d.bbox_y, d.bbox_w, d.bbox_h), img.width, img.height)
            annotations.append(
                {
                    "id": d.id,
                    "image_id": img.id,
                    "category_id": CATEGORY_IDS[d.category.value],
                    "bbox": box,
                    "area": round(box[2] * box[3], 2),
                    "iscrowd": 0,
                    "score": round(d.confidence, 4),
                }
            )

    return {
        "info": {
            "description": "CamTrap Lite export (MegaDetector detections + human review)",
            "date_created": datetime.now(UTC).isoformat(timespec="seconds"),
            "min_conf": min_conf,
        },
        "images": coco_images,
        "annotations": annotations,
        "categories": CATEGORIES,
    }
