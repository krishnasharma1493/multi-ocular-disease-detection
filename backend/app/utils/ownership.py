from typing import TypeVar

from sqlmodel import Session, SQLModel

from app.core.errors import AppError

M = TypeVar("M", bound=SQLModel)


def get_owned_or_404(session: Session, model: type[M], obj_id: int, owner_id: int | None) -> M:
    """Load a row only if it belongs to the caller. Always 404, never 403, so we don't confirm it exists."""
    obj = session.get(model, obj_id)
    if obj is None or getattr(obj, "owner_id", None) != owner_id:
        raise AppError(404, "NOT_FOUND", "Resource not found")
    return obj
