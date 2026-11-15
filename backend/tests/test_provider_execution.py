import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import threading
import time

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.agent_models import ChatMessage, ChatTurn
from app.config import settings
from app.conversation_service import conversation_service
from app.db import Base
from app.model_routing import ModelResult, ModelRouter, normalize_interactive_failure
from app.provider_execution import ProviderCancellation


class SuccessfulCloud:
    provider = "cloud"

    def __init__(self, calls=None):
        self.calls = calls if calls is not None else []

    def chat(self, task_type, prompt, *, cancel_token=None):
        self.calls.append(prompt)
        return ModelResult(True, None, "cloud", "cloud-test", text=f"cloud:{prompt}")


def router_with_cloud(monkeypatch):
    monkeypatch.setattr(settings, "model_routing_mode", "local_first")
    instance = ModelRouter()
    instance.cloud = SuccessfulCloud()
    instance._record = lambda *args, **kwargs: None
    instance._budget_available = lambda: True
    return instance


@pytest.mark.asyncio
async def test_hard_total_deadline_expires_despite_continuous_local_chunks(monkeypatch):
    instance = router_with_cloud(monkeypatch)
    lifecycle = []

    def endless_chunks(task_type, prompt, *, cancel_token=None):
        while True:
            time.sleep(0.002)
            yield "x"

    instance.local.stream_chat = endless_chunks
    started = time.monotonic()
    result = await instance.execute_stream(
        "teaching", "deadline", turn_id="deadline-turn", deadline_seconds=0.05,
        poll_seconds=0.002, on_event=lambda event: lifecycle.append(event),
    )
    elapsed = time.monotonic() - started

    assert 0.04 <= elapsed < 0.25
    assert result.success is True and result.provider == "cloud"
    assert result.attempts[0].status == "timed_out"
    assert result.attempts[0].failure_kind == "timeout"
    assert [event.event for event in lifecycle] == ["local_started", "local_failed", "cloud_started"]


@pytest.mark.asyncio
async def test_late_local_final_is_discarded_after_cloud_success(monkeypatch):
    instance = router_with_cloud(monkeypatch)

    def ignores_cancellation(task_type, prompt, *, cancel_token=None):
        time.sleep(0.09)
        yield "late-local-final"

    instance.local.stream_chat = ignores_cancellation
    result = await instance.execute_stream("teaching", "late", turn_id="late-turn", deadline_seconds=0.02, poll_seconds=0.002)
    snapshot = (result.text, result.provider, result.model_name, result.route_reason, result.attempts)
    await asyncio.sleep(0.12)

    assert result.text == "cloud:late"
    assert "late-local-final" not in (result.text or "")
    assert (result.text, result.provider, result.model_name, result.route_reason, result.attempts) == snapshot


@pytest.mark.asyncio
async def test_request_cancellation_reaches_local_and_never_starts_cloud(monkeypatch):
    instance = router_with_cloud(monkeypatch)
    request_cancel = ProviderCancellation()
    local_started = threading.Event()
    local_stopped = threading.Event()
    lifecycle = []

    def cancellable_local(task_type, prompt, *, cancel_token=None):
        local_started.set()
        try:
            while not cancel_token.cancelled:
                time.sleep(0.002)
                yield "partial"
        finally:
            local_stopped.set()

    instance.local.stream_chat = cancellable_local
    task = asyncio.create_task(instance.execute_stream(
        "teaching", "cancel", turn_id="cancel-turn", cancellation=request_cancel,
        poll_seconds=0.002, on_event=lambda event: lifecycle.append(event),
    ))
    assert await asyncio.to_thread(local_started.wait, 1)
    request_cancel.cancel()
    result = await task

    assert result.success is False
    assert result.failure_kind == "cancelled"
    assert await asyncio.to_thread(local_stopped.wait, 1)
    assert instance.cloud.calls == []
    assert "cloud_started" not in [event.event for event in lifecycle]


@pytest.mark.asyncio
async def test_two_concurrent_turns_keep_local_and_cloud_metadata_isolated(monkeypatch):
    instance = router_with_cloud(monkeypatch)

    def local(task_type, prompt, *, cancel_token=None):
        if prompt == "A":
            raise httpx.ConnectError("offline")
        yield f"local:{prompt}"

    instance.local.stream_chat = local
    result_a, result_b = await asyncio.gather(
        instance.execute_stream("teaching", "A", turn_id="turn-A"),
        instance.execute_stream("teaching", "B", turn_id="turn-B"),
    )

    assert (result_a.turn_id, result_a.provider, result_a.text) == ("turn-A", "cloud", "cloud:A")
    assert (result_b.turn_id, result_b.provider, result_b.text) == ("turn-B", "ollama", "local:B")
    assert {attempt.turn_id for attempt in result_a.attempts} == {"turn-A"}
    assert {attempt.turn_id for attempt in result_b.attempts} == {"turn-B"}


@pytest.mark.asyncio
async def test_two_reverse_order_cloud_fallbacks_keep_attempt_identity(monkeypatch):
    instance = router_with_cloud(monkeypatch)

    def unavailable(task_type, prompt, *, cancel_token=None):
        raise httpx.ConnectError("offline")
        yield

    class ReverseCloud:
        provider = "cloud"

        def chat(self, task_type, prompt, *, cancel_token=None):
            time.sleep(0.06 if prompt == "slow-A" else 0.005)
            return ModelResult(True, None, "cloud", f"model-{prompt}", text=f"reply-{prompt}")

    instance.local.stream_chat = unavailable
    instance.cloud = ReverseCloud()
    result_a, result_b = await asyncio.gather(
        instance.execute_stream("teaching", "slow-A", turn_id="fallback-A"),
        instance.execute_stream("teaching", "fast-B", turn_id="fallback-B"),
    )

    assert (result_a.turn_id, result_a.model_name, result_a.text) == ("fallback-A", "model-slow-A", "reply-slow-A")
    assert (result_b.turn_id, result_b.model_name, result_b.text) == ("fallback-B", "model-fast-B", "reply-fast-B")
    assert {attempt.turn_id for attempt in result_a.attempts} == {"fallback-A"}
    assert {attempt.turn_id for attempt in result_b.attempts} == {"fallback-B"}


