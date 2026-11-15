from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_knowledge_relations_create_list_delete():
    source = client.post("/api/knowledge-topics", json={"name": "关系源"}).json()
    target = client.post("/api/knowledge-topics", json={"name": "关系目标"}).json()
    created = client.post(f"/api/knowledge-topics/{source['id']}/relations", json={"target_topic_id": target["id"], "relation_type": "prerequisite"})
    assert created.status_code == 201
    relation_id = created.json()["id"]

    listed = client.get(f"/api/knowledge-topics/{source['id']}/relations")
    assert listed.status_code == 200
    assert listed.json()[0]["id"] == relation_id

    deleted = client.delete(f"/api/knowledge-relations/{relation_id}")
    assert deleted.status_code == 204
    assert client.get(f"/api/knowledge-topics/{source['id']}/relations").json() == []


def test_knowledge_relation_rejects_missing_target():
    source = client.post("/api/knowledge-topics", json={"name": "只有源"}).json()
    response = client.post(f"/api/knowledge-topics/{source['id']}/relations", json={"target_topic_id": 999999, "relation_type": "related"})
    assert response.status_code == 404


def test_knowledge_graph_returns_nodes_and_edges():
    source = client.post("/api/knowledge-topics", json={"name": "图谱源"}).json()
    target = client.post("/api/knowledge-topics", json={"name": "图谱目标"}).json()
    client.post(f"/api/knowledge-topics/{source['id']}/relations", json={"target_topic_id": target["id"], "relation_type": "related"})
    graph = client.get("/api/knowledge-graph")
    assert graph.status_code == 200
    assert {node["id"] for node in graph.json()["nodes"]} >= {source["id"], target["id"]}
    assert graph.json()["edges"][0]["source_topic_id"] == source["id"]


def test_knowledge_topic_update():
    topic = client.post("/api/knowledge-topics", json={"name": "待更新主题"}).json()
    response = client.patch(f"/api/knowledge-topics/{topic['id']}", json={"definition": "新的定义"})
    assert response.status_code == 200
    assert response.json()["definition"] == "新的定义"
    assert response.json()["verified_level"] == 0
    verified = client.post(f"/api/knowledge-topics/{topic['id']}/verify", json={"verified_level": 3, "evidence": "独立解释并完成一个可复现实例"})
    assert verified.status_code == 200
    assert verified.json()["verified_level"] == 3


def test_knowledge_relation_duplicate_is_rejected():
    source = client.post("/api/knowledge-topics", json={"name": "唯一源"}).json()
    target = client.post("/api/knowledge-topics", json={"name": "唯一目标"}).json()
    payload = {"target_topic_id": target["id"], "relation_type": "related"}
    assert client.post(f"/api/knowledge-topics/{source['id']}/relations", json=payload).status_code == 201
    assert client.post(f"/api/knowledge-topics/{source['id']}/relations", json=payload).status_code in (409, 422)
