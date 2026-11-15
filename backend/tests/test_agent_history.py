from concurrent.futures import ThreadPoolExecutor
import asyncio
from datetime import datetime, timezone
from pathlib import Path
import threading
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.agent_models import ChatMessage, ChatTurn
from app.conversation_service import TurnConflictError, conversation_service
from app.db import Base
from app.db import get_db
from app.main import app
from app.model_routing import ModelResult
from app.provider_execution import ProviderAttempt, ProviderExecutionResult, ProviderLifecycleEvent


def execution_result(text: str, turn_id: str = "test-turn") -> ProviderExecutionResult:
    return ProviderExecutionResult(turn_id, True, text, "ollama", "test-local", "local_stream_success", None, None, ())


def test_agent_chat_persists_history_and_can_be_listed():
    client = TestClient(app)
    with patch("app.main.agent_bridge.run_study_coach", return_value=ModelResult(True, None, "ollama", "test-local", text="先完成一个最小练习。", route_reason="local_success")):
        response = client.post("/api/agent/chat", json={"message": "我今天学什么？", "session_id": "test-session", "persona": "anna", "request_id": "normal-turn"})

    assert response.status_code == 200
    body = response.json()
    assert body["session_id"] == "test-session"
    assert body["request_id"] == body["turn_id"] == "normal-turn"
    history = client.get("/api/agent/history/test-session")
    assert history.status_code == 200
    assert [item["role"] for item in history.json()] == ["user", "assistant"]
    assert history.json()[0]["content"] == "我今天学什么？"
    assert {item["turn_id"] for item in history.json()} == {"normal-turn"}
    assert {item["persona"] for item in history.json()} == {"anna"}
    assert {item["turn_status"] for item in history.json()} == {"completed"}
    assert {item["provider"] for item in history.json()} == {"ollama"}
    assert {item["model_name"] for item in history.json()} == {"test-local"}


def test_agent_chat_classifies_output_and_returns_confirmable_conversions():
    client = TestClient(app)
    with patch("app.main.agent_bridge.run_study_coach", return_value=ModelResult(True, None, "ollama", "test-local", text="建议先完成一个最小练习，再记录验证结果。", route_reason="local_success")):
        response = client.post("/api/agent/chat", json={"message": "给我一个学习建议", "session_id": "metadata-session"})

    assert response.status_code == 200
    body = response.json()
    assert body["output_type"] == "suggestion"
    assert body["basis"]
    assert body["uncertainty"]
    assert {item["operation"] for item in body["actions"]} == {"create_note", "create_task", "create_topic"}

    action = body["actions"][0]
    preview = client.post("/api/agent/change", json={"operation": action["operation"], "payload": action["payload"]})
    assert preview.status_code == 200
    assert preview.json()["executed"] is False


