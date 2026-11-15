from pathlib import Path
from zipfile import ZipFile

from app import file_import


def test_html_import_extracts_readable_content_without_scripts(client, tmp_path: Path):
    document = tmp_path / "lesson.html"
    document.write_text(
        """<!doctype html>
        <html><head><title>网页课程</title><style>.hidden { display:none }</style></head>
        <body><h1>HTTP 基础</h1><p>请求由方法、路径和状态码组成。</p>
        <script>token = 'should-not-be-indexed'</script>
        <ul><li>GET</li><li>POST</li></ul></body></html>""",
        encoding="utf-8",
    )
    directory = client.post("/api/authorized-directories", json={"path": str(tmp_path)}).json()

    response = client.post(f"/api/authorized-directories/{directory['id']}/scan")

    assert response.status_code == 200
    item = response.json()["files"][0]
    assert item["content_status"] == "imported"
    assert "HTTP 基础" in item["content"]
    assert "请求由方法" in item["content"]
    assert "GET" in item["content"]
    assert "should-not-be-indexed" not in item["content"]
    assert "<h1>" not in item["content"]


def test_docx_import_extracts_paragraphs_and_tables(client, tmp_path: Path):
    document = tmp_path / "lesson.docx"
    document_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
    <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
      <w:body>
        <w:p><w:r><w:t>课程标题</w:t></w:r></w:p>
        <w:p><w:r><w:t>正文说明</w:t></w:r><w:r><w:tab/><w:t>第二句</w:t></w:r></w:p>
        <w:tbl>
          <w:tr><w:tc><w:p><w:r><w:t>方法</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>用途</w:t></w:r></w:p></w:tc></w:tr>
          <w:tr><w:tc><w:p><w:r><w:t>GET</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>读取资源</w:t></w:r></w:p></w:tc></w:tr>
        </w:tbl>
      </w:body>
    </w:document>"""
    with ZipFile(document, "w") as archive:
        archive.writestr("word/document.xml", document_xml)
    directory = client.post("/api/authorized-directories", json={"path": str(tmp_path)}).json()

    response = client.post(f"/api/authorized-directories/{directory['id']}/scan")

    assert response.status_code == 200
    item = response.json()["files"][0]
    assert item["content_status"] == "imported"
    assert "课程标题" in item["content"]
    assert "正文说明\t第二句" in item["content"]
    assert "| 方法 | 用途 |" in item["content"]
    assert "| GET | 读取资源 |" in item["content"]


def test_document_parser_reports_empty_documents(client, tmp_path: Path):
    document = tmp_path / "empty.html"
    document.write_text("<html><head><title>空页面</title></head><body><script>ignore()</script></body></html>", encoding="utf-8")
    directory = client.post("/api/authorized-directories", json={"path": str(tmp_path)}).json()

    response = client.post(f"/api/authorized-directories/{directory['id']}/scan")

    assert response.status_code == 200
    assert response.json()["files"][0]["content_status"] == "empty"


def test_supported_code_extensions_are_scanned_and_indexed(client, tmp_path: Path):
    samples = {
        "main.py": "print('python')\n",
        "app.ts": "const answer: number = 42;\n",
        "service.java": "class Service {}\n",
        "native.c": "int main(void) { return 0; }\n",
        "engine.cpp": "int main() { return 0; }\n",
        "query.sql": "SELECT 1;\n",
        "player.gd": "extends Node\n",
    }
    for name, content in samples.items():
        (tmp_path / name).write_text(content, encoding="utf-8")
    directory = client.post("/api/authorized-directories", json={"path": str(tmp_path)}).json()

    response = client.post(f"/api/authorized-directories/{directory['id']}/scan")

    assert response.status_code == 200
    files = {item["relative_path"]: item for item in response.json()["files"]}
    assert set(files) == set(samples)
    assert all(item["content_status"] == "imported" for item in files.values())
    assert files["main.py"]["content"] == samples["main.py"]
    assert files["player.gd"]["content"] == samples["player.gd"]


def test_web_import_is_previewed_then_confirmed_into_knowledge_base(client, monkeypatch):
    monkeypatch.setattr(
        file_import,
        "_fetch_web_page",
        lambda _url: {
            "url": "https://example.com/course",
            "final_url": "https://example.com/course",
            "title": "HTTP 课程",
            "mime_type": "text/html",
            "raw": "<html><body><h1>HTTP 课程</h1><p>请求和响应。</p></body></html>".encode("utf-8"),
            "content": "HTTP 课程\n请求和响应。",
            "content_status": "imported",
        },
    )

    fetched = client.post("/api/imports/web", json={"url": "https://example.com/course"})

    assert fetched.status_code == 200
    resource = fetched.json()
    assert resource["requires_confirmation"] is True
    assert resource["content_status"] == "imported"
    assert resource["title"] == "HTTP 课程"

    preview = client.post(f"/api/imports/web/{resource['resource_id']}/confirm", json={"confirmed": False})
    assert preview.status_code == 200
    assert preview.json()["preview"][0]["will_create_note"] is True

    confirmed = client.post(f"/api/imports/web/{resource['resource_id']}/confirm", json={"confirmed": True})
    assert confirmed.status_code == 200
    assert confirmed.json()["created_notes"] == 1
    assert client.get("/api/notes").json()[0]["source_path"] == "https://example.com/course"
    search = client.get("/api/imports/search", params={"q": "请求和响应"})
    assert search.status_code == 200
    assert search.json()["matches"][0]["web_resource_id"] == resource["resource_id"]
    integrity = client.get("/api/imports/integrity").json()
    assert integrity["web_resources"][0]["status"] == "healthy"
    assert integrity["orphan_files"] == []
    assert client.get("/api/backup/json").json()["web_resources"][0]["url"] == "https://example.com/course"

    repeated = client.post(f"/api/imports/web/{resource['resource_id']}/confirm", json={"confirmed": True})
    assert repeated.status_code == 200
    assert repeated.json()["reused"] is True


def test_web_import_rejects_private_network_targets(client):
    response = client.post("/api/imports/web", json={"url": "http://127.0.0.1:8000/health"})

    assert response.status_code == 400
    assert "公网" in response.json()["detail"]
