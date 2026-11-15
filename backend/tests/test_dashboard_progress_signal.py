def test_dashboard_exposes_explicit_recent_progress_signal(client):
    empty = client.get("/api/dashboard")
    assert empty.status_code == 200
    assert empty.json()["progress_signal"]["status"] == "no_recent_activity"

    created = client.post(
        "/api/daily-logs",
        json={
            "raw_text": "完成 FastAPI 练习并记录接口测试输出。",
            "extracted_duration": 45,
            "extracted_outputs": ["接口测试输出"],
            "understood_content": ["请求与响应的区别"],
            "confirm": True,
        },
    )
    assert created.status_code in {200, 201}

    signal = client.get("/api/dashboard").json()["progress_signal"]
    assert signal["status"] == "progress"
    assert signal["recent_minutes"] >= 45
    assert signal["recent_evidence_count"] >= 2
    assert signal["basis"]
