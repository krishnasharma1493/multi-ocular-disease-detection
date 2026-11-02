from collections.abc import Iterator

from sqlmodel import Session, SQLModel, create_engine

from app.core.config import settings

_is_sqlite = settings.database_url.startswith("sqlite")
engine = create_engine(
    settings.database_url,
    # check_same_thread: FastAPI runs sync routes in a threadpool; timeout: wait instead of "database is locked"
    connect_args={"check_same_thread": False, "timeout": 15} if _is_sqlite else {},
)


def init_db() -> None:
    import app.models  # noqa: F401 — registers every table on SQLModel.metadata

    SQLModel.metadata.create_all(engine)


def reset_db() -> None:
    import app.models  # noqa: F401

    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session
