from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def make_note():
    response = client.post(
        "/api/notes",
        json={
            "title": "FastAPI 依赖注入",
            "summary": "记录依赖注入的核心理解",
            "content": "依赖注入可以把组件依赖交给框架管理。\n\n实践：使用 Depends 声明依赖。",
            "tags": ["FastAPI", "后端"],
        },
    )
    assert response.status_code == 201
    return response.json()


def test_blog_draft_requires_confirmation_and_does_not_modify_source_note():
    note = make_note()

    preview = client.post(f"/api/notes/{note['id']}/blog-drafts/generate", json={})
    assert preview.status_code == 200
    assert preview.json()["executed"] is False
    assert preview.json()["requires_confirmation"] is True
    assert "发布前请人工核对" in preview.json()["preview"]["content"]
    assert client.get(f"/api/notes/{note['id']}/blog-drafts").json() == []

    confirmed = client.post(f"/api/notes/{note['id']}/blog-drafts/generate", json={"confirmed": True})
    assert confirmed.status_code == 200
    body = confirmed.json()
    assert body["executed"] is True
    draft = body["draft"]
    assert draft["source_note_id"] == note["id"]
    assert draft["source_version"] == 1
    assert draft["generation_mode"] == "deterministic"
    source = client.get("/api/notes").json()[0]
    assert source["id"] == note["id"]
    assert source["content"] == note["content"]


def test_blog_draft_can_be_listed_and_exported():
    note = make_note()
    response = client.post(f"/api/notes/{note['id']}/blog-drafts/generate", json={"confirmed": True})
    draft_id = response.json()["draft"]["id"]

    listed = client.get(f"/api/notes/{note['id']}/blog-drafts")
    assert listed.status_code == 200
    assert listed.json()[0]["id"] == draft_id

    for fmt, media_type in (("md", "text/markdown"), ("txt", "text/plain"), ("html", "text/html")):
        exported = client.get(f"/api/blog-drafts/{draft_id}/export/{fmt}")
        assert exported.status_code == 200
        assert exported.headers["content-type"].startswith(media_type)
        assert "FastAPI 依赖注入" in exported.text


def test_blog_drafts_are_in_backup():
    note = make_note()
    client.post(f"/api/notes/{note['id']}/blog-drafts/generate", json={"confirmed": True})
    backup = client.get("/api/backup/json")
    assert backup.status_code == 200
    assert len(backup.json()["blog_drafts"]) == 1


def test_missing_blog_draft_and_invalid_format_are_rejected():
    assert client.get("/api/blog-drafts/999999").status_code == 404
    assert client.get("/api/blog-drafts/999999/export/md").status_code == 404
    note = make_note()
    draft_id = client.post(f"/api/notes/{note['id']}/blog-drafts/generate", json={"confirmed": True}).json()["draft"]["id"]
    assert client.get(f"/api/blog-drafts/{draft_id}/export/pdf").status_code == 422
