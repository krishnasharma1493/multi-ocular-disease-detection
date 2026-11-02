from datetime import datetime
from enum import Enum

from sqlmodel import Field, SQLModel

from app.utils.time import utcnow


class ReviewDecision(str, Enum):
    agree = "agree"
    disagree = "disagree"
    unsure = "unsure"


class ReviewBase(SQLModel):
    decision: ReviewDecision
    note: str | None = Field(default=None, max_length=1000)


class Review(ReviewBase, table=True):
    id: int | None = Field(default=None, primary_key=True)
    owner_id: int = Field(foreign_key="user.id", index=True)
    screening_id: int = Field(foreign_key="screening.id", index=True)
    created_at: datetime = Field(default_factory=utcnow)
