"""Live inference never falls back to a stored result; demo results are opt-in and labelled; slow or
failing inference returns a clear error; every live result records which model produced it; the upload
gate explains its rejections. Runs without PyTorch (a fake screener stands in for the model)."""
import io
import time

import numpy as np
import pytest
from PIL import Image, ImageFilter

from app.core.config import BACKEND_DIR, settings
from app.modules.screenings import inference
from app.modules.screenings.service import MIN_SHARPNESS, MIN_SHARPNESS_DISC, image_quality

API = "/api/v1"
SEED = BACKEND_DIR / "seed_data" / "images"


class FakeScreener:
    labels = ["M", "C", "G", "D"]
    thresholds = [0.781, 0.290, 0.542, 0.480]
    layer_name = "features.8"

    def __init__(self, delay=0.0, fail=False):
        self.delay, self.fail = delay, fail

    def predict(self, image):
        time.sleep(self.delay)
        if self.fail:
            raise RuntimeError("device error")
        return [0.01, 0.95, 0.02, 0.10]

    def explain(self, image, class_indices):
        return {i: [[0.0, 1.0], [0.5, 0.2]] for i in class_indices}

    def model_info(self):
        return {"run_id": "20261103-b0-test", "checkpoint_sha256": "ab" * 32, "model_name": "efficientnet_b0",
                "img_size": 384, "labels": self.labels, "thresholds": self.thresholds, "temperature": None}


@pytest.fixture
def live(monkeypatch):
    """Pretend the model is loaded; yields a setter for the fake screener."""
    monkeypatch.setattr(settings, "USE_MOCKS", False)

    def use(screener):
        monkeypatch.setattr(inference, "screener", screener)
    yield use
    inference.run_with_timeout(lambda: None, 10)  # let a timed-out fake finish before the next test


def _analyze(client, auth, sid):
    return client.post(f"{API}/screenings/{sid}/analyze", headers=auth)


def test_fixtures_off_means_model_offline(client, auth, monkeypatch):
    monkeypatch.setattr(settings, "DEMO_FIXTURES", False)
    r = _analyze(client, auth, 7)  # seeded, has a fixture: still no result without the demo setting
    assert r.status_code == 503 and r.json()["error"]["code"] == "MODEL_OFFLINE"


def test_live_failure_is_an_error_not_a_fixture(client, auth, live):
    live(FakeScreener(fail=True))
    r = _analyze(client, auth, 7)  # screening 7 has a fixture and DEMO_FIXTURES is on in tests
    assert r.status_code == 500 and r.json()["error"]["code"] == "INFERENCE_FAILED"
    assert "no result was produced" in r.json()["error"]["message"]


def test_inference_timeout(client, auth, live, monkeypatch):
    monkeypatch.setattr(settings, "INFERENCE_TIMEOUT_S", 0.2)
    live(FakeScreener(delay=1.0))
    r = _analyze(client, auth, 7)
    assert r.status_code == 504 and r.json()["error"]["code"] == "INFERENCE_TIMEOUT"


def test_live_result_records_model_and_is_not_demo(client, auth, live):
    live(FakeScreener())
    sid = client.post(f"{API}/screenings", headers=auth, json={"patient_ref": "P-LIVE"}).json()["data"]["id"]
    photo = (SEED / "cataract_354_right.jpg").read_bytes()
    assert client.put(f"{API}/screenings/{sid}/image", headers=auth,
                      files={"file": ("c.jpg", photo, "image/jpeg")}).status_code == 200
    data = _analyze(client, auth, sid).json()["data"]
    assert data["source"] == "live" and data["demo"] is False
    assert data["model"] == {"run_id": "20261103-b0-test", "checkpoint_sha256": "ab" * 32,
                             "model_name": "efficientnet_b0", "img_size": 384, "labels": ["M", "C", "G", "D"],
                             "thresholds": [0.781, 0.290, 0.542, 0.480], "temperature": None}
    assert data["overall"] == "Possible: Cataract" and [m["disease"] for m in data["maps"]] == ["Cataract"]
    stored = client.get(f"{API}/screenings/{sid}", headers=auth).json()["data"]["result"]
    assert stored["model"]["checkpoint_sha256"] == "ab" * 32  # kept with the screening
    assert client.delete(f"{API}/screenings/{sid}", headers=auth).status_code == 200


# ── Upload gate ──────────────────────────────────────────────────────────────

def _fundus() -> Image.Image:
    return Image.open(SEED / "normal_115_right.jpg").convert("RGB")


def _disc_closeup(img: Image.Image) -> Image.Image:
    """A frame-filling crop of the central retina, like an ACRIMA optic-disc photo (no black border)."""
    w, h = img.size
    return img.crop((int(w * .38), int(h * .38), int(w * .62), int(h * .62))).resize((512, 512), Image.BICUBIC)


def test_quality_reasons():
    ok = image_quality(_fundus())
    assert ok.ok and ok.kind == "full fundus" and ok.minimum == MIN_SHARPNESS
    black = image_quality(Image.new("RGB", (400, 400)))
    assert not black.ok and "almost entirely black" in black.reason
    blue = image_quality(Image.new("RGB", (400, 400), (20, 60, 200)))
    assert not blue.ok and "colours" in blue.reason
    blurred = image_quality(_fundus().filter(ImageFilter.GaussianBlur(12)))
    assert not blurred.ok and blurred.reason.startswith("Too blurred") and "full fundus" in blurred.reason


def test_disc_closeup_gets_its_own_minimum():
    disc = image_quality(_disc_closeup(_fundus()))
    assert disc.kind == "disc close-up" and disc.minimum == MIN_SHARPNESS_DISC


@pytest.mark.parametrize("source", ["ACRIMA", "HYGD", "PAPILA"])
def test_real_glaucoma_photos_pass_the_gate(source):
    """Every held-out photo from the glaucoma datasets is accepted (needs the local data/ folder)."""
    import pandas as pd

    labels = BACKEND_DIR.parent / "data" / "labels.csv"
    if not labels.is_file():
        pytest.skip("data/labels.csv not available")
    df = pd.read_csv(labels)
    paths = df[(df.source == source) & (df.split == "test")].path
    paths = [BACKEND_DIR.parent / p for p in paths if (BACKEND_DIR.parent / p).is_file()]
    if not paths:
        pytest.skip(f"{source} images not available")
    rejected = [p.name for p in paths if not image_quality(Image.open(p).convert("RGB")).ok]
    assert rejected == []


def test_upload_rejection_gives_the_reason(client, auth):
    sid = client.post(f"{API}/screenings", headers=auth, json={"patient_ref": "P-GATE"}).json()["data"]["id"]
    buf = io.BytesIO()
    _fundus().filter(ImageFilter.GaussianBlur(12)).resize((600, 520)).save(buf, "JPEG", quality=85)
    r = client.put(f"{API}/screenings/{sid}/image", headers=auth, files={"file": ("blur.jpg", buf.getvalue(), "image/jpeg")})
    body = r.json()["error"]
    assert r.status_code == 422 and body["code"] == "IMAGE_QUALITY"
    assert body["message"].startswith("Too blurred to screen") and "FULL FUNDUS" in body["fields"]["file"][0]
    assert np.isfinite(float(body["fields"]["file"][0].split()[1]))
    assert client.delete(f"{API}/screenings/{sid}", headers=auth).status_code == 200  # leave the seeded counts as they were
