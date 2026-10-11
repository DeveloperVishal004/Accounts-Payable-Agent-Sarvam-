from collections.abc import Iterator

from sqlmodel import Session, SQLModel, create_engine

from app.config import settings

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False, "timeout": 30},
    pool_size=20,
    max_overflow=20,
)


def init_db() -> None:
    from app import models  # noqa: F401  (register tables)

    SQLModel.metadata.create_all(engine)


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session
