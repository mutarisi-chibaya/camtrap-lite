"""The shared "after detection" step, used by both the worker and the results importer.

Keeping this in one place means a detection from the local worker and one imported from a
MegaDetector batch-output JSON (Colab, or LILA's precomputed results) are saved and
post-processed identically.
"""

import logging

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.ml.types import DetectionResult
from app.models import Detection, DetectionCategory, Image, ImageStatus
from app.services import events, static, triage

log = logging.getLogger(__name__)

PENDING_STATUSES = (ImageStatus.uploaded, ImageStatus.queued)


def save_detections(db: Session, image: Image, results: list[DetectionResult]) -> int:
    """Replace the image's detections and mark it processed. Returns how many were kept.

    Detections below DETECTION_MIN_CONF are dropped: they can never change triage
    (anything under AUTO_EMPTY_CONF counts as empty anyway) and MegaDetector batch files
    list thousands of near-zero boxes.
    """
    min_conf = get_settings().detection_min_conf
    db.execute(delete(Detection).where(Detection.image_id == image.id))
    kept = 0
    for r in results:
        if r.confidence < min_conf:
            continue
        x, y, w, h = r.bbox
        db.add(
            Detection(
                image_id=image.id,
                category=DetectionCategory(r.category),
                confidence=r.confidence,
                bbox_x=x,
                bbox_y=y,
                bbox_w=w,
                bbox_h=h,
            )
        )
        kept += 1
    image.status = ImageStatus.processed
    return kept


def camera_is_done(db: Session, camera_id: int) -> bool:
    """True once no image of the camera is still waiting for detection."""
    pending = db.scalar(
        select(func.count())
        .select_from(Image)
        .where(Image.camera_id == camera_id, Image.status.in_(PENDING_STATUSES))
    )
    return pending == 0


def post_process_camera(db: Session, camera_id: int) -> None:
    """Event grouping -> static finder -> triage for one camera, then commit."""
    events.group_events(db, camera_id)
    static.find_static_clusters(db, camera_id)
    triage.triage_camera(db, camera_id)
    db.commit()
    log.info("post-processed camera %s", camera_id)


def finalize_cameras_if_done(db: Session, camera_ids: set[int]) -> list[int]:
    """Run post-processing for every camera in `camera_ids` whose images are all processed."""
    done = [cid for cid in sorted(camera_ids) if camera_is_done(db, cid)]
    for cid in done:
        post_process_camera(db, cid)
    return done
