"""A fresh clone runs with no backend/.env: public demo password, private generated signing key."""
import stat

from app.core import config


def test_defaults_without_env_file(monkeypatch):
    for key in ("JWT_SECRET", "DEMO_PASSWORD"):
        monkeypatch.delenv(key, raising=False)
    s = config.Settings(_env_file=None)  # type: ignore[call-arg]
    assert s.DEMO_PASSWORD == config.DEFAULT_DEMO_PASSWORD
    assert s.JWT_SECRET == ""  # filled in by load_settings from the local key file


def test_generated_signing_key_is_local_stable_and_private(tmp_path, monkeypatch):
    key_file = tmp_path / ".jwt_secret"
    monkeypatch.setattr(config, "JWT_SECRET_FILE", key_file)
    first = config._local_jwt_secret()
    assert len(first) == 64 and key_file.is_file()
    assert stat.S_IMODE(key_file.stat().st_mode) == 0o600  # readable by this user only
    assert config._local_jwt_secret() == first  # same key on every start, so sign-ins survive restarts
