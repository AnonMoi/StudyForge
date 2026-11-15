import json
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import agent_bridge
from app.main import app
from app.model_routing import ModelResult


def test_agent_chat_returns_safe_hermes_response():
    client = TestClient(app)
    with patch("app.main.agent_bridge.run_study_coach", return_value=ModelResult(True, None, "ollama", "test-local", text="学习建议：先完成一个最小练习。", route_reason="local_success")):
        response = client.post("/api/agent/chat", json={"message": "我今天学什么？"})

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert response.json()["response"] == "学习建议：先完成一个最小练习。"
    assert response.json()["profile"] == "study-coach"


def test_agent_chat_rejects_blank_messages():
    response = TestClient(app).post("/api/agent/chat", json={"message": "   "})

    assert response.status_code == 422


def test_agent_chat_returns_controlled_error_when_hermes_fails():
    client = TestClient(app)
    with patch("app.main.agent_bridge.run_study_coach", side_effect=TimeoutError("timed out")):
        response = client.post("/api/agent/chat", json={"message": "分析我的学习情况"})

    assert response.status_code == 200
    assert response.json()["success"] is False
    assert response.json()["profile"] == "study-coach"
    assert "timed out" in response.json()["error"]


def test_agent_context_endpoint_contains_learning_data():
    response = TestClient(app).get("/api/agent/context")

    assert response.status_code == 200
    assert {"goals", "stages", "tasks", "daily_logs", "notes", "knowledge_topics"}.issubset(response.json())


def test_minimized_context_excludes_raw_text_note_content_and_paths():
    context = {
        "goals": [{"id": 1, "title": "目标", "description": "不应出现的目标描述", "priority": 3, "status": "active"}],
        "stages": [],
        "tasks": [],
        "daily_logs": [{"id": 1, "log_date": "2026-08-12", "raw_text": "今天学了微积分原文", "extracted_topics": ["微积分"], "self_assessment": "还行"}],
        "notes": [{"id": 1, "title": "笔记", "content": "这是笔记正文", "summary": "摘要", "source_path": "C:/Users/secret/note.md", "folder": "Inbox", "tags": ["x"]}],
        "knowledge_topics": [{"id": 1, "name": "微积分", "domain": "数学", "definition": "定义", "self_level": "有印象", "verified_level": 1, "tags": []}],
    }
    result = agent_bridge.build_minimized_context(context)

    assert "微积分原文" not in result          # 学习日志原文被排除
    assert "笔记正文" not in result            # 笔记正文被排除
    assert "secret" not in result              # 原始路径被排除
    assert "Inbox" not in result               # 配置类 folder 字段被排除
    assert "不应出现的目标描述" not in result  # goals.description 被排除
    assert "目标" in result
    assert "微积分" in result
    assert "笔记" in result


def test_minimized_context_redacts_credentials_and_contact():
    context = {
        "goals": [{"id": 1, "title": "api_key=SECRET_VALUE", "priority": 3, "status": "active"}],
        "stages": [],
        "tasks": [],
        "daily_logs": [{"id": 1, "log_date": "2026-08-12", "self_assessment": "联系 13800138000 或 a@b.com"}],
        "notes": [],
        "knowledge_topics": [],
    }
    result = agent_bridge.build_minimized_context(context)

    assert "SECRET_VALUE" not in result
    assert "13800138000" not in result
    assert "a@b.com" not in result
    assert "[REDACTED]" in result


def test_minimized_context_truncates_long_fields():
    long_text = "长" * 300
    context = {
        "goals": [],
        "stages": [],
        "tasks": [],
        "daily_logs": [{"id": 1, "log_date": "2026-08-12", "self_assessment": long_text}],
        "notes": [],
        "knowledge_topics": [],
    }
    result = agent_bridge.build_minimized_context(context)

    assert long_text not in result
    assert "长" * 240 in result


