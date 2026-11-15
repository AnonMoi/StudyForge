from fastapi.testclient import TestClient

from app.main import app
from app.models import DailyLog, DailyLogReview, LearningGoal, LearningProject, LearningStage, ReviewCard, ReviewHistory, StudyTask, TeachingAttempt, TeachingSession, WeeklyPlan
from app.notes_models import Note, KnowledgeTopic


def test_restore_remaps_all_cross_entity_ids_including_review_and_teaching_graph():
    client = TestClient(app)
    backup = {
        "goals": [{"id": 1001, "title": "源目标", "description": "目标描述", "priority": 2, "status": "active"}],
        "projects": [{"id": 2001, "title": "源项目", "description": "项目描述", "status": "active", "skills": ["Python"], "outcomes": [], "milestones": []}],
        "knowledge_topics": [{"id": 3001, "name": "源主题", "domain": "工程", "definition": "定义", "self_level": "有印象", "verified_level": 1, "tags": [], "prerequisites": [], "evidence": []}],
        "notes": [{"id": 4001, "title": "源笔记", "content": "内容", "summary": "摘要", "tags": [], "folder": "Inbox", "visibility": "private", "status": "draft", "linked_topic_ids": [3001], "linked_task_ids": [6001], "linked_project_ids": [2001]}],
        "stages": [{"id": 5001, "goal_id": 1001, "title": "源阶段", "capability_targets": [], "prerequisites": [], "order_index": 1, "status": "active"}],
        "tasks": [{"id": 6001, "title": "源任务", "description": "任务描述", "stage_id": 5001, "project_id": 2001, "topic_id": 3001, "priority": 1, "status": "not_started", "due_date": "2026-08-20", "task_type": "practice", "week_key": "2026-W34"}],
        "daily_logs": [{"id": 7001, "log_date": "2026-08-15", "raw_text": "源日志", "extracted_topics": [], "extracted_outputs": [], "understood_content": [], "unresolved_questions": [], "structured_status": "confirmed", "project_id": 2001, "topic_ids": [3001], "note_ids": [4001]}],
        "reviews": [{"id": 8001, "daily_log_id": 7001, "review_date": "2026-08-16", "note": "复盘", "topic_id": 3001, "status": "pending", "quality": 4, "interval_days": 2, "ease_factor": 2.6, "repetitions": 1}],
        "weekly_plans": [{"id": 9001, "week_key": "2026-W34", "goal_id": 1001, "project_id": 2001, "objective": "完成源任务", "expected_outputs": [], "reflection": "", "blockers": "", "status": "draft"}],
        "review_cards": [{"id": 10001, "front": "源问题", "back": "源答案", "hint": "提示", "topic_id": 3001, "source_note_id": 4001, "status": "active", "due_date": "2026-08-16", "interval_days": 1, "ease_factor": 2.5, "repetitions": 0}],
        "review_history": [{"id": 11001, "card_id": 10001, "quality": 3, "interval_before": 1, "interval_after": 2, "ease_before": 2.5, "ease_after": 2.5, "repetitions_before": 0, "repetitions_after": 1, "due_before": "2026-08-15", "due_after": "2026-08-17", "reviewed_at": "2026-08-15T10:00:00+00:00"}],
        "teaching_sessions": [{"id": 12001, "title": "源教学", "topic_id": 3001, "task_id": 6001, "stage_id": 5001, "status": "active", "explanation": "讲解"}],
        "teaching_attempts": [{"id": 13001, "session_id": 12001, "topic_id": 3001, "task_id": 6001, "stage_id": 5001, "phase": "practice", "prompt": "源问题", "expected_answer": "源答案", "rubric": ["定义"], "user_answer": "回答", "score": 4, "feedback": "反馈", "recommendation": "建议", "review_card_id": 10001, "created_at": "2026-08-15T10:01:00+00:00", "answered_at": "2026-08-15T10:02:00+00:00", "evaluated_at": "2026-08-15T10:03:00+00:00"}],
    }

    response = client.post("/api/backup/restore", json={"backup": backup, "confirmed": True})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["restored_counts"]["goals"] == 1
    assert result["restored_counts"]["review_history"] == 1
    assert result["restored_counts"]["teaching_attempts"] == 1

    goals = client.get("/api/goals").json()
    projects = client.get("/api/projects").json()
    topics = client.get("/api/knowledge-topics").json()
    notes = client.get("/api/notes").json()
    stages = client.get("/api/stages").json()
    tasks = client.get("/api/tasks").json()
    logs = client.get("/api/daily-logs").json()
    plans = client.get("/api/weekly-plans").json()
    cards = client.get("/api/review-cards").json()
    sessions = client.get("/api/teaching/sessions").json()

    goal = next(item for item in goals if item["title"] == "源目标")
    project = next(item for item in projects if item["title"] == "源项目")
    topic = next(item for item in topics if item["name"] == "源主题")
    note = next(item for item in notes if item["title"] == "源笔记")
    stage = next(item for item in stages if item["title"] == "源阶段")
    task = next(item for item in tasks if item["title"] == "源任务")
    log = next(item for item in logs if item["raw_text"] == "源日志")
    plan = next(item for item in plans if item["week_key"] == "2026-W34")
    card = next(item for item in cards if item["front"] == "源问题")
    session = next(item for item in sessions if item["title"] == "源教学")

    assert goal["id"] != 1001 and project["id"] != 2001 and topic["id"] != 3001
    assert stage["goal_id"] == goal["id"]
    assert task["stage_id"] == stage["id"] and task["project_id"] == project["id"] and task["topic_id"] == topic["id"]
    assert note["linked_topic_ids"] == [topic["id"]]
    assert note["linked_task_ids"] == [task["id"]]
    assert note["linked_project_ids"] == [project["id"]]
    assert log["project_id"] == project["id"] and log["topic_ids"] == [topic["id"]] and log["note_ids"] == [note["id"]]
    assert plan["goal_id"] == goal["id"] and plan["project_id"] == project["id"]
    assert card["topic_id"] == topic["id"] and card["source_note_id"] == note["id"]
    assert session["topic_id"] == topic["id"] and session["task_id"] == task["id"] and session["stage_id"] == stage["id"]
    assert session["attempts"][0]["session_id"] == session["id"]
    assert session["attempts"][0]["topic_id"] == topic["id"]
    assert session["attempts"][0]["task_id"] == task["id"]
    assert session["attempts"][0]["stage_id"] == stage["id"]
    assert session["attempts"][0]["review_card_id"] == card["id"]
    history = client.get(f"/api/review-cards/{card['id']}/history")
    assert history.status_code == 200
    assert history.json()[0]["card_id"] == card["id"]


def test_restore_skips_records_with_unresolved_required_foreign_keys():
    client = TestClient(app)
    backup = {
        "tasks": [{"id": 9901, "title": "缺项目任务", "project_id": 9902, "status": "not_started"}],
        "review_cards": [{"id": 9903, "front": "缺主题卡", "back": "答案", "topic_id": 9904, "due_date": "2026-08-15"}],
        "teaching_sessions": [{"id": 9905, "title": "缺任务教学", "task_id": 9906}],
    }
    response = client.post("/api/backup/restore", json={"backup": backup, "confirmed": True})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["restored_counts"]["tasks"] == 0
    assert result["restored_counts"]["review_cards"] == 0
    assert result["restored_counts"]["teaching_sessions"] == 0
    assert result["skipped_counts"]["tasks"] == 1
    assert result["skipped_counts"]["review_cards"] == 1
    assert result["skipped_counts"]["teaching_sessions"] == 1
