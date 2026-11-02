"""Demo data: users, eight screenings with ODIR test-split photos, stored results and two reviews.

    python -m app.seed            # create tables and seed an empty database
    python -m app.seed --reset    # drop everything (tables and uploaded photos) and reseed
"""
import argparse
import json
import secrets
import shutil
from datetime import timedelta
from pathlib import Path

from PIL import Image
from sqlmodel import Session, select

from app.core.config import BACKEND_DIR, settings
from app.core.db import engine, init_db, reset_db
from app.modules.reviews.models import Review, ReviewDecision
from app.modules.screenings.models import Eye, Screening, ScreeningStatus
from app.modules.screenings.service import build_result, image_sha256, load_fixtures
from app.modules.users.models import User
from app.utils.time import utcnow

SEED_DIR = BACKEND_DIR / "seed_data"
SPACING = timedelta(minutes=9)  # seed screenings are spread over the last hour so the ledger reads as a day


def _store_seed_image(name: str) -> tuple[str, dict]:
    source = SEED_DIR / "images" / name
    filename = f"{secrets.token_hex(16)}{Path(name).suffix.lower()}"
    shutil.copyfile(source, settings.upload_dir / filename)
    with Image.open(source) as im:
        meta = {"name": name, "width": im.width, "height": im.height, "type": "JPG" if im.format == "JPEG" else im.format,
                "bytes": source.stat().st_size}
    return filename, meta


def seed(session: Session) -> None:
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    data = json.loads((SEED_DIR / "demo.json").read_text(encoding="utf-8"))
    fixtures = load_fixtures()
    now = utcnow()

    users: dict[str, User] = {}
    for u in data["users"]:
        user = User(email=u["email"].lower(), name=u["name"], is_admin=u.get("is_admin", False))
        session.add(user)
        users[user.email] = user
    session.commit()

    count = len(data["screenings"])
    for i, s in enumerate(data["screenings"]):
        created = now - SPACING * (count - i)
        filename, meta = _store_seed_image(s["image"]) if s.get("image") else (None, None)
        screening = Screening(
            owner_id=users[s["owner"].lower()].id,
            patient_ref=s["patient_ref"],
            eye=Eye(s.get("eye", "unknown")),
            notes=s.get("notes"),
            status=ScreeningStatus(s.get("status", "pending")),
            image_filename=filename,
            image_meta=meta,
            created_at=created,
            updated_at=created,
        )
        session.add(screening)
        session.flush()  # assigns the id used to look up the fixture
        canned = fixtures.get(str(screening.id))
        if screening.status != ScreeningStatus.pending and canned and canned.get("sha256") == image_sha256(filename):
            result = build_result(int(screening.id), canned["labels"], canned["probabilities"], canned["thresholds"],
                                  source="fixture", latency_ms=0, maps=canned.get("maps"))
            screening.result = result.model_dump(mode="json")
            screening.analyzed_at = created
        elif screening.status != ScreeningStatus.pending:
            screening.status = ScreeningStatus.pending  # no stored result: never show a status without one
    session.commit()

    for r in data.get("reviews", []):
        screening = session.get(Screening, r["screening_id"])
        if screening is None or screening.result is None:
            continue
        session.add(Review(owner_id=users[r["owner"].lower()].id, screening_id=r["screening_id"],
                           decision=ReviewDecision(r["decision"]), note=r.get("note"),
                           created_at=screening.created_at + timedelta(minutes=3)))
    session.commit()


def _clear_uploads() -> None:
    if settings.upload_dir.is_dir():
        for path in settings.upload_dir.iterdir():
            if path.is_file():
                path.unlink(missing_ok=True)


def seed_if_empty() -> None:
    with Session(engine) as session:
        if session.exec(select(User)).first() is None:
            seed(session)


def reset_and_seed() -> None:
    reset_db()
    _clear_uploads()
    with Session(engine) as session:
        seed(session)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Create tables and load demo data")
    parser.add_argument("--reset", action="store_true", help="drop all tables and uploaded images first")
    args = parser.parse_args()
    if args.reset:
        reset_and_seed()
    else:
        init_db()
        seed_if_empty()
    print("Demo data ready")
