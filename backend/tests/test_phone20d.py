"""Image source and phone + 20D photo preparation.

A phone + 20D shot is simulated from a seed photo: rotated 180 degrees, pasted as a circle covering 45% of the
frame height on a dim, noisy skin-coloured canvas, with a black lens-rim ring around it and two glare spots.
"""
import io

import numpy as np
import pytest
from PIL import Image, ImageDraw
from sqlalchemy import create_engine

from app.core.config import BACKEND_DIR, settings
from app.modules.screenings.migrate import ensure_screening_columns
from app.modules.screenings.phone20d import prepare_phone_20d

API = "/api/v1"
SEED = BACKEND_DIR / "seed_data" / "images"
W, H = 4000, 3000


def simulate(name="normal_115_right.jpg", *, centre=(W // 2, H // 2), glare=True, retina=True, blob=0, seed=0):
    rng = np.random.default_rng(seed)
    canvas = Image.fromarray(np.clip(rng.normal((70, 40, 32), 10, (H, W, 3)), 0, 255).astype(np.uint8))
    d = round(H * 0.45)
    cx, cy = centre
    draw = ImageDraw.Draw(canvas)
    if retina:
        draw.ellipse((cx - d // 2 - 60, cy - d // 2 - 60, cx + d // 2 + 60, cy + d // 2 + 60), fill=(0, 0, 0))  # lens rim
        photo = Image.open(SEED / name).convert("RGB").rotate(180).resize((d, d))
        mask = Image.new("L", (d, d), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, d - 1, d - 1), fill=255)
        canvas.paste(photo, (cx - d // 2, cy - d // 2), mask)
        if glare:
            draw.ellipse((cx - 150, cy - 200, cx - 90, cy - 150), fill=(255, 255, 250))
            draw.ellipse((cx + 100, cy + 80, cx + 170, cy + 130), fill=(255, 255, 245))
        if blob:
            draw.ellipse((cx - blob, cy - blob, cx + blob, cy + blob), fill=(255, 255, 255))
    return canvas


def jpeg(image: Image.Image) -> bytes:
    buf = io.BytesIO()
    image.save(buf, "JPEG", quality=88)
    return buf.getvalue()


@pytest.fixture(autouse=True)
def big_uploads(monkeypatch):
    monkeypatch.setattr(settings, "MAX_UPLOAD_MB", 25)  # a 12-megapixel phone photo is far over the 1 MB test cap


def create(client, auth, source, **extra):
    r = client.post(f"{API}/screenings", headers=auth, json={"eye": "right", "image_source": source, **extra})
    assert r.status_code == 201, r.text
    return r.json()["data"]


def upload(client, auth, sid, data, name="phone.jpg"):
    return client.put(f"{API}/screenings/{sid}/image", headers=auth, files={"file": (name, data, "image/jpeg")})


def test_simulated_phone_shot_is_prepared(client, auth):
    sid = create(client, auth, "phone_20d")["id"]
    r = upload(client, auth, sid, jpeg(simulate()))
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert data["image_source"] == "phone_20d" and data["has_image"]
    meta = data["image"]
    assert meta["width"] == meta["height"] and 1200 < meta["width"] < 1500  # square around the 1350 px circle

    path = settings.upload_dir
    shot = client.get(f"{API}/screenings/{sid}/image", headers=auth)
    stored = Image.open(io.BytesIO(shot.content)).convert("RGB")
    assert stored.size == (meta["width"], meta["height"])
    arr = np.asarray(stored)
    assert arr[:20, :20].max() < 15 and arr[-20:, -20:].max() < 15 and arr[:20, -20:].max() < 15  # black corners

    # Upright again: it matches the original seed photo, not its upside-down copy
    seed = Image.open(SEED / "normal_115_right.jpg").convert("RGB").resize((256, 256))
    small = np.asarray(stored.resize((256, 256))).astype(float)
    yy, xx = np.mgrid[:256, :256]
    inside = (xx - 128) ** 2 + (yy - 128) ** 2 < 100 ** 2
    upright = np.abs(small - np.asarray(seed).astype(float))[inside].mean()
    flipped = np.abs(small - np.asarray(seed.rotate(180)).astype(float))[inside].mean()
    assert upright < flipped and upright < 25

    # Both files exist: the prepared view and the original upload
    from app.core.db import engine
    from app.modules.screenings.models import Screening
    from sqlmodel import Session
    with Session(engine) as session:
        row = session.get(Screening, sid)
        original = row.image_meta["original"]
        assert (path / row.image_filename).is_file() and (path / original["filename"]).is_file()
        assert (path / original["filename"]).stat().st_size == original["bytes"]
        assert set(row.image_meta["circle"]) == {"x", "y", "r"} and 600 < row.image_meta["circle"]["r"] < 700
        assert row.image_meta["glare"] < 0.02
        files = (path / row.image_filename, path / original["filename"])

    assert client.delete(f"{API}/screenings/{sid}", headers=auth).status_code == 200
    assert not any(f.exists() for f in files)  # both removed with the screening


def test_replacing_a_phone_photo_removes_the_old_files(client, auth):
    sid = create(client, auth, "phone_20d")["id"]
    assert upload(client, auth, sid, jpeg(simulate())).status_code == 200
    before = set(settings.upload_dir.iterdir())
    assert upload(client, auth, sid, jpeg(simulate("dr_5_right.jpg", seed=3))).status_code == 200
    after = set(settings.upload_dir.iterdir())
    assert len(after - before) == 2 and len(before - after) == 2  # two new files, two old ones gone
    client.delete(f"{API}/screenings/{sid}", headers=auth)


def test_no_retina_circle_is_rejected_with_a_plain_reason(client, auth):
    sid = create(client, auth, "phone_20d")["id"]
    r = upload(client, auth, sid, jpeg(simulate(retina=False)))
    body = r.json()["error"]
    assert r.status_code == 422 and body["code"] == "IMAGE_QUALITY"
    assert body["message"].startswith("We couldn't find the round view of the retina")
    assert body["fields"]["file"][0]
    assert client.get(f"{API}/screenings/{sid}", headers=auth).json()["data"]["has_image"] is False
    client.delete(f"{API}/screenings/{sid}", headers=auth)


def test_glare_is_rejected_with_a_plain_reason(client, auth):
    sid = create(client, auth, "phone_20d")["id"]
    r = upload(client, auth, sid, jpeg(simulate(blob=300)))
    body = r.json()["error"]
    assert r.status_code == 422 and body["code"] == "IMAGE_QUALITY"
    assert body["message"].startswith("Too much glare from the light") and "GLARE" in body["fields"]["file"][0]
    client.delete(f"{API}/screenings/{sid}", headers=auth)


def test_circle_cut_off_by_the_frame_is_rejected():
    result = prepare_phone_20d(simulate(centre=(W // 2, 560)))  # the circle's top edge is outside the photo
    assert not result.ok and result.reason.startswith("The round view of the retina is cut off")


def test_tiny_circle_is_rejected():
    canvas = simulate(retina=False)
    ImageDraw.Draw(canvas).ellipse((1900, 1400, 2060, 1560), fill=(200, 90, 40))  # a 160 px speck on a 3000 px frame
    result = prepare_phone_20d(canvas)
    assert not result.ok and result.reason.startswith(("The round view of the retina is too small", "We couldn't find"))


def test_glare_spots_alone_are_accepted():
    result = prepare_phone_20d(simulate())
    assert result.ok and result.glare < 0.02 and result.image.width == result.image.height


@pytest.mark.parametrize("name", ["cataract_112_right.jpg", "dr_5_right.jpg", "glaucoma_1234_right.jpg", "myopia_1547_right.jpg"])
def test_other_seed_photos_are_found(name):
    assert prepare_phone_20d(simulate(name)).ok


def test_clinic_upload_is_unchanged(client, auth):
    sid = create(client, auth, "clinic_fundus")["id"]
    raw = (SEED / "cataract_354_right.jpg").read_bytes()
    r = upload(client, auth, sid, raw, "cataract_354_right.jpg")
    assert r.status_code == 200, r.text
    assert "original" not in (r.json()["data"]["image"] or {})
    assert client.get(f"{API}/screenings/{sid}/image", headers=auth).content == raw  # stored byte for byte
    client.delete(f"{API}/screenings/{sid}", headers=auth)


def test_a_screening_without_patient_ref_gets_the_default(client, auth):
    r = client.post(f"{API}/screenings", headers=auth, json={"eye": "right", "image_source": "phone_20d"})
    assert r.status_code == 201
    data = r.json()["data"]
    assert data["patient_ref"] == "Me" and data["image_source"] == "phone_20d"
    plain = client.post(f"{API}/screenings", headers=auth, json={}).json()["data"]
    assert plain["patient_ref"] == "Me" and plain["image_source"] == "unknown"
    assert client.post(f"{API}/screenings", headers=auth, json={"image_source": "tablet"}).status_code == 400
    for sid in (data["id"], plain["id"]):
        client.delete(f"{API}/screenings/{sid}", headers=auth)


def test_changing_the_source_removes_the_photo_and_result(client, auth):
    sid = create(client, auth, "clinic_fundus")["id"]
    assert upload(client, auth, sid, (SEED / "cataract_354_right.jpg").read_bytes()).status_code == 200
    same = client.patch(f"{API}/screenings/{sid}", headers=auth, json={"image_source": "clinic_fundus"}).json()["data"]
    assert same["has_image"] is True  # unchanged source keeps the photo
    changed = client.patch(f"{API}/screenings/{sid}", headers=auth, json={"image_source": "phone_20d"}).json()["data"]
    assert changed["image_source"] == "phone_20d" and changed["has_image"] is False
    assert changed["result"] is None and changed["status"] == "pending"
    assert client.get(f"{API}/screenings/{sid}/image", headers=auth).status_code == 404
    client.delete(f"{API}/screenings/{sid}", headers=auth)


def test_old_database_gets_the_column(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE screening (id INTEGER PRIMARY KEY, owner_id INTEGER, patient_ref VARCHAR)")
        conn.exec_driver_sql("INSERT INTO screening (owner_id, patient_ref) VALUES (1, 'P-0001'), (1, 'P-0002')")
    ensure_screening_columns(engine)
    ensure_screening_columns(engine)  # running it twice changes nothing
    with engine.begin() as conn:
        rows = conn.exec_driver_sql("SELECT patient_ref, image_source FROM screening ORDER BY id").fetchall()
    assert rows == [("P-0001", "unknown"), ("P-0002", "unknown")]


def test_migration_skips_a_fresh_database(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'fresh.db'}")
    ensure_screening_columns(engine)  # no screening table yet: nothing to do, no error
    with engine.begin() as conn:
        assert conn.exec_driver_sql("PRAGMA table_info(screening)").fetchall() == []
