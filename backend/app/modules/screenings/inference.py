"""The trained EfficientNet-B0 checkpoint, loaded once at startup.

`screener` is None when the model is not loaded (USE_MOCKS=true or a load failure). Screenings then
fail with 503 MODEL_OFFLINE, unless DEMO_FIXTURES=true lets seeded samples show a labelled demo result.
"""
import hashlib
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from typing import Any, Callable, TypeVar

import numpy as np
from PIL import Image

from app.core.config import settings

logger = logging.getLogger(__name__)
T = TypeVar("T")

# One worker: the model runs one screening at a time, and a slow one can't pile up threads
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="inference")


class InferenceTimeout(Exception):
    pass


def run_with_timeout(fn: Callable[[], T], timeout_s: float) -> T:
    """Run fn on the inference thread; raise InferenceTimeout if it (plus any queue wait) takes too long.

    PyTorch can't be interrupted, so a timed-out call still finishes in the background; the request
    just stops waiting for it and the next screening queues behind it.
    """
    future = _executor.submit(fn)
    try:
        return future.result(timeout=timeout_s)
    except FutureTimeout:
        future.cancel()  # only helps if it hadn't started yet
        raise InferenceTimeout(f"no result within {timeout_s:g} s") from None


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class Screener:
    """predict() and explain() are thread-safe (one forward pass at a time)."""

    def __init__(self) -> None:
        # Imported here so a missing or broken PyTorch only disables live mode instead of crashing the app
        from src.gradcam import target_layer
        from src.model import get_device, load_checkpoint

        self.device = get_device() if settings.MODEL_DEVICE == "auto" else settings.MODEL_DEVICE
        self.model, self.checkpoint = load_checkpoint(str(settings.model_checkpoint_path), self.device)
        self.checkpoint_sha256 = _sha256(str(settings.model_checkpoint_path))
        self.layer_name, self.layer = target_layer(self.model, self.checkpoint["model_name"])
        self._lock = threading.Lock()
        self.predict(Image.new("RGB", (512, 512)))  # warm-up: the first MPS call is slow

    @property
    def labels(self) -> list[str]:
        return list(self.checkpoint["labels"])

    @property
    def thresholds(self) -> list[float]:
        return [float(t) for t in self.checkpoint["thresholds"]]

    @property
    def tta(self) -> bool:
        return bool(self.checkpoint.get("tta", False))

    @property
    def temperature(self) -> list[float] | None:
        t = self.checkpoint.get("temperature")
        return [float(x) for x in t] if t is not None else None

    def model_info(self) -> dict[str, Any]:
        """Which model and thresholds produced a result (stored with every live result)."""
        meta = self.checkpoint.get("meta") or {}
        return {"run_id": meta.get("run_id"), "checkpoint_sha256": self.checkpoint_sha256,
                "model_name": self.checkpoint["model_name"], "img_size": self.checkpoint["img_size"],
                "labels": self.labels, "thresholds": self.thresholds, "temperature": self.temperature, "tta": self.tta}

    def _tensor(self, image: Image.Image):
        from src.dataset import to_tensor  # crop_fundus -> resize -> ImageNet normalise, exactly like validation

        return to_tensor(image.convert("RGB"), self.checkpoint["img_size"]).to(self.device)

    def predict(self, image: Image.Image) -> list[float]:
        """Sigmoid probability per label, in checkpoint order (M, C, G, D), calibrated when the checkpoint
        has a temperature (exactly like `src.pipeline.run_evaluation`)."""
        import torch

        from src.model import calibrated_sigmoid, forward_logits

        tensor = self._tensor(image)
        with self._lock, torch.no_grad():
            logits = forward_logits(self.model, tensor, self.tta)  # same flip-averaging the thresholds were fitted with
            return calibrated_sigmoid(logits, self.temperature)[0].cpu().tolist()

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
    """Called once from the lifespan. Never raises: on failure screenings return 503 MODEL_OFFLINE."""
    global screener
    if settings.USE_MOCKS:
        logger.info("USE_MOCKS=true: model not loaded")
        screener = None
        return
    try:
        screener = Screener()
        info = screener.model_info()
        logger.info("Model loaded on %s: run %s, checkpoint sha256 %s, labels %s, thresholds %s",
                    screener.device, info["run_id"] or "not recorded", screener.checkpoint_sha256[:12],
                    screener.labels, [round(t, 3) for t in screener.thresholds])
    except Exception:
        logger.exception("Model failed to load from %s; screenings will return MODEL_OFFLINE",
                         settings.model_checkpoint_path)
        screener = None
