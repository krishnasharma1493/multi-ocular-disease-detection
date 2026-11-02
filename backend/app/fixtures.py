"""Precompute seeded screenings' results with the REAL model, for offline use.

    python -m app.fixtures     # requires the model to load (USE_MOCKS=false)

Writes seed_data/signature_fixtures.json keyed by seeded screening id, with the photo's sha256 so a
fixture can only ever describe the exact photo it was computed on. There is no default entry.
"""
import json

from PIL import Image
from sqlmodel import Session, col, select

from app.core.config import settings
from app.core.db import engine
from app.modules.screenings import inference
from app.modules.screenings.models import Screening
from app.modules.screenings.service import FIXTURES, image_sha256, live_result
from app.seed import reset_and_seed


def main() -> None:
    reset_and_seed()
    inference.load_screener()
    screener = inference.screener
    if screener is None:
        raise SystemExit("Model did not load (is USE_MOCKS=true?); cannot precompute fixtures")
    out: dict[str, dict] = {}
    with Session(engine) as session:
        for s in session.exec(select(Screening).order_by(col(Screening.id))).all():
            if s.image_filename is None:
                continue
            with Image.open(settings.upload_dir / s.image_filename) as image:
                result = live_result(screener, int(s.id), image.convert("RGB"))
            out[str(s.id)] = {
                "sha256": image_sha256(s.image_filename),
                "labels": [f.code for f in result.findings],
                "probabilities": [f.probability for f in result.findings],
                "thresholds": [f.threshold for f in result.findings],
                "maps": [m.model_dump() for m in result.maps],
            }
    FIXTURES.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    reset_and_seed()  # stored results on seeded screenings now match the new fixtures
    print(f"Wrote {len(out)} fixtures to {FIXTURES}")


if __name__ == "__main__":
    main()
