from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db import Base, get_db
from app.main import app
from app import db as app_db
from app import model_routing
from app import file_import as app_file_import


@pytest.fixture(scope="session")
def test_engine(tmp_path_factory):
    database_path = Path(tmp_path_factory.mktemp("learning-workstation-db")) / "test.sqlite3"
    engine = create_engine(
        f"sqlite:///{database_path.as_posix()}",
        connect_args={"check_same_thread": False},
    )
    from app import models, notes_models, file_import, agent_models, github_integration  # noqa: F401
    Base.metadata.create_all(bind=engine)
    return engine


@pytest.fixture(autouse=True)
def isolated_database(test_engine, tmp_path_factory, monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    connection = test_engine.connect()
    transaction = connection.begin()
    session_factory = sessionmaker(bind=connection, autoflush=False, autocommit=False)
    session = session_factory()

    def override_get_db():
        yield session

    app.dependency_overrides[get_db] = override_get_db
    storage_path = Path(tmp_path_factory.mktemp("learning-workstation-import-storage"))
    monkeypatch.setattr(app_file_import, "data_dir", lambda: storage_path)
    monkeypatch.setattr(app_db, "SessionLocal", lambda: session)
    monkeypatch.setattr(model_routing, "SessionLocal", lambda: session)
    model_routing.router._cache.clear()
    try:
        yield
    finally:
        model_routing.router._cache.clear()
        app.dependency_overrides.clear()
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def db_session(test_engine) -> Generator[Session, None, None]:
    connection = test_engine.connect()
    transaction = connection.begin()
    session = sessionmaker(bind=connection, autoflush=False, autocommit=False)()
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
