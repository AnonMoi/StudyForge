from types import SimpleNamespace
from unittest.mock import patch


def test_structured_teaching_evaluation_is_persisted(client):
    session = client.post("/api/teaching/sessions", json={"title": "结构化评价测试"}).json()
    attempt = client.post(
        f"/api/teaching/sessions/{session['id']}/attempts",
        json={"prompt": "解释缓存", "expected_answer": "缓存保存结果以减少重复计算", "rubric": ["定义", "收益"]},
    ).json()
    client.post(f"/api/teaching/sessions/{session['id']}/attempts/{attempt['id']}/answer", json={"user_answer": "缓存可以减少重复计算。"})
    fake_result = SimpleNamespace(
        success=True,
        data={
            "score": 4,
            "confidence": 0.88,
            "covered_rubric": ["收益"],
            "missing_rubric": ["定义"],
            "misconceptions": [],
            "error_type": None,
            "feedback": "覆盖了收益，补充缓存的定义即可。",
            "recommendation": "下次复习时先给出定义，再说明收益。",
        },
        text=None,
    )
    with patch("app.main.router.run_task", return_value=fake_result):
        response = client.post(f"/api/teaching/sessions/{session['id']}/attempts/{attempt['id']}/evaluate")
    assert response.status_code == 200
    body = response.json()
    assert body["evaluation_source"] == "structured_model"
    assert body["evaluation_confidence"] == 0.88
    assert body["evaluation_details"]["missing_rubric"] == ["定义"]


def test_invalid_or_low_confidence_model_evaluation_falls_back_locally(client):
    session = client.post("/api/teaching/sessions", json={"title": "评价回退测试"}).json()
    attempt = client.post(
        f"/api/teaching/sessions/{session['id']}/attempts",
        json={"prompt": "解释索引", "expected_answer": "索引帮助数据库快速定位记录", "rubric": ["作用"]},
    ).json()
    client.post(f"/api/teaching/sessions/{session['id']}/attempts/{attempt['id']}/answer", json={"user_answer": "我不确定。"})
    fake_result = SimpleNamespace(success=True, data={"score": 5, "confidence": 0.2}, text=None)
    with patch("app.main.router.run_task", return_value=fake_result):
        response = client.post(f"/api/teaching/sessions/{session['id']}/attempts/{attempt['id']}/evaluate")
    assert response.status_code == 200
    assert response.json()["evaluation_source"] == "local_deterministic"


def test_high_confidence_low_score_model_evaluation_fills_missing_error_type(client):
    session = client.post("/api/teaching/sessions", json={"title": "低分错因补齐测试"}).json()
    attempt = client.post(
        f"/api/teaching/sessions/{session['id']}/attempts",
        json={"prompt": "解释事务", "expected_answer": "事务保证一组操作的原子性", "rubric": ["原子性"]},
    ).json()
    client.post(
        f"/api/teaching/sessions/{session['id']}/attempts/{attempt['id']}/answer",
        json={"user_answer": "我不确定。"},
    )
    fake_result = SimpleNamespace(
        success=True,
        data={
            "score": 2,
            "confidence": 0.9,
            "covered_rubric": [],
            "missing_rubric": ["原子性"],
            "misconceptions": [],
            "error_type": None,
            "feedback": "需要补充原子性的定义。",
            "recommendation": "用一个事务例子重新回答。",
        },
        text=None,
    )
    with patch("app.main.router.run_task", return_value=fake_result):
        response = client.post(f"/api/teaching/sessions/{session['id']}/attempts/{attempt['id']}/evaluate")
    assert response.status_code == 200
    body = response.json()
    assert body["evaluation_source"] == "structured_model"
    assert body["error_type"] == "概念理解不足"