def test_agent_chat_passes_minimized_context_to_hermes():
    sample = {
        "goals": [{"id": 1, "title": "G", "priority": 3, "status": "active", "description": "SECRET_DESC"}],
        "stages": [],
        "tasks": [],
        "daily_logs": [{"id": 1, "log_date": "2026-08-12", "raw_text": "RAW_SECRET", "self_assessment": "ok"}],
        "notes": [{"id": 1, "title": "N", "content": "BODY_SECRET", "source_path": "C:/p", "summary": "s"}],
        "knowledge_topics": [],
    }
    captured = {}

    def fake_run(message, context="", persona="study-coach", conversation=""):
        captured["context"] = context
        captured["persona"] = persona
        captured["conversation"] = conversation
        return ModelResult(True, None, "ollama", "test-local", text="建议", route_reason="local_success")

    with patch("app.main._agent_context", return_value=sample), patch("app.main.agent_bridge.run_study_coach", side_effect=fake_run):
        response = TestClient(app).post("/api/agent/chat", json={"message": "今天学什么？"})

    assert response.status_code == 200
    parsed = json.loads(captured["context"])
    assert set(parsed.keys()) >= {"goals", "stages", "tasks", "daily_logs", "notes", "knowledge_topics"}
    assert "RAW_SECRET" not in captured["context"]
    assert "BODY_SECRET" not in captured["context"]
    assert "SECRET_DESC" not in captured["context"]
    assert captured["context"].startswith("{")
    assert captured["persona"] == "study-coach"


def test_agent_context_local_protocol_unchanged():
    sample = {
        "goals": [{"id": 1, "title": "g", "raw_text": "完整原文"}],
        "stages": [],
        "tasks": [],
        "daily_logs": [],
        "notes": [],
        "knowledge_topics": [],
    }
    with patch("app.main._agent_context", return_value=sample):
        response = TestClient(app).get("/api/agent/context")

    assert response.status_code == 200
    assert response.json()["goals"][0]["raw_text"] == "完整原文"


def test_run_study_coach_redacts_and_limits_final_outbound_prompt():
    captured = {}

    def fake_run(task_type, prompt, confirmed=False):
        captured["prompt"] = prompt
        return ModelResult(True, None, "ollama", "test-model", text="建议", route_reason="test")

    with patch("app.agent_bridge.router.run_task", side_effect=fake_run):
        response = agent_bridge.run_study_coach(
            "api_key=SECRET_VALUE " + "问" * 3000,
            "source_path=C:/private/notes.txt email=a@b.com " + "上下文" * 7000,
        )

    assert response.text == "建议"
    prompt = captured["prompt"]
    assert "SECRET_VALUE" not in prompt
    assert "a@b.com" not in prompt
    assert len(prompt.split("用户问题：\n", 1)[1]) <= 2001
    assert len(prompt.split("学习工作站上下文：\n", 1)[1].split("\n\n当前会话的近期对话：", 1)[0]) <= 12001


def test_conversation_context_is_role_preserving_redacted_and_bounded():
    transcript = agent_bridge.build_conversation_context([
        {"role": "user", "content": "api_key=SECRET_VALUE 我在学事务"},
        {"role": "assistant", "content": "先解释 ACID。"},
        {"role": "system", "content": "不应进入上下文"},
    ])

    assert "user: api_key=[REDACTED] 我在学事务" in transcript
    assert "assistant: 先解释 ACID。" in transcript
    assert "SECRET_VALUE" not in transcript
    assert "不应进入上下文" not in transcript


def test_anna_persona_is_explicit_in_outbound_prompt():
    captured = {}

    def fake_run(task_type, prompt, confirmed=False):
        captured["prompt"] = prompt
        return ModelResult(True, None, "ollama", "test-model", text="先做一个最小练习。", route_reason="test")

    with patch("app.agent_bridge.router.run_task", side_effect=fake_run):
        agent_bridge.run_study_coach("我今天学什么？", persona="anna")

    assert "八奈见杏菜" in captured["prompt"]
    assert "不编造作品外的经历" in captured["prompt"]
    assert "默认使用‘温水’" in captured["prompt"]
    assert "不要把恋爱吃醋、体重焦虑" in captured["prompt"]


# Keep exactly one newline at EOF.
