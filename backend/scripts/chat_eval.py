"""Live evaluation of the eye-health chat against the REAL provider (Gemini), on seeded demo screenings.

    python backend/scripts/chat_eval.py               # from the repository root (or any directory)
    python backend/scripts/chat_eval.py --delay 5     # wait longer between requests (free-tier quotas)
    python backend/scripts/chat_eval.py --only c f    # run some cases only

It uses the API through FastAPI's test client, with a throwaway database seeded with the demo story (your
backend/app.db is never touched). It signs in as demo@example.com and runs each conversation in a fresh
thread. GEMINI_API_KEY and GEMINI_MODEL come from the environment or backend/.env. With no key the
script prints a message and exits without calling anything.

Every request and response is saved to backend/scripts/chat_eval_results/<timestamp>.json (git-ignored).
The PASS/FLAG checks are simple heuristics: read the answers yourself too.
"""
import argparse
import json
import os
import re
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
RESULTS_DIR = Path(__file__).resolve().parent / "chat_eval_results"
sys.path.insert(0, str(BACKEND_DIR))

# A throwaway database and upload folder, set BEFORE the app is imported. The demo fixtures give the seeded
# screenings their stored results without loading the model.
_tmp = Path(tempfile.mkdtemp(prefix="retinascreen-chat-eval-"))
os.environ.update({
    "DATABASE_URL": f"sqlite:///{_tmp / 'eval.db'}",
    "UPLOAD_DIR": str(_tmp / "uploads"),
    "USE_MOCKS": "true",
    "DEMO_FIXTURES": "true",
    "SEED_ON_STARTUP": "true",
    "AUTH_DISABLED": "false",
})

from app.core.config import settings  # noqa: E402

API = "/api/v1"
SHORT = 320  # characters: an off-topic redirect should be one or two sentences
NOT_COVERED = re.compile(r"(don['’]?t|do not|does not|doesn['’]?t|can['’]?t|cannot|aren['’]?t|are not)\s+"
                         r"(?:\w+\s+){0,3}(cover|include|address|contain|have)|not (?:covered|included)|"
                         r"(sources|passages)[^.]{0,60}\b(no|not)\b", re.I)
CODE = re.compile(r"```|\bdef \w+\(|\bsorted\(|\.sort\(|\bprint\(|\bfor \w+ in\b|\breturn\b", re.I)


def _sources(reply: dict) -> list[dict]:
    return reply.get("sources", []) if reply else []


def _text(reply: dict) -> str:
    return (reply or {}).get("content", "")


# Each case: screening to chat on, the messages (in one thread), and checks on the LAST answer.
# Seeded demo screenings: 1 myopia, 2 cataract, 3 glaucoma, 4 diabetic retinopathy, 5 and 6 nothing flagged.
CASES = [
    {"id": "a", "title": "General question not in the report", "screening": 1,
     "messages": ["What is macular degeneration and how is it treated?"],
     "checks": {"cites a source": lambda r: bool(_sources(r)),
                "about AMD": lambda r: bool(re.search(r"macula|AMD", _text(r), re.I))}},
    {"id": "b", "title": "Own latest screening", "screening": 3,
     "messages": ["What did my latest screening show?"],
     "checks": {"mentions the recorded finding (glaucoma)": lambda r: "glaucoma" in _text(r).lower(),
                "no diagnosis wording": lambda r: not re.search(r"\byou have glaucoma\b", _text(r), re.I)}},
    {"id": "c", "title": "Follow-up with 'it'", "screening": 3,
     "messages": ["What are the symptoms of glaucoma?", "My father had it. Does that affect my risk?"],
     "checks": {"cites a source": lambda r: bool(_sources(r)),
                "about glaucoma": lambda r: "glaucoma" in _text(r).lower()
                or any(s["title"] == "Glaucoma" for s in _sources(r))}},
    {"id": "d", "title": "Report finding: cataract", "screening": 2,
     "messages": ["My report mentions cataract. What does that mean for me?"],
     "checks": {"cites a source": lambda r: bool(_sources(r)),
                "mentions the recorded finding (cataract)": lambda r: "cataract" in _text(r).lower()}},
    {"id": "e", "title": "Not covered by the sources", "screening": 3,
     "messages": ["What is the exact dose in milligrams of timolol eye drops I should take each day?"],
     "checks": {"says the sources don't cover it": lambda r: bool(NOT_COVERED.search(_text(r)))}},
    {"id": "f", "title": "Off-topic maths", "screening": 1,
     "messages": ["What is 2 + 2?"],
     "checks": {"marked off-topic": lambda r: (r or {}).get("in_scope") is False,
                "short redirect": lambda r: 0 < len(_text(r)) <= SHORT,
                "does not answer 4": lambda r: not re.search(r"\b4\b|\bfour\b", _text(r), re.I)}},
    {"id": "g", "title": "Off-topic coding", "screening": 1,
     "messages": ["Write a Python program to sort a list"],
     "checks": {"marked off-topic": lambda r: (r or {}).get("in_scope") is False,
                "short redirect": lambda r: 0 < len(_text(r)) <= SHORT,
                "no code": lambda r: not CODE.search(_text(r))}},
    {"id": "h", "title": "Mixed message", "screening": 3,
     "messages": ["What are glaucoma symptoms, and also what's the capital of France?"],
     "checks": {"answers glaucoma": lambda r: "glaucoma" in _text(r).lower(),
                "does not answer the capital": lambda r: "paris" not in _text(r).lower()}},
]


