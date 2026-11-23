"""GET / POST /api/v1/screenings/{id}/chat: one eye-health chat thread per screening."""
import logging
import re
from datetime import timedelta

from fastapi import APIRouter
from sqlalchemy import func
from sqlmodel import col, select

from app.core.deps import CurrentUser, SessionDep
from app.core.errors import AppError
from app.core.schemas import Envelope
from app.modules.chat import llm
from app.modules.chat.context import ChatContext, build_context
from app.modules.chat.models import ChatMessage, ChatRole
from app.modules.chat.prompts import SYSTEM_INSTRUCTIONS
from app.modules.chat.schemas import ChatExchange, ChatMessageCreate, ChatMessageRead, SourceRef
from app.modules.screenings.models import Screening
from app.utils.ownership import get_owned_or_404
from app.utils.time import utcnow

router = APIRouter(prefix="/screenings", tags=["chat"])
logger = logging.getLogger(__name__)

RATE_LIMIT = 20  # user messages per screening per hour
UNAVAILABLE = "The assistant is unavailable right now. Your screening result is still available."
_CITATION = re.compile(r"\[(S\d+)\]")


def _read(m: ChatMessage) -> ChatMessageRead:
    return ChatMessageRead(id=int(m.id or 0), role=m.role, content=m.content, in_scope=m.in_scope,
                           sources=[SourceRef(**s) for s in (m.sources or [])], created_at=m.created_at)


def _thread(session, screening_id: int, owner_id: int) -> list[ChatMessage]:
    return list(session.exec(
        select(ChatMessage).where(ChatMessage.screening_id == screening_id, ChatMessage.owner_id == owner_id)
        .order_by(col(ChatMessage.created_at), col(ChatMessage.id))).all())


def _generate(ctx: ChatContext) -> dict:
    """Call the provider; one retry when the reply is not the JSON we asked for. Any failure -> 503."""
    system = f"{SYSTEM_INSTRUCTIONS}\n\n{ctx.system_context}"
    try:
        provider = llm.get_provider()
        try:
            return provider.generate(system, ctx.turns)
        except llm.LLMInvalidOutput as exc:
            logger.warning("Chat reply was invalid, retrying once: %s", exc)
            return provider.generate(system, ctx.turns)
    except Exception as exc:  # noqa: BLE001 — every provider failure means "unavailable", never a 500
        logger.warning("Chat unavailable: %s: %s", type(exc).__name__, exc)
        raise AppError(503, "CHAT_UNAVAILABLE", UNAVAILABLE) from None


def _sources(reply: dict, ctx: ChatContext) -> tuple[str, list[dict]]:
    """Keep only citations of passages that were actually supplied, and attach their metadata."""
    answer = reply["answer"]
    cited = [s for s in reply.get("sources_used", []) if isinstance(s, str)] + _CITATION.findall(answer)
    used = [sid for sid in dict.fromkeys(s.strip().strip("[]").upper() for s in cited) if sid in ctx.passages]
    # A citation marker for a passage that was never supplied is removed from the text
    answer = _CITATION.sub(lambda m: m.group(0) if m.group(1) in ctx.passages else "", answer)
    answer = re.sub(r"[ \t]+([.,;:])", r"\1", re.sub(r"[ \t]{2,}", " ", answer)).strip()
    sources = [SourceRef(id=sid, title=p.doc_title, section=p.section, version=p.version, url=p.url,
                         review_status=p.review_status).model_dump()
               for sid in sorted(used, key=lambda s: int(s[1:])) for p in [ctx.passages[sid]]]
    return answer, sources


@router.get("/{screening_id}/chat", response_model=Envelope[list[ChatMessageRead]], summary="Chat thread")
def get_chat(screening_id: int, session: SessionDep, user: CurrentUser):
    get_owned_or_404(session, Screening, screening_id, user.id)
    return Envelope(data=[_read(m) for m in _thread(session, screening_id, int(user.id or 0))])


@router.post("/{screening_id}/chat", response_model=Envelope[ChatExchange], status_code=201,
             summary="Ask the eye-health assistant")
def post_chat(screening_id: int, body: ChatMessageCreate, session: SessionDep, user: CurrentUser):
    screening = get_owned_or_404(session, Screening, screening_id, user.id)
    owner_id = int(user.id or 0)
    since = utcnow() - timedelta(hours=1)
    recent = session.exec(select(func.count()).select_from(ChatMessage).where(
        ChatMessage.screening_id == screening_id, ChatMessage.owner_id == owner_id,
        ChatMessage.role == ChatRole.user, col(ChatMessage.created_at) >= since)).one()
    if recent >= RATE_LIMIT:
        raise AppError(429, "RATE_LIMITED",
                       f"You can ask up to {RATE_LIMIT} questions per screening per hour. Please try again later.")

    ctx = build_context(session, screening, owner_id, body.message)
    reply = _generate(ctx)
    answer, sources = _sources(reply, ctx)

    # Stored only after a successful generation: an outage leaves no half-written exchange
    asked = ChatMessage(owner_id=owner_id, screening_id=screening_id, role=ChatRole.user, content=body.message)
    session.add(asked)
    session.flush()  # the question gets the earlier id and timestamp
    answered = ChatMessage(owner_id=owner_id, screening_id=screening_id, role=ChatRole.assistant,
                           content=answer, in_scope=bool(reply["in_scope"]), sources=sources)
    session.add(answered)
    session.commit()
    session.refresh(asked)
    session.refresh(answered)
    return Envelope(data=ChatExchange(user_message=_read(asked), assistant_message=_read(answered)))
