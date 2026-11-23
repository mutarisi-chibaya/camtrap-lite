"""Detector-independent result types (no torch / megadetector imports here)."""

from dataclasses import dataclass
from typing import Any

# MegaDetector's batch-output category ids.
MD_CATEGORIES = {"1": "animal", "2": "person", "3": "vehicle"}


@dataclass(frozen=True)
class DetectionResult:
    category: str  # "animal" | "person" | "vehicle"
    confidence: float
    bbox: tuple[float, float, float, float]  # normalised x, y, w, h (top-left origin)


def from_md_detections(
    detections: list[dict[str, Any]] | None, categories: dict[str, str] | None = None
) -> list[DetectionResult]:
    """Convert MegaDetector-format detections (``{category, conf, bbox}``) to our type.

    The same dict format comes out of MegaDetector's in-process API and its batch-output
    JSON files, so the worker and the importer both use this.
    """
    categories = categories or MD_CATEGORIES
    out = []
    for d in detections or []:
        name = categories.get(str(d["category"]))
        if name not in ("animal", "person", "vehicle"):
            continue
        x, y, w, h = (float(v) for v in d["bbox"])
        out.append(DetectionResult(name, float(d["conf"]), (x, y, w, h)))
    return out
