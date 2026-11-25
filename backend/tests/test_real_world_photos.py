"""Photos from outside the clinic: screenshots with white margins, and small photos.

prepare_fundus must give the model the same input for a photo whether or not it sits on a white or grey
margin, and small photos must get the adjusted cut-offs (cutoffs.py), while full-size photos keep the
trained ones exactly.
"""
import numpy as np
from PIL import Image, ImageDraw

from app.core.config import BACKEND_DIR
from app.modules.screenings.cutoffs import RUN_ID, SMALL_CUTOFFS, cutoffs
from app.modules.screenings.service import image_quality
from app.modules.screenings.summary import patient_summary
from app.modules.screenings.models import ImageSource, Screening
from src.preprocessing import crop_fundus, prepare_fundus

SEED = BACKEND_DIR / "seed_data" / "images" / "normal_115_right.jpg"
TRAINED = [0.9726, 0.1476, 0.2702, 0.3660]


def on_white(photo: Image.Image, label=True) -> Image.Image:
    """A screenshot: white margin to the right and below, with a grey caption box in one corner."""
    canvas = Image.new("RGB", (int(photo.width * 1.15), int(photo.height * 1.25)), "white")
    canvas.paste(photo, (0, 0))
    if label:
        draw = ImageDraw.Draw(canvas)
        draw.rectangle((photo.width - 40, photo.height - 40, photo.width - 4, photo.height - 4), fill=(240, 240, 240))
        draw.text((photo.width - 30, photo.height - 34), "A", fill=(0, 0, 0))
    return canvas


def test_white_margin_is_removed():
    photo = Image.open(SEED).convert("RGB")
    clean = prepare_fundus(photo)
    pasted = prepare_fundus(on_white(photo))
    assert pasted.shape == clean.shape
    assert np.abs(pasted.astype(int) - clean.astype(int)).mean() < 1.0
    assert crop_fundus(on_white(photo)).shape != clean.shape  # the old crop kept the margin


def test_clean_photo_matches_the_training_crop():
    photo = Image.open(SEED).convert("RGB")
    a, b = prepare_fundus(photo), crop_fundus(photo)
    assert a.shape == b.shape and np.abs(a.astype(int) - b.astype(int)).mean() < 1.0


def test_bright_optic_disc_is_kept():
    # A near-white disc inside the retina is part of it, not background
    photo = Image.open(SEED).convert("RGB")
    ImageDraw.Draw(photo).ellipse((330, 230, 390, 290), fill=(250, 248, 245))
    out = prepare_fundus(on_white(photo, label=False))
    assert out[230:290, 330:390].mean() > 200


def test_screenshot_passes_the_quality_check():
    assert image_quality(on_white(Image.open(SEED).convert("RGB"))).ok


def test_full_size_photos_keep_the_trained_cutoffs():
    assert cutoffs(TRAINED, 512, RUN_ID) == TRAINED
    assert cutoffs(TRAINED, 2000, RUN_ID) == TRAINED
    assert cutoffs(TRAINED, 200, "another-run") == TRAINED
    assert cutoffs(TRAINED, None, RUN_ID) == TRAINED


def test_small_photos_get_the_small_photo_cutoffs():
    small = cutoffs(TRAINED, 240, RUN_ID)
    assert np.allclose(small, SMALL_CUTOFFS)
    mid = cutoffs(TRAINED, 400, RUN_ID)
    assert SMALL_CUTOFFS[1] > mid[1] > TRAINED[1]  # cataract: between the two
    assert mid[3] == TRAINED[3]                    # diabetic retinopathy is back to trained from 320 px


def test_small_photo_is_called_less_certain():
    findings = [{"code": c, "disease": d, "probability": 0.01, "threshold": 0.5, "positive": False}
                for c, d in zip("MCGD", ["Myopia", "Cataract", "Glaucoma", "Diabetic Retinopathy"])]
    screening = Screening(id=1, owner_id=1, eye="right", image_source=ImageSource.clinic_fundus,
                          image_filename="x.jpg", image_meta={"sharpness": 0.8},
                          result={"findings": findings, "photo_px": 300})
    assert any("small (300 pixels" in u for u in patient_summary(screening).uncertainty)
    screening.result = {"findings": findings, "photo_px": 900}
    assert not any("pixels across" in u for u in patient_summary(screening).uncertainty)


def test_near_zero_score_is_not_close_to_a_low_cutoff():
    from app.modules.screenings.summary import _plain_finding
    low = {"code": "G", "disease": "Glaucoma", "probability": 0.013, "threshold": 0.093, "positive": False}
    assert not _plain_finding(low, True).borderline
    near = {"code": "D", "disease": "Diabetic Retinopathy", "probability": 0.30, "threshold": 0.366, "positive": False}
    assert _plain_finding(near, True).borderline  # normal cut-offs keep the 0.10 band