def test_agent_stream_returns_sse_events_and_persists_messages():
    client = TestClient(app)
    with patch("app.main.agent_bridge.execute_study_coach", return_value=execution_result("第一步。\n第二步。")):
        response = client.post("/api/agent/chat/stream", json={"message": "给我学习建议", "session_id": "stream-session"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: token" in response.text
    assert "第一步。" in response.text
    assert "event: done" in response.text
    assert "event: meta" in response.text
    assert len(client.get("/api/agent/history/stream-session").json()) == 2


def test_agent_stream_emits_correlated_provider_lifecycle_in_order():
    client = TestClient(app)

    async def fake_execution(*args, **kwargs):
        now = datetime.now(timezone.utc)
        local = ProviderAttempt("local-attempt", kwargs["turn_id"], "ollama", "local", "local", "running", None, "local_started", now, None, now, 0)
        kwargs["on_event"](ProviderLifecycleEvent("local_started", local))
        local_failed = ProviderAttempt("local-attempt", kwargs["turn_id"], "ollama", "local", "local", "timed_out", "timeout", "local_timeout", now, now, now, 20)
        kwargs["on_event"](ProviderLifecycleEvent("local_failed", local_failed))
        cloud = ProviderAttempt("cloud-attempt", kwargs["turn_id"], "zhiapi", "cloud", "cloud", "running", None, "cloud_started", now, None, None, 0)
        kwargs["on_event"](ProviderLifecycleEvent("cloud_started", cloud))
        return ProviderExecutionResult(kwargs["turn_id"], True, "fallback", "zhiapi", "cloud", "local_first_local_unavailable_cloud_fallback", None, None, (local_failed, cloud))

    with patch("app.main.agent_bridge.execute_study_coach", side_effect=fake_execution):
        response = client.post("/api/agent/chat/stream", json={"message": "fallback", "session_id": "lifecycle", "request_id": "lifecycle-turn"})

    positions = [response.text.index(f"event: {event}") for event in ("accepted", "local_started", "local_failed", "cloud_started", "meta", "token", "completed", "done")]
    assert positions == sorted(positions)
    assert response.text.count('"request_id": "lifecycle-turn"') == 8
    assert '"attempt_id": "local-attempt"' in response.text
    assert '"attempt_id": "cloud-attempt"' in response.text


def test_agent_chat_rejects_unknown_persona():
    response = TestClient(app).post("/api/agent/chat", json={"message": "给我建议", "persona": "unknown"})

    assert response.status_code == 422


def test_failed_turn_requires_a_new_request_id_for_retry():
    client = TestClient(app)
    attempts = {"count": 0}

    async def fake_stream(*args, **kwargs):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise RuntimeError("temporary failure")
        return execution_result("重试后的完整回复。", kwargs.get("turn_id", "retry"))

    payload = {"message": "同一轮重试", "session_id": "retry-session", "request_id": "retry-turn-1"}
    with patch("app.main.agent_bridge.execute_study_coach", side_effect=fake_stream):
        first = client.post("/api/agent/chat/stream", json=payload)
        duplicate = client.post("/api/agent/chat/stream", json=payload)
        second = client.post("/api/agent/chat/stream", json={**payload, "request_id": "retry-turn-2"})

    assert "event: error" in first.text
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "TURN_FAILED"
    assert "重试后的完整回复。" in second.text
    history = client.get("/api/agent/history/retry-session").json()
    assert [item["role"] for item in history] == ["user", "user", "assistant"]
    assert [item["turn_status"] for item in history] == ["failed", "completed", "completed"]
    assert history[0]["content"] == "同一轮重试"


def test_same_text_with_distinct_request_ids_creates_distinct_turns(client):
    with patch("app.main.agent_bridge.execute_study_coach", side_effect=[execution_result("A", "same-a"), execution_result("B", "same-b")]):
        first = client.post("/api/agent/chat/stream", json={"message": "继续", "session_id": "same-text", "request_id": "same-a"})
        second = client.post("/api/agent/chat/stream", json={"message": "继续", "session_id": "same-text", "request_id": "same-b"})

    assert first.status_code == second.status_code == 200
    history = client.get("/api/agent/history/same-text").json()
    assert [item["turn_id"] for item in history] == ["same-a", "same-a", "same-b", "same-b"]


def test_completed_request_is_replayed_without_provider_invocation(client):
    calls = {"count": 0}

    async def fake_stream(*args, **kwargs):
        calls["count"] += 1
        return execution_result("只生成一次", kwargs.get("turn_id", "replay-turn"))

    payload = {"message": "断线后重放", "session_id": "replay", "persona": "anna", "request_id": "replay-turn"}
    with patch("app.main.agent_bridge.execute_study_coach", side_effect=fake_stream):
        first = client.post("/api/agent/chat/stream", json=payload)
        replay = client.post("/api/agent/chat/stream", json=payload)

    assert first.status_code == replay.status_code == 200
    assert calls["count"] == 1
    assert "只生成一次" in replay.text
    assert '"replay_reason": "idempotent_replay"' in replay.text
    assert '"provider": "ollama"' in replay.text
    assert len(client.get("/api/agent/history/replay").json()) == 2


def test_reversed_completion_reconstructs_turn_order_and_persona(db_session):
    conversation_service.begin_turn(db_session, request_id="turn-a", session_id="shared", persona="anna", message="A")
    conversation_service.begin_turn(db_session, request_id="turn-b", session_id="shared", persona="study-coach", message="B")
    conversation_service.complete_turn(db_session, turn_id="turn-b", response="B answer")
    conversation_service.complete_turn(db_session, turn_id="turn-a", response="A answer")

    rows = conversation_service.history_messages(db_session, session_id="shared")
    assert [(message.turn_id, message.role, message.persona) for message, _ in rows] == [
        ("turn-a", "user", "anna"),
        ("turn-a", "assistant", "anna"),
        ("turn-b", "user", "study-coach"),
        ("turn-b", "assistant", "study-coach"),
    ]


def test_pending_turn_is_excluded_from_prompt_snapshot(db_session):
    conversation_service.begin_turn(db_session, request_id="complete", session_id="snapshot", persona="anna", message="已完成问题")
    conversation_service.complete_turn(db_session, turn_id="complete", response="已完成回答")
    conversation_service.begin_turn(db_session, request_id="pending", session_id="snapshot", persona="study-coach", message="并发中的半轮")

    messages = conversation_service.completed_context_messages(db_session, session_id="snapshot")
    assert [(item.role, item.content) for item in messages] == [("user", "已完成问题"), ("assistant", "已完成回答")]


def test_concurrent_duplicate_request_has_one_execution_owner(tmp_path: Path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'concurrent-turn.sqlite3').as_posix()}", connect_args={"check_same_thread": False, "timeout": 5})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def claim() -> str:
        with factory() as db:
            try:
                result = conversation_service.begin_turn(db, request_id="one-request", session_id="shared", persona="anna", message="只执行一次")
                return "owner" if result.owns_execution else "replay"
            except TurnConflictError as exc:
                return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: claim(), range(2)))

    with factory() as db:
        assert db.scalar(select(ChatTurn).where(ChatTurn.turn_id == "one-request")) is not None
        assert len(list(db.scalars(select(ChatMessage).where(ChatMessage.turn_id == "one-request")))) == 1
    assert sorted(outcomes) == ["TURN_RUNNING", "owner"]