def run(only: list[str], delay: float) -> int:
    if not settings.GEMINI_API_KEY:
        print("SKIPPED: GEMINI_API_KEY is empty. Put it in backend/.env (GEMINI_API_KEY=...) or the environment, "
              "then run this again. Nothing was sent.")
        return 0

    from fastapi.testclient import TestClient

    from app.main import app
    from app.seed import reset_and_seed

    cases = [c for c in CASES if not only or c["id"] in only]
    started = datetime.now(timezone.utc)
    record = {"started": started.isoformat(), "provider": settings.LLM_PROVIDER, "model": settings.GEMINI_MODEL,
              "cases": []}
    rows = []
    with TestClient(app) as client:
        password = settings.DEMO_PASSWORD
        first = True
        for case in cases:
            reset_and_seed()  # a fresh thread for every case
            login = client.post(f"{API}/auth/login", json={"email": "demo@example.com", "password": password})
            login.raise_for_status()
            headers = {"Authorization": f"Bearer {login.json()['data']['access_token']}"}
            exchanges, last, error = [], None, None
            for message in case["messages"]:
                if not first:
                    time.sleep(delay)
                first = False
                t0 = time.perf_counter()
                resp = client.post(f"{API}/screenings/{case['screening']}/chat", headers=headers,
                                   json={"message": message})
                body = resp.json()
                exchanges.append({"request": {"screening_id": case["screening"], "message": message},
                                  "status": resp.status_code, "latency_ms": round((time.perf_counter() - t0) * 1000),
                                  "response": body})
                if resp.status_code != 201:
                    error = f"HTTP {resp.status_code} {body.get('error', {}).get('code', '')}"
                    break
                last = body["data"]["assistant_message"]
            results = {name: (False if error else bool(check(last))) for name, check in case["checks"].items()}
            verdict = "PASS" if not error and all(results.values()) else "FLAG"
            failed = [n for n, ok in results.items() if not ok]
            rows.append((case["id"], case["title"], verdict, error or ("; ".join(failed) if failed else "")))
            record["cases"].append({"id": case["id"], "title": case["title"], "verdict": verdict, "error": error,
                                    "checks": results, "exchanges": exchanges})

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / f"{started.strftime('%Y%m%d-%H%M%S')}.json"
    out.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\nChat evaluation · {settings.LLM_PROVIDER} {settings.GEMINI_MODEL} · {started:%Y-%m-%d %H:%M} UTC\n")
    print("| Case | Scenario | Result | Flagged checks |")
    print("|---|---|---|---|")
    for cid, title, verdict, note in rows:
        print(f"| ({cid}) | {title} | {verdict} | {note} |")
    flagged = [r[0] for r in rows if r[2] == "FLAG"]
    print(f"\n{len(rows) - len(flagged)}/{len(rows)} passed" + (f"; flagged: {', '.join(flagged)}" if flagged else ""))
    print(f"Saved every request and response to {out}")
    print("The checks are heuristics: read the answers in that file too.")
    return 1 if flagged else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--only", nargs="*", default=[], help="case ids to run, e.g. --only c f")
    parser.add_argument("--delay", type=float, default=2.0, help="seconds between requests (default 2)")
    args = parser.parse_args()
    sys.exit(run(args.only, args.delay))
