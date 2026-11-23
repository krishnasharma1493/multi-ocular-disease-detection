import tempfile
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlmodel import Session, select

from app.core.config import settings
from app.modules.users.migrate import ensure_user_columns
from app.modules.users.models import User

API = "/api/v1"


def test_register_and_users_me(client):
    register_payload = {
        "name": "  Asha Sharma  ",
        "email": "Asha.Unique@Example.com",
        "password": "eight+chars",
    }
    r = client.post(f"{API}/auth/register", json=register_payload)
    assert r.status_code == 201, r.text
    res = r.json()
    assert res["success"] is True
    data = res["data"]
    assert "access_token" in data and data["access_token"]
    assert data["token_type"] == "bearer"
    user_data = data["user"]
    assert user_data["name"] == "Asha Sharma"
    assert user_data["email"] == "asha.unique@example.com"
    assert user_data["is_admin"] is False
    assert "password_hash" not in user_data
    assert "password_hash" not in r.text

    # Token works on GET /users/me
    token = data["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    me_resp = client.get(f"{API}/users/me", headers=headers)
    assert me_resp.status_code == 200, me_resp.text
    me_data = me_resp.json()["data"]
    assert me_data["email"] == "asha.unique@example.com"
    assert me_data["name"] == "Asha Sharma"
    assert "password_hash" not in me_data
    assert "password_hash" not in me_resp.text


def test_duplicate_email_different_case_409(client):
    first_user = {
        "name": "Original User",
        "email": "duplicate.test@example.com",
        "password": "password123",
    }
    r1 = client.post(f"{API}/auth/register", json=first_user)
    assert r1.status_code == 201, r1.text

    # Duplicate with different casing
    duplicate_payload = {
        "name": "Duplicate User",
        "email": "DUPLICATE.TEST@EXAMPLE.COM",
        "password": "password456",
    }
    r2 = client.post(f"{API}/auth/register", json=duplicate_payload)
    assert r2.status_code == 409, r2.text
    err = r2.json()["error"]
    assert err["code"] == "CONFLICT"
    assert err["message"] == "An account with this email already exists"
    assert "email" in err["fields"]
    assert "password_hash" not in r2.text

    # Duplicate against seeded demo account
    seeded_dup = {
        "name": "Fake Demo",
        "email": "DEMO@example.com",
        "password": "password789",
    }
    r3 = client.post(f"{API}/auth/register", json=seeded_dup)
    assert r3.status_code == 409, r3.text
    assert r3.json()["error"]["code"] == "CONFLICT"


def test_registration_validation_errors(client):
    # Short password
    r_short = client.post(
        f"{API}/auth/register",
        json={"name": "Valid Name", "email": "valid@example.com", "password": "short"},
    )
    assert r_short.status_code == 400
    assert r_short.json()["error"]["code"] == "VALIDATION_ERROR"
    assert "password" in r_short.json()["error"]["fields"]

    # Bad email (no domain dot)
    r_bad_email = client.post(
        f"{API}/auth/register",
        json={"name": "Valid Name", "email": "bad@nodot", "password": "validpassword"},
    )
    assert r_bad_email.status_code == 400
    assert r_bad_email.json()["error"]["code"] == "VALIDATION_ERROR"
    assert "email" in r_bad_email.json()["error"]["fields"]

    # Bad email (no @)
    r_no_at = client.post(
        f"{API}/auth/register",
        json={"name": "Valid Name", "email": "notanemail.com", "password": "validpassword"},
    )
    assert r_no_at.status_code == 400
    assert r_no_at.json()["error"]["code"] == "VALIDATION_ERROR"
    assert "email" in r_no_at.json()["error"]["fields"]

    # Whitespace-only name
    r_blank_name = client.post(
        f"{API}/auth/register",
        json={"name": "   ", "email": "good@example.com", "password": "validpassword"},
    )
    assert r_blank_name.status_code == 400
    assert r_blank_name.json()["error"]["code"] == "VALIDATION_ERROR"
    assert "name" in r_blank_name.json()["error"]["fields"]

    # Missing fields
    r_empty = client.post(f"{API}/auth/register", json={})
    assert r_empty.status_code == 400
    assert r_empty.json()["error"]["code"] == "VALIDATION_ERROR"


def test_login_and_credential_verification(client):
    email = "patient.login@example.com"
    password = "my-secret-password"
    reg = client.post(
        f"{API}/auth/register",
        json={"name": "Login Patient", "email": email, "password": password},
    )
    assert reg.status_code == 201

    # Login with the new password -> 200
    login_ok = client.post(f"{API}/auth/login", json={"email": email, "password": password})
    assert login_ok.status_code == 200
    assert "access_token" in login_ok.json()["data"]
    assert "password_hash" not in login_ok.text

    # Login with the demo password on the new account -> 401 with same message as unknown email
    login_demo_on_new = client.post(
        f"{API}/auth/login",
        json={"email": email, "password": settings.DEMO_PASSWORD},
    )
    unknown = client.post(
        f"{API}/auth/login",
        json={"email": "nonexistent@example.com", "password": "any-password"},
    )
    assert login_demo_on_new.status_code == 401
    assert unknown.status_code == 401
    assert login_demo_on_new.json()["error"]["message"] == unknown.json()["error"]["message"]
    assert login_demo_on_new.json()["error"]["message"] == "Email or password not recognised"

    # Wrong password on registered account -> 401 with same message
    wrong_pw = client.post(
        f"{API}/auth/login",
        json={"email": email, "password": "wrong-password"},
    )
    assert wrong_pw.status_code == 401
    assert wrong_pw.json()["error"]["message"] == unknown.json()["error"]["message"]

    # Seeded demo@example.com still logs in with the demo password
    demo_login = client.post(
        f"{API}/auth/login",
        json={"email": "demo@example.com", "password": settings.DEMO_PASSWORD},
    )
    assert demo_login.status_code == 200
    assert demo_login.json()["data"]["user"]["email"] == "demo@example.com"


def test_patient_screenings_isolation(client):
    email = "isolated.patient@example.com"
    reg = client.post(
        f"{API}/auth/register",
        json={"name": "Isolated Patient", "email": email, "password": "securepassword123"},
    )
    assert reg.status_code == 201
    token = reg.json()["data"]["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # New user's GET /screenings total is 0
    screenings_resp = client.get(f"{API}/screenings", headers=headers)
    assert screenings_resp.status_code == 200
    screenings_data = screenings_resp.json()
    assert screenings_data["pagination"]["total"] == 0
    assert len(screenings_data["data"]) == 0

    # New user accessing a demo screening (e.g. ID 1) -> 404
    demo_screening_resp = client.get(f"{API}/screenings/1", headers=headers)
    assert demo_screening_resp.status_code == 404
    assert demo_screening_resp.json()["error"]["code"] == "NOT_FOUND"


def test_existing_database_migration():
    """Verify that starting against a database created before this change adds password_hash without losing rows."""
    with tempfile.TemporaryDirectory(prefix="migration-test-") as tmpdir:
        db_path = Path(tmpdir) / "pre_change.db"
        engine = create_engine(f"sqlite:///{db_path}")

        # Simulate old database table schema before Issue #19
        with engine.begin() as conn:
            conn.exec_driver_sql(
                "CREATE TABLE user ("
                "  id INTEGER PRIMARY KEY,"
                "  email VARCHAR(254) NOT NULL,"
                "  name VARCHAR(80) NOT NULL,"
                "  is_admin BOOLEAN NOT NULL,"
                "  created_at DATETIME NOT NULL"
                ")"
            )
            conn.exec_driver_sql(
                "INSERT INTO user (id, email, name, is_admin, created_at) "
                "VALUES (1, 'legacy@example.com', 'Legacy User', 0, '2026-01-01 12:00:00')"
            )
            conn.exec_driver_sql(
                "INSERT INTO user (id, email, name, is_admin, created_at) "
                "VALUES (2, 'admin@example.com', 'Admin User', 1, '2026-01-01 12:00:00')"
            )

        # Before migration, check columns
        with engine.begin() as conn:
            cols_before = {r[1] for r in conn.exec_driver_sql("PRAGMA table_info(user)").fetchall()}
            assert "password_hash" not in cols_before

        # Run migration helper
        ensure_user_columns(engine)

        # After migration, check columns and preserved rows
        with engine.begin() as conn:
            cols_after = {r[1] for r in conn.exec_driver_sql("PRAGMA table_info(user)").fetchall()}
            assert "password_hash" in cols_after

            rows = conn.exec_driver_sql("SELECT id, email, name, is_admin, password_hash FROM user ORDER BY id").fetchall()
            assert len(rows) == 2
            assert rows[0] == (1, "legacy@example.com", "Legacy User", 0, None)
            assert rows[1] == (2, "admin@example.com", "Admin User", 1, None)

        # Idempotent: running again does not fail or duplicate columns
        ensure_user_columns(engine)

        # SQLModel Session can query and insert into migrated table
        with Session(engine) as session:
            legacy = session.get(User, 1)
            assert legacy is not None
            assert legacy.email == "legacy@example.com"
            assert legacy.password_hash is None

            new_user = User(
                email="new@example.com",
                name="New Migrated",
                is_admin=False,
                password_hash="scrypt$test$hash",
            )
            session.add(new_user)
            session.commit()
            session.refresh(new_user)
            assert new_user.id == 3
            assert new_user.password_hash == "scrypt$test$hash"
