from datetime import date, timedelta


def test_review_scheduler_previews_then_confirms_new_review(client):
    log = client.post(
        "/api/daily-logs",
        json={
            "raw_text": "完成复习安排测试",
            "log_date": (date.today() - timedelta(days=1)).isoformat(),
            "extracted_topics": ["复习调度"],
            "extracted_duration": 30,
            "extracted_outputs": ["测试结果"],
            "confirm": True,
        },
    )
    assert log.status_code == 201

    preview = client.post("/api/reviews/schedule", json={"lookahead_days": 7})
    assert preview.status_code == 200
    preview_data = preview.json()
    assert preview_data["requires_confirmation"] is True
    assert preview_data["recommendations"][0]["daily_log_id"] == log.json()["id"]
    assert preview_data["recommendations"][0]["review_date"] == date.today().isoformat()

    confirmed = client.post("/api/reviews/schedule", json={"lookahead_days": 7, "confirmed": True})
    assert confirmed.status_code == 200
    assert confirmed.json()["executed"] is True
    assert len(confirmed.json()["created_reviews"]) == 1

    repeated = client.post("/api/reviews/schedule", json={"lookahead_days": 7})
    assert repeated.status_code == 200
    assert repeated.json()["recommendations"] == []
