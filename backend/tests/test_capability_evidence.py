def test_capability_evidence_exposes_practice_attempts_and_review_errors(client):
    topic = client.post(
        "/api/knowledge-topics",
        json={"name": "Python 列表", "domain": "Python"},
    ).json()
    goal = client.post("/api/goals", json={"title": "能力证据闭环"}).json()
    stage = client.post(
        f"/api/goals/{goal['id']}/stages",
        json={"title": "Python 练习", "capability_targets": ["Python"]},
    ).json()
    assert stage["id"]

    exercise = client.post(
        "/api/exercises",
        json={
            "title": "Python 列表求和",
            "exercise_type": "algorithm",
            "prompt": "使用 Python 计算列表总和",
            "difficulty": "easy",
            "topic_id": topic["id"],
            "validation_spec": {"cases": []},
        },
    ).json()
    attempt = client.post(
        f"/api/exercises/{exercise['id']}/attempts",
        json={"code": "print('ok')"},
    ).json()
    card = client.post(
        "/api/review-cards",
        json={
            "front": "Python 列表如何求和？",
            "back": "使用 sum",
            "topic_id": topic["id"],
        },
    ).json()
    answered = client.post(
        f"/api/review-cards/{card['id']}/answer",
        json={"quality": 1, "error_type": "概念混淆", "error_note": "忘记列表求和方法"},
    )
    assert answered.status_code == 200

    assessed = client.post("/api/capabilities/assess")
    assert assessed.status_code == 200
    capability = next(item for item in assessed.json()["profiles"] if item["name"] == "Python")

    response = client.get(f"/api/capabilities/{capability['id']}/evidence")
    assert response.status_code == 200
    payload = response.json()
    assert payload["capability"]["id"] == capability["id"]
    assert payload["practice"]["exercise_count"] == 1
    assert payload["practice"]["attempt_count"] == 1
    assert payload["practice"]["passed_attempt_count"] == int(attempt["passed"])
    assert payload["practice"]["exercises"][0]["attempts"][0]["id"] == attempt["id"]
    assert payload["review"]["card_count"] == 1
    assert payload["review"]["error_event_count"] == 1
    assert payload["review"]["by_error_type"]["概念混淆"] == 1
    assert payload["review"]["cards"][0]["id"] == card["id"]
    assert payload["review"]["cards"][0]["error_events"][0]["id"]
    assert any(item["source_type"] == "practice_attempt" for item in payload["saved_evidence"])


def test_capability_evidence_returns_empty_related_collections(client):
    goal = client.post("/api/goals", json={"title": "孤立能力"}).json()
    stage = client.post(
        f"/api/goals/{goal['id']}/stages",
        json={"title": "孤立能力阶段", "capability_targets": ["孤立能力"]},
    ).json()
    assert stage["id"]
    assessed = client.post("/api/capabilities/assess")
    capability = next(item for item in assessed.json()["profiles"] if item["name"] == "孤立能力")

    response = client.get(f"/api/capabilities/{capability['id']}/evidence")
    assert response.status_code == 200
    payload = response.json()
    assert payload["topics"] == []
    assert payload["practice"] == {
        "exercise_count": 0,
        "attempt_count": 0,
        "passed_attempt_count": 0,
        "pass_rate": None,
        "exercises": [],
    }
    assert payload["review"]["card_count"] == 0
    assert payload["review"]["error_event_count"] == 0
    assert payload["review"]["cards"] == []
