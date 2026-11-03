"""Screening results: the live model, or a clearly labelled demo result, never a made-up one.

- Live: the model loaded at startup runs on the screening's photo, plus Grad-CAM for each positive disease.
  If it fails or times out, the request fails with a clear error. It never falls back to a stored result.
- Demo (DEMO_FIXTURES=true only): when the model is not loaded, seeded sample screenings may show the
  result the real model produced for that exact photo earlier (`python -m app.fixtures`), marked
  source="fixture", demo=true. Any other screening gets 503 MODEL_OFFLINE.
"""
import hashlib
import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Literal

import cv2
import numpy as np
from PIL import Image

from app.core.config import BACKEND_DIR, settings
from app.core.errors import AppError
from app.modules.screenings import inference
from app.modules.screenings.models import Screening
from app.modules.screenings.schemas import AttentionMap, Finding, ModelInfo, ScreeningResult
from src.labels import DISEASES, LABELS  # display names live in the ML package

logger = logging.getLogger(__name__)
FIXTURES = BACKEND_DIR / "seed_data" / "signature_fixtures.json"
NO_TARGET = "No Myopia, Cataract, Glaucoma or Diabetic Retinopathy detected"
DISCLAIMER = "Research prototype, not a medical device. This is not a diagnosis; confirm with an ophthalmologist."
NAMES = dict(zip(LABELS, DISEASES))
MIN_SHARPNESS = 0.30       # full fundus photo (round field of view on a black background)
MIN_SHARPNESS_DISC = 0.18  # optic-disc close-up that fills the frame: naturally smoother (no fine vessels
                           # at that zoom); the softest real one in ACRIMA scores 0.19


def build_result(
    screening_id: int,
    labels: list[str],
    probabilities: list[float],
    thresholds: list[float],
    source: Literal["live", "fixture"],
    latency_ms: int,
    maps: list[dict[str, Any]] | None = None,
    model: dict[str, Any] | None = None,
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
        model=ModelInfo(**model) if model else ModelInfo(labels=list(labels), thresholds=[float(t) for t in thresholds]),
    )


