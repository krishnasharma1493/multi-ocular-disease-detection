"""The demo path end to end, plus every error code the frontend relies on."""
from pathlib import Path

from app.core.config import BACKEND_DIR

API = "/api/v1"
SEED_IMG = BACKEND_DIR / "seed_data" / "images" / "cataract_354_right.jpg"


def test_health_and_auth(client, auth):
    assert client.get("/health").json() == {"status": "ok"}
    me = client.get(f"{API}/users/me", headers=auth).json()["data"]
    assert me["email"] == "demo@example.com"
    # 401: no token, bad token, wrong password and unknown email (same message)
    assert client.get(f"{API}/users/me").status_code == 401
    bad = client.get(f"{API}/users/me", headers={"Authorization": "Bearer nope"})
    assert bad.status_code == 401 and bad.json()["error"]["code"] == "UNAUTHORIZED"
    wrong = client.post(f"{API}/auth/login", json={"email": "demo@example.com", "password": "wrong-password"})
    unknown = client.post(f"{API}/auth/login", json={"email": "x@y.z", "password": "wrong-password"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["error"]["message"] == unknown.json()["error"]["message"]
    # 400 validation envelope
    v = client.post(f"{API}/auth/login", json={})
    assert v.status_code == 400 and v.json()["error"]["code"] == "VALIDATION_ERROR" and "email" in v.json()["error"]["fields"]


def test_seeded_story(client, auth, judge):
    page = client.get(f"{API}/screenings?limit=20", headers=auth).json()
    assert page["pagination"]["total"] == 7
    statuses = {s["patient_ref"]: s["status"] for s in page["data"]}
    assert statuses["P-0175"] == "pending" and statuses["P-0152"] == "reviewed"
    assert client.get(f"{API}/screenings?limit=20", headers=judge).json()["pagination"]["total"] == 1
    # Seed 6 is the documented miss: myopia below its threshold
    six = client.get(f"{API}/screenings/6", headers=auth).json()["data"]["result"]
    myopia = next(f for f in six["findings"] if f["code"] == "M")
    assert not myopia["positive"] and myopia["probability"] < myopia["threshold"]
    assert client.get(f"{API}/screenings/2/reviews", headers=auth).json()["data"][0]["decision"] == "agree"
    # Another user's screening is invisible
    assert client.get(f"{API}/screenings/8", headers=auth).status_code == 404


def test_create_upload_analyze_review(client, auth):
    created = client.post(f"{API}/screenings", headers=auth, json={"patient_ref": "P-0180", "eye": "right"})
    assert created.status_code == 201
    sid = created.json()["data"]["id"]
    # 409: review before analysis
    assert client.post(f"{API}/screenings/{sid}/reviews", headers=auth, json={"decision": "agree"}).status_code == 409
    # 400 NO_IMAGE
    assert client.post(f"{API}/screenings/{sid}/analyze", headers=auth).json()["error"]["code"] == "NO_IMAGE"
    # 415 non-image, 413 oversize (MAX_UPLOAD_MB=1 in tests)
    r = client.put(f"{API}/screenings/{sid}/image", headers=auth, files={"file": ("notes.txt", b"hello", "text/plain")})
    assert r.status_code == 415 and r.json()["error"]["code"] == "UNSUPPORTED_MEDIA_TYPE"
    r = client.put(f"{API}/screenings/{sid}/image", headers=auth,
                   files={"file": ("big.jpg", b"\xff" * (1024 * 1024 + 10), "image/jpeg")})
    assert r.status_code == 413 and r.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"
    data = SEED_IMG.read_bytes()
    up = client.put(f"{API}/screenings/{sid}/image", headers=auth, files={"file": (SEED_IMG.name, data, "image/jpeg")})
    assert up.status_code == 200 and up.json()["data"]["has_image"] and up.json()["data"]["status"] == "pending"
    assert client.get(f"{API}/screenings/{sid}/image", headers=auth).content == data
    # Model offline (USE_MOCKS) and no fixture for this new screening -> 503, never a made-up result
    off = client.post(f"{API}/screenings/{sid}/analyze", headers=auth)
    assert off.status_code == 503 and off.json()["error"]["code"] == "MODEL_OFFLINE"
    # Demo mode: seeded pending screening 7 returns its precomputed real result, labelled demo
    seven = client.post(f"{API}/screenings/7/analyze", headers=auth).json()["data"]
    assert seven["overall"] == "Possible: Cataract" and seven["source"] == "fixture" and seven["maps"]
    assert seven["demo"] is True and seven["model"]["thresholds"]
    review = client.post(f"{API}/screenings/7/reviews", headers=auth, json={"decision": "agree", "note": "ok"})
    assert review.status_code == 201
    assert client.get(f"{API}/screenings/7", headers=auth).json()["data"]["status"] == "reviewed"
    assert client.post(f"{API}/screenings/7/reviews", headers=auth, json={"decision": "maybe"}).status_code == 400
    # Edit, search, filter, stats, delete
    assert client.patch(f"{API}/screenings/{sid}", headers=auth, json={"notes": "edited"}).json()["data"]["notes"] == "edited"
    found = client.get(f"{API}/screenings?q=p-018&status=pending", headers=auth).json()
    assert [s["id"] for s in found["data"]] == [sid]
    stats = client.get(f"{API}/screenings/stats", headers=auth).json()["data"]
    assert stats["total"] == 8 and stats["positives"]["Cataract"] >= 2 and len(stats["recent"]) == 5
    assert client.delete(f"{API}/screenings/{sid}", headers=auth).status_code == 200
    assert client.get(f"{API}/screenings/{sid}", headers=auth).status_code == 404


def test_model_card_and_admin_reset(client, auth, judge):
    card = client.get(f"{API}/model", headers=auth).json()["data"]
    assert [d["code"] for d in card["diseases"]] == ["M", "C", "G", "D"]
    assert card["live"] is False and len(card["limitations"]) == 5
    metrics = Path(BACKEND_DIR.parent / "outputs" / "metrics.json")
    if metrics.exists():
        import json

        assert card["test_images"] == json.loads(metrics.read_text())["test"]["num_images"]
    assert client.post(f"{API}/demo/reset", headers=judge).status_code == 403
    assert client.post(f"{API}/demo/reset", headers=auth).status_code == 200
    assert client.get(f"{API}/nope", headers=auth).json()["error"]["code"] == "NOT_FOUND"


def test_seed_photos_are_test_split():
    """Seed photos must be ODIR test-split images, so nobody is shown a photo the model trained on."""
    import csv
    import json

    import pytest

    labels = BACKEND_DIR.parent / "data" / "labels.csv"
    if not labels.exists():
        pytest.skip("data/labels.csv not present on this machine")
    with labels.open(newline="") as fh:
        split = {row["filename"]: row["split"] for row in csv.DictReader(fh)}
    demo = json.loads((BACKEND_DIR / "seed_data" / "demo.json").read_text())
    for s in demo["screenings"]:
        source = s["image"].split("_", 1)[1]  # "cataract_354_right.jpg" -> "354_right.jpg"
        assert split.get(source) == "test", f"{s['image']} ({source}) is not in the test split"
