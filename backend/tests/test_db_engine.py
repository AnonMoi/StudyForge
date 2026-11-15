from sqlalchemy.pool import StaticPool

from app.db import _engine_options


def test_in_memory_sqlite_uses_one_connection_for_background_workers():
    options = _engine_options("sqlite://")

    assert options["connect_args"] == {"check_same_thread": False}
    assert options["poolclass"] is StaticPool


def test_file_sqlite_keeps_normal_pooling():
    options = _engine_options("sqlite:///learning.db")

    assert options["connect_args"] == {"check_same_thread": False}
    assert "poolclass" not in options
