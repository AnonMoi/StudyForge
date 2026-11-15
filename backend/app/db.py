from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

from .config import settings


class Base(DeclarativeBase):
    pass


def _engine_options(database_url: str) -> dict[str, object]:
    if not database_url.startswith("sqlite"):
        return {}
    options: dict[str, object] = {"connect_args": {"check_same_thread": False}}
    # A memory database must share one connection with the scheduler thread;
    # otherwise each thread sees a different empty database.
    if database_url.split("?", 1)[0] in {"sqlite://", "sqlite:///:memory:"}:
        options["poolclass"] = StaticPool
    return options


engine = create_engine(settings.database_url, **_engine_options(settings.database_url))
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    from . import models, notes_models, file_import, agent_models, github_integration, job_analysis  # noqa: F401

    Base.metadata.create_all(bind=engine)
    from .migrations import run_sqlite_migrations

    run_sqlite_migrations(engine)


__all__ = ["Base", "SessionLocal", "engine", "get_db", "init_db"]
