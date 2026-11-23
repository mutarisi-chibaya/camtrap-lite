"""Load a MegaDetector batch-output JSON into the database.

Works with our Colab notebook's output and with LILA's precomputed results. Entries are
matched to Image rows by `original_filename`:

1. exact relative path (``KAR_S1/A01/A01_R1/x.JPG``),
2. path suffix, either way round (results may hold absolute Colab paths such as
   ``/content/images/KAR_S1/...``, or the DB may hold the longer path),
3. bare filename, but only if it is unique within the candidate images.
"""

import logging
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ml.types import MD_CATEGORIES, from_md_detections
from app.models import Image, ImageStatus
from app.services.pipeline import finalize_cameras_if_done, save_detections

log = logging.getLogger(__name__)


@dataclass
class ImportReport:
    matched: int = 0
    failed: int = 0
    detections: int = 0
    missing_from_db: list[str] = field(default_factory=list)
    finalized_cameras: list[int] = field(default_factory=list)


def _norm(path: str) -> str:
    return path.replace("\\", "/").lstrip("./").lower()


class _Matcher:
    def __init__(self, images: list[Image]) -> None:
        self.by_path = {_norm(i.original_filename): i for i in images}
        by_name: dict[str, list[Image]] = {}
        for i in images:
            by_name.setdefault(PurePosixPath(_norm(i.original_filename)).name, []).append(i)
        self.by_name = by_name

    def find(self, file: str) -> Image | None:
        key = _norm(file)
        if key in self.by_path:
            return self.by_path[key]
        for path, img in self.by_path.items():
            if key.endswith("/" + path) or path.endswith("/" + key):
                return img
        candidates = self.by_name.get(PurePosixPath(key).name, [])
        return candidates[0] if len(candidates) == 1 else None


def import_md_results(
    db: Session, results: dict[str, Any], camera_id: int | None = None
) -> ImportReport:
    """Save detections from `results` and post-process every camera that is now complete.

    `camera_id` limits matching to one camera; None matches against all images.
    """
    query = select(Image)
    if camera_id is not None:
        query = query.where(Image.camera_id == camera_id)
    matcher = _Matcher(list(db.scalars(query)))
    categories = results.get("detection_categories") or MD_CATEGORIES

    report = ImportReport()
    touched: set[int] = set()
    for entry in results.get("images", []):
        image = matcher.find(entry["file"])
        if image is None:
            report.missing_from_db.append(entry["file"])
            continue
        touched.add(image.camera_id)
        if entry.get("failure"):
            image.status = ImageStatus.failed
            report.failed += 1
            continue
        dets = from_md_detections(entry.get("detections"), categories)
        report.detections += save_detections(db, image, dets)
        report.matched += 1
    db.commit()

    if report.missing_from_db:
        log.warning("%d result entries had no matching image", len(report.missing_from_db))
    report.finalized_cameras = finalize_cameras_if_done(db, touched)
    return report
