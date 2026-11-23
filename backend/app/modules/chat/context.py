"""Everything the model sees, built on the server from the database: never from text the client sends.

Included: this screening (date, eye, image source, photo quality, status, findings with borderline flags and
caveats), the same patient's other screenings (newest 10) with comparability notes, the last turns of this
thread, and NEI passages labelled S1…Sk.

Never included: the user's name or email, screening notes, patient references, or any other user's data.
All patient rows are read with owner_id = the signed-in user.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlmodel import Session, col, select

from app.modules.chat.models import ChatMessage, ChatRole
from app.modules.knowledge.index import Passage, search
from app.modules.screenings.models import Screening

BORDERLINE = 0.10          # |probability - threshold| <= this is borderline
HISTORY_LIMIT = 10         # other screenings of the same patient
CONVERSATION_LIMIT = 20    # last 10 turns = 10 questions and their 10 answers
MAX_PASSAGES = 4
EVALUATED_SOURCE = "clinic_fundus"  # the only image source the model was evaluated on


@dataclass
class ChatContext:
    system_context: str               # appended to SYSTEM_INSTRUCTIONS
    turns: list[dict[str, str]]       # earlier messages, then the new user message
    passages: dict[str, Passage]      # "S1" -> passage


def image_source(screening: Screening) -> str:
    # The image_source column is added by another PR; until then every screening reads as "unknown"
    return getattr(screening, "image_source", None) or "unknown"


def _when(value: datetime | None) -> str:
    return value.strftime("%Y-%m-%d %H:%M UTC") if value else "unknown date"


def _photo(s: Screening) -> tuple[str, bool]:
    """(description, gradable). Gradable = a photo exists and has an AI result."""
    if not s.image_filename:
        return "no photo uploaded", False
    sharp = (s.image_meta or {}).get("sharpness")
    quality = f"sharpness score {sharp}" if sharp is not None else "sharpness not recorded"
    return f"photo present ({quality})", s.result is not None


def _findings(result: dict[str, Any] | None) -> list[str]:
    if not result:
        return ["No AI result yet (not analyzed)."]
    lines = []
    for f in result.get("findings", []):
        p, t = float(f["probability"]), float(f["threshold"])
        flag = "FLAGGED as a possible sign" if f["positive"] else "not flagged"
        border = " - BORDERLINE (within 0.10 of the threshold)" if abs(p - t) <= BORDERLINE else ""
        lines.append(f"{f['disease']}: probability {p:.0%}, threshold {t:.0%}, {flag}{border}")
    return lines


def _caveats(s: Screening) -> list[str]:
    notes = []
    if s.result and s.result.get("demo"):
        notes.append("This result is a stored DEMO result (precomputed for a sample photo), not a live run.")
    source = image_source(s)
    if source != EVALUATED_SOURCE:
        kind = "is a phone photo taken through a 20D lens" if source == "phone_20d" else "comes from an unknown source"
        notes.append(f"EXPERIMENTAL reading: the photo {kind}; the model was only evaluated on clinic fundus "
                     "photos, so this reading may be unreliable.")
    if s.image_filename and (s.image_meta or {}).get("sharpness") is None:
        notes.append("Photo quality (sharpness) was not recorded for this photo.")
    if s.result:
        notes.append("A screening is not a diagnosis; an eye doctor must confirm any finding.")
    return notes


def _describe(s: Screening, label: str) -> list[str]:
    photo, _ = _photo(s)
    lines = [f"{label}: screening #{s.id} on {_when(s.created_at)}, {s.eye.value} eye, image source "
             f"{image_source(s)}, {photo}, status {s.status.value}."]
    if s.result:
        lines.append(f"  Overall line: {s.result.get('overall')}")
    lines += [f"  - {line}" for line in _findings(s.result)]
    lines += [f"  Caveat: {c}" for c in _caveats(s)]
    return lines


def _comparability(current: Screening, other: Screening) -> list[str]:
    reasons = []
    if current.eye != other.eye or "unknown" in (current.eye.value, other.eye.value):
        reasons.append(f"different or unknown eyes ({current.eye.value} vs {other.eye.value})")
    for s in (current, other):
        if not _photo(s)[1]:
            reasons.append(f"screening #{s.id} lacks a gradable photo or an AI result")
        if image_source(s) != EVALUATED_SOURCE:
            reasons.append(f"screening #{s.id} is an experimental reading ({image_source(s)} source)")
    if not reasons:
        return []
    return [f"  Comparability with this screening: NOT reliable ({'; '.join(reasons)}). These records cannot "
            "support a reliable conclusion about change."]


def _records(session: Session, screening: Screening, owner_id: int) -> str:
    lines = ["PATIENT RECORDS (from the database; facts the screening recorded)", ""]
    lines += _describe(screening, "THIS SCREENING")
    others = session.exec(
        select(Screening).where(Screening.owner_id == owner_id, Screening.id != screening.id)
        .order_by(col(Screening.created_at).desc(), col(Screening.id).desc()).limit(HISTORY_LIMIT)
    ).all()
    lines.append("")
    if not others:
        lines.append("HISTORY: no previous screening. This is the patient's only screening on record.")
    else:
        lines.append(f"HISTORY: the patient's other screenings, newest first ({len(others)} shown):")
        for other in others:
            lines += _describe(other, "Other")
            lines += _comparability(screening, other)
    return "\n".join(lines)


def _passages_block(passages: dict[str, Passage]) -> str:
    if not passages:
        return ("REFERENCE PASSAGES: none matched this question. The approved sources do not cover it; "
                "say so and do not cite any source.")
    blocks = ["REFERENCE PASSAGES (National Eye Institute patient pages; cite as [S#])"]
    for sid, p in passages.items():
        blocks.append(f"[{sid}] {p.section} (NEI, updated {p.version})\n{p.text}")
    return "\n\n".join(blocks)


def retrieve(message: str, previous_user_message: str | None) -> list[Passage]:
    """Passages for the new message plus the previous user message, so a follow-up such as
    "My father had it" after a glaucoma question still finds glaucoma passages."""
    found = search(f"{previous_user_message} {message}" if previous_user_message else message, k=MAX_PASSAGES)
    if previous_user_message:  # the new message alone may match passages the combined query diluted
        found += search(message, k=MAX_PASSAGES)
    unique: dict[tuple[str, str], Passage] = {}
    for p in found:
        unique.setdefault((p.url, p.section), p)
    return list(unique.values())[:MAX_PASSAGES]


def build_context(session: Session, screening: Screening, owner_id: int, message: str) -> ChatContext:
    history = session.exec(
        select(ChatMessage).where(ChatMessage.screening_id == screening.id, ChatMessage.owner_id == owner_id)
        .order_by(col(ChatMessage.created_at).desc(), col(ChatMessage.id).desc()).limit(CONVERSATION_LIMIT)
    ).all()[::-1]
    previous = next((m.content for m in reversed(history) if m.role == ChatRole.user), None)
    passages = {f"S{i + 1}": p for i, p in enumerate(retrieve(message, previous))}
    turns = [{"role": m.role.value, "content": m.content} for m in history]
    turns.append({"role": "user", "content": message})
    system_context = "\n\n".join([_records(session, screening, owner_id), _passages_block(passages)])
    return ChatContext(system_context=system_context, turns=turns, passages=passages)
