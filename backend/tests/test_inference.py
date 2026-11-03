"""The app's live inference must match the training/evaluation pipeline and label order.

Guards against the classic causes of "cataract photos come back as diabetic retinopathy":
a different label order, missing eval mode, train-time augmentation, or different preprocessing.
Uses the real checkpoint (skipped when PyTorch or the checkpoint is unavailable).
"""
from pathlib import Path

import pytest

torch = pytest.importorskip("torch")

from PIL import Image  # noqa: E402

from app.core.config import BACKEND_DIR, settings  # noqa: E402
from app.modules.screenings.service import build_result  # noqa: E402

IMAGES = BACKEND_DIR / "seed_data" / "images"
pytestmark = pytest.mark.skipif(not Path(settings.model_checkpoint_path).is_file(), reason="no checkpoint")


@pytest.fixture(scope="module")
def screener():
    from app.modules.screenings.inference import Screener

    return Screener()


def test_matches_evaluation_pipeline(screener):
    """Same photo through the evaluation path (val_transforms on the crop) and the app path."""
    from src.dataset import val_transforms
    from src.preprocessing import crop_fundus

    assert screener.labels == ["M", "C", "G", "D"]
    assert not screener.model.training  # dropout off, batch-norm statistics frozen
    transform = val_transforms(screener.checkpoint["img_size"])
    for name in ("cataract_112_right.jpg", "dr_5_right.jpg", "normal_115_right.jpg"):
        image = Image.open(IMAGES / name).convert("RGB")
        x = transform(image=crop_fundus(image))["image"].unsqueeze(0).to(screener.device)
        with torch.no_grad():
            # Exactly what evaluation does: the checkpoint's own flip-averaging and temperature scaling
            from src.model import calibrated_sigmoid, forward_logits

            logits = forward_logits(screener.model, x, screener.checkpoint.get("tta", False))
            expected = calibrated_sigmoid(logits, screener.checkpoint.get("temperature"))[0].cpu().tolist()
        assert screener.predict(image) == pytest.approx(expected, abs=1e-5)
        assert screener.predict(image) == pytest.approx(expected, abs=1e-5)  # deterministic: no augmentation


@pytest.mark.parametrize("name, expected", [
    ("cataract_112_right.jpg", {"Cataract"}),
    ("cataract_354_right.jpg", {"Cataract"}),
    ("dr_5_right.jpg", {"Diabetic Retinopathy"}),
    ("myopia_1547_right.jpg", {"Myopia"}),
    ("normal_115_right.jpg", set()),
])
def test_held_out_photos_get_the_right_disease(screener, name, expected):
    """ODIR test-split photos (never trained on): the positive set must equal the doctors' label."""
    image = Image.open(IMAGES / name).convert("RGB")
    result = build_result(0, screener.labels, screener.predict(image), screener.thresholds, "live", 0)
    assert {f.disease for f in result.findings if f.positive} == expected
    by_disease = {f.disease: f for f in result.findings}
    if "Cataract" in expected:
        assert not by_disease["Diabetic Retinopathy"].positive
