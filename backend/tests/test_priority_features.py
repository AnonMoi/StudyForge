from datetime import date


def test_capability_assessment_keeps_history_and_proposes_a_confirmable_plan(client):
    goal = client.post("/api/goals", json={"title": "Python 能力闭环"}).json()
    stage = client.post(
        f"/api/goals/{goal['id']}/stages",
        json={"title": "Python 基础", "capability_targets": ["Python"]},
    ).json()
    task = client.post(
        "/api/tasks",
        json={"title": "Python 列表练习", "stage_id": stage["id"], "due_date": date.today().isoformat()},
    ).json()
    client.patch(f"/api/tasks/{task['id']}", json={"status": "in_progress"})
    client.patch(f"/api/tasks/{task['id']}", json={"status": "pending_verification"})
    verified = client.post(
        f"/api/tasks/{task['id']}/verify",
        json={"target_status": "completed", "evidence": "完成并通过列表练习测试"},
    )
    assert verified.status_code == 200

    assessment = client.post("/api/capabilities/assess")
    assert assessment.status_code == 200
    profile = next(item for item in assessment.json()["profiles"] if item["name"] == "Python")
    history = client.get(f"/api/capabilities/{profile['id']}/history")
    assert history.status_code == 200
    assert history.json()[0]["new_level"] > 0

    proposal = client.post(f"/api/capabilities/{profile['id']}/plan")
    assert proposal.status_code == 200
    assert proposal.json()["requires_confirmation"] is True
    executed = client.post(
        f"/api/agent/plan-adjustment/{proposal.json()['proposal_id']}/execute",
        json={"confirmed": True},
    )
    assert executed.status_code == 200
    assert executed.json()["executed"] is True


def test_algorithm_and_sql_exercises_validate_attempts(client):
    algorithm = client.post(
        "/api/exercises",
        json={
            "title": "数组求和",
            "exercise_type": "algorithm",
            "prompt": "读取一行 JSON 数组并输出总和。",
            "difficulty": "easy",
            "validation_spec": {"cases": [{"stdin": "[1, 2, 3]", "expected_stdout": "6"}]},
        },
    )
    assert algorithm.status_code == 201
    attempt = client.post(
        f"/api/exercises/{algorithm.json()['id']}/attempts",
        json={"code": "import json\nprint(sum(json.loads(input())))"},
    )
    assert attempt.status_code == 201
    assert attempt.json()["passed"] is True

    sql = client.post(
        "/api/exercises",
        json={
            "title": "按部门汇总",
            "exercise_type": "sql",
            "prompt": "查询每个部门的总薪资。",
            "difficulty": "easy",
            "validation_spec": {
                "schema_sql": "CREATE TABLE employees (department TEXT, salary INTEGER);",
                "seed_sql": "INSERT INTO employees VALUES ('数据', 10), ('数据', 20), ('产品', 15);",
                "expected_rows": [["产品", 15], ["数据", 30]],
            },
        },
    )
    assert sql.status_code == 201
    sql_attempt = client.post(
        f"/api/exercises/{sql.json()['id']}/attempts",
        json={"query": "SELECT department, SUM(salary) FROM employees GROUP BY department ORDER BY department"},
    )
    assert sql_attempt.status_code == 201
    assert sql_attempt.json()["passed"] is True


def test_code_run_requires_confirmation_and_blocks_dangerous_imports(client):
    preview = client.post("/api/code-runs", json={"code": "print('ok')", "confirmed": False})
    assert preview.status_code == 200
    assert preview.json()["requires_confirmation"] is True

    blocked = client.post(
        "/api/code-runs",
        json={"code": "import os\nprint(os.listdir('.'))", "confirmed": True},
    )
    assert blocked.status_code == 422

    executed = client.post("/api/code-runs", json={"code": "print('ok')", "confirmed": True})
    assert executed.status_code == 201
    assert executed.json()["status"] == "passed"
    assert executed.json()["stdout"].strip() == "ok"


def test_project_milestones_have_board_timeline_and_evidence_views(client):
    project = client.post("/api/projects", json={"title": "练习项目"}).json()
    milestone = client.post(
        f"/api/projects/{project['id']}/milestones",
        json={"title": "完成 API", "due_date": date.today().isoformat()},
    )
    assert milestone.status_code == 201
    updated = client.patch(
        f"/api/project-milestones/{milestone.json()['id']}",
        json={"status": "completed", "evidence": "接口测试全部通过"},
    )
    assert updated.status_code == 200
    board = client.get(f"/api/projects/{project['id']}/board")
    timeline = client.get(f"/api/projects/{project['id']}/timeline")
    assert board.status_code == 200
    assert board.json()["columns"]["completed"][0]["title"] == "完成 API"
    assert timeline.status_code == 200
    assert any(item["type"] == "milestone" for item in timeline.json()["items"])


def test_review_error_analysis_groups_type_topic_and_trend(client):
    topic = client.post("/api/knowledge-topics", json={"name": "SQL", "domain": "数据库"}).json()
    card = client.post(
        "/api/review-cards",
        json={"front": "什么是 JOIN？", "back": "表连接", "topic_id": topic["id"]},
    ).json()
    for _ in range(2):
        answered = client.post(
            f"/api/review-cards/{card['id']}/answer",
            json={"quality": 1, "error_type": "概念混淆", "error_note": "混淆连接条件"},
        )
        assert answered.status_code == 200

    analysis = client.get("/api/review-cards/errors/analysis?days=30")
    assert analysis.status_code == 200
    payload = analysis.json()
    assert payload["by_error_type"]["概念混淆"] >= 2
    assert payload["by_topic"]["SQL"] >= 2
    assert payload["trend"]
    assert payload["recommendations"]


def test_priority_entities_are_in_full_backup_and_restore_preview(client):
    project = client.post("/api/projects", json={"title": "备份项目"}).json()
    client.post(f"/api/projects/{project['id']}/milestones", json={"title": "备份里程碑"})
    exercise = client.post("/api/exercises", json={"title": "备份练习", "exercise_type": "algorithm", "validation_spec": {"cases": []}}).json()
    client.post(f"/api/exercises/{exercise['id']}/attempts", json={"code": "print('backup')"})
    client.post("/api/code-runs", json={"code": "print('backup')", "confirmed": True})
    client.post("/api/capabilities/assess")

    backup = client.get("/api/backup/json")
    assert backup.status_code == 200
    payload = backup.json()
    assert payload["project_milestones"]
    assert payload["practice_exercises"]
    assert payload["practice_attempts"]
    assert payload["code_runs"]
    assert "capability_assessments" in payload
    preview = client.post("/api/backup/restore", json={"backup": payload, "confirmed": False})
    assert preview.status_code == 200
    assert preview.json()["preview"]["project_milestones"] >= 1
    restored = client.post("/api/backup/restore", json={"backup": payload, "confirmed": True})
    assert restored.status_code == 200
