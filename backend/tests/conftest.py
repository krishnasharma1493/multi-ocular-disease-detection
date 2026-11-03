"""Test environment: set BEFORE the app is imported, so the developer's app.db and uploads/ are never touched."""
import os
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="retinascreen-test-"))
os.environ.update({
    "APP_ENV": "test",
    "USE_MOCKS": "true",              # no torch weights, no GPU
    "DEMO_FIXTURES": "true",          # demo mode: seeded screenings use their precomputed (labelled) results
    "DATABASE_URL": f"sqlite:///{_tmp / 'test.db'}",
    "UPLOAD_DIR": str(_tmp / "uploads"),
    "JWT_SECRET": "t" * 64,
    "DEMO_PASSWORD": "test-demo-password",
    "SEED_ON_STARTUP": "true",
    "AUTH_DISABLED": "false",
    "MAX_UPLOAD_MB": "1",
})

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.seed import reset_and_seed  # noqa: E402

PASSWORD = os.environ["DEMO_PASSWORD"]


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        reset_and_seed()
        yield c


def _token(client: TestClient, email: str) -> dict[str, str]:
    r = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['data']['access_token']}"}


@pytest.fixture(scope="session")
def auth(client):
    return _token(client, "demo@example.com")


@pytest.fixture(scope="session")
def judge(client):
    return _token(client, "judge@example.com")
