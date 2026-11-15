from app.model_routing import ModelResult


def test_daily_log_new_fields_and_note_link_are_saved(client):
    note = client.post("/api/notes", json={"title": "日志关联笔记", "content": "依赖注入"}).json()
    response = client.post(
        "/api/daily-logs",
        json={
            "raw_text": "完成 API 练习，解决参数校验问题，下一步补测试。",
            "completed_tasks": ["API 练习"],
            "resolved_questions": ["边界校验"],
            "next_steps": ["补充异常路径测试"],
            "note_ids": [note["id"]],
            "confirm": True,
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["completed_tasks"] == ["API 练习"]
    assert body["resolved_questions"] == ["边界校验"]
    assert body["next_steps"] == ["补充异常路径测试"]
    assert body["note_ids"] == [note["id"]]


def test_daily_log_rejects_missing_note_link(client):
    response = client.post("/api/daily-logs", json={"raw_text": "记录", "note_ids": [999999]})
    assert response.status_code == 404


def test_note_agent_preview_and_confirm_preserve_note_body(client, monkeypatch):
    note = client.post(
        "/api/notes",
        json={"title": "原始标题", "content": "# FastAPI\n\n```python\nprint('ok')\n```", "tags": ["旧"]},
    ).json()

    def fake_run_structured(task_type, prompt, required_keys, confirmed=False):
        assert task_type == "format_note"
        return ModelResult(
            True,
            {
                "suggested_title": "更清晰的标题",
                "summary": "说明 FastAPI 示例。",
                "suggested_tags": ["FastAPI", "Python"],
                "technical_issues": [],
                "missing_prerequisites": [],
                "related_note_ids": [],
                "review_questions": ["为什么需要测试？"],
                "quality_score": 86,
                "quality_dimensions": {"structure": 90},
            },
            "ollama",
            "local-test",
        )

    monkeypatch.setattr("app.main.router.run_structured", fake_run_structured)
    preview = client.post(f"/api/notes/{note['id']}/agent/analyze", json={})
    assert preview.status_code == 200
    assert preview.json()["requires_confirmation"] is True
    assert client.get("/api/notes").json()[0]["ai_review_status"] == "not_reviewed"

    confirmed = client.post(
        f"/api/notes/{note['id']}/agent/analyze",
        json={"confirmed": True, "apply_fields": ["summary", "tags"]},
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["applied_fields"] == ["summary", "tags"]
    saved = client.get("/api/notes").json()[0]
    assert saved["content"] == note["content"]
    assert saved["summary"] == "说明 FastAPI 示例。"
    assert saved["ai_review"]["quality_score"] == 86
    quality = client.get("/api/notes/quality-summary")
    assert quality.status_code == 200
    assert quality.json()["reviewed_notes"] == 1


def test_task_note_association_is_queryable_from_task_side(client):
    task = client.post("/api/tasks", json={"title": "关联任务"}).json()
    note = client.post("/api/notes", json={"title": "关联内容", "linked_task_ids": [task["id"]]}).json()
    response = client.get(f"/api/tasks/{task['id']}/notes")
    assert response.status_code == 200
    assert response.json()[0]["id"] == note["id"]


def test_knowledge_graph_exposes_profile_job_direction_gaps(client):
    client.put("/api/user-profile", json={"target_job_directions": ["后端开发"]})
    topic = client.post("/api/knowledge-topics", json={"name": "FastAPI", "domain": "后端开发"}).json()
    graph = client.get("/api/knowledge-graph")
    assert graph.status_code == 200
    analysis = graph.json()["analysis"]
    assert analysis["job_direction"] == "后端开发"
    assert "FastAPI" in analysis["job_relevant_topics"]
    assert any(item["topic_id"] == topic["id"] for item in analysis["job_direction_gaps"])


def test_directory_permission_changes_are_audited(client, tmp_path):
    item = client.post("/api/authorized-directories", json={"path": str(tmp_path)}).json()
    updated = client.patch(f"/api/authorized-directories/{item['id']}/permissions", json={"write_access": True})
    assert updated.status_code == 200
    audits = client.get("/api/audits", params={"entity_type": "authorized_directory"})
    assert audits.status_code == 200
    assert any(row["action"] == "permissions_update" for row in audits.json())
