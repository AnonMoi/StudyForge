from types import SimpleNamespace
from unittest.mock import patch


def test_teaching_loop_answer_evaluate_and_recommendation(client):
    topic = client.post("/api/knowledge-topics", json={"name": "Python 闭包"}).json()
    session = client.post(
        "/api/teaching/sessions",
        json={"title": "闭包教学", "topic_id": topic["id"], "explanation": "闭包保留了定义时的词法环境。"},
    )
    assert session.status_code == 201
    session_id = session.json()["id"]

    attempt = client.post(
        f"/api/teaching/sessions/{session_id}/attempts",
        json={
            "prompt": "什么是闭包？",
            "expected_answer": "闭包保留定义时的词法环境，可以访问外层函数变量。",
            "rubric": ["定义", "词法环境", "外层变量"],
        },
    )
    assert attempt.status_code == 201
    attempt_id = attempt.json()["id"]

    answered = client.post(
        f"/api/teaching/sessions/{session_id}/attempts/{attempt_id}/answer",
        json={"user_answer": "它可以访问外层变量。"},
    )
    assert answered.status_code == 200
    assert answered.json()["answered_at"] is not None

    evaluated = client.post(f"/api/teaching/sessions/{session_id}/attempts/{attempt_id}/evaluate")
    assert evaluated.status_code == 200
    body = evaluated.json()
    assert body["score"] < 4
    assert body["error_type"]
    assert body["review_card_id"] is not None
    assert body["feedback"]

    recommendations = client.get(f"/api/teaching/sessions/{session_id}/recommendations")
    assert recommendations.status_code == 200
    assert recommendations.json()["review_card_ids"] == [body["review_card_id"]]


def test_teaching_loop_rejects_evaluation_without_answer(client):
    session = client.post("/api/teaching/sessions", json={"title": "未作答测试"}).json()
    attempt = client.post(
        f"/api/teaching/sessions/{session['id']}/attempts",
        json={"prompt": "解释一个概念"},
    ).json()
    response = client.post(f"/api/teaching/sessions/{session['id']}/attempts/{attempt['id']}/evaluate")
    assert response.status_code == 409


def test_teaching_loop_uses_local_first_router_for_future_agent_extension(client):
    session = client.post("/api/teaching/sessions", json={"title": "路由兼容测试"})
    assert session.status_code == 201
    with patch("app.main.router.run_task") as run_task:
        run_task.return_value.success = True
        assert session.json()["status"] == "active"
        run_task.assert_not_called()


def test_interview_generation_uses_interview_rubric(client):
    session = client.post(
        "/api/teaching/sessions",
        json={"title": "模拟面试 · Python 后端实习生", "explanation": "目标岗位：Python 后端实习生"},
    ).json()
    with patch("app.main.router.run_task", return_value=SimpleNamespace(success=True, text="请介绍一个后端项目并说明技术取舍。")):
        response = client.post(f"/api/teaching/sessions/{session['id']}/generate", json={"instruction": "生成一个面试问题"})
    assert response.status_code == 200
    attempt = response.json()["attempts"][0]
    assert attempt["phase"] == "interview"
    assert attempt["rubric"] == ["背景与目标", "技术决策", "结果证据", "复盘与改进"]
    assert "Python 后端实习生" in attempt["prompt"]
