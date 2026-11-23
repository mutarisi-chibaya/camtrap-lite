"""MegaDetector wrapper. This is the only module that imports the `megadetector` package.

Uses the package's documented in-process API (megadetector 10.x):
``run_detector.load_detector("MDV5A")`` downloads/loads MDv5a, and
``detector.generate_detections_one_image(pil_image, image_id, detection_threshold)``
returns a dict in the batch-output format (``detections: [{category, conf, bbox}]``,
``failure``). MegaDetector picks a CUDA GPU automatically when one is available.
"""

from abc import ABC, abstractmethod
from typing import BinaryIO

from app.ml.types import DetectionResult, from_md_detections

DEFAULT_MODEL = "MDV5A"


class DetectionError(RuntimeError):
    pass


class Detector(ABC):
    @abstractmethod
    def detect(self, image: BinaryIO, image_id: str = "image") -> list[DetectionResult]:
        """Run detection on one encoded image (e.g. a JPEG stream)."""


class MegaDetector(Detector):
    def __init__(
        self, model: str = DEFAULT_MODEL, threshold: float = 0.05, force_cpu: bool = False
    ) -> None:
        # Imported lazily: torch is heavy, and only the worker needs it.
        from megadetector.detection import run_detector
        from megadetector.visualization import visualization_utils

        self._load_image = visualization_utils.load_image
        self._model = run_detector.load_detector(model, force_cpu=force_cpu)
        self.threshold = threshold
        self.model_name = model

    def detect(self, image: BinaryIO, image_id: str = "image") -> list[DetectionResult]:
        pil = self._load_image(image)  # applies EXIF rotation, converts to RGB
        result = self._model.generate_detections_one_image(
            pil, image_id=image_id, detection_threshold=self.threshold
        )
        if result.get("failure"):
            raise DetectionError(f"{image_id}: {result['failure']}")
        return from_md_detections(result.get("detections"))


def gpu_available() -> bool:
    try:
        import torch
    except ImportError:
        return False
    return bool(torch.cuda.is_available())
