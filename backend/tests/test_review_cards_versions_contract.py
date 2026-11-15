from datetime import date


def test_task_extensions_are_persisted(client):
    response = client.post(
        "/api/tasks",
        json={
            "title": "完成周计划验收",
            "week_key": date.today().isoformat(),
            "task_type": "output",
            "expected_outcome": "形成可复现的验收记录",
            "agent_feedback": "优先补齐接口回归",
        },
    )
    assert response.status_code == 201
    payload = response.json()
    assert payload["week_key"] == date.today().isoformat()
    assert payload["task_type"] == "output"
    assert payload["expected_outcome"] == "形成可复现的验收记录"
    assert payload["agent_feedback"] == "优先补齐接口回归"


def test_note_versions_capture_updates_and_restore(client):
    created = client.post("/api/notes", json={"title": "版本笔记", "content": "第一版", "tags": ["v1"]})
    assert created.status_code == 201
    note_id = created.json()["id"]

    updated = client.patch(f"/api/notes/{note_id}", json={"content": "第二版", "tags": ["v2"]})
    assert updated.status_code == 200

    versions = client.get(f"/api/notes/{note_id}/versions")
    assert versions.status_code == 200
    assert [item["version_number"] for item in versions.json()] == [2, 1]
    assert versions.json()[0]["content"] == "第一版"

    restored = client.post(f"/api/notes/{note_id}/versions/1/restore")
    assert restored.status_code == 200
    assert restored.json()["content"] == "第一版"
    assert restored.json()["tags"] == ["v1"]


def test_review_cards_support_generation_due_and_answer(client):
    note = client.post(
        "/api/notes",
        json={"title": "复习来源", "content": "第一要点\n\n第二要点"},
    )
    assert note.status_code == 201
    note_id = note.json()["id"]

    generated = client.post("/api/review-cards/generate", params={"note_id": note_id})
    assert generated.status_code == 200
    assert generated.json()["requires_confirmation"] is True
    confirmed = client.post("/api/review-cards/generate", params={"note_id": note_id, "confirmed": True})
    cards = confirmed.json()["cards"]
    assert len(cards) == 2
    assert client.post("/api/review-cards/generate", params={"note_id": note_id, "confirmed": True}).json()["reused"] is True

    due = client.get("/api/review-cards/due")
    assert due.status_code == 200
    assert {item["id"] for item in due.json()} == {item["id"] for item in cards}

    answered = client.post(f"/api/review-cards/{cards[0]['id']}/answer", json={"quality": 4})
    assert answered.status_code == 200
    assert answered.json()["last_quality"] == 4
    assert answered.json()["repetitions"] == 1
    assert answered.json()["due_date"] > date.today().isoformat()


def test_request_id_and_security_headers_are_consistent(client):
    response = client.get("/api/health", headers={"X-Request-ID": "contract-001"})
    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "contract-001"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "same-origin"


def test_missing_resource_error_keeps_compatible_detail_and_structured_error(client):
    response = client.get("/api/notes/999999/versions")
    assert response.status_code == 404
    payload = response.json()
    assert payload["detail"] == "笔记不存在"
    assert payload["error"]["code"] == "NOT_FOUND"
    assert payload["error"]["status"] == 404
    assert payload["error"]["request_id"] == response.headers["X-Request-ID"]
