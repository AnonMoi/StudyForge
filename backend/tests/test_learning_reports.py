from datetime import date, timedelta


def test_daily_report_generation_is_persisted_and_idempotent(client):
    log = client.post(
        "/api/daily-logs",
        json={
            "raw_text": "学习 FastAPI，完成一个接口练习，输出了测试代码。",
            "log_date": date.today().isoformat(),
            "extracted_topics": ["FastAPI"],
            "extracted_duration": 45,
            "extracted_outputs": ["测试代码"],
            "understood_content": ["依赖注入"],
            "unresolved_questions": ["事务边界"],
            "confirm": True,
        },
    )
    assert log.status_code == 201

    first = client.post("/api/reports/daily/generate", json={})
    assert first.status_code == 200
    body = first.json()
    assert body["report_type"] == "daily"
    assert body["source_snapshot"]["study_minutes"] == 45
    assert body["source_snapshot"]["output_count"] == 1
    assert body["recommendations"]

    second = client.post("/api/reports/daily/generate", json={})
    assert second.status_code == 200
    assert second.json()["id"] == body["id"]
    assert client.get("/api/reports").json()[0]["id"] == body["id"]


def test_all_report_types_support_empty_data_and_export(client):
    for report_type in ("daily", "weekly", "stage", "bottleneck"):
        response = client.post(f"/api/reports/{report_type}/generate", json={})
        assert response.status_code == 200
        assert response.json()["source_snapshot"]["task_count"] == 0
        assert "API_KEY" not in response.text

    report_id = client.get("/api/reports").json()[0]["id"]
    for file_format in ("json", "txt", "md", "html"):
        exported = client.get(f"/api/reports/{report_id}/export/{file_format}")
        assert exported.status_code == 200
        assert "learning-report-" in exported.headers.get("content-disposition", "")


def test_report_generation_does_not_modify_tasks(client):
    task = client.post(
        "/api/tasks",
        json={"title": "待完成任务", "due_date": date.today().isoformat(), "status": "not_started"},
    )
    assert task.status_code == 201
    task_id = task.json()["id"]

    report = client.post("/api/reports/weekly/generate", json={})
    assert report.status_code == 200
    unchanged = next(item for item in client.get("/api/tasks").json() if item["id"] == task_id)
    assert unchanged["status"] == "not_started"


def test_bottleneck_report_identifies_unfinished_task_and_low_review_quality(client):
    task = client.post(
        "/api/tasks",
        json={"title": "反复延期的任务", "due_date": date.today().isoformat(), "status": "not_started"},
    )
    assert task.status_code == 201
    log = client.post(
        "/api/daily-logs",
        json={
            "raw_text": "复习数据库，仍然不确定索引原理。",
            "log_date": date.today().isoformat(),
            "extracted_topics": ["数据库"],
            "extracted_duration": 30,
            "unresolved_questions": ["索引原理"],
            "confirm": True,
        },
    )
    assert log.status_code == 201
    review = client.post(
        f"/api/daily-logs/{log.json()['id']}/reviews",
        json={"review_date": date.today().isoformat(), "topic_id": None},
    )
    assert review.status_code == 201
    review_id = review.json()["id"]
    updated = client.patch(f"/api/reviews/{review_id}", json={"status": "completed", "quality": 1})
    assert updated.status_code == 200

    response = client.post(
        "/api/reports/bottleneck/generate",
        json={
            "period_start": date.today().isoformat(),
            "period_end": (date.today() + timedelta(days=1)).isoformat(),
            "force_new_version": True,
        },
    )
    assert response.status_code == 200
    weak_points = response.json()["weak_points"]
    assert any(item.get("point") == "数据库" for item in weak_points)
    assert any("复习质量" == item.get("point") for item in weak_points)
