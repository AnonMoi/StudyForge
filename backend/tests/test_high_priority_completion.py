def test_model_settings_are_editable_and_router_mode_is_applied(client):
    from app.config import settings

    original = {key: getattr(settings, key) for key in ("model_routing_mode", "daily_cloud_call_limit", "daily_cost_limit")}
    try:
        response = client.put(
            "/api/settings",
            json={"model_routing_mode": "local_only", "daily_cloud_call_limit": 7, "daily_cost_limit": 1.5},
        )
        assert response.status_code == 200
        assert response.json()["model_routing_mode"] == "local_only"
        assert client.get("/api/settings").json()["daily_cloud_call_limit"] == 7
        from app.model_routing import router
        assert router.task_policy("learning_plan")["provider"] == "local"
    finally:
        for key, value in original.items():
            setattr(settings, key, value)


def test_report_feedback_creates_and_executes_confirmable_task_proposal(client):
    report = client.post("/api/reports/daily/generate", json={"force_new_version": True})
    assert report.status_code == 200
    feedback = client.post(
        f"/api/reports/{report.json()['id']}/feedback",
        json={"feedback_type": "accepted", "proposed_change": {"title": "复习报告中的薄弱点", "estimated_minutes": 25}},
    )
    assert feedback.status_code == 201
    proposals = client.get(f"/api/reports/{report.json()['id']}/proposals")
    assert proposals.status_code == 200
    proposal = proposals.json()[0]
    assert proposal["changes"][0]["operation"] == "create"
    executed = client.post(f"/api/agent/plan-adjustment/{proposal['proposal_id']}/execute", json={"confirmed": True})
    assert executed.status_code == 200
    assert executed.json()["executed"] is True
    assert executed.json()["result"]["applied"] == 1


def test_report_feedback_effects_and_version_comparison_are_public(client):
    first = client.post("/api/reports/daily/generate", json={"force_new_version": True}).json()
    feedback = client.post(
        f"/api/reports/{first['id']}/feedback",
        json={"feedback_type": "accepted", "note": "建议与当前目标一致"},
    )
    assert feedback.status_code == 201
    proposal = client.get(f"/api/reports/{first['id']}/proposals").json()[0]

    effects_before = client.get(f"/api/reports/{first['id']}/feedback/effects")
    assert effects_before.status_code == 200
    assert effects_before.json()["summary"]["proposal_status"]["pending"] == 1
    assert effects_before.json()["feedback"][0]["proposal_id"] == proposal["proposal_id"]

    executed = client.post(f"/api/agent/plan-adjustment/{proposal['proposal_id']}/execute", json={"confirmed": True})
    assert executed.status_code == 200
    effects_after = client.get(f"/api/reports/{first['id']}/feedback/effects")
    assert effects_after.json()["summary"]["proposal_status"]["executed"] == 1
    assert effects_after.json()["feedback"][0]["proposal_status"] == "executed"

    second = client.post("/api/reports/daily/generate", json={"force_new_version": True}).json()
    compared = client.get(f"/api/reports/compare?left_id={first['id']}&right_id={second['id']}")
    assert compared.status_code == 200
    assert compared.json()["left"]["version"] < compared.json()["right"]["version"]
    assert "evidence" in compared.json()["changes"]
    assert "weak_points" in compared.json()["changes"]


def test_topic_edit_and_verification_are_available_from_public_api(client):
    topic = client.post("/api/knowledge-topics", json={"name": "测试主题", "tags": ["旧"]}).json()
    updated = client.patch(
        f"/api/knowledge-topics/{topic['id']}",
        json={"definition": "可复核的定义", "tags": ["新"], "self_level": "能解释"},
    )
    assert updated.status_code == 200
    assert updated.json()["tags"] == ["新"]
    verified = client.post(
        f"/api/knowledge-topics/{topic['id']}/verify",
        json={"verified_level": 4, "evidence": "完成一道关联练习", "source_type": "practice"},
    )
    assert verified.status_code == 200
    assert verified.json()["verified_level"] == 4
    assert verified.json()["evidence"][-1]["source_type"] == "practice"


def test_practice_evidence_and_deep_analytics_are_reported(client):
    topic = client.post("/api/knowledge-topics", json={"name": "算法", "domain": "算法"}).json()
    exercise = client.post(
        "/api/exercises",
        json={
            "title": "求和指标练习",
            "exercise_type": "algorithm",
            "topic_id": topic["id"],
            "prompt": "输出数组和",
            "difficulty": "easy",
            "validation_spec": {"cases": [{"stdin": "[1,2]", "expected_stdout": "3"}]},
        },
    ).json()
    attempt = client.post(f"/api/exercises/{exercise['id']}/attempts", json={"code": "import json\nprint(sum(json.loads(input())))"})
    assert attempt.status_code == 201 and attempt.json()["passed"] is True
    project = client.post("/api/projects", json={"title": "指标项目"}).json()
    milestone = client.post(f"/api/projects/{project['id']}/milestones", json={"title": "第一步"}).json()
    client.patch(f"/api/project-milestones/{milestone['id']}", json={"status": "completed", "evidence": "已验证"})
    analytics = client.get("/api/analytics/summary?days=30")
    assert analytics.status_code == 200
    metrics = analytics.json()["metrics"]
    assert metrics["practice_attempts"] == 1
    assert metrics["practice_pass_rate"] == 1.0
    assert metrics["project_progress_rate"] == 1.0
    assessed = client.post("/api/capabilities/assess")
    profile = next(item for item in assessed.json()["profiles"] if item["name"] == "算法")
    details = client.get("/api/capabilities").json()["profiles"]
    algorithm = next(item for item in details if item["id"] == profile["id"])
    assert any(item["source_type"] == "practice_attempt" for item in algorithm["evidence"])


def test_new_entities_support_field_level_merge_and_revert(client):
    exercise = client.post(
        "/api/exercises",
        json={"title": "合并练习", "exercise_type": "algorithm", "validation_spec": {"cases": []}},
    ).json()
    backup = client.get("/api/backup/json").json()
    backup["practice_exercises"][0]["prompt"] = "来自备份的更新提示"
    preview = client.post("/api/backup/merge", json={"backup": backup, "confirmed": False})
    assert preview.status_code == 200
    patch = next(item for item in preview.json()["preview"]["patches"] if item["entity_type"] == "practice_exercises")
    assert "prompt" in patch["fields"]
    merged = client.post(
        "/api/backup/merge",
        json={"backup": backup, "confirmed": True, "selections": [{"entity_type": "practice_exercises", "match_key": exercise["title"], "fields": ["prompt"]}]},
    )
    assert merged.status_code == 200
    batch_id = merged.json()["merge_batch_id"]
    assert client.post(f"/api/backup/merge-batches/{batch_id}/revert", json={"confirmed": True}).status_code == 200