def load_fixtures() -> dict[str, dict[str, Any]]:
    try:
        return json.loads(FIXTURES.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


@dataclass
class Quality:
    sharpness: float       # 0-1, Laplacian variance on the cropped square the model sees
    minimum: float         # the sharpness this kind of photo needs
    kind: str              # "full fundus" | "disc close-up" | "unknown"
    ok: bool
    reason: str | None     # why it was rejected, in plain words (None when ok)

    @property
    def detail(self) -> str:
        return (f"SHARPNESS {self.sharpness:.3f} · MINIMUM {self.minimum:.2f} · {self.kind.upper()}"
                if self.kind != "unknown" else "NO FUNDUS FOUND IN THE PHOTO")


def image_quality(image: Image.Image) -> Quality:
    """Is this a fundus photo sharp enough to screen? Checked on the cropped square the model sees.

    A full fundus photo is a round field of view on black; an optic-disc close-up (as in ACRIMA) fills
    the whole frame and is naturally smoother, so it gets its own, lower sharpness minimum.
    """
    from src.preprocessing import crop_fundus

    small = cv2.resize(crop_fundus(image), (512, 512), interpolation=cv2.INTER_AREA)
    mask = small.max(axis=2) > 15
    inner = cv2.erode(mask.astype(np.uint8), np.ones((15, 15), np.uint8)) > 0
    if inner.sum() < 1000:
        return Quality(0.0, MIN_SHARPNESS, "unknown", False,
                       "No fundus found: the photo is almost entirely black")
    lap = cv2.Laplacian(cv2.cvtColor(small, cv2.COLOR_RGB2GRAY), cv2.CV_64F)
    sharpness = float(np.clip(np.log10(lap[inner].var() + 1) / 2, 0, 1))
    red, blue = small[..., 0][mask].mean(), small[..., 2][mask].mean()
    if mask.mean() <= 0.2:
        return Quality(sharpness, MIN_SHARPNESS, "unknown", False,
                       "Not a fundus photo: the retina covers too little of the image")
    if red <= blue:
        return Quality(sharpness, MIN_SHARPNESS, "unknown", False,
                       "Not a fundus photo: the colours don't look like a retina (it should be mostly red-orange)")
    # A round full-fundus field covers at most ~87% of its square (ODIR max 0.865); close-ups fill the frame
    disc = mask.mean() >= 0.90
    kind, minimum = ("disc close-up", MIN_SHARPNESS_DISC) if disc else ("full fundus", MIN_SHARPNESS)
    if sharpness < minimum:
        return Quality(sharpness, minimum, kind, False,
                       f"Too blurred to screen: sharpness {sharpness:.3f} is below the {minimum:.2f} "
                       f"a {kind} photo needs. Refocus and retake")
    return Quality(sharpness, minimum, kind, True, None)


def live_result(screener: "inference.Screener", screening_id: int, image: Image.Image) -> ScreeningResult:
    labels, thresholds = screener.labels, screener.thresholds

    def run() -> tuple[list[float], int, dict[int, Any]]:
        started = time.perf_counter()
        probabilities = screener.predict(image)
        latency = round((time.perf_counter() - started) * 1000)
        positive = [i for i, (p, t) in enumerate(zip(probabilities, thresholds)) if round(p, 4) >= round(t, 4)]
        return probabilities, latency, screener.explain(image, positive)

    try:
        probabilities, latency_ms, grids = inference.run_with_timeout(run, settings.INFERENCE_TIMEOUT_S)
    except inference.InferenceTimeout:
        logger.error("Screening %s timed out after %s s", screening_id, settings.INFERENCE_TIMEOUT_S)
        raise AppError(504, "INFERENCE_TIMEOUT",
                       f"The model took longer than {settings.INFERENCE_TIMEOUT_S:g} seconds, so no result was "
                       "produced. Try again in a moment.") from None
    except Exception:  # device error, out of memory, ...
        logger.exception("Live screening %s failed", screening_id)
        raise AppError(500, "INFERENCE_FAILED",
                       "The model failed on this photo, so no result was produced. Try again; if it keeps "
                       "failing, check the server log.") from None
    maps = [{"disease": NAMES.get(labels[i], labels[i]), "layer": screener.layer_name,
             "available": grids[i] is not None, "grid": grids[i]} for i in grids]
    return build_result(screening_id, labels, probabilities, thresholds, "live", latency_ms, maps,
                        screener.model_info())


def run_screening(screening: Screening) -> ScreeningResult:
    screener = None if settings.USE_MOCKS else inference.screener
    if screener is not None:
        try:
            with Image.open(settings.upload_dir / str(screening.image_filename)) as image:
                image = image.convert("RGB")
        except Exception:
            logger.exception("Stored photo for screening %s can't be read", screening.id)
            raise AppError(422, "IMAGE_UNREADABLE",
                           "The stored photo can't be read. Upload it again, then analyze.") from None
        return live_result(screener, int(screening.id or 0), image)
    if settings.DEMO_FIXTURES:
        return _fixture(screening)
    raise AppError(503, "MODEL_OFFLINE", "Model offline: the screening model is not loaded, so this photo "
                   "can't be screened. Check the server log, then restart the server.")


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
        raise AppError(503, "MODEL_OFFLINE", "Model offline: no live result is possible, and this photo "
                       "has no precomputed demo result")
    return fixture_result(int(screening.id or 0), canned)


def fixture_result(screening_id: int, canned: dict[str, Any]) -> ScreeningResult:
    """A demo result: what the real model produced earlier for this exact photo (labelled demo=true)."""
    model = {"run_id": canned.get("run_id"), "checkpoint_sha256": canned.get("checkpoint_sha256"),
             "labels": canned["labels"], "thresholds": canned["thresholds"]}
    return build_result(screening_id, canned["labels"], canned["probabilities"], canned["thresholds"],
                        "fixture", 0, canned.get("maps"), model)
