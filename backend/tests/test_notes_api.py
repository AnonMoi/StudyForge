from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def make_note(**overrides):
    payload = {
        "title": "Python 测试笔记",
        "content": "pytest 可以验证行为。",
        "summary": "测试摘要",
        "tags": ["Python", "测试"],
    }
    payload.update(overrides)
    response = client.post("/api/notes", json=payload)
    assert response.status_code == 201
    return response.json()


def test_note_can_be_edited():
    note = make_note()
    response = client.patch(f"/api/notes/{note['id']}", json={"title": "更新后的标题", "content": "新内容"})
    assert response.status_code == 200
    assert response.json()["title"] == "更新后的标题"
    assert response.json()["content"] == "新内容"


def test_notes_can_be_searched_in_title_content_and_tags():
    make_note(title="FastAPI 入门", content="路由与依赖注入")
    make_note(title="SQLite 记录", content="数据库索引", tags=["后端"])
    response = client.get("/api/notes", params={"q": "依赖注入"})
    assert response.status_code == 200
    assert [item["title"] for item in response.json()] == ["FastAPI 入门"]
    response = client.get("/api/notes", params={"q": "后端"})
    assert [item["title"] for item in response.json()] == ["SQLite 记录"]


def test_note_can_be_archived_and_archived_notes_are_hidden_by_default():
    note = make_note()
    response = client.post(f"/api/notes/{note['id']}/archive")
    assert response.status_code == 200
    assert response.json()["status"] == "archived"
    assert client.get("/api/notes").json() == []
    assert client.get("/api/notes", params={"include_archived": "true"}).json()[0]["id"] == note["id"]


def test_note_can_be_deleted():
    note = make_note()
    response = client.delete(f"/api/notes/{note['id']}")
    assert response.status_code == 204
    assert client.get("/api/notes", params={"include_archived": "true"}).json() == []


def test_note_can_be_exported_as_markdown_txt_and_html():
    note = make_note(title="导出标题", content="# 正文", tags=["学习"])
    for fmt, media_type, expected in [
        ("markdown", "text/markdown", "# 导出标题"),
        ("txt", "text/plain", "导出标题"),
        ("html", "text/html", "<h1>导出标题</h1>"),
    ]:
        response = client.get(f"/api/notes/{note['id']}/export/{fmt}")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith(media_type)
        assert expected in response.text


def test_missing_note_returns_not_found():
    assert client.patch("/api/notes/999999", json={"title": "x"}).status_code == 404
    assert client.delete("/api/notes/999999").status_code == 404
    assert client.get("/api/notes/999999/export/txt").status_code == 404


# Compatibility: clients may use the query-form export endpoint.
def test_note_export_query_format_is_supported():
    note = make_note()
    response = client.get(f"/api/notes/{note['id']}/export", params={"format": "txt"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")


def test_note_export_md_alias_is_supported():
    note = make_note()
    response = client.get(f"/api/notes/{note['id']}/export/md")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")


def test_invalid_export_format_is_rejected():
    note = make_note()
    assert client.get(f"/api/notes/{note['id']}/export/pdf").status_code == 422
    assert client.get(f"/api/notes/{note['id']}/export", params={"format": "pdf"}).status_code == 422
