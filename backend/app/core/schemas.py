from typing import Generic, Literal, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class Envelope(BaseModel, Generic[T]):
    success: Literal[True] = True
    data: T


class Pagination(BaseModel):
    total: int
    page: int
    limit: int
    total_pages: int


class Page(BaseModel, Generic[T]):
    success: Literal[True] = True
    data: list[T]
    pagination: Pagination


class ErrorDetail(BaseModel):
    code: str
    message: str
    fields: dict[str, list[str]] | None = None


class ErrorBody(BaseModel):
    success: Literal[False] = False
    error: ErrorDetail
