from datetime import datetime
from enum import Enum
from typing import Any

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel

from app.utils.time import utcnow

MAX_MESSAGE_CHARS = 4000


class ChatRole(str, Enum):
    user = "user"
    assistant = "assistant"


class ChatMessage(SQLModel, table=True):
    """One message of the single chat thread of a screening. Always read with BOTH screening_id and owner_id."""
    id: int | None = Field(default=None, primary_key=True)
    owner_id: int = Field(foreign_key="user.id", index=True)
    screening_id: int = Field(foreign_key="screening.id", index=True)
    role: ChatRole
    content: str = Field(max_length=8000)  # user messages are capped at MAX_MESSAGE_CHARS by the request schema
    in_scope: bool | None = None           # assistant only: False for an off-topic redirect
    sources: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))  # assistant only
    created_at: datetime = Field(default_factory=utcnow, index=True)
