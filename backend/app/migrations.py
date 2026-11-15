from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import Engine, text


MIGRATION_VERSION = 40


def _table_exists(connection, table: str) -> bool:
    return connection.execute(
        text("SELECT 1 FROM sqlite_master WHERE type='table' AND name=:table"),
        {"table": table},
    ).scalar_one_or_none() is not None


def _table_columns(connection, table: str) -> set[str]:
    return {row[1] for row in connection.execute(text(f"PRAGMA table_info({table})"))}


def _add_columns(connection, table: str, columns: Iterable[tuple[str, str]]) -> None:
    if not _table_exists(connection, table):
        return
    existing = _table_columns(connection, table)
    for name, definition in columns:
        if name not in existing:
            connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {definition}"))


def run_sqlite_migrations(engine: Engine) -> None:
    if engine.dialect.name != "sqlite":
        return
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at DATETIME NOT NULL)"))
        current = connection.execute(text("SELECT COALESCE(MAX(version), 0) FROM schema_migrations")).scalar_one()
        if current < 1:
            _add_columns(connection, "knowledge_topics", (("tags", "JSON DEFAULT '[]'"),))
            _add_columns(connection, "authorized_directories", (
                ("local_analysis", "BOOLEAN DEFAULT 1"),
                ("cloud_transfer", "BOOLEAN DEFAULT 0"),
                ("write_access", "BOOLEAN DEFAULT 0"),
                ("excluded_extensions", "JSON DEFAULT '[]'"),
            ))
            _add_columns(connection, "model_call_logs", (("confidence", "FLOAT"), ("route_reason", "VARCHAR(200)")))
            connection.execute(text("INSERT INTO schema_migrations(version, applied_at) VALUES (1, CURRENT_TIMESTAMP)"))
            current = 1
        if current < 2:
            # Keep the migration ledger explicit; v2 records the post-MVP schema baseline.
            connection.execute(text("INSERT INTO schema_migrations(version, applied_at) VALUES (2, CURRENT_TIMESTAMP)"))
            current = 2
        if current < 3:
            _add_columns(connection, "study_tasks", (("project_id", "INTEGER"), ("topic_id", "INTEGER")))
            _add_columns(connection, "daily_logs", (("project_id", "INTEGER"), ("topic_ids", "JSON DEFAULT '[]'"), ("note_ids", "JSON DEFAULT '[]'")))
            _add_columns(connection, "daily_log_reviews", (("quality", "INTEGER"), ("interval_days", "INTEGER DEFAULT 1"), ("ease_factor", "FLOAT DEFAULT 2.5"), ("repetitions", "INTEGER DEFAULT 0"), ("topic_id", "INTEGER")))
            _add_columns(connection, "learning_projects", (("milestones", "JSON DEFAULT '[]'"),))
            _add_columns(connection, "notes", (("folder", "VARCHAR(240) DEFAULT 'Inbox'"), ("source_path", "VARCHAR(1024)"), ("visibility", "VARCHAR(40) DEFAULT 'private'"), ("ai_review_status", "VARCHAR(40) DEFAULT 'not_reviewed'"), ("linked_topic_ids", "JSON DEFAULT '[]'"), ("linked_task_ids", "JSON DEFAULT '[]'"), ("linked_project_ids", "JSON DEFAULT '[]'")))
            _add_columns(connection, "knowledge_topics", (("prerequisites", "JSON DEFAULT '[]'"), ("evidence", "JSON DEFAULT '[]'"), ("last_reviewed_at", "DATETIME"), ("next_review_at", "DATETIME")))
            connection.execute(text("CREATE TABLE IF NOT EXISTS capability_profiles (id INTEGER PRIMARY KEY, name VARCHAR(160) NOT NULL UNIQUE, description TEXT NOT NULL DEFAULT '', level FLOAT NOT NULL DEFAULT 0, confidence FLOAT NOT NULL DEFAULT 0, evidence_count INTEGER NOT NULL DEFAULT 0, last_assessed_at DATETIME, evidence JSON NOT NULL DEFAULT '[]', created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL)"))
            connection.execute(text("CREATE TABLE IF NOT EXISTS capability_evidence (id INTEGER PRIMARY KEY, capability_id INTEGER NOT NULL, source_type VARCHAR(40) NOT NULL, source_id INTEGER, score FLOAT NOT NULL DEFAULT 0, note TEXT NOT NULL DEFAULT '', created_at DATETIME NOT NULL, FOREIGN KEY(capability_id) REFERENCES capability_profiles(id) ON DELETE CASCADE)"))
            connection.execute(text("INSERT INTO schema_migrations(version, applied_at) VALUES (3, CURRENT_TIMESTAMP)"))
            current = 3
        if current < 4:
            _add_columns(connection, "knowledge_topics", (("prerequisites", "JSON DEFAULT '[]'"), ("evidence", "JSON DEFAULT '[]'"), ("last_reviewed_at", "DATETIME"), ("next_review_at", "DATETIME")))
            connection.execute(text("INSERT INTO schema_migrations(version, applied_at) VALUES (4, CURRENT_TIMESTAMP)"))
            current = 4
        if current < 5:
            connection.execute(text("CREATE TABLE IF NOT EXISTS backup_snapshots (id INTEGER PRIMARY KEY, label VARCHAR(200) NOT NULL DEFAULT '手动快照', source VARCHAR(40) NOT NULL DEFAULT 'local', sha256 VARCHAR(64) NOT NULL UNIQUE, payload JSON NOT NULL DEFAULT '{}', summary JSON NOT NULL DEFAULT '{}', created_at DATETIME NOT NULL)"))
            connection.execute(text("CREATE TABLE IF NOT EXISTS restore_batches (id INTEGER PRIMARY KEY, snapshot_id INTEGER, status VARCHAR(40) NOT NULL DEFAULT 'completed', requested_counts JSON NOT NULL DEFAULT '{}', restored_counts JSON NOT NULL DEFAULT '{}', skipped_counts JSON NOT NULL DEFAULT '{}', created_ids JSON NOT NULL DEFAULT '{}', created_at DATETIME NOT NULL, reverted_at DATETIME, FOREIGN KEY(snapshot_id) REFERENCES backup_snapshots(id) ON DELETE SET NULL)"))
            connection.execute(text("INSERT INTO schema_migrations(version, applied_at) VALUES (5, CURRENT_TIMESTAMP)"))
            current = 5
        if current < 6:
            connection.execute(text("CREATE TABLE IF NOT EXISTS agent_plan_proposals (id INTEGER PRIMARY KEY, status VARCHAR(40) NOT NULL DEFAULT 'pending', reason TEXT NOT NULL DEFAULT '', signal_summary JSON NOT NULL DEFAULT '{}', changes JSON NOT NULL DEFAULT '[]', impact JSON NOT NULL DEFAULT '{}', created_at DATETIME NOT NULL, executed_at DATETIME)"))
            connection.execute(text("INSERT INTO schema_migrations(version, applied_at) VALUES (6, CURRENT_TIMESTAMP)"))
            current = 6
        if current < 7:
            _add_columns(connection, "model_call_logs", (("input_tokens", "INTEGER"), ("output_tokens", "INTEGER"), ("total_tokens", "INTEGER")))
            connection.execute(text("INSERT INTO schema_migrations(version, applied_at) VALUES (7, CURRENT_TIMESTAMP)"))
            current = 7
        if current < 8:
            _add_columns(connection, "model_call_logs", (("token_source", "VARCHAR(20)"),))
            connection.execute(text("INSERT INTO schema_migrations(version, applied_at) VALUES (8, CURRENT_TIMESTAMP)"))
            current = 8
        if current < 9:
            connection.execute(text("CREATE TABLE IF NOT EXISTS agent_change_batches (id INTEGER PRIMARY KEY, operation VARCHAR(80) NOT NULL, status VARCHAR(40) NOT NULL DEFAULT 'executed', changes JSON NOT NULL DEFAULT '[]', before_data JSON NOT NULL DEFAULT '[]', after_data JSON NOT NULL DEFAULT '[]', created_at DATETIME NOT NULL, reverted_at DATETIME)"))
            connection.execute(text("INSERT INTO schema_migrations(version, applied_at) VALUES (9, CURRENT_TIMESTAMP)"))
            current = 9
        if current < 10:
            _add_columns(connection, "study_tasks", (("week_key", "VARCHAR(20)"), ("task_type", "VARCHAR(40) NOT NULL DEFAULT 'practice'"), ("expected_outcome", "TEXT NOT NULL DEFAULT ''"), ("agent_feedback", "TEXT NOT NULL DEFAULT ''")))
            connection.execute(text("CREATE TABLE IF NOT EXISTS review_cards (id INTEGER PRIMARY KEY, front TEXT NOT NULL, back TEXT NOT NULL DEFAULT '', hint TEXT NOT NULL DEFAULT '', topic_id INTEGER, source_note_id INTEGER, status VARCHAR(40) NOT NULL DEFAULT 'active', due_date DATE NOT NULL, interval_days INTEGER NOT NULL DEFAULT 1, ease_factor FLOAT NOT NULL DEFAULT 2.5, repetitions INTEGER NOT NULL DEFAULT 0, last_quality INTEGER, created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL, FOREIGN KEY(topic_id) REFERENCES knowledge_topics(id) ON DELETE SET NULL, FOREIGN KEY(source_note_id) REFERENCES notes(id) ON DELETE SET NULL)"))
            connection.execute(text("CREATE TABLE IF NOT EXISTS note_versions (id INTEGER PRIMARY KEY, note_id INTEGER NOT NULL, version_number INTEGER NOT NULL, title VARCHAR(200) NOT NULL, content TEXT NOT NULL DEFAULT '', summary TEXT NOT NULL DEFAULT '', tags JSON NOT NULL DEFAULT '[]', change_note TEXT NOT NULL DEFAULT '', created_at DATETIME NOT NULL, UNIQUE(note_id, version_number), FOREIGN KEY(note_id) REFERENCES notes(id) ON DELETE CASCADE)"))
            connection.execute(text("INSERT INTO schema_migrations(version, applied_at) VALUES (10, CURRENT_TIMESTAMP)"))
            current = 10
        if current < 11:
            connection.execute(text("CREATE TABLE IF NOT EXISTS review_history (id INTEGER PRIMARY KEY, card_id INTEGER NOT NULL, quality INTEGER NOT NULL, interval_before INTEGER NOT NULL DEFAULT 1, interval_after INTEGER NOT NULL DEFAULT 1, ease_before FLOAT NOT NULL DEFAULT 2.5, ease_after FLOAT NOT NULL DEFAULT 2.5, repetitions_before INTEGER NOT NULL DEFAULT 0, repetitions_after INTEGER NOT NULL DEFAULT 0, due_before DATE NOT NULL, due_after DATE NOT NULL, reviewed_at DATETIME NOT NULL, FOREIGN KEY(card_id) REFERENCES review_cards(id) ON DELETE CASCADE)"))
            connection.execute(text("INSERT INTO schema_migrations(version, applied_at) VALUES (11, CURRENT_TIMESTAMP)"))
            current = 11
        if current < 12:
            connection.execute(text("CREATE TABLE IF NOT EXISTS weekly_plans (id INTEGER PRIMARY KEY, week_key VARCHAR(20) NOT NULL UNIQUE, goal_id INTEGER, project_id INTEGER, objective TEXT NOT NULL DEFAULT '', expected_outputs JSON NOT NULL DEFAULT '[]', reflection TEXT NOT NULL DEFAULT '', blockers TEXT NOT NULL DEFAULT '', status VARCHAR(40) NOT NULL DEFAULT 'draft', created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL, FOREIGN KEY(goal_id) REFERENCES learning_goals(id) ON DELETE SET NULL, FOREIGN KEY(project_id) REFERENCES learning_projects(id) ON DELETE SET NULL)"))
            connection.execute(text("INSERT INTO schema_migrations(version, applied_at) VALUES (12, CURRENT_TIMESTAMP)"))
            current = 12
        if current < 13:
            _add_columns(connection, "imported_files", (
                ("raw_file_path", "VARCHAR(1200)"),
                ("content_file_path", "VARCHAR(1200)"),
                ("index_file_path", "VARCHAR(1200)"),
                ("content_sha256", "VARCHAR(64)"),
                ("index_sha256", "VARCHAR(64)"),
                ("index_status", "VARCHAR(40) DEFAULT 'missing'"),
                ("last_verified_at", "DATETIME"),
            ))
            _add_columns(connection, "file_analyses", (
                ("result_file_path", "VARCHAR(1200)"),
                ("result_sha256", "VARCHAR(64)"),
            ))
            connection.execute(text("INSERT INTO schema_migrations(version, applied_at) VALUES (13, CURRENT_TIMESTAMP)"))
            current = 13
        if current < 14:
            connection.execute(text("CREATE TABLE IF NOT EXISTS teaching_sessions (id INTEGER PRIMARY KEY, title VARCHAR(200) NOT NULL, topic_id INTEGER, task_id INTEGER, stage_id INTEGER, status VARCHAR(40) NOT NULL DEFAULT 'active', explanation TEXT NOT NULL DEFAULT '', created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL, FOREIGN KEY(topic_id) REFERENCES knowledge_topics(id) ON DELETE SET NULL, FOREIGN KEY(task_id) REFERENCES study_tasks(id) ON DELETE SET NULL, FOREIGN KEY(stage_id) REFERENCES learning_stages(id) ON DELETE SET NULL)"))
            connection.execute(text("CREATE TABLE IF NOT EXISTS teaching_attempts (id INTEGER PRIMARY KEY, session_id INTEGER NOT NULL, topic_id INTEGER, task_id INTEGER, stage_id INTEGER, phase VARCHAR(40) NOT NULL DEFAULT 'practice', prompt TEXT NOT NULL, expected_answer TEXT NOT NULL DEFAULT '', rubric JSON NOT NULL DEFAULT '[]', user_answer TEXT NOT NULL DEFAULT '', score INTEGER, error_type VARCHAR(80), feedback TEXT NOT NULL DEFAULT '', recommendation TEXT NOT NULL DEFAULT '', review_card_id INTEGER, created_at DATETIME NOT NULL, answered_at DATETIME, evaluated_at DATETIME, FOREIGN KEY(session_id) REFERENCES teaching_sessions(id) ON DELETE CASCADE, FOREIGN KEY(topic_id) REFERENCES knowledge_topics(id) ON DELETE SET NULL, FOREIGN KEY(task_id) REFERENCES study_tasks(id) ON DELETE SET NULL, FOREIGN KEY(stage_id) REFERENCES learning_stages(id) ON DELETE SET NULL, FOREIGN KEY(review_card_id) REFERENCES review_cards(id) ON DELETE SET NULL)"))
            connection.execute(text("INSERT INTO schema_migrations(version, applied_at) VALUES (14, CURRENT_TIMESTAMP)"))
            current = 14
        if current < 15:
            connection.execute(text("CREATE TABLE IF NOT EXISTS backup_merge_batches (id INTEGER PRIMARY KEY, status VARCHAR(40) NOT NULL DEFAULT 'completed', patches JSON NOT NULL DEFAULT '[]', created_at DATETIME NOT NULL, reverted_at DATETIME)"))
            connection.execute(text("INSERT INTO schema_migrations(version, applied_at) VALUES (15, CURRENT_TIMESTAMP)"))
            current = 15
        if current < 16:
            _add_columns(connection, "model_call_logs", (("billing_source", "VARCHAR(40) DEFAULT 'estimated_rate'"),))
            connection.execute(text("INSERT INTO schema_migrations(version, applied_at) VALUES (16, CURRENT_TIMESTAMP)"))
            current = 16
        if current < 17:
            connection.execute(text("CREATE TABLE IF NOT EXISTS provider_bill_imports (id INTEGER PRIMARY KEY, provider VARCHAR(40) NOT NULL, period_start DATE, period_end DATE, source_name VARCHAR(240) NOT NULL DEFAULT 'manual', currency VARCHAR(12) NOT NULL DEFAULT 'CNY', total_amount FLOAT NOT NULL DEFAULT 0, matched_amount FLOAT NOT NULL DEFAULT 0, unmatched_amount FLOAT NOT NULL DEFAULT 0, line_count INTEGER NOT NULL DEFAULT 0, matched_count INTEGER NOT NULL DEFAULT 0, unmatched_count INTEGER NOT NULL DEFAULT 0, lines JSON NOT NULL DEFAULT '[]', created_at DATETIME NOT NULL)"))
            connection.execute(text("INSERT INTO schema_migrations(version, applied_at) VALUES (17, CURRENT_TIMESTAMP)"))
            current = 17
        if current < 18:
            connection.execute(text("CREATE TABLE IF NOT EXISTS provider_bill_syncs (id INTEGER PRIMARY KEY, provider VARCHAR(40) NOT NULL, period_start DATE NOT NULL, period_end DATE NOT NULL, status VARCHAR(40) NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0, max_attempts INTEGER NOT NULL DEFAULT 3, source_name VARCHAR(240), line_count INTEGER NOT NULL DEFAULT 0, bill_import_id INTEGER, error TEXT, started_at DATETIME, last_attempt_at DATETIME, completed_at DATETIME, created_at DATETIME NOT NULL, FOREIGN KEY(bill_import_id) REFERENCES provider_bill_imports(id) ON DELETE SET NULL)"))
            connection.execute(text("INSERT INTO schema_migrations(version, applied_at) VALUES (18, CURRENT_TIMESTAMP)"))
            current = 18
        if current < 19:
            _add_columns(connection, "teaching_attempts", (("evaluation_source", "VARCHAR(40) DEFAULT 'local_deterministic'"), ("evaluation_confidence", "FLOAT"), ("evaluation_details", "JSON DEFAULT '{}'")))
            connection.execute(text("INSERT INTO schema_migrations(version, applied_at) VALUES (19, CURRENT_TIMESTAMP)"))
            current = 19
        if current < 20:
            _add_columns(connection, "study_tasks", (("completed_at", "DATETIME"), ("last_verified_at", "DATETIME"), ("next_review_date", "DATE")))
            connection.execute(text("CREATE TABLE IF NOT EXISTS task_verifications (id INTEGER PRIMARY KEY, task_id INTEGER NOT NULL, target_status VARCHAR(40) NOT NULL, evidence TEXT NOT NULL DEFAULT '', note TEXT NOT NULL DEFAULT '', actual_minutes INTEGER, verified_at DATETIME NOT NULL, created_at DATETIME NOT NULL, FOREIGN KEY(task_id) REFERENCES study_tasks(id) ON DELETE CASCADE)"))
            connection.execute(text("INSERT INTO schema_migrations(version, applied_at) VALUES (20, CURRENT_TIMESTAMP)"))
            current = 20
        if current < 21:
            connection.execute(text("CREATE TABLE IF NOT EXISTS task_time_entries (id INTEGER PRIMARY KEY, task_id INTEGER NOT NULL, started_at DATETIME NOT NULL, paused_at DATETIME, ended_at DATETIME, duration_seconds INTEGER NOT NULL DEFAULT 0, status VARCHAR(20) NOT NULL DEFAULT 'running', created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL, FOREIGN KEY(task_id) REFERENCES study_tasks(id) ON DELETE CASCADE)"))
            connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_task_time_entries_active_task ON task_time_entries(task_id) WHERE status = 'running'"))
            connection.execute(text("INSERT INTO schema_migrations(version, applied_at) VALUES (21, CURRENT_TIMESTAMP)"))
            current = 21
        if current < 22:
            connection.execute(text("CREATE TABLE IF NOT EXISTS learning_reports (id INTEGER PRIMARY KEY, report_type VARCHAR(30) NOT NULL, period_start DATE NOT NULL, period_end DATE NOT NULL, stage_id INTEGER, title VARCHAR(240) NOT NULL, summary TEXT NOT NULL DEFAULT '', evidence JSON NOT NULL DEFAULT '[]', achievements JSON NOT NULL DEFAULT '[]', unfinished_items JSON NOT NULL DEFAULT '[]', weak_points JSON NOT NULL DEFAULT '[]', recommendations JSON NOT NULL DEFAULT '[]', proposed_changes JSON NOT NULL DEFAULT '[]', confidence FLOAT NOT NULL DEFAULT 1.0, source_snapshot JSON NOT NULL DEFAULT '{}', status VARCHAR(30) NOT NULL DEFAULT 'generated', generation_mode VARCHAR(30) NOT NULL DEFAULT 'deterministic', version INTEGER NOT NULL DEFAULT 1, created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL, FOREIGN KEY(stage_id) REFERENCES learning_stages(id) ON DELETE SET NULL)"))
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_learning_reports_period ON learning_reports(report_type, period_start, period_end)"))
            connection.execute(text("INSERT INTO schema_migrations(version, applied_at) VALUES (22, CURRENT_TIMESTAMP)"))
            current = 22
        if current < 23:
            _add_columns(connection, "model_call_logs", (("retry_count", "INTEGER NOT NULL DEFAULT 0"), ("fallback_used", "BOOLEAN NOT NULL DEFAULT 0")))
            connection.execute(text("INSERT INTO schema_migrations(version, applied_at) VALUES (23, CURRENT_TIMESTAMP)"))
            current = 23
        if current < 24:
            _add_columns(connection, "learning_reports", (("model_provider", "VARCHAR(40)"), ("model_name", "VARCHAR(120)"), ("retry_count", "INTEGER NOT NULL DEFAULT 0"), ("fallback_used", "BOOLEAN NOT NULL DEFAULT 0")))
            connection.execute(text("INSERT INTO schema_migrations(version, applied_at) VALUES (24, CURRENT_TIMESTAMP)"))
            current = 24
        if current < 25:
            _add_columns(connection, "authorized_directories", (
                ("authorized_at", "DATETIME"),
                ("revoked_at", "DATETIME"),
                ("last_scanned_at", "DATETIME"),
                ("scan_enabled", "BOOLEAN NOT NULL DEFAULT 1"),
            ))
            directory_columns = _table_columns(connection, "authorized_directories")
            if _table_exists(connection, "authorized_directories"):
                if "created_at" in directory_columns:
                    connection.execute(text("UPDATE authorized_directories SET authorized_at = COALESCE(authorized_at, created_at, CURRENT_TIMESTAMP)"))
                else:
                    connection.execute(text("UPDATE authorized_directories SET authorized_at = CURRENT_TIMESTAMP"))
            connection.execute(text("CREATE TABLE IF NOT EXISTS application_state (key VARCHAR(80) PRIMARY KEY, value JSON NOT NULL DEFAULT '{}', updated_at DATETIME NOT NULL)"))
            connection.execute(text("CREATE TABLE IF NOT EXISTS file_change_alerts (id INTEGER PRIMARY KEY, directory_id INTEGER NOT NULL, relative_path VARCHAR(1024) NOT NULL, change_type VARCHAR(20) NOT NULL, old_sha256 VARCHAR(64), new_sha256 VARCHAR(64), detected_at DATETIME NOT NULL, acknowledged_at DATETIME, FOREIGN KEY(directory_id) REFERENCES authorized_directories(id) ON DELETE CASCADE)"))
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_file_change_alerts_directory ON file_change_alerts(directory_id, acknowledged_at, detected_at)"))
            connection.execute(text("INSERT INTO schema_migrations(version, applied_at) VALUES (25, CURRENT_TIMESTAMP)"))
            current = 25
        if current < 26:
            connection.execute(text("CREATE TABLE IF NOT EXISTS blog_drafts (id INTEGER PRIMARY KEY, source_note_id INTEGER NOT NULL, source_version INTEGER, title VARCHAR(240) NOT NULL, content TEXT NOT NULL DEFAULT '', excerpt TEXT NOT NULL DEFAULT '', status VARCHAR(30) NOT NULL DEFAULT 'draft', generation_mode VARCHAR(30) NOT NULL DEFAULT 'deterministic', model_provider VARCHAR(40), model_name VARCHAR(120), source_snapshot JSON NOT NULL DEFAULT '{}', created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL, FOREIGN KEY(source_note_id) REFERENCES notes(id) ON DELETE CASCADE)"))
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_blog_drafts_source_note ON blog_drafts(source_note_id, created_at)"))
            connection.execute(text("INSERT INTO schema_migrations(version, applied_at) VALUES (26, CURRENT_TIMESTAMP)"))
            current = 26
        if current < 27:
            _add_columns(connection, "review_cards", (
                ("card_type", "VARCHAR(40) NOT NULL DEFAULT 'qa'"),
                ("error_type", "VARCHAR(80)"),
                ("error_count", "INTEGER NOT NULL DEFAULT 0"),
                ("last_error_note", "TEXT NOT NULL DEFAULT ''"),
            ))
            connection.execute(text("CREATE TABLE IF NOT EXISTS knowledge_graph_layouts (id INTEGER PRIMARY KEY, node_positions JSON NOT NULL DEFAULT '{}', zoom FLOAT NOT NULL DEFAULT 1.0, updated_at DATETIME NOT NULL)"))
            connection.execute(text("CREATE TABLE IF NOT EXISTS report_feedback (id INTEGER PRIMARY KEY, report_id INTEGER NOT NULL, feedback_type VARCHAR(40) NOT NULL, note TEXT NOT NULL DEFAULT '', proposed_change JSON NOT NULL DEFAULT '{}', created_at DATETIME NOT NULL, FOREIGN KEY(report_id) REFERENCES learning_reports(id) ON DELETE CASCADE)"))
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_report_feedback_report ON report_feedback(report_id, created_at)"))
            connection.execute(text("INSERT INTO schema_migrations(version, applied_at) VALUES (27, CURRENT_TIMESTAMP)"))
            current = 27
        if current < 28:
            _add_columns(connection, "daily_logs", (
                ("ai_extracted", "JSON DEFAULT '{}'"),
                ("confirmed_fields", "JSON DEFAULT '[]'"),
                ("field_sources", "JSON DEFAULT '{}'"),
            ))
            connection.execute(text("CREATE TABLE IF NOT EXISTS file_write_batches (id INTEGER PRIMARY KEY, directory_id INTEGER NOT NULL, relative_path VARCHAR(1024) NOT NULL, before_exists BOOLEAN NOT NULL DEFAULT 0, before_sha256 VARCHAR(64), before_content TEXT, after_sha256 VARCHAR(64) NOT NULL, status VARCHAR(30) NOT NULL DEFAULT 'written', created_at DATETIME NOT NULL, reverted_at DATETIME, FOREIGN KEY(directory_id) REFERENCES authorized_directories(id) ON DELETE CASCADE)"))
            connection.execute(text("INSERT INTO schema_migrations(version, applied_at) VALUES (28, CURRENT_TIMESTAMP)"))
            current = 28
        if current < 29:
            connection.execute(text("CREATE TABLE IF NOT EXISTS project_milestones (id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL, title VARCHAR(240) NOT NULL, description TEXT NOT NULL DEFAULT '', status VARCHAR(30) NOT NULL DEFAULT 'pending', due_date DATE, order_index INTEGER NOT NULL DEFAULT 0, evidence TEXT NOT NULL DEFAULT '', completed_at DATETIME, created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL, FOREIGN KEY(project_id) REFERENCES learning_projects(id) ON DELETE CASCADE)"))
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_project_milestones_project ON project_milestones(project_id, order_index, id)"))
            connection.execute(text("CREATE TABLE IF NOT EXISTS capability_assessments (id INTEGER PRIMARY KEY, capability_id INTEGER NOT NULL, previous_level FLOAT NOT NULL DEFAULT 0, new_level FLOAT NOT NULL DEFAULT 0, evidence_count INTEGER NOT NULL DEFAULT 0, evidence_snapshot JSON NOT NULL DEFAULT '[]', trigger VARCHAR(40) NOT NULL DEFAULT 'manual', created_at DATETIME NOT NULL, FOREIGN KEY(capability_id) REFERENCES capability_profiles(id) ON DELETE CASCADE)"))
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_capability_assessments_profile ON capability_assessments(capability_id, created_at)"))
            connection.execute(text("CREATE TABLE IF NOT EXISTS practice_exercises (id INTEGER PRIMARY KEY, title VARCHAR(240) NOT NULL, exercise_type VARCHAR(30) NOT NULL, prompt TEXT NOT NULL DEFAULT '', difficulty VARCHAR(30) NOT NULL DEFAULT 'medium', topic_id INTEGER, validation_spec JSON NOT NULL DEFAULT '{}', hints JSON NOT NULL DEFAULT '[]', status VARCHAR(30) NOT NULL DEFAULT 'active', created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL, FOREIGN KEY(topic_id) REFERENCES knowledge_topics(id) ON DELETE SET NULL)"))
            connection.execute(text("CREATE TABLE IF NOT EXISTS practice_attempts (id INTEGER PRIMARY KEY, exercise_id INTEGER NOT NULL, code TEXT NOT NULL DEFAULT '', query TEXT NOT NULL DEFAULT '', answer TEXT NOT NULL DEFAULT '', status VARCHAR(30) NOT NULL DEFAULT 'failed', passed BOOLEAN NOT NULL DEFAULT 0, score FLOAT, feedback TEXT NOT NULL DEFAULT '', stdout TEXT NOT NULL DEFAULT '', stderr TEXT NOT NULL DEFAULT '', duration_ms INTEGER NOT NULL DEFAULT 0, created_at DATETIME NOT NULL, FOREIGN KEY(exercise_id) REFERENCES practice_exercises(id) ON DELETE CASCADE)"))
            connection.execute(text("CREATE TABLE IF NOT EXISTS code_runs (id INTEGER PRIMARY KEY, exercise_id INTEGER, code TEXT NOT NULL, stdin TEXT NOT NULL DEFAULT '', status VARCHAR(30) NOT NULL DEFAULT 'failed', stdout TEXT NOT NULL DEFAULT '', stderr TEXT NOT NULL DEFAULT '', exit_code INTEGER, duration_ms INTEGER NOT NULL DEFAULT 0, policy JSON NOT NULL DEFAULT '{}', created_at DATETIME NOT NULL, FOREIGN KEY(exercise_id) REFERENCES practice_exercises(id) ON DELETE SET NULL)"))
            connection.execute(text("INSERT INTO schema_migrations(version, applied_at) VALUES (29, CURRENT_TIMESTAMP)"))
            current = 29
        if current < 30:
            _add_columns(connection, "review_history", (("error_type", "VARCHAR(80)"), ("error_note", "TEXT NOT NULL DEFAULT ''")))
            connection.execute(text("INSERT INTO schema_migrations(version, applied_at) VALUES (30, CURRENT_TIMESTAMP)"))
            current = 30
        if current < 31:
            connection.execute(text("CREATE TABLE IF NOT EXISTS web_resources (id INTEGER PRIMARY KEY, url VARCHAR(2048) NOT NULL, final_url VARCHAR(2048) NOT NULL, title VARCHAR(500) NOT NULL DEFAULT '', sha256 VARCHAR(64) NOT NULL, size INTEGER NOT NULL DEFAULT 0, mime_type VARCHAR(160), content_status VARCHAR(40) NOT NULL DEFAULT 'metadata_only', parse_error TEXT, raw_file_path VARCHAR(1200), content_file_path VARCHAR(1200), index_file_path VARCHAR(1200), content_sha256 VARCHAR(64), index_sha256 VARCHAR(64), index_status VARCHAR(40) NOT NULL DEFAULT 'missing', fetched_at DATETIME NOT NULL, confirmed_at DATETIME, created_at DATETIME NOT NULL)"))
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_web_resources_created_at ON web_resources(created_at, id)"))
            connection.execute(text("INSERT INTO schema_migrations(version, applied_at) VALUES (31, CURRENT_TIMESTAMP)"))
            current = 31
        if current < 32:
            connection.execute(text("CREATE TABLE IF NOT EXISTS github_repositories (id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL, owner VARCHAR(120) NOT NULL, name VARCHAR(120) NOT NULL, full_name VARCHAR(240) NOT NULL, html_url VARCHAR(2048) NOT NULL DEFAULT '', default_branch VARCHAR(240) NOT NULL DEFAULT 'main', private BOOLEAN NOT NULL DEFAULT 0, description TEXT NOT NULL DEFAULT '', last_synced_sha VARCHAR(64), last_sync_at DATETIME, created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL, UNIQUE(project_id, full_name), FOREIGN KEY(project_id) REFERENCES learning_projects(id) ON DELETE CASCADE)"))
            connection.execute(text("CREATE TABLE IF NOT EXISTS github_commits (id INTEGER PRIMARY KEY, repository_id INTEGER NOT NULL, sha VARCHAR(64) NOT NULL, message TEXT NOT NULL DEFAULT '', author_name VARCHAR(240) NOT NULL DEFAULT '', author_login VARCHAR(120) NOT NULL DEFAULT '', committed_at DATETIME, html_url VARCHAR(2048) NOT NULL DEFAULT '', additions INTEGER NOT NULL DEFAULT 0, deletions INTEGER NOT NULL DEFAULT 0, changed_files INTEGER NOT NULL DEFAULT 0, files JSON NOT NULL DEFAULT '[]', analysis_status VARCHAR(40) NOT NULL DEFAULT 'pending_confirmation', analysis JSON NOT NULL DEFAULT '{}', analysis_confirmed BOOLEAN NOT NULL DEFAULT 0, imported_at DATETIME NOT NULL, UNIQUE(repository_id, sha), FOREIGN KEY(repository_id) REFERENCES github_repositories(id) ON DELETE CASCADE)"))
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_github_commits_repository_date ON github_commits(repository_id, committed_at, id)"))
            connection.execute(text("INSERT INTO schema_migrations(version, applied_at) VALUES (32, CURRENT_TIMESTAMP)"))
            current = 32
        if current < 33:
            connection.execute(text("CREATE TABLE IF NOT EXISTS job_analyses (id INTEGER PRIMARY KEY, title VARCHAR(240) NOT NULL, source_text TEXT NOT NULL DEFAULT '', source_hash VARCHAR(64) NOT NULL, extracted_skills JSON NOT NULL DEFAULT '[]', matched_topics JSON NOT NULL DEFAULT '[]', matched_capabilities JSON NOT NULL DEFAULT '[]', project_evidence JSON NOT NULL DEFAULT '[]', gaps JSON NOT NULL DEFAULT '[]', recommendations JSON NOT NULL DEFAULT '[]', confidence FLOAT NOT NULL DEFAULT 0.0, created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL)"))
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_job_analyses_created_at ON job_analyses(created_at, id)"))
            connection.execute(text("INSERT INTO schema_migrations(version, applied_at) VALUES (33, CURRENT_TIMESTAMP)"))
            current = 33
        if current < 34:
            connection.execute(text("CREATE TABLE IF NOT EXISTS user_profiles (id INTEGER PRIMARY KEY, major VARCHAR(160) NOT NULL DEFAULT '', grade VARCHAR(80) NOT NULL DEFAULT '', long_term_goal TEXT NOT NULL DEFAULT '', target_job_directions JSON NOT NULL DEFAULT '[]', confirmed_skills JSON NOT NULL DEFAULT '[]', unverified_skills JSON NOT NULL DEFAULT '[]', weak_capabilities JSON NOT NULL DEFAULT '[]', learning_preferences JSON NOT NULL DEFAULT '[]', proactive_level VARCHAR(40) NOT NULL DEFAULT '中主动', profile_confirmed BOOLEAN NOT NULL DEFAULT 0, created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL)"))
            connection.execute(text("INSERT INTO schema_migrations(version, applied_at) VALUES (34, CURRENT_TIMESTAMP)"))
            current = 34
        if current < 35:
            _add_columns(connection, "daily_logs", (("completed_tasks", "JSON DEFAULT '[]'"), ("resolved_questions", "JSON DEFAULT '[]'"), ("next_steps", "JSON DEFAULT '[]'")))
            connection.execute(text("INSERT INTO schema_migrations(version, applied_at) VALUES (35, CURRENT_TIMESTAMP)"))
            current = 35
        if current < 36:
            _add_columns(connection, "notes", (("ai_review", "JSON DEFAULT '{}'"),))
            connection.execute(text("INSERT INTO schema_migrations(version, applied_at) VALUES (36, CURRENT_TIMESTAMP)"))
            current = 36
        if current < 37:
            _add_columns(connection, "learning_projects", (
                ("path", "VARCHAR(1024) NOT NULL DEFAULT ''"),
                ("repository_url", "VARCHAR(2048) NOT NULL DEFAULT ''"),
                ("technologies", "JSON NOT NULL DEFAULT '[]'"),
                ("authorized_directory_id", "INTEGER"),
            ))
            connection.execute(text("INSERT INTO schema_migrations(version, applied_at) VALUES (37, CURRENT_TIMESTAMP)"))
            current = 37
        if current < 38:
            _add_columns(connection, "authorized_directories", (
                ("allowed_extensions", "JSON NOT NULL DEFAULT '[]'"),
                ("excluded_patterns", "JSON NOT NULL DEFAULT '[]'"),
            ))
            connection.execute(text("INSERT INTO schema_migrations(version, applied_at) VALUES (38, CURRENT_TIMESTAMP)"))
            current = 38
        if current < 39:
            connection.execute(text("CREATE TABLE IF NOT EXISTS chat_turns (id INTEGER PRIMARY KEY, turn_id VARCHAR(120) NOT NULL UNIQUE, session_id VARCHAR(120) NOT NULL, persona VARCHAR(40) NOT NULL, status VARCHAR(24) NOT NULL DEFAULT 'pending', created_at DATETIME NOT NULL, completed_at DATETIME)"))
            _add_columns(connection, "chat_messages", (
                ("turn_id", "VARCHAR(120)"),
                ("persona", "VARCHAR(40)"),
                ("status", "VARCHAR(24) NOT NULL DEFAULT 'completed'"),
            ))
            if _table_exists(connection, "chat_messages"):
                rows = connection.execute(text("SELECT id, session_id, role, created_at FROM chat_messages WHERE turn_id IS NULL ORDER BY session_id, id")).mappings().all()
                index = 0
                while index < len(rows):
                    current_row = rows[index]
                    following = rows[index + 1] if index + 1 < len(rows) else None
                    paired = bool(
                        current_row["role"] == "user"
                        and following is not None
                        and following["session_id"] == current_row["session_id"]
                        and following["role"] == "assistant"
                    )
                    turn_id = f"legacy-{current_row['id']}"
                    status = "completed" if paired else "legacy_unpaired"
                    completed_at = following["created_at"] if paired else current_row["created_at"]
                    connection.execute(text("INSERT OR IGNORE INTO chat_turns(turn_id, session_id, persona, status, created_at, completed_at) VALUES (:turn_id, :session_id, 'legacy', :status, :created_at, :completed_at)"), {
                        "turn_id": turn_id,
                        "session_id": current_row["session_id"],
                        "status": status,
                        "created_at": current_row["created_at"],
                        "completed_at": completed_at,
                    })
                    connection.execute(text("UPDATE chat_messages SET turn_id=:turn_id, persona='legacy', status='completed' WHERE id=:id"), {"turn_id": turn_id, "id": current_row["id"]})
                    if paired and following is not None:
                        connection.execute(text("UPDATE chat_messages SET turn_id=:turn_id, persona='legacy', status='completed' WHERE id=:id"), {"turn_id": turn_id, "id": following["id"]})
                        index += 2
                    else:
                        index += 1
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_chat_turns_session_created ON chat_turns(session_id, created_at, id)"))
            if _table_exists(connection, "chat_messages"):
                connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_chat_messages_turn_role ON chat_messages(turn_id, role) WHERE turn_id IS NOT NULL"))
                connection.execute(text("CREATE INDEX IF NOT EXISTS ix_chat_messages_turn_id ON chat_messages(turn_id)"))
            connection.execute(text("INSERT INTO schema_migrations(version, applied_at) VALUES (39, CURRENT_TIMESTAMP)"))
            current = 39
        if current < 40:
            _add_columns(connection, "chat_turns", (
                ("provider", "VARCHAR(40)"),
                ("model_name", "VARCHAR(160)"),
                ("route_reason", "VARCHAR(200)"),
                ("failure_kind", "VARCHAR(40)"),
            ))
            connection.execute(text("INSERT INTO schema_migrations(version, applied_at) VALUES (40, CURRENT_TIMESTAMP)"))
            current = 40


__all__ = ["MIGRATION_VERSION", "run_sqlite_migrations"]
