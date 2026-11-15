import threading
import time
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import file_import as app_file_import
from app import db as app_db
from app import model_routing
from app.db import Base, get_db
from app.main import app


@pytest.fixture
def threaded_scan_database(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'scan-jobs.sqlite3').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    from app import agent_models, file_import, models, notes_models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_db():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    monkeypatch.setitem(app.dependency_overrides, get_db, override_get_db)
    monkeypatch.setattr(app_db, "SessionLocal", session_factory)
    monkeypatch.setattr(model_routing, "SessionLocal", session_factory)
    yield
    engine.dispose()


def wait_for_scan_job(client, directory_id: int, job_id: str, terminal: set[str] | None = None):
    terminal = terminal or {"completed", "failed", "cancelled"}
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        response = client.get(f"/api/authorized-directories/{directory_id}/scan/jobs/{job_id}")
        assert response.status_code == 200
        job = response.json()
        if job["status"] in terminal:
            return job
        time.sleep(0.05)
    raise AssertionError(f"scan job {job_id} did not reach a terminal state")


def create_authorized_directory(client, root: Path) -> int:
    response = client.post(
        "/api/authorized-directories",
        json={"path": str(root), "label": "扫描测试目录"},
    )
    assert response.status_code == 201
    return response.json()["id"]


def test_scan_job_is_persisted_and_reported_through_public_api(threaded_scan_database, client, tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    (root / "lesson.md").write_text("# FastAPI\n", encoding="utf-8")
    directory_id = create_authorized_directory(client, root)

    started = client.post(f"/api/authorized-directories/{directory_id}/scan/jobs")
    assert started.status_code == 200
    initial = started.json()
    assert initial["directory_id"] == directory_id
    assert initial["status"] in {"queued", "running", "completed"}
    assert initial["progress"] >= 0
    assert initial["attempts"] >= 0
    assert initial["max_attempts"] == 3

    finished = wait_for_scan_job(client, directory_id, initial["job_id"])
    assert finished["status"] == "completed", finished
    assert finished["progress"] == 100
    assert finished["attempts"] == 1
    assert finished["result"]["files_scanned"] == 1

    listed = client.get(f"/api/authorized-directories/{directory_id}/scan/jobs")
    assert listed.status_code == 200
    assert listed.json()[0]["job_id"] == initial["job_id"]

    duplicate_after_completion = client.post(f"/api/authorized-directories/{directory_id}/scan/jobs")
    assert duplicate_after_completion.status_code == 200


def test_running_scan_can_be_cancelled_and_retried(threaded_scan_database, client, tmp_path, monkeypatch):
    root = tmp_path / "source"
    root.mkdir()
    (root / "lesson.md").write_text("# Cancellation\n", encoding="utf-8")
    directory_id = create_authorized_directory(client, root)
    scan_started = threading.Event()
    release_scan = threading.Event()
    original_scan = app_file_import._scan_authorized_directory

    def blocked_scan(directory_id, payload, db, progress_callback=None):
        scan_started.set()
        release_scan.wait(timeout=5)
        return original_scan(directory_id, payload, db, progress_callback=progress_callback)

    monkeypatch.setattr(app_file_import, "_scan_authorized_directory", blocked_scan)
    started = client.post(f"/api/authorized-directories/{directory_id}/scan/jobs")
    assert started.status_code == 200
    job_id = started.json()["job_id"]
    assert scan_started.wait(timeout=5)

    cancelled = client.delete(f"/api/authorized-directories/{directory_id}/scan/jobs/{job_id}")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    release_scan.set()
    cancelled_final = wait_for_scan_job(client, directory_id, job_id)
    assert cancelled_final["status"] == "cancelled"
    assert cancelled_final["attempts"] == 1

    retry_started = client.post(f"/api/authorized-directories/{directory_id}/scan/jobs/{job_id}/retry")
    assert retry_started.status_code == 200
    assert retry_started.json()["status"] in {"queued", "running", "completed"}
    assert scan_started.wait(timeout=5)
    release_scan.set()
    retried = wait_for_scan_job(client, directory_id, job_id)
    assert retried["status"] == "completed", retried
    assert retried["attempts"] == 2


def test_scan_job_rejects_retry_while_active_and_after_completion(threaded_scan_database, client, tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    (root / "lesson.md").write_text("# Retry contract\n", encoding="utf-8")
    directory_id = create_authorized_directory(client, root)

    started = client.post(f"/api/authorized-directories/{directory_id}/scan/jobs")
    assert started.status_code == 200
    job_id = started.json()["job_id"]
    active_retry = client.post(f"/api/authorized-directories/{directory_id}/scan/jobs/{job_id}/retry")
    assert active_retry.status_code == 409
    finished = wait_for_scan_job(client, directory_id, job_id)
    assert finished["status"] == "completed", finished
    completed_retry = client.post(f"/api/authorized-directories/{directory_id}/scan/jobs/{job_id}/retry")
    assert completed_retry.status_code == 409
