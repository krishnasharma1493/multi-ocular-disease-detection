"""Model regression gates.

- Golden set: the 8 committed held-out photos must give the recorded probabilities and findings.
  Runs anywhere the checkpoint is (it is committed), so it runs in CI.
- Recall floors: sensitivity on ODIR *validation* photos must not fall below the floors. Validation,
  not test: the test split is scored once per final model and never used as a gate. Needs the local
  data/ folder (not in git), so it is skipped in CI.
"""
import json
from pathlib import Path

import pytest

torch = pytest.importorskip("torch")

from PIL import Image  # noqa: E402

from app.core.config import BACKEND_DIR, settings  # noqa: E402

GOLDEN = json.loads((Path(__file__).parent / "golden" / "golden.json").read_text())
IMAGES = BACKEND_DIR / "seed_data" / "images"
REPO = BACKEND_DIR.parent
# Regression floors, about 5 points under the current model's ODIR validation sensitivity
# (run 20261103-1108-b0-512-ft: M 0.920, C 0.900, G 0.704, D 0.747). Glaucoma and DR floors were raised
# with this model. M and C stay as they were: the new model's sensitivity-first thresholds sit at those
# levels. Raise them when a better model is promoted; never lower them without a written reason. The goals
# for a new model are in src/calibration.py TARGETS.
RECALL_FLOORS = {"M": 0.88, "C": 0.90, "G": 0.65, "D": 0.70}

pytestmark = pytest.mark.skipif(not Path(settings.model_checkpoint_path).is_file(), reason="no checkpoint")


@pytest.fixture(scope="module")
def screener():
    from app.modules.screenings.inference import Screener

    return Screener()


def test_golden_set(screener):
    assert screener.checkpoint_sha256 == GOLDEN["checkpoint_sha256"], (
        "The checkpoint changed. If that is intended, re-record with `python -m tests.golden.update` "
        "and review the diff of golden.json")
    assert screener.labels == GOLDEN["labels"]
    assert screener.thresholds == pytest.approx(GOLDEN["thresholds"], abs=1e-9)
    for name, want in GOLDEN["images"].items():
        probs = screener.predict(Image.open(IMAGES / name).convert("RGB"))
        assert probs == pytest.approx(want["probabilities"], abs=2e-3), name  # CPU / CUDA / MPS differ slightly
        positive = [c for c, p, t in zip(screener.labels, probs, screener.thresholds) if p >= t]
        assert positive == want["positive"], name


def test_odir_validation_recall_floors(screener):
    import numpy as np
    import pandas as pd

    labels_csv = REPO / "data" / "labels.csv"
    if not labels_csv.is_file():
        pytest.skip("data/labels.csv not available (images are not in git)")
    df = pd.read_csv(labels_csv)
    df = df[(df.source == "ODIR") & (df.split == "val")]
    paths = [REPO / p for p in df.path]
    if not all(p.is_file() for p in paths):
        pytest.skip("ODIR images not available")
    probs = np.array([screener.predict(Image.open(p).convert("RGB")) for p in paths])
    recalls = {}
    for i, code in enumerate(screener.labels):
        y = df[code].to_numpy()
        recalls[code] = float((probs[y == 1, i] >= screener.thresholds[i]).mean())
    failing = {c: round(r, 3) for c, r in recalls.items() if r < RECALL_FLOORS[c]}
    assert not failing, f"ODIR validation sensitivity below floor: {failing} (floors {RECALL_FLOORS})"
