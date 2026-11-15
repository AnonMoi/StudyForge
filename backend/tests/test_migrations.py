from sqlalchemy import create_engine, inspect, text

from app.db import Base
from app.migrations import MIGRATION_VERSION, run_sqlite_migrations


def test_sqlite_migrations_are_idempotent_and_recorded(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'migration.sqlite3').as_posix()}")
    Base.metadata.create_all(bind=engine)
    run_sqlite_migrations(engine)
    run_sqlite_migrations(engine)

    with engine.connect() as connection:
        versions = connection.execute(text("SELECT version FROM schema_migrations ORDER BY version")).scalars().all()
        assert versions == list(range(1, MIGRATION_VERSION + 1))
        assert inspect(engine).has_table("schema_migrations")
        columns = {column["name"] for column in inspect(engine).get_columns("model_call_logs")}
        assert {"confidence", "route_reason", "retry_count", "fallback_used"}.issubset(columns)
        report_columns = {column["name"] for column in inspect(engine).get_columns("learning_reports")}
        assert {"model_provider", "model_name", "retry_count", "fallback_used"}.issubset(report_columns)
        directory_columns = {column["name"] for column in inspect(engine).get_columns("authorized_directories")}
        assert {"authorized_at", "revoked_at", "last_scanned_at", "scan_enabled"}.issubset(directory_columns)
        assert inspect(engine).has_table("application_state")
        assert inspect(engine).has_table("file_change_alerts")
        assert inspect(engine).has_table("blog_drafts")
        assert inspect(engine).has_table("agent_change_batches")
        turn_columns = {column["name"] for column in inspect(engine).get_columns("chat_turns")}
        assert {"provider", "model_name", "route_reason", "failure_kind"}.issubset(turn_columns)
        assert versions[-1] == MIGRATION_VERSION


def test_migration_adds_legacy_columns(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'legacy.sqlite3').as_posix()}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE knowledge_topics (id INTEGER PRIMARY KEY, name VARCHAR(160))"))
        connection.execute(text("CREATE TABLE authorized_directories (id INTEGER PRIMARY KEY, path VARCHAR(1024))"))
        connection.execute(text("CREATE TABLE model_call_logs (id INTEGER PRIMARY KEY)"))

    run_sqlite_migrations(engine)

    inspector = inspect(engine)
    assert "tags" in {column["name"] for column in inspector.get_columns("knowledge_topics")}
    assert {"local_analysis", "cloud_transfer", "write_access", "excluded_extensions", "authorized_at", "revoked_at", "last_scanned_at", "scan_enabled"}.issubset(
        {column["name"] for column in inspector.get_columns("authorized_directories")}
    )
    assert {"confidence", "route_reason", "retry_count", "fallback_used"}.issubset(
        {column["name"] for column in inspector.get_columns("model_call_logs")}
    )


def test_migration_is_safe_when_optional_tables_are_missing(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'partial.sqlite3').as_posix()}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE knowledge_topics (id INTEGER PRIMARY KEY, name VARCHAR(160))"))

    run_sqlite_migrations(engine)

    with engine.connect() as connection:
        versions = connection.execute(text("SELECT version FROM schema_migrations ORDER BY version")).scalars().all()
    assert versions == list(range(1, MIGRATION_VERSION + 1))
    assert "tags" in {column["name"] for column in inspect(engine).get_columns("knowledge_topics")}
    assert inspect(engine).has_table("blog_drafts")


def test_current_version_is_stable_after_repeated_runs(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'stable.sqlite3').as_posix()}")
    Base.metadata.create_all(bind=engine)
    for _ in range(3):
        run_sqlite_migrations(engine)

    with engine.connect() as connection:
        count = connection.execute(text("SELECT COUNT(*) FROM schema_migrations")).scalar_one()
    assert count == MIGRATION_VERSION


def test_schema_migrations_table_has_primary_key(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'pk.sqlite3').as_posix()}")
    Base.metadata.create_all(bind=engine)
    run_sqlite_migrations(engine)

    primary_keys = inspect(engine).get_pk_constraint("schema_migrations")["constrained_columns"]
    assert primary_keys == ["version"]


def test_chat_turn_migration_preserves_legacy_history_without_inventing_ambiguous_pairs(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'legacy-chat.sqlite3').as_posix()}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE chat_messages (id INTEGER PRIMARY KEY, session_id VARCHAR(120) NOT NULL, role VARCHAR(20) NOT NULL, content TEXT NOT NULL, created_at DATETIME NOT NULL)"))
        connection.execute(text("INSERT INTO chat_messages VALUES (1, 'paired', 'user', '问题', '2026-01-01 10:00:00')"))
        connection.execute(text("INSERT INTO chat_messages VALUES (2, 'paired', 'assistant', '回答', '2026-01-01 10:00:01')"))
        connection.execute(text("INSERT INTO chat_messages VALUES (3, 'ambiguous', 'user', 'A', '2026-01-01 11:00:00')"))
        connection.execute(text("INSERT INTO chat_messages VALUES (4, 'ambiguous', 'user', 'B', '2026-01-01 11:00:01')"))
        connection.execute(text("INSERT INTO chat_messages VALUES (5, 'ambiguous', 'assistant', '回答B', '2026-01-01 11:00:02')"))

    run_sqlite_migrations(engine)

    with engine.connect() as connection:
        rows = connection.execute(text("SELECT m.id, m.turn_id, m.persona, t.status FROM chat_messages m JOIN chat_turns t ON t.turn_id=m.turn_id ORDER BY m.id")).all()
    assert rows[0][1] == rows[1][1]
    assert rows[0][2] == rows[1][2] == "legacy"
    assert rows[0][3] == rows[1][3] == "completed"
    assert rows[2][3] == "legacy_unpaired"
    assert rows[3][1] == rows[4][1]
    assert rows[3][3] == rows[4][3] == "completed"


assert MIGRATION_VERSION >= 1
