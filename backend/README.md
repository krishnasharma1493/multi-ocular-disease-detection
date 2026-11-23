# RetinaScreen backend

FastAPI + SQLModel (SQLite) API for the RetinaScreen web app. It loads the repository's EfficientNet-B0 checkpoint once at start-up, and also serves the built frontend (`../frontend/dist`) on the same port.

## Setup (≈5 minutes)

Prerequisites: Python 3.10+ and the repository venv with the ML requirements (`pip install -r ../requirements.txt`).

```bash
cd backend
pip install -r requirements.txt            # exact versions: requirements.lock.txt
cp .env.example .env                       # optional: works without it (demo defaults)
python -m app.seed --reset                 # tables + eight seeded ODIR test-split screenings
uvicorn app.main:app --port 7860           # http://127.0.0.1:7860 , API docs at /docs
```

Sign in as `demo@example.com` or `judge@example.com` with `camp-S3HqmECzyZSY` (public demo password; override `DEMO_PASSWORD` in `.env`). With no `JWT_SECRET`, a random signing key is generated on first start and kept in `backend/.jwt_secret` (git-ignored). `.env` values are validated at start-up; a too-short `JWT_SECRET` / `DEMO_PASSWORD` stops the server with a readable message. Relative paths resolve against `backend/`.

## Commands

| Command | What it does |
|---|---|
| `python -m app.seed --reset` | Drops tables and uploaded photos, reseeds users, 8 screenings and 2 reviews (< 1 s). |
| `python -m app.fixtures` | Runs the **real** model on every seeded photo and rewrites `seed_data/signature_fixtures.json` (with each photo's sha256 and Grad-CAM maps). |
| `python -m knowledge.fetch_nei` | Re-downloads the NEI reference pages for the chat into `knowledge/sources/` (see [knowledge/README.md](knowledge/README.md)). The search index `knowledge.db` rebuilds itself at start-up when they change. |
| `python -m pytest -q` | Smoke tests with `USE_MOCKS=true`, a temp database and temp uploads (no GPU, no weights). |

## Fallbacks

- `USE_MOCKS=true`: the model is never loaded. Seeded screenings get their precomputed real result, and any other photo gets **503 MODEL_OFFLINE**. There is no default fixture.
- `AUTH_DISABLED=true`: every request acts as the first seeded user (synthetic data only).

## Endpoints (`/api/v1`, see `/docs`)

`POST /auth/login` · `GET /users/me` · `GET /screenings?page&limit&q&status` · `GET /screenings/stats` · `POST /screenings` · `GET|PATCH|DELETE /screenings/{id}` · `PUT|GET /screenings/{id}/image` · `POST /screenings/{id}/analyze` · `GET|POST /screenings/{id}/reviews` · `GET|POST /screenings/{id}/chat` · `GET /model` · `POST /demo/reset` (admin) · `GET /health`.

Errors always use `{"success": false, "error": {"code", "message", "fields"?}}`: 400 `VALIDATION_ERROR` / `NO_IMAGE`, 401 `UNAUTHORIZED`, 403 `FORBIDDEN`, 404 `NOT_FOUND`, 409 `CONFLICT`, 413 `PAYLOAD_TOO_LARGE`, 415 `UNSUPPORTED_MEDIA_TYPE`, 422 `IMAGE_QUALITY`, 429 `RATE_LIMITED`, 503 `MODEL_OFFLINE` / `CHAT_UNAVAILABLE`.

## Eye-health chat

Each screening has one chat thread, `GET|POST /api/v1/screenings/{id}/chat` (`app/modules/chat/`). A patient can ask about eye diseases, symptoms, risk factors, tests and treatments, and about their own screenings and history.

- **Grounding.** The server builds the model's context from the database (`context.py`): this screening (date, eye, image source, photo quality, status, each finding's probability, threshold and flag, borderline when within 0.10 of the threshold, demo and experimental-source caveats), the same patient's other screenings (newest 10) with comparability notes, the last 10 turns, and up to 4 NEI passages from `search()` on the new message plus the previous question. Passages are labelled `S1…`. The patient's name, email, notes and patient reference, and other users' data, are never sent.
- **Rules.** The system instructions are a single constant, `SYSTEM_INSTRUCTIONS` in `app/modules/chat/prompts.py`:
  - eye health only, with a one- or two-sentence redirect for anything else (`in_scope: false`), and only the eye part answered in a mixed message;
  - "your report recorded" / "you told me" / "the source says" kept apart, with citations only to the supplied `[S#]`;
  - "the approved sources don't cover it" when they don't;
  - no diagnosis; quality, borderline and experimental caveats kept;
  - urgent symptoms sent to urgent care;
  - plain, brief and kind.
- **Output checks.** The model must return `{"in_scope", "answer", "sources_used"}`. Cited ids that were not supplied are dropped. An invalid reply is retried once.
- **Limits and failures.** Messages are 1–4000 characters (400 `VALIDATION_ERROR`), with 20 questions per screening per hour (429 `RATE_LIMITED`). A missing `GEMINI_API_KEY`, a timeout, an HTTP error or a second invalid reply returns 503 `CHAT_UNAVAILABLE`, and nothing is stored. Screening results are unaffected. Another user's screening id gives 404.
- **Settings** (server-side only, `.env`): `LLM_PROVIDER=gemini`, `GEMINI_API_KEY`, `GEMINI_MODEL=gemini-2.5-flash`, `LLM_TIMEOUT_S=20`. Deleting a screening deletes its messages.

Screening statuses are `pending`, `analyzed` and `reviewed`. The PRD's `refer` flag and `referred` status were removed: the app shows no referral controls.

`pip-audit` was not run for this lock file.
