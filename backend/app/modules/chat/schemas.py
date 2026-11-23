from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.modules.chat.models import MAX_MESSAGE_CHARS, ChatRole


class ChatMessageCreate(BaseModel):
    message: str = Field(max_length=MAX_MESSAGE_CHARS)

    @field_validator("message")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Type a question first")
        return value


class SourceRef(BaseModel):
    id: str              # "S1" … as cited in the answer
    title: str
    section: str
    version: str
    url: str
    review_status: str


class ChatMessageRead(BaseModel):
    id: int
    role: ChatRole
    content: str
    in_scope: bool | None = None
    sources: list[SourceRef] = []
    created_at: datetime


class ChatExchange(BaseModel):
    user_message: ChatMessageRead
    assistant_message: ChatMessageRead