def test_concurrent_duplicate_http_requests_invoke_provider_once(tmp_path: Path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'concurrent-http.sqlite3').as_posix()}", connect_args={"check_same_thread": False, "timeout": 5})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    provider_started = threading.Event()
    provider_release = threading.Event()
    provider_calls = {"count": 0}

    def override_get_db():
        with factory() as db:
            yield db

    async def fake_stream(*args, **kwargs):
        provider_calls["count"] += 1
        provider_started.set()
        assert await asyncio.to_thread(provider_release.wait, 5)
        return execution_result("唯一回复", kwargs.get("turn_id", "http-one"))

    payload = {"message": "并发重复", "session_id": "http-shared", "persona": "anna", "request_id": "http-one"}
    app.dependency_overrides[get_db] = override_get_db
    try:
        with patch("app.main.agent_bridge.execute_study_coach", side_effect=fake_stream), ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(lambda: TestClient(app).post("/api/agent/chat/stream", json=payload))
            assert provider_started.wait(timeout=5)
            duplicate = pool.submit(lambda: TestClient(app).post("/api/agent/chat/stream", json=payload)).result(timeout=5)
            provider_release.set()
            original = first.result(timeout=5)
    finally:
        provider_release.set()

    assert original.status_code == 200
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "TURN_RUNNING"
    assert provider_calls["count"] == 1
    with factory() as db:
        assert len(list(db.scalars(select(ChatMessage).where(ChatMessage.turn_id == "http-one")))) == 2


def test_request_id_cannot_be_reused_for_different_payload(db_session):
    conversation_service.begin_turn(db_session, request_id="fixed", session_id="shared", persona="anna", message="第一条")
    with pytest.raises(TurnConflictError, match="请求 ID") as error:
        conversation_service.begin_turn(db_session, request_id="fixed", session_id="shared", persona="anna", message="另一条")
    assert error.value.code == "REQUEST_ID_REUSED"
