def test_job_analysis_previews_local_evidence_without_writing(client):
    topic = client.post("/api/knowledge-topics", json={"name": "FastAPI", "definition": "Python Web API"}).json()
    capability = client.post("/api/capabilities/assess").json()["profiles"]
    assert capability
    project = client.post("/api/projects", json={"title": "服务项目", "skills": ["Python"], "outcomes": ["完成 API"]}).json()

    description = "Python 后端岗位，要求 FastAPI、SQL、Docker 和测试能力，负责 REST API 开发。"
    preview = client.post("/api/job-analyses", json={"title": "Python 后端实习生", "description": description}).json()
    assert preview["requires_confirmation"] is True
    assert "Python" in preview["analysis"]["extracted_skills"]
    assert "FastAPI" in preview["analysis"]["extracted_skills"]
    assert any(item["id"] == topic["id"] for item in preview["analysis"]["matched_topics"])
    assert any(item["id"] == project["id"] for item in preview["analysis"]["project_evidence"])
    assert client.get("/api/job-analyses").json() == []


def test_job_analysis_confirmation_is_persisted_and_exported(client):
    before = client.get("/api/capabilities").json()["profiles"]
    description = "需要掌握 Python、SQL、Linux 和 Git，并能通过项目证明实践能力。"
    saved = client.post("/api/job-analyses", json={"title": "数据开发岗位", "description": description, "confirmed": True})
    assert saved.status_code == 200
    row = saved.json()["analysis"]
    assert saved.json()["requires_confirmation"] is False
    assert row["source_hash"]
    assert row["recommendations"]
    listed = client.get("/api/job-analyses").json()
    assert listed[0]["id"] == row["id"]
    backup = client.get("/api/backup/json").json()
    assert backup["job_analyses"][0]["title"] == "数据开发岗位"
    backup["job_analyses"][0]["recommendations"] = ["补充一个 SQL 实践证据"]
    merge_preview = client.post("/api/backup/merge", json={"backup": backup, "confirmed": False})
    assert merge_preview.status_code == 200
    assert any(item["entity_type"] == "job_analyses" for item in merge_preview.json()["preview"]["patches"])
    after = client.get("/api/capabilities").json()["profiles"]
    assert [(item["id"], item["level"]) for item in after] == [(item["id"], item["level"]) for item in before]


def test_job_analysis_rejects_short_descriptions(client):
    response = client.post("/api/job-analyses", json={"title": "岗位", "description": "太短"})
    assert response.status_code == 422
