# RetinaScreen backend

FastAPI + SQLModel (SQLite) API for the RetinaScreen web app. It loads the repository's EfficientNet-B0 checkpoint once at start-up, and also serves the built frontend (`../frontend/dist`) on the same port.

## Setup (≈5 minutes)

Prerequisites: Python 3.10+ and the repository venv with the ML requirements (`pip install -r ../requirements.txt`).

```bash
cd backend
pip install -r requirements.txt            # exact versions: requirements.lock.txt
cp .env.example .env                       # set JWT_SECRET (64 hex) and DEMO_PASSWORD (8+ chars)
python -m app.seed --reset                 # tables + eight seeded ODIR test-split screenings
uvicorn app.main:app --port 7860           # http://127.0.0.1:7860 , API docs at /docs
```

`.env` values are validated at start-up; a missing or short `JWT_SECRET` / `DEMO_PASSWORD` stops the server with a readable message. Relative paths resolve against `backend/`.

## Commands

| Command | What it does |
|---|---|
| `python -m app.seed --reset` | Drops tables and uploaded photos, reseeds users, 8 screenings and 2 reviews (< 1 s). |
| `python -m app.fixtures` | Runs the **real** model on every seeded photo and rewrites `seed_data/signature_fixtures.json` (with each photo's sha256 and Grad-CAM maps). |
| `python -m pytest -q` | Smoke tests with `USE_MOCKS=true`, a temp database and temp uploads (no GPU, no weights). |

## Fallbacks

- `USE_MOCKS=true`: the model is never loaded. Seeded screenings get their precomputed real result, and any other photo gets **503 MODEL_OFFLINE**. There is no default fixture.
- `AUTH_DISABLED=true`: every request acts as the first seeded user (synthetic data only).

## Endpoints (`/api/v1`, see `/docs`)

`POST /auth/login` · `GET /users/me` · `GET /screenings?page&limit&q&status` · `GET /screenings/stats` · `POST /screenings` · `GET|PATCH|DELETE /screenings/{id}` · `PUT|GET /screenings/{id}/image` · `POST /screenings/{id}/analyze` · `GET|POST /screenings/{id}/reviews` · `GET /model` · `POST /demo/reset` (admin) · `GET /health`.

Errors always use `{"success": false, "error": {"code", "message", "fields"?}}`: 400 `VALIDATION_ERROR` / `NO_IMAGE`, 401 `UNAUTHORIZED`, 403 `FORBIDDEN`, 404 `NOT_FOUND`, 409 `CONFLICT`, 413 `PAYLOAD_TOO_LARGE`, 415 `UNSUPPORTED_MEDIA_TYPE`, 422 `IMAGE_QUALITY`, 503 `MODEL_OFFLINE`.

Screening statuses are `pending`, `analyzed` and `reviewed`. The PRD's `refer` flag and `referred` status were removed: the app shows no referral controls.

`pip-audit` was not run for this lock file.
