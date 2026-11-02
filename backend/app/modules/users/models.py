from datetime import datetime

from sqlmodel import Field, SQLModel

from app.utils.time import utcnow


class User(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    email: str = Field(index=True, unique=True, max_length=254)
    name: str = Field(max_length=80)
    is_admin: bool = False
    created_at: datetime = Field(default_factory=utcnow)
