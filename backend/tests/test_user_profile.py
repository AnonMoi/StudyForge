def profile_payload():
    return {
        "major": "数据科学与大数据技术",
        "grade": "大一",
        "long_term_goal": "建立可迁移的计算机基础并完成后端项目",
        "target_job_directions": ["后端开发", "数据开发", "AI Agent"],
        "confirmed_skills": ["Python", "Git"],
        "unverified_skills": ["操作系统", "计算机网络"],
        "weak_capabilities": ["Python 工程化", "数据库与 SQL"],
        "learning_preferences": ["项目驱动", "先理解原理再练习"],
        "proactive_level": "中主动",
    }


def test_user_profile_is_singleton_and_editable(client):
    initial = client.get("/api/user-profile")

    assert initial.status_code == 200
    assert initial.json()["id"] == 1
    assert initial.json()["profile_confirmed"] is False

    updated = client.put("/api/user-profile", json=profile_payload())

    assert updated.status_code == 200
    body = updated.json()
    assert body["id"] == 1
    assert body["major"] == "数据科学与大数据技术"
    assert body["target_job_directions"] == ["后端开发", "数据开发", "AI Agent"]
    assert body["profile_confirmed"] is True
    assert client.get("/api/user-profile").json()["long_term_goal"].startswith("建立可迁移")


def test_setup_initialize_previews_then_creates_initial_learning_plan(client):
    payload = {"profile": profile_payload(), "create_initial_plan": True, "confirmed": False}

    preview = client.post("/api/setup/initialize", json=payload)

    assert preview.status_code == 200
    preview_body = preview.json()
    assert preview_body["executed"] is False
    assert preview_body["requires_confirmation"] is True
    assert preview_body["profile_preview"]["long_term_goal"].startswith("建立可迁移")
    assert preview_body["plan_preview"]["goal_title"] == profile_payload()["long_term_goal"]
    assert client.get("/api/setup/status").json()["requires_onboarding"] is True

    payload["confirmed"] = True
    executed = client.post("/api/setup/initialize", json=payload)

    assert executed.status_code == 200
    result = executed.json()
    assert result["executed"] is True
    assert result["created_goal_id"] is not None
    assert result["created_stage_id"] is not None
    assert result["created_task_id"] is not None

    setup = client.get("/api/setup/status").json()
    assert setup["completed"] is True
    assert setup["profile_confirmed"] is True
    assert setup["first_plan_generated"] is True
    assert client.get("/api/goals").json()[0]["title"] == profile_payload()["long_term_goal"]


def test_import_profile_draft_is_preview_only_and_uses_deterministic_fallback(client, tmp_path, monkeypatch):
    from app import file_import

    monkeypatch.setattr(file_import.model_router, "run_structured", lambda *args, **kwargs: type("FailedResult", (), {"success": False, "data": None, "provider": None, "model_name": None, "confidence": 0.0})())
    (tmp_path / "lesson.py").write_text("def hello():\n    return 'world'\n", encoding="utf-8")
    (tmp_path / "notes.md").write_text("# HTTP 基础\n记录请求和响应。\n", encoding="utf-8")
    directory = client.post("/api/authorized-directories", json={"path": str(tmp_path), "label": "学习资料"}).json()
    scan = client.post(f"/api/authorized-directories/{directory['id']}/scan")
    import_id = scan.json()["import_id"]

    draft = client.post(f"/api/imports/{import_id}/profile-draft")

    assert draft.status_code == 200
    body = draft.json()
    assert body["executed"] is False
    assert body["requires_confirmation"] is True
    assert body["generation_mode"] in {"local_model", "deterministic_fallback"}
    assert "Python" in body["profile_draft"]["unverified_skills"]
    assert client.get("/api/user-profile").json()["profile_confirmed"] is False
