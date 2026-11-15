from fastapi.testclient import TestClient

from app.main import app


def test_topic_can_be_created_with_json_tags_and_edited():
    client = TestClient(app)
    created = client.post("/api/knowledge-topics", json={"name": "SQL", "definition": "查询语言", "tags": ["数据库", "基础"]})
    assert created.status_code == 201
    topic_id = created.json()["id"]
    assert created.json()["tags"] == ["数据库", "基础"]

    updated = client.patch(f"/api/knowledge-topics/{topic_id}", json={"definition": "关系数据库查询语言", "tags": ["数据库", "查询"]})
    assert updated.status_code == 200
    assert updated.json()["definition"] == "关系数据库查询语言"
    assert updated.json()["tags"] == ["数据库", "查询"]


def test_topics_can_be_searched_by_text_and_tag():
    client = TestClient(app)
    client.post("/api/knowledge-topics", json={"name": "FastAPI", "definition": "Python web framework", "tags": ["Python", "web"]})
    client.post("/api/knowledge-topics", json={"name": "SQLite", "definition": "embedded database", "tags": ["database"]})

    assert [item["name"] for item in client.get("/api/knowledge-topics", params={"q": "python"}).json()] == ["FastAPI"]
    assert [item["name"] for item in client.get("/api/knowledge-topics", params={"tag": "database"}).json()] == ["SQLite"]


def test_topic_relations_can_be_created_and_listed():
    client = TestClient(app)
    source = client.post("/api/knowledge-topics", json={"name": "HTTP"}).json()
    target = client.post("/api/knowledge-topics", json={"name": "FastAPI"}).json()

    relation = client.post(
        f"/api/knowledge-topics/{source['id']}/relations",
        json={"target_topic_id": target["id"], "relation_type": "prerequisite"},
    )
    assert relation.status_code == 201
    assert relation.json()["source_topic_id"] == source["id"]
    assert relation.json()["target_topic_id"] == target["id"]
    listed = client.get(f"/api/knowledge-topics/{source['id']}/relations")
    assert listed.status_code == 200
    assert listed.json()[0]["relation_type"] == "prerequisite"


def test_topic_edit_and_relation_require_existing_records():
    client = TestClient(app)
    assert client.patch("/api/knowledge-topics/999999", json={"name": "missing"}).status_code == 404
    assert client.post("/api/knowledge-topics/999999/relations", json={"target_topic_id": 1, "relation_type": "related"}).status_code == 404
    topic = client.post("/api/knowledge-topics", json={"name": "Only"}).json()
    assert client.post(f"/api/knowledge-topics/{topic['id']}/relations", json={"target_topic_id": 999999, "relation_type": "related"}).status_code == 404
