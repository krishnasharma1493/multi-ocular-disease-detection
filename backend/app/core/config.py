import sys
from pathlib import Path
from typing import Literal

from pydantic import Field, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]  # backend/
REPO_ROOT = BACKEND_DIR.parent                      # contains src/, outputs/


class Settings(BaseSettings):
    # .env is read from backend/ whatever directory Uvicorn was started from
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", env_file_encoding="utf-8", extra="ignore")

    APP_ENV: Literal["development", "demo", "test"] = "development"
    PORT: int = 7860

    DATABASE_URL: str = "sqlite:///./app.db"

    JWT_SECRET: str = Field(min_length=32)
    JWT_EXPIRES_MINUTES: int = Field(default=720, ge=5, le=60 * 48)
    DEMO_PASSWORD: str = Field(min_length=8)
    AUTH_DISABLED: bool = False

    CORS_ORIGINS: str = "http://localhost:5173"
    SEED_ON_STARTUP: bool = True

    ENABLE_REALTIME: bool = False
    ENABLE_SCHEDULER: bool = False
    REVIEW_REMINDER_MINUTES: int = Field(default=30, ge=1, le=24 * 60)

    MODEL_CHECKPOINT: str = "../outputs/best_efficientnet_b0.pth"
    MODEL_METRICS: str = "../outputs/metrics.json"
    MODEL_DEVICE: Literal["auto", "cpu", "cuda", "mps"] = "auto"
    USE_MOCKS: bool = False
    # Demo only: when the model is not loaded, seeded sample screenings may show the result the real model
    # produced for them earlier. Off by default, so a live failure is an error, never a stored result.
    DEMO_FIXTURES: bool = False
    # Seconds one screening (forward pass + Grad-CAM) may take before the request fails with 504
    INFERENCE_TIMEOUT_S: float = Field(default=30, gt=0, le=600)

    UPLOAD_DIR: str = "./uploads"
    MAX_UPLOAD_MB: int = Field(default=10, ge=1, le=25)

    # Built React app (npm run build) served on the same port as the API
    FRONTEND_DIST: str = "../frontend/dist"

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip().rstrip("/") for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def max_upload_bytes(self) -> int:
        return self.MAX_UPLOAD_MB * 1024 * 1024

    @staticmethod
    def _resolve(path: str) -> Path:
        """Relative paths are relative to backend/, whatever directory Uvicorn was started from."""
        p = Path(path)
        return p if p.is_absolute() else (BACKEND_DIR / p).resolve()

    @property
    def database_url(self) -> str:
        prefix = "sqlite:///"
        if self.DATABASE_URL.startswith(prefix) and not self.DATABASE_URL.startswith(prefix + "/"):
            return prefix + str(self._resolve(self.DATABASE_URL[len(prefix):]))
        return self.DATABASE_URL

    @property
    def model_checkpoint_path(self) -> Path:
        return self._resolve(self.MODEL_CHECKPOINT)

    @property
    def model_metrics_path(self) -> Path:
        return self._resolve(self.MODEL_METRICS)

    @property
    def upload_dir(self) -> Path:
        return self._resolve(self.UPLOAD_DIR)

    @property
    def frontend_dist(self) -> Path:
        return self._resolve(self.FRONTEND_DIST)


def load_settings() -> Settings:
    try:
        return Settings()  # type: ignore[call-arg]  # values come from env vars / .env
    except ValidationError as exc:
        print(f"Invalid environment variables (check backend/.env):\n{exc}", file=sys.stderr)
        sys.exit(1)


settings = load_settings()
