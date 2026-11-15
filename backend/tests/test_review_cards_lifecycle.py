from datetime import date


def make_card(client, front="问题"):
    response = client.post("/api/review-cards", json={"front": front, "back": "答案", "hint": "提示"})
    assert response.status_code == 201
    return response.json()


def test_review_card_can_edit_archive_restore_and_soft_delete(client):
    card = make_card(client)
    updated = client.patch(f"/api/review-cards/{card['id']}", json={"front": "更新后的问题", "back": "更新后的答案"})
    assert updated.status_code == 200
    assert updated.json()["front"] == "更新后的问题"

    archived = client.post(f"/api/review-cards/{card['id']}/archive")
    assert archived.status_code == 200
    assert archived.json()["status"] == "archived"
    assert client.get("/api/review-cards").json() == []
    assert client.get("/api/review-cards?include_completed=true").json()[0]["status"] == "archived"

    restored = client.post("/api/review-cards/bulk", json={"card_ids": [card["id"]], "action": "restore"})
    assert restored.status_code == 200
    assert restored.json()[0]["status"] == "active"

    deleted = client.delete(f"/api/review-cards/{card['id']}")
    assert deleted.status_code == 200
    assert deleted.json()["status"] == "deleted"
    assert client.get("/api/review-cards").json() == []
    assert client.get("/api/review-cards?include_deleted=true").json()[0]["status"] == "deleted"


def test_review_card_bulk_actions_and_stats(client):
    first = make_card(client, "一")
    second = make_card(client, "二")
    bulk = client.post("/api/review-cards/bulk", json={"card_ids": [first["id"], second["id"]], "action": "archive"})
    assert bulk.status_code == 200
    assert {item["status"] for item in bulk.json()} == {"archived"}

    stats = client.get("/api/review-cards/stats")
    assert stats.status_code == 200
    assert stats.json()["total_cards"] == 2
    assert stats.json()["archived_cards"] == 2


def test_review_history_is_recorded_and_exposes_scheduler_snapshot(client):
    card = make_card(client)
    answered = client.post(f"/api/review-cards/{card['id']}/answer", json={"quality": 4})
    assert answered.status_code == 200
    assert answered.json()["repetitions"] == 1
    assert answered.json()["due_date"] > date.today().isoformat()

    history = client.get(f"/api/review-cards/{card['id']}/history")
    assert history.status_code == 200
    assert len(history.json()) == 1
    item = history.json()[0]
    assert item["quality"] == 4
    assert item["interval_before"] == 1
    assert item["interval_after"] == 1
    assert item["repetitions_before"] == 0
    assert item["repetitions_after"] == 1


def test_archived_card_cannot_be_answered(client):
    card = make_card(client)
    assert client.post(f"/api/review-cards/{card['id']}/archive").status_code == 200
    response = client.post(f"/api/review-cards/{card['id']}/answer", json={"quality": 5})
    assert response.status_code == 409