@pytest.mark.asyncio
@pytest.mark.parametrize("block", ["disabled", "budget", "privacy"])
async def test_ineligible_cloud_paths_emit_no_cloud_started(monkeypatch, block):
    instance = router_with_cloud(monkeypatch)
    lifecycle = []

    def unavailable(task_type, prompt, *, cancel_token=None):
        raise httpx.ConnectError("offline")
        yield

    instance.local.stream_chat = unavailable
    if block == "disabled":
        instance.cloud = None
    elif block == "budget":
        instance._budget_available = lambda: False
    else:
        instance.classify_risk = lambda prompt: "high"

    result = await instance.execute_stream("teaching", "blocked", turn_id=f"blocked-{block}", on_event=lambda event: lifecycle.append(event))
    assert result.success is False
    assert "cloud_started" not in [event.event for event in lifecycle]
    assert result.route_reason == {"disabled": "cloud_disabled", "budget": "cloud_budget_blocked", "privacy": "cloud_privacy_blocked"}[block]


@pytest.mark.asyncio
async def test_cloud_only_stream_starts_cloud_without_local_attempt(monkeypatch):
    instance = router_with_cloud(monkeypatch)
    from app.config import settings

    monkeypatch.setattr(settings, "model_routing_mode", "cloud_only")
    lifecycle = []
    local_calls = []

    def local_stream(*args, **kwargs):
        local_calls.append(args)
        yield "错误的本地结果"

    instance.local.stream_chat = local_stream
    result = await instance.execute_stream("teaching", "解释事务", turn_id="cloud-only", on_event=lambda event: lifecycle.append(event))

    assert result.success is True
    assert result.provider == "cloud"
    assert [event.event for event in lifecycle] == ["cloud_started"]
    assert [attempt.stage for attempt in result.attempts] == ["cloud"]
    assert local_calls == []


@pytest.mark.asyncio
async def test_cloud_only_stream_does_not_fallback_to_local_when_cloud_disabled(monkeypatch):
    instance = router_with_cloud(monkeypatch)
    from app.config import settings

    monkeypatch.setattr(settings, "model_routing_mode", "cloud_only")
    instance.cloud = None
    instance.local.stream_chat = lambda *args, **kwargs: pytest.fail("local provider must not be called")

    result = await instance.execute_stream("teaching", "解释事务", turn_id="cloud-only-disabled")

    assert result.success is False
    assert result.provider == "router"
    assert result.route_reason == "cloud_disabled"
    assert result.attempts == ()


def test_completed_and_cancelled_terminal_race_has_exactly_one_winner(tmp_path: Path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'terminal-race.sqlite3').as_posix()}", connect_args={"check_same_thread": False, "timeout": 5})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with factory() as db:
        conversation_service.begin_turn(db, request_id="race", session_id="shared", persona="anna", message="race")

    barrier = threading.Barrier(2)

    def complete():
        with factory() as db:
            barrier.wait()
            return conversation_service.complete_turn(db, turn_id="race", response="answer", provider="ollama", model_name="local", route_reason="local_stream_success")

    def cancel():
        with factory() as db:
            barrier.wait()
            return conversation_service.cancel_turn(db, turn_id="race")

    with ThreadPoolExecutor(max_workers=2) as pool:
        complete_future = pool.submit(complete)
        cancel_future = pool.submit(cancel)
        winners = [complete_future.result(), cancel_future.result()]

    assert sorted(winners) == [False, True]
    with factory() as db:
        turn = db.scalar(select(ChatTurn).where(ChatTurn.turn_id == "race"))
        assistants = list(db.scalars(select(ChatMessage).where(ChatMessage.turn_id == "race", ChatMessage.role == "assistant")))
        assert turn.status in {"completed", "cancelled"}
        assert (turn.status == "completed") == (len(assistants) == 1)


def test_disconnect_after_completion_cannot_overwrite_and_replay_is_stable(tmp_path: Path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'completed-disconnect.sqlite3').as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with factory() as db:
        conversation_service.begin_turn(db, request_id="completed", session_id="shared", persona="anna", message="question")
        assert conversation_service.complete_turn(db, turn_id="completed", response="answer", provider="ollama", model_name="local", route_reason="local_stream_success") is True
        assert conversation_service.cancel_turn(db, turn_id="completed") is False
        replay = conversation_service.begin_turn(db, request_id="completed", session_id="shared", persona="anna", message="question")
        assert replay.owns_execution is False
        assert replay.assistant_content == "answer"
        assert replay.turn.status == "completed"


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (TimeoutError("deadline"), "timeout"),
        (httpx.ConnectError("offline"), "unavailable"),
        (httpx.HTTPStatusError("bad request", request=httpx.Request("POST", "http://test"), response=httpx.Response(400)), "request_error"),
        (ValueError("bad payload"), "response_error"),
    ],
)
def test_interactive_failures_are_normalized_to_structured_kinds(error, expected):
    assert normalize_interactive_failure(error) == expected
