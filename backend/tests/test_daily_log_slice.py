from datetime import date

from fastapi.testclient import TestClient

from app.main import app


def test_daily_log_structured_fields_can_be_edited_before_confirmation():
    client = TestClient(app)
    created = client.post(
        "/api/daily-logs",
        json={"raw_text": "学习 FastAPI", "extracted_topics": ["FastAPI"], "extracted_duration": 30},
    )
    assert created.status_code == 201
    log_id = created.json()["id"]

    updated = client.patch(
        f"/api/daily-logs/{log_id}",
        json={
            "extracted_topics": ["FastAPI", "SQLite"],
            "extracted_duration": 45,
            "extracted_outputs": ["完成接口"],
            "understood_content": ["依赖注入"],
            "unresolved_questions": ["事务边界"],
            "self_assessment": "基本掌握",
        },
    )
    assert updated.status_code == 200
    assert updated.json()["extracted_duration"] == 45
    assert updated.json()["extracted_topics"] == ["FastAPI", "SQLite"]
    assert updated.json()["structured_status"] == "pending_review"


def test_daily_log_can_be_confirmed_and_linked_to_a_review():
    client = TestClient(app)
    created = client.post("/api/daily-logs", json={"raw_text": "复习 SQL 查询"})
    log_id = created.json()["id"]

    confirmed = client.patch(
        f"/api/daily-logs/{log_id}",
        json={"confirm": True, "self_assessment": "已掌握"},
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["structured_status"] == "confirmed"

    review = client.post(
        f"/api/daily-logs/{log_id}/reviews",
        json={"review_date": str(date.today()), "note": "用一道题检验"},
    )
    assert review.status_code == 201
    assert review.json()["daily_log_id"] == log_id
    assert review.json()["status"] == "pending"
    assert client.get(f"/api/daily-logs/{log_id}/reviews").json()[0]["note"] == "用一道题检验"


def test_review_requires_existing_daily_log():
    response = TestClient(app).post(
        "/api/daily-logs/999999/reviews",
        json={"review_date": "2026-08-11"},
    )
    assert response.status_code == 404


def test_daily_log_update_requires_existing_log():
    response = TestClient(app).patch("/api/daily-logs/999999", json={"confirm": True})
    assert response.status_code == 404


def test_daily_log_preserves_completion_resolution_and_next_step_fields():
    client = TestClient(app)
    response = client.post(
        "/api/daily-logs",
        json={
            "raw_text": "完成了一个 API 练习，解决了参数校验问题。",
            "completed_tasks": ["API 参数校验练习"],
            "resolved_questions": ["为什么要在边界层校验？"],
            "next_steps": ["补充异常路径测试"],
            "confirm": True,
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["completed_tasks"] == ["API 参数校验练习"]
    assert body["resolved_questions"] == ["为什么要在边界层校验？"]
    assert body["next_steps"] == ["补充异常路径测试"]

    updated = client.patch(
        f"/api/daily-logs/{body['id']}",
        json={"next_steps": ["补充异常路径测试", "写一篇复盘笔记"]},
    )
    assert updated.status_code == 200
    assert updated.json()["next_steps"][-1] == "写一篇复盘笔记"


def test_confirmed_daily_log_can_be_corrected_from_history():
    client = TestClient(app)
    created = client.post(
        "/api/daily-logs",
        json={"raw_text": "初始记录", "extracted_topics": ["旧主题"], "confirm": True},
    )
    assert created.status_code == 201

    updated = client.patch(
        f"/api/daily-logs/{created.json()['id']}",
        json={"raw_text": "修正后的记录", "extracted_topics": ["新主题"], "confirm": True},
    )

    assert updated.status_code == 200
    assert updated.json()["raw_text"] == "修正后的记录"
    assert updated.json()["extracted_topics"] == ["新主题"]
    assert updated.json()["structured_status"] == "confirmed"
