"""Re-record the golden regression set from the current checkpoint.

    cd backend && python -m tests.golden.update

Run this only on purpose, after promoting a new model: the diff of golden.json then shows exactly
which probabilities and positive findings changed, and the change is reviewed like code.
"""
import json
from pathlib import Path

from PIL import Image

from app.core.config import BACKEND_DIR
from app.modules.screenings.inference import Screener

IMAGES = BACKEND_DIR / "seed_data" / "images"
OUT = Path(__file__).with_name("golden.json")


def main() -> None:
    screener = Screener()
    entries = {}
    for path in sorted(IMAGES.glob("*.jpg")):
        probs = screener.predict(Image.open(path).convert("RGB"))
        entries[path.name] = {"probabilities": [round(p, 5) for p in probs],
                              "positive": [c for c, p, t in zip(screener.labels, probs, screener.thresholds) if p >= t]}
    OUT.write_text(json.dumps({"checkpoint_sha256": screener.checkpoint_sha256, "labels": screener.labels,
                               "thresholds": screener.thresholds, "images": entries}, indent=1) + "\n")
    print(f"Wrote {len(entries)} golden images to {OUT}")


if __name__ == "__main__":
    main()
