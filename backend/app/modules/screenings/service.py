"""Screening results: live model or precomputed fixture, never a made-up result.

- Live: the model loaded at startup runs on the screening's photo, plus Grad-CAM for each positive disease.
- Fixture: when the model is not loaded (USE_MOCKS=true or load failure), seeded screenings use the
  result the real model produced for them (`python -m app.fixtures`). There is no default fixture:
  any other screening gets 503 MODEL_OFFLINE.
"""
import hashlib
import json
import logging
import time
from typing import Any, Literal

import cv2
import numpy as np
from PIL import Image

from app.core.config import BACKEND_DIR, settings
from app.core.errors import AppError
from app.modules.screenings import inference
from app.modules.screenings.models import Screening
from app.modules.screenings.schemas import AttentionMap, Finding, ScreeningResult
from src.labels import DISEASES, LABELS  # display names live in the ML package

logger = logging.getLogger(__name__)
FIXTURES = BACKEND_DIR / "seed_data" / "signature_fixtures.json"
NO_TARGET = "No Myopia, Cataract, Glaucoma or Diabetic Retinopathy detected"
DISCLAIMER = "Research prototype, not a medical device. This is not a diagnosis; confirm with an ophthalmologist."
NAMES = dict(zip(LABELS, DISEASES))
MIN_SHARPNESS = 0.30


def build_result(
    screening_id: int,
    labels: list[str],
    probabilities: list[float],
    thresholds: list[float],
    source: Literal["live", "fixture"],
    latency_ms: int,
    maps: list[dict[str, Any]] | None = None,
) -> ScreeningResult:
    findings = [
        Finding(code=code, disease=NAMES.get(code, code), probability=round(p, 4), threshold=round(t, 4),
                positive=round(p, 4) >= round(t, 4))
        for code, p, t in zip(labels, probabilities, thresholds)
    ]
    positives = [f.disease for f in findings if f.positive]
    return ScreeningResult(
        screening_id=screening_id,
        overall=f"Possible: {', '.join(positives)}" if positives else NO_TARGET,
        any_positive=bool(positives),
        findings=findings,
        maps=[AttentionMap(**m) for m in (maps or [])],
        source=source,
        latency_ms=latency_ms,
        disclaimer=DISCLAIMER,
    )


def load_fixtures() -> dict[str, dict[str, Any]]:
    try:
        return json.loads(FIXTURES.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def image_quality(image: Image.Image) -> tuple[float, bool]:
    """(sharpness 0-1, looks like a fundus photo) on the cropped square the model sees."""
    from src.preprocessing import crop_fundus

    small = cv2.resize(crop_fundus(image), (512, 512), interpolation=cv2.INTER_AREA)
    mask = small.max(axis=2) > 15
    inner = cv2.erode(mask.astype(np.uint8), np.ones((15, 15), np.uint8)) > 0
    if inner.sum() < 1000:
        return 0.0, False
    lap = cv2.Laplacian(cv2.cvtColor(small, cv2.COLOR_RGB2GRAY), cv2.CV_64F)
    sharpness = float(np.clip(np.log10(lap[inner].var() + 1) / 2, 0, 1))
    red, blue = small[..., 0][mask].mean(), small[..., 2][mask].mean()
    return sharpness, bool(mask.mean() > 0.2 and red > blue)


def live_result(screener: "inference.Screener", screening_id: int, image: Image.Image) -> ScreeningResult:
    started = time.perf_counter()
    probabilities = screener.predict(image)
    latency_ms = round((time.perf_counter() - started) * 1000)
    labels, thresholds = screener.labels, screener.thresholds
    positive = [i for i, (p, t) in enumerate(zip(probabilities, thresholds)) if round(p, 4) >= round(t, 4)]
    grids = screener.explain(image, positive)
    maps = [{"disease": NAMES.get(labels[i], labels[i]), "layer": screener.layer_name,
             "available": grids[i] is not None, "grid": grids[i]} for i in positive]
    return build_result(screening_id, labels, probabilities, thresholds, "live", latency_ms, maps)


def run_screening(screening: Screening) -> ScreeningResult:
    screener = inference.screener
    if not settings.USE_MOCKS and screener is not None:
        try:
            with Image.open(settings.upload_dir / str(screening.image_filename)) as image:
                return live_result(screener, int(screening.id or 0), image.convert("RGB"))
        except Exception:  # corrupt file, device error, out of memory
            logger.warning("Live screening failed; trying the fixture", exc_info=True)
    return _fixture(screening)


def image_sha256(filename: str | None) -> str | None:
    if not filename:
        return None
    try:
        return hashlib.sha256((settings.upload_dir / filename).read_bytes()).hexdigest()
    except OSError:
        return None


def _fixture(screening: Screening) -> ScreeningResult:
    canned = load_fixtures().get(str(screening.id))
    # A fixture only describes the exact photo it was computed on (ids can be reused after deletes)
    if canned is None or canned.get("sha256") != image_sha256(screening.image_filename):
        # Never present a canned medical result as if it described this image
        raise AppError(503, "MODEL_OFFLINE", "Model offline: no result for this image")
    return build_result(int(screening.id or 0), canned["labels"], canned["probabilities"], canned["thresholds"],
                        "fixture", 0, canned.get("maps"))
