"""The trained EfficientNet-B0 checkpoint, loaded once at startup.

`screener` is None when the model is not loaded (USE_MOCKS=true or a load failure); the
service then serves precomputed fixtures for seeded screenings only (see service.py).
"""
import logging
import threading

import numpy as np
from PIL import Image

from app.core.config import settings

logger = logging.getLogger(__name__)


class Screener:
    """predict() and explain() are thread-safe (one forward pass at a time)."""

    def __init__(self) -> None:
        # Imported here so a missing or broken PyTorch only disables live mode instead of crashing the app
        from src.gradcam import target_layer
        from src.model import get_device, load_checkpoint

        self.device = get_device() if settings.MODEL_DEVICE == "auto" else settings.MODEL_DEVICE
        self.model, self.checkpoint = load_checkpoint(str(settings.model_checkpoint_path), self.device)
        self.layer_name, self.layer = target_layer(self.model, self.checkpoint["model_name"])
        self._lock = threading.Lock()
        self.predict(Image.new("RGB", (512, 512)))  # warm-up: the first MPS call is slow

    @property
    def labels(self) -> list[str]:
        return list(self.checkpoint["labels"])

    @property
    def thresholds(self) -> list[float]:
        return [float(t) for t in self.checkpoint["thresholds"]]

    def _tensor(self, image: Image.Image):
        from src.dataset import to_tensor  # crop_fundus -> resize -> ImageNet normalise, exactly like validation

        return to_tensor(image.convert("RGB"), self.checkpoint["img_size"]).to(self.device)

    def predict(self, image: Image.Image) -> list[float]:
        """Sigmoid probability per label, in checkpoint order (M, C, G, D)."""
        import torch

        tensor = self._tensor(image)
        with self._lock, torch.no_grad():
            return torch.sigmoid(self.model(tensor))[0].cpu().tolist()

    def explain(self, image: Image.Image, class_indices: list[int]) -> dict[int, list[list[float]] | None]:
        """Grad-CAM grid (values 0-1) per requested class, or None when the map is empty."""
        from src.gradcam import grad_cam

        tensor = self._tensor(image)
        out: dict[int, list[list[float]] | None] = {}
        with self._lock:
            for i in class_indices:
                cam = grad_cam(self.model, tensor, self.layer, i)
                out[i] = None if cam is None else np.round(cam, 4).tolist()
        return out


screener: Screener | None = None


def load_screener() -> None:
    """Called once from the lifespan. Never raises: on failure the app serves fixtures."""
    global screener
    if settings.USE_MOCKS:
        logger.info("USE_MOCKS=true: model not loaded; serving fixtures")
        screener = None
        return
    try:
        screener = Screener()
        logger.info("Model loaded on %s (labels %s)", screener.device, screener.labels)
    except Exception:
        logger.exception("Model failed to load from %s; serving fixtures", settings.model_checkpoint_path)
        screener = None
