from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from threading import Event, Lock
from typing import Callable


class ProviderCancellation:
    """Thread-safe request/attempt cancellation signal with close callbacks."""

    def __init__(self) -> None:
        self._event = Event()
        self._lock = Lock()
        self._callbacks: dict[int, Callable[[], None]] = {}
        self._next_callback_id = 0

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def cancel(self) -> None:
        with self._lock:
            if self._event.is_set():
                return
            self._event.set()
            callbacks = list(self._callbacks.values())
            self._callbacks.clear()
        for callback in callbacks:
            try:
                callback()
            except Exception:
                pass

    def register(self, callback: Callable[[], None]) -> Callable[[], None]:
        with self._lock:
            if self._event.is_set():
                run_now = True
                callback_id = -1
            else:
                run_now = False
                callback_id = self._next_callback_id
                self._next_callback_id += 1
                self._callbacks[callback_id] = callback
        if run_now:
            callback()

        def unregister() -> None:
            if callback_id >= 0:
                with self._lock:
                    self._callbacks.pop(callback_id, None)

        return unregister


class ProviderCancelledError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProviderAttempt:
    attempt_id: str
    turn_id: str
    provider: str
    model_name: str
    stage: str
    status: str
    failure_kind: str | None
    route_reason: str | None
    started_at: datetime
    finished_at: datetime | None
    deadline_at: datetime | None
    elapsed_ms: int


@dataclass(frozen=True)
class ProviderLifecycleEvent:
    event: str
    attempt: ProviderAttempt


@dataclass(frozen=True)
class ProviderExecutionResult:
    turn_id: str
    success: bool
    text: str | None
    provider: str
    model_name: str
    route_reason: str
    failure_kind: str | None
    error: str | None
    attempts: tuple[ProviderAttempt, ...]


__all__ = [
    "ProviderAttempt",
    "ProviderCancellation",
    "ProviderCancelledError",
    "ProviderExecutionResult",
    "ProviderLifecycleEvent",
]
