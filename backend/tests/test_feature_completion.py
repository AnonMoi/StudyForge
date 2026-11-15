from datetime import date


def test_readiness_reports_database_ready(client):
    response = client.get("/api/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert response.json()["checks"]["database"] == "ok"


def test_review_card_types_and_error_summary(client):
    created = client.post(
        "/api/review-cards",
        json={"front": "解释依赖注入", "back": "答案", "card_type": "explain"},
    )
    assert created.status_code == 201
    assert created.json()["card_type"] == "explain"
    answered = client.post(
        f"/api/review-cards/{created.json()['id']}/answer",
        json={"quality": 1, "error_type": "概念混淆", "error_note": "没有区分容器和依赖"},
    )
    assert answered.status_code == 200
    assert answered.json()["error_type"] == "概念混淆"
    summary = client.get("/api/review-cards/errors")
    assert summary.status_code == 200
    assert summary.json()["total_errors"] == 1
    assert summary.json()["by_type"]["概念混淆"] == 1


def test_task_completion_requires_evidence_and_verification(client):
    task = client.post("/api/tasks", json={"title": "证据门槛任务"}).json()

    direct_update = client.patch(f"/api/tasks/{task['id']}", json={"status": "completed"})
    assert direct_update.status_code == 422
    direct_mastery = client.patch(f"/api/tasks/{task['id']}", json={"status": "mastered"})
    assert direct_mastery.status_code == 422

    client.patch(f"/api/tasks/{task['id']}", json={"status": "in_progress"})
    pending = client.patch(f"/api/tasks/{task['id']}", json={"status": "pending_verification"})
    assert pending.status_code == 200
    without_evidence = client.post(f"/api/tasks/{task['id']}/verify", json={"target_status": "completed"})
    assert without_evidence.status_code == 422

    verified = client.post(
        f"/api/tasks/{task['id']}/verify",
        json={"target_status": "completed", "evidence": "通过专项测试"},
    )
    assert verified.status_code == 200
    assert verified.json()["status"] == "completed"


def test_graph_layout_is_persisted(client):
    saved = client.put(
        "/api/knowledge-graph/layout",
        json={"node_positions": {"1": {"x": 120, "y": 80}}, "zoom": 1.2},
    )
    assert saved.status_code == 200
    loaded = client.get("/api/knowledge-graph/layout")
    assert loaded.status_code == 200
    assert loaded.json()["node_positions"]["1"]["x"] == 120
    assert loaded.json()["zoom"] == 1.2


def test_report_feedback_is_persisted(client):
    report = client.post(
        "/api/reports/daily/generate",
        json={"period_start": date.today().isoformat(), "period_end": date.today().isoformat()},
    )
    assert report.status_code == 200
    feedback = client.post(
        f"/api/reports/{report.json()['id']}/feedback",
        json={"feedback_type": "helpful", "note": "证据清晰"},
    )
    assert feedback.status_code == 201
    listed = client.get(f"/api/reports/{report.json()['id']}/feedback")
    assert listed.status_code == 200
    assert listed.json()[0]["feedback_type"] == "helpful"


def test_task_impact_preview_explains_relation_prerequisites_and_schedule(client):
    goal = client.post("/api/goals", json={"title": "后端主线"}).json()
    stage = client.post(
        f"/api/goals/{goal['id']}/stages",
        json={"title": "Web 基础", "prerequisites": ["HTTP 基础"]},
    ).json()
    prerequisite = client.post("/api/knowledge-topics", json={"name": "网络基础"}).json()
    topic = client.post(
        "/api/knowledge-topics",
        json={"name": "FastAPI", "prerequisites": [prerequisite["id"]]},
    ).json()
    client.post(
        "/api/tasks",
        json={"title": "已有计划", "week_key": "2026-08-18", "estimated_minutes": 300},
    )

    preview = client.post(
        "/api/tasks/impact-preview",
        json={
            "title": "实现接口练习",
            "stage_id": stage["id"],
            "topic_id": topic["id"],
            "week_key": "2026-08-18",
            "estimated_minutes": 45,
            "task_type": "practice",
        },
    )
    assert preview.status_code == 200
    body = preview.json()
    assert body["relation"]["goal"]["title"] == "后端主线"
    assert body["relation"]["stage"]["title"] == "Web 基础"
    assert body["prerequisites"] == ["HTTP 基础", "网络基础"]
    assert body["schedule_impact"]["after_estimated_minutes"] == 345
    assert body["impact_level"] == "low"
    assert client.get("/api/tasks").json()[0]["title"] == "已有计划"
