
def test_note_version_diff_and_field_restore(client):
    created = client.post("/api/notes", json={"title": "版本差异", "content": "第一版正文", "summary": "旧摘要", "tags": ["旧"]})
    assert created.status_code == 201
    note_id = created.json()["id"]
    client.patch(f"/api/notes/{note_id}", json={"content": "第二版正文", "summary": "新摘要", "tags": ["新"]})

    diff = client.get(f"/api/notes/{note_id}/versions/diff", params={"from_version": 1, "to_version": 2})
    assert diff.status_code == 200
    assert diff.json()["fields"]["content"]["before"] == "第一版正文"
    assert diff.json()["fields"]["content"]["after"] == "第二版正文"
    assert diff.json()["content_diff"]["hunks"] == [{
        "kind": "replace",
        "before_start": 1,
        "before_count": 1,
        "after_start": 1,
        "after_count": 1,
        "before_lines": ["第一版正文"],
        "after_lines": ["第二版正文"],
    }]

    restored = client.post(f"/api/notes/{note_id}/versions/1/restore", json={"confirmed": True, "fields": ["content"]})
    assert restored.status_code == 200
    assert restored.json()["content"] == "第一版正文"
    assert restored.json()["summary"] == "新摘要"
    assert restored.json()["tags"] == ["新"]


def test_note_restore_requires_confirmation(client):
    created = client.post("/api/notes", json={"title": "确认恢复", "content": "正文"})
    note_id = created.json()["id"]
    client.patch(f"/api/notes/{note_id}", json={"content": "新正文"})
    response = client.post(f"/api/notes/{note_id}/versions/1/restore", json={"fields": ["content"]})
    assert response.status_code == 409
