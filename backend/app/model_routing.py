from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import queue
import re
import threading
import time
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from uuid import uuid4

import httpx
from sqlalchemy import func, select

from .config import settings
from .db import SessionLocal
from .models import ModelCallLog
from .provider_execution import ProviderAttempt, ProviderCancellation, ProviderCancelledError, ProviderExecutionResult, ProviderLifecycleEvent


@dataclass
class ModelResult:
    success: bool
    data: dict[str, Any] | None
    provider: str
    model_name: str
    error: str | None = None
    duration_ms: int = 0
    text: str | None = None
    confidence: float | None = None
    route_reason: str | None = None
    retry_count: int = 0
    fallback_used: bool = False
    _input_tokens: int | None = None
    _output_tokens: int | None = None
    _total_tokens: int | None = None
    failure_kind: str | None = None


@dataclass(frozen=True)
class _WorkerOutcome:
    value: Any = None
    error: BaseException | None = None
    finished_monotonic: float = 0.0


def _accepts_cancel_token(callable_value: Callable[..., Any]) -> bool:
    try:
        signature = inspect.signature(callable_value)
    except (TypeError, ValueError):
        return False
    return "cancel_token" in signature.parameters or any(parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in signature.parameters.values())


async def _run_cancellable_worker(
    call: Callable[[ProviderCancellation], Any],
    *,
    request_cancel: ProviderCancellation,
    attempt_cancel: ProviderCancellation,
    deadline_monotonic: float | None,
    monotonic: Callable[[], float],
    poll_seconds: float,
) -> _WorkerOutcome:
    outcomes: queue.Queue[_WorkerOutcome] = queue.Queue(maxsize=1)

    def worker() -> None:
        try:
            outcomes.put(_WorkerOutcome(value=call(attempt_cancel), finished_monotonic=monotonic()))
        except Exception as exc:
            outcomes.put(_WorkerOutcome(error=exc, finished_monotonic=monotonic()))

    threading.Thread(target=worker, name="studyforge-provider-attempt", daemon=True).start()
    while True:
        try:
            outcome = outcomes.get_nowait()
        except queue.Empty:
            outcome = None
        if outcome is not None:
            if deadline_monotonic is not None and outcome.finished_monotonic > deadline_monotonic:
                attempt_cancel.cancel()
                raise TimeoutError("local provider exceeded total deadline")
            if request_cancel.cancelled:
                attempt_cancel.cancel()
                raise ProviderCancelledError("request cancelled")
            return outcome
        if request_cancel.cancelled:
            attempt_cancel.cancel()
            raise ProviderCancelledError("request cancelled")
        if deadline_monotonic is not None and monotonic() >= deadline_monotonic:
            attempt_cancel.cancel()
            raise TimeoutError("local provider exceeded total deadline")
        await asyncio.sleep(max(0.0, poll_seconds))


LOCAL_AVAILABILITY_FAILURE = "availability"
LOCAL_RESPONSE_FAILURE = "response"
LOCAL_REQUEST_FAILURE = "request"


def classify_local_failure(error: BaseException | str | None) -> str:
    """Classify whether a local failure safely permits a sequential cloud fallback."""
    if isinstance(error, (httpx.TimeoutException, httpx.ConnectError, httpx.NetworkError, httpx.RemoteProtocolError)):
        return LOCAL_AVAILABILITY_FAILURE
    if isinstance(error, httpx.HTTPStatusError):
        status = error.response.status_code
        return LOCAL_AVAILABILITY_FAILURE if status >= 500 or status in {408, 429} else LOCAL_REQUEST_FAILURE
    if isinstance(error, (KeyError, TypeError, ValueError, json.JSONDecodeError)):
        return LOCAL_RESPONSE_FAILURE
    message = str(error or "").lower()
    availability_markers = ("offline", "unavailable", "timed out", "timeout", "connection refused", "connect error", "network error")
    return LOCAL_AVAILABILITY_FAILURE if any(marker in message for marker in availability_markers) else LOCAL_RESPONSE_FAILURE


def normalize_interactive_failure(error: BaseException | str | None) -> str:
    if isinstance(error, ProviderCancelledError):
        return "cancelled"
    if isinstance(error, TimeoutError):
        return "timeout"
    legacy_kind = classify_local_failure(error)
    return {
        LOCAL_AVAILABILITY_FAILURE: "unavailable",
        LOCAL_REQUEST_FAILURE: "request_error",
        LOCAL_RESPONSE_FAILURE: "response_error",
    }[legacy_kind]


def redact_sensitive(value: str) -> str:
    """Remove common credentials and direct identifiers before external transfer/logging."""
    value = re.sub(r"(?i)(token|api[_-]?key|password|passwd|secret)\s*[:=]\s*\S+", r"\1=[REDACTED]", value)
    value = re.sub(r"\bsk-[A-Za-z0-9_-]+\b", "[REDACTED]", value)
    # Keep the email character classes ASCII-only; Unicode \w causes pathological
    # backtracking on long non-Latin documents that contain no email address.
    value = re.sub(r"[A-Za-z0-9_.+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "[REDACTED_EMAIL]", value)
    value = re.sub(r"(?<!\d)1\d{10}(?!\d)", "[REDACTED_PHONE]", value)
    return value


def validate_structured_data(data: Any, required_keys: set[str] | None = None) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValueError("structured model result must be an object")
    if required_keys:
        missing = sorted(key for key in required_keys if key not in data)
        if missing:
            raise ValueError(f"structured model result missing keys: {', '.join(missing)}")
    for key in ("topics", "outputs", "understood", "unresolved_questions"):
        if key in data and (not isinstance(data[key], list) or not all(isinstance(item, str) for item in data[key])):
            raise ValueError(f"structured model result field {key} must be a string array")
    for key in ("evidence", "achievements", "unfinished_items", "weak_points", "recommendations", "proposed_changes"):
        if key in data and not isinstance(data[key], list):
            raise ValueError(f"structured model result field {key} must be an array")
    for key in ("title", "summary"):
        if key in data and not isinstance(data[key], str):
            raise ValueError(f"structured model result field {key} must be a string")
    if "confidence" in data and (not isinstance(data["confidence"], (int, float)) or isinstance(data["confidence"], bool) or not 0 <= float(data["confidence"]) <= 1):
        raise ValueError("structured model result confidence must be a number between 0 and 1")
    if "duration_minutes" in data and data["duration_minutes"] is not None and (not isinstance(data["duration_minutes"], int) or isinstance(data["duration_minutes"], bool)):
        raise ValueError("structured model result duration_minutes must be an integer or null")
    return data


def estimate_tokens(value: str | None) -> int:
    """Estimate token count locally without sending text anywhere."""
    text = value or ""
    return max(1, len(text) // 3)


def extract_usage(body: dict[str, Any] | None) -> tuple[int | None, int | None, int | None]:
    """Extract usage counts from OpenAI-compatible and Ollama response bodies."""
    if not isinstance(body, dict):
        return None, None, None
    usage = body.get("usage")
    source = usage if isinstance(usage, dict) else body

    def number(*keys: str) -> int | None:
        for key in keys:
            value = source.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return int(value)
        return None

    prompt_tokens = number("prompt_tokens", "prompt_eval_count")
    completion_tokens = number("completion_tokens", "eval_count")
    total_tokens = number("total_tokens")
    if total_tokens is None and prompt_tokens is not None and completion_tokens is not None:
        total_tokens = prompt_tokens + completion_tokens
    return (
        prompt_tokens,
        completion_tokens,
        total_tokens,
    )


class OllamaAdapter:
    provider = "ollama"

    def health_check(self) -> bool:
        try:
            response = httpx.get(f"{settings.local_model_base_url}/models", timeout=min(5.0, settings.local_model_timeout_seconds), trust_env=False)
            return response.is_success
        except httpx.HTTPError:
            return False

    def structured_output(self, prompt: str, schema: dict[str, Any] | None = None) -> ModelResult:
        started = time.perf_counter()
        required_keys = set(schema.get("required", [])) if isinstance(schema, dict) else set()
        try:
            response = httpx.post(
                f"{settings.local_model_base_url.rsplit('/v1', 1)[0]}/api/chat",
                json={"model": settings.local_model_name, "messages": [{"role": "user", "content": prompt}], "stream": False, "think": False, "format": "json", "options": {"temperature": 0, "num_predict": 1200}},
                timeout=45,
                trust_env=False,
            )
            response.raise_for_status()
            data = validate_structured_data(json.loads(response.json().get("message", {}).get("content", "")), required_keys)
            confidence = data.get("confidence") if isinstance(data.get("confidence"), (int, float)) else 0.65
            return ModelResult(True, data, self.provider, settings.local_model_name, duration_ms=int((time.perf_counter() - started) * 1000), confidence=float(confidence), route_reason="local_structured_output")
        except (httpx.HTTPError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            return ModelResult(False, None, self.provider, settings.local_model_name, redact_sensitive(str(exc)), int((time.perf_counter() - started) * 1000), route_reason="local_structured_output_failure")

    def summarize(self, prompt: str) -> ModelResult:
        return self.chat("summarize", prompt)

    def classify(self, prompt: str) -> ModelResult:
        return self.chat("classify", prompt)

    def analyze(self, prompt: str) -> ModelResult:
        return self.chat("analyze", prompt)

    def stream(self, task_type: str, prompt: str):
        yield self.chat(task_type, prompt)

    def stream_chat(self, task_type: str, prompt: str, *, cancel_token: ProviderCancellation | None = None):
        system_prompt = {
            "teaching": "你是本地计算机教师，用清晰步骤解释概念。",
        }.get(task_type, "你是本地学习助手。")
        request_args = {
            "headers": {"Authorization": "Bearer " + (settings.local_model_api_key or "ollama")},
            "json": {"model": settings.local_model_name, "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}], "temperature": 0.3, "max_tokens": settings.max_tokens_per_request, "stream": True},
            "timeout": settings.local_model_timeout_seconds,
        }
        client: httpx.Client | None = None
        unregister: Callable[[], None] = lambda: None
        if cancel_token is None:
            context = httpx.stream("POST", f"{settings.local_model_base_url}/chat/completions", trust_env=False, **request_args)
        else:
            client = httpx.Client(trust_env=False)
            unregister = cancel_token.register(client.close)
            context = client.stream("POST", f"{settings.local_model_base_url}/chat/completions", **request_args)
        try:
            with context as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if cancel_token is not None and cancel_token.cancelled:
                        raise ProviderCancelledError("provider attempt cancelled")
                    if not line:
                        continue
                    raw = line.strip()
                    if raw.startswith("data:"):
                        raw = raw[5:].strip()
                    if raw == "[DONE]":
                        continue
                    payload = json.loads(raw)
                    choices = payload.get("choices") or []
                    content = (choices[0].get("delta") or {}).get("content") if choices else None
                    if content is None and choices:
                        content = (choices[0].get("message") or {}).get("content")
                    if content is None:
                        message = payload.get("message")
                        content = message.get("content") if isinstance(message, dict) else None
                    if content is None and isinstance(payload.get("response"), str):
                        content = payload["response"]
                    if content:
                        yield str(content)
        finally:
            unregister()
            if client is not None:
                client.close()

    def chat(self, task_type: str, prompt: str) -> ModelResult:
        started = time.perf_counter()
        system_prompt = {
            "writing": "你是本地技术写作助手。只基于用户材料组织草稿，不要虚构事实。",
            "learning_plan": "你是本地学习规划助手。根据学习证据给出可执行建议。",
            "teaching": "你是本地计算机教师，用清晰步骤解释概念。",
            "teaching_evaluation": "你是本地计算机教师，只输出符合要求的结构化 JSON 评价。",
            "knowledge_analysis": "你是本地知识分析助手，识别主题和前置知识。",
        }.get(task_type, "你是本地学习助手。")
        try:
            response = httpx.post(
                f"{settings.local_model_base_url}/chat/completions",
                headers={"Authorization": "Bearer " + (settings.local_model_api_key or "ollama")},
                json={"model": settings.local_model_name, "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}], "temperature": 0.3, "max_tokens": settings.max_tokens_per_request},
                timeout=settings.local_model_timeout_seconds,
                trust_env=False,
            )
            response.raise_for_status()
            payload = response.json()
            message = payload["choices"][0]["message"]
            content = message.get("content") or message.get("reasoning") or ""
            if not content:
                raise ValueError("local model returned empty content")
            prompt_tokens, completion_tokens, total_tokens = extract_usage(payload)
            return ModelResult(True, None, self.provider, settings.local_model_name, duration_ms=int((time.perf_counter() - started) * 1000), text=content, confidence=0.75, route_reason="local_first_local_success", _input_tokens=prompt_tokens, _output_tokens=completion_tokens, _total_tokens=total_tokens)
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            return ModelResult(False, None, self.provider, settings.local_model_name, str(exc), int((time.perf_counter() - started) * 1000), route_reason="local_first_local_failure", failure_kind=classify_local_failure(exc))

    def structured_log(self, raw_text: str) -> ModelResult:
        started = time.perf_counter()
        prompt = (
            "Extract this study log as JSON only. Keys: topics (array of strings), duration_minutes (integer or null), "
            "outputs (array of strings), understood (array of strings), unresolved_questions (array of strings), "
            "completed_tasks (array of strings), resolved_questions (array of strings), next_steps (array of strings), "
            "self_assessment (string or null). Do not invent facts.\n\n" + raw_text
        )
        try:
            native_response = httpx.post(
                f"{settings.local_model_base_url.rsplit('/v1', 1)[0]}/api/chat",
                json={"model": settings.local_model_name, "messages": [{"role": "user", "content": prompt}], "stream": False, "think": False, "format": "json", "options": {"temperature": 0, "num_predict": 512}}, timeout=30, trust_env=False,
            )
            native_response.raise_for_status()
            native_payload = native_response.json()
            data = json.loads(native_payload.get("message", {}).get("content", ""))
            data = validate_structured_data(data, {"topics", "duration_minutes", "outputs", "understood", "unresolved_questions", "self_assessment"})
            data.setdefault("completed_tasks", [])
            data.setdefault("resolved_questions", [])
            data.setdefault("next_steps", [])
            confidence = data.get("confidence") if isinstance(data.get("confidence"), (int, float)) else None
            prompt_tokens, completion_tokens, total_tokens = extract_usage(native_payload)
            return ModelResult(True, data, self.provider, settings.local_model_name, duration_ms=int((time.perf_counter() - started) * 1000), confidence=confidence, route_reason="local_success", _input_tokens=prompt_tokens, _output_tokens=completion_tokens, _total_tokens=total_tokens)
        except (httpx.HTTPError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            pass
        try:
            response = httpx.post(
                f"{settings.local_model_base_url}/chat/completions",
                headers={"Authorization": "Bearer " + (settings.local_model_api_key or "ollama")},
                json={"model": settings.local_model_name, "messages": [{"role": "user", "content": prompt}], "temperature": 0, "max_tokens": 512, "think": False, "response_format": {"type": "json_object"}}, timeout=30, trust_env=False,
            )
            response.raise_for_status()
            payload = response.json()
            message = payload["choices"][0]["message"]
            data = json.loads(message.get("content") or message.get("reasoning") or "")
            data = validate_structured_data(data, {"topics", "duration_minutes", "outputs", "understood", "unresolved_questions", "self_assessment"})
            data.setdefault("completed_tasks", [])
            data.setdefault("resolved_questions", [])
            data.setdefault("next_steps", [])
            confidence = data.get("confidence") if isinstance(data.get("confidence"), (int, float)) else None
            prompt_tokens, completion_tokens, total_tokens = extract_usage(payload)
            return ModelResult(True, data, self.provider, settings.local_model_name, duration_ms=int((time.perf_counter() - started) * 1000), confidence=confidence, route_reason="local_success", _input_tokens=prompt_tokens, _output_tokens=completion_tokens, _total_tokens=total_tokens)
        except (httpx.HTTPError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            return ModelResult(False, None, self.provider, settings.local_model_name, str(exc), int((time.perf_counter() - started) * 1000))


class CloudAdapter:
    provider = "zhiapi"

    def __init__(self, api_key: str, post: Callable[..., Any] | None = None) -> None:
        self.api_key = api_key
        self._custom_post = post
        self._post = post or (lambda *args, **kwargs: httpx.post(*args, trust_env=False, **kwargs))

    def health_check(self) -> bool:
        if not self.api_key:
            return False
        try:
            response = self._post(f"{settings.cloud_model_base_url}/models", headers={"Authorization": f"Bearer {self.api_key}"}, timeout=5)
            if bool(getattr(response, "is_success", False)):
                return True
            # zhiapi serves chat completions but does not expose the optional
            # OpenAI model-discovery endpoint. A 404 here means the host is
            # reachable; it must not be confused with an outage or auth error.
            return self.provider == "zhiapi" and getattr(response, "status_code", None) == 404
        except httpx.HTTPError:
            return False

    def structured_output(self, prompt: str, schema: dict[str, Any] | None = None) -> ModelResult:
        started = time.perf_counter()
        required_keys = set(schema.get("required", [])) if isinstance(schema, dict) else set()
        try:
            response = self._post(
                f"{settings.cloud_model_base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={"model": settings.cloud_model_name, "messages": [{"role": "user", "content": redact_sensitive(prompt)}], "temperature": 0, "max_tokens": min(settings.max_tokens_per_request, 1600), "response_format": {"type": "json_object"}},
                timeout=45,
            )
            if response.is_error:
                response.raise_for_status()
            payload = response.json()
            content = payload["choices"][0]["message"].get("content", "")
            data = validate_structured_data(json.loads(content), required_keys)
            prompt_tokens, completion_tokens, total_tokens = extract_usage(payload)
            confidence = data.get("confidence") if isinstance(data.get("confidence"), (int, float)) else 0.65
            return ModelResult(True, data, self.provider, settings.cloud_model_name, duration_ms=int((time.perf_counter() - started) * 1000), text=content, confidence=float(confidence), route_reason="cloud_structured_output", _input_tokens=prompt_tokens, _output_tokens=completion_tokens, _total_tokens=total_tokens)
        except (httpx.HTTPError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            return ModelResult(False, None, self.provider, settings.cloud_model_name, redact_sensitive(str(exc)), int((time.perf_counter() - started) * 1000), route_reason="cloud_structured_output_failure")

    def summarize(self, prompt: str) -> ModelResult:
        return self.chat("summarize", prompt)

    def classify(self, prompt: str) -> ModelResult:
        return self.chat("classify", prompt)

    def analyze(self, prompt: str) -> ModelResult:
        return self.chat("analyze", prompt)

    def stream(self, task_type: str, prompt: str):
        yield self.chat(task_type, prompt)

    def structured_log(self, raw_text: str) -> ModelResult:
        started = time.perf_counter()
        try:
            response = self._post(
                f"{settings.cloud_model_base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={"model": settings.cloud_model_name, "messages": [{"role": "user", "content": redact_sensitive(raw_text)}], "temperature": 0, "max_tokens": min(settings.max_tokens_per_request, 512), "response_format": {"type": "json_object"}},
                timeout=30,
            )
            if response.is_error:
                response.raise_for_status()
            payload = response.json()
            content = payload["choices"][0]["message"].get("content", "")
            data = validate_structured_data(json.loads(content), {"topics", "duration_minutes", "outputs", "understood", "unresolved_questions", "self_assessment"})
            data.setdefault("completed_tasks", [])
            data.setdefault("resolved_questions", [])
            data.setdefault("next_steps", [])
            prompt_tokens, completion_tokens, total_tokens = extract_usage(payload)
            return ModelResult(True, data, self.provider, settings.cloud_model_name, duration_ms=int((time.perf_counter() - started) * 1000), text=content, route_reason="cloud_success", _input_tokens=prompt_tokens, _output_tokens=completion_tokens, _total_tokens=total_tokens)
        except (httpx.HTTPError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            return ModelResult(False, None, self.provider, settings.cloud_model_name, redact_sensitive(str(exc)), int((time.perf_counter() - started) * 1000))

    def chat(self, task_type: str, prompt: str, *, cancel_token: ProviderCancellation | None = None) -> ModelResult:
        started = time.perf_counter()
        client: httpx.Client | None = None
        unregister: Callable[[], None] = lambda: None
        try:
            request_args = {
                "headers": {"Authorization": f"Bearer {self.api_key}"},
                "json": {
                    "model": settings.cloud_model_name,
                    "messages": [{"role": "system", "content": self._system_prompt(task_type)}, {"role": "user", "content": redact_sensitive(prompt)}],
                    "temperature": 0.4,
                    "max_tokens": settings.max_tokens_per_request,
                },
                "timeout": 60,
            }
            if cancel_token is not None and self._custom_post is None:
                client = httpx.Client(trust_env=False)
                unregister = cancel_token.register(client.close)
                response = client.post(f"{settings.cloud_model_base_url}/chat/completions", **request_args)
            else:
                response = self._post(f"{settings.cloud_model_base_url}/chat/completions", **request_args)
            if response.is_error:
                response.raise_for_status()
            payload = response.json()
            content = payload["choices"][0]["message"].get("content", "")
            if not content:
                raise ValueError("cloud model returned empty content")
            prompt_tokens, completion_tokens, total_tokens = extract_usage(payload)
            return ModelResult(True, None, self.provider, settings.cloud_model_name, duration_ms=int((time.perf_counter() - started) * 1000), text=content, route_reason="cloud_success", _input_tokens=prompt_tokens, _output_tokens=completion_tokens, _total_tokens=total_tokens)
        except (httpx.HTTPError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            return ModelResult(False, None, self.provider, settings.cloud_model_name, redact_sensitive(str(exc)), int((time.perf_counter() - started) * 1000))
        finally:
            unregister()
            if client is not None:
                client.close()

    @staticmethod
    def _system_prompt(task_type: str) -> str:
        prompts = {
            "writing": "你是高质量技术写作助手。根据用户提供的学习材料，整理成结构清晰、事实准确、适合复习或发布前编辑的中文草稿。不要虚构经历或结论。",
            "learning_plan": "你是学习规划专家。根据学习证据设计可执行的阶段计划，说明依据、前置知识、任务量和不确定性。",
            "teaching": "你是计算机科学教师。用循序渐进、苏格拉底式的问题帮助用户理解复杂原理，不把猜测说成事实。",
            "code_review": "你是严谨的代码审查员。指出逻辑、安全、测试和可维护性问题，并给出可验证的改进建议。",
            "knowledge_analysis": "你是知识体系分析助手。识别前置知识、薄弱点和关联关系，区分证据与推测。",
        }
        return prompts.get(task_type, "你是个人学习助手，请基于提供的材料给出准确、可执行的回答。")


class ModelRouter:
    def __init__(self) -> None:
        self.local = OllamaAdapter()
        self.cloud = CloudAdapter(settings.cloud_model_api_key) if settings.cloud_model_enabled and settings.cloud_model_api_key else None
        self._cache: dict[str, tuple[float, ModelResult]] = {}

    def refresh_adapters(self) -> None:
        self.cloud = CloudAdapter(settings.cloud_model_api_key) if settings.cloud_model_enabled and settings.cloud_model_api_key else None

    @staticmethod
    def _deterministic_daily_log() -> dict[str, Any]:
        return {
            "topics": [],
            "duration_minutes": None,
            "outputs": [],
            "understood": [],
            "unresolved_questions": [],
            "completed_tasks": [],
            "resolved_questions": [],
            "next_steps": [],
            "self_assessment": None,
        }

    @staticmethod
    def _deterministic_teaching_result(prompt: str, error: str | None = None) -> ModelResult:
        """Keep basic coaching usable offline without presenting rules as model output."""
        question = prompt.rsplit("用户问题：", 1)[-1].strip() if "用户问题：" in prompt else "当前学习问题"
        question = question.splitlines()[0][:160] or "当前学习问题"
        text = (
            f"当前本地模型不可用，先为“{question}”提供离线学习步骤：\n"
            "1. 先用自己的话写出定义、输入输出和一个最小例子。\n"
            "2. 再补充一个边界情况，说明它为什么成立或失败。\n"
            "3. 把仍然不确定的地方记录为待验证问题，模型恢复后再请求针对性讲解。"
        )
        return ModelResult(
            True,
            None,
            "deterministic",
            "rule_based",
            error=f"local teaching unavailable; deterministic fallback used: {error or 'unknown'}",
            text=text,
            confidence=0.2,
            route_reason="teaching_deterministic_fallback",
            fallback_used=True,
        )

    def classify_risk(self, raw_text: str) -> str:
        if re.search(r"(?i)(password|passwd|token|api[_-]?key|secret|身份证|银行卡|密码)", raw_text):
            return "high"
        if re.search(r"(?i)(email|phone|address|邮箱|电话|住址)", raw_text):
            return "medium"
        return "low"

    def should_use_cloud(self, raw_text: str) -> bool:
        return self.cloud is not None and self.classify_risk(raw_text) == "low"

    def task_policy(self, task_type: str) -> dict[str, Any]:
        local_tasks = {"daily_log", "format_note", "summarize", "classify", "flashcards", "file_index"}
        high_tasks = {"code_review", "file_cloud_analysis", "bulk_plan_change"}
        cloud_tasks = {"writing", "learning_plan", "teaching", "teaching_evaluation", "knowledge_analysis"}
        if settings.model_routing_mode == "cloud_only":
            if task_type in high_tasks:
                return {"provider": "cloud", "risk": "high", "requires_confirmation": True, "reason": "已配置为所有任务使用云端；高风险任务仍需确认"}
            risk = "medium" if task_type in cloud_tasks else "low"
            return {"provider": "cloud", "risk": risk, "requires_confirmation": False, "reason": "已配置为所有任务直接使用云端"}
        if task_type in high_tasks:
            if settings.model_routing_mode == "local_only":
                return {"provider": "local", "risk": "high", "requires_confirmation": False, "reason": "已配置为仅使用本地模型"}
            return {"provider": "cloud", "risk": "high", "requires_confirmation": True, "reason": "该任务可能影响代码或学习计划，必须确认后使用云端"}
        if task_type in cloud_tasks:
            if settings.model_routing_mode == "local_only":
                return {"provider": "local", "risk": "medium", "requires_confirmation": False, "reason": "已配置为仅使用本地模型"}
            if settings.model_routing_mode == "cloud_confirmed":
                return {"provider": "cloud", "risk": "medium", "requires_confirmation": True, "reason": "已配置为调用云端前必须确认"}
            return {"provider": "local_first", "fallback_provider": "cloud", "risk": "medium", "requires_confirmation": False, "reason": "中风险任务先在本机处理，失败或低置信度时才升级云端"}
        if task_type in local_tasks:
            return {"provider": "local", "risk": "low", "requires_confirmation": False, "reason": "隐私敏感、结构化或低成本任务默认留在本机"}
        return {"provider": "local", "risk": "low", "requires_confirmation": False, "reason": "未知任务默认留在本机，避免意外上传"}

    def run_task(self, task_type: str, prompt: str, confirmed: bool = False) -> ModelResult:
        policy = self.task_policy(task_type)
        if policy["requires_confirmation"] and not confirmed:
            return ModelResult(False, None, "router", "none", "cloud confirmation required")
        if policy["provider"] == "local_first":
            attempts = max(0, settings.model_max_retries) + 1
            local_result = ModelResult(False, None, "ollama", settings.local_model_name, "local processing unavailable")
            for attempt in range(attempts):
                try:
                    local_result = self.local.chat(task_type, prompt)
                except Exception as exc:
                    local_result = ModelResult(False, None, "ollama", settings.local_model_name, redact_sensitive(str(exc)))
                local_result.retry_count = attempt
                if local_result.success:
                    break
                if settings.model_retry_backoff_seconds > 0 and attempt < attempts - 1:
                    time.sleep(settings.model_retry_backoff_seconds * (attempt + 1))
            if local_result.success:
                local_result.route_reason = "local_first_local_success"
                self._record(local_result, task_type, policy["risk"], len(prompt), upgraded=False)
                return local_result
            local_result.failure_kind = local_result.failure_kind or classify_local_failure(local_result.error)
            if local_result.failure_kind != LOCAL_AVAILABILITY_FAILURE:
                local_result.route_reason = "local_first_local_response_failure"
                self._record(local_result, task_type, policy["risk"], len(prompt), upgraded=False)
                return local_result
            if self.cloud is None:
                local_result.error = f"local model unavailable; cloud unavailable: {local_result.error or 'unknown'}"
                local_result.route_reason = "local_first_cloud_unavailable"
                self._record(local_result, task_type, policy["risk"], len(prompt), upgraded=False)
                return local_result
            if not self._budget_available():
                local_result.error = "local model unavailable; cloud budget exceeded"
                local_result.route_reason = "local_first_budget_blocked_local_unavailable"
                self._record(local_result, task_type, policy["risk"], len(prompt), upgraded=False)
                return local_result
            if self.classify_risk(prompt) != "low":
                local_result.error = "local model unavailable; cloud fallback blocked by privacy policy"
                local_result.route_reason = "local_first_privacy_blocked"
                self._record(local_result, task_type, policy["risk"], len(prompt), upgraded=False)
                return local_result
            cloud_result = self.cloud.chat(task_type, prompt)
            cloud_result.fallback_used = True
            cloud_result.route_reason = "local_first_local_unavailable_cloud_fallback"
            self._record(cloud_result, task_type, policy["risk"], len(prompt), upgraded=True)
            return cloud_result
        if policy["provider"] == "cloud":
            if self.cloud is None:
                return ModelResult(False, None, "router", "none", "cloud model is disabled or not configured")
            if not self._budget_available():
                return ModelResult(False, None, "router", "none", "cloud budget exceeded")
            try:
                result = self.cloud.chat(task_type, prompt)
            except Exception as exc:
                result = ModelResult(False, None, getattr(self.cloud, "provider", "cloud"), settings.cloud_model_name, redact_sensitive(str(exc)), failure_kind="provider_error")
            result.route_reason = policy["reason"]
            self._record(result, task_type, policy["risk"], len(prompt), upgraded=False)
            return result
        if task_type == "teaching":
            try:
                result = self.local.chat(task_type, prompt)
            except Exception as exc:
                result = ModelResult(False, None, "ollama", settings.local_model_name, redact_sensitive(str(exc)))
            if result.success and result.text:
                result.route_reason = "teaching_local_success"
                self._record(result, task_type, policy["risk"], len(prompt), upgraded=False)
                return result
            fallback = self._deterministic_teaching_result(prompt, result.error)
            self._record(fallback, task_type, policy["risk"], len(prompt), upgraded=False)
            return fallback
        result = self.local.structured_log(prompt)
        result.route_reason = policy["reason"]
        self._record(result, task_type, policy["risk"], len(prompt), upgraded=False)
        return result

    @staticmethod
    def _stream_delta(existing: str, incoming: str) -> str:
        """Drop a repeated prefix when a provider restarts a stream after disconnect."""
        if not existing or not incoming:
            return incoming
        if incoming.startswith(existing):
            return incoming[len(existing):]
        max_overlap = min(len(existing), len(incoming))
        for size in range(max_overlap, 0, -1):
            if existing.endswith(incoming[:size]):
                return incoming[size:]
        return incoming

    async def execute_stream(
        self,
        task_type: str,
        prompt: str,
        *,
        turn_id: str,
        cancellation: ProviderCancellation | None = None,
        on_event: Callable[[ProviderLifecycleEvent], None] | None = None,
        deadline_seconds: float | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        poll_seconds: float = 0.02,
    ) -> ProviderExecutionResult:
        """Run one request-scoped, strictly sequential LOCAL-FIRST provider execution."""
        policy = self.task_policy(task_type)
        request_cancel = cancellation or ProviderCancellation()
        emit = on_event or (lambda event: None)
        attempts: list[ProviderAttempt] = []
        if settings.model_routing_mode == "cloud_only":
            return await self._execute_cloud_stream(
                task_type,
                prompt,
                turn_id=turn_id,
                policy=policy,
                request_cancel=request_cancel,
                emit=emit,
                monotonic=monotonic,
                poll_seconds=poll_seconds,
            )
        local_started_at = datetime.now(timezone.utc)
        local_started_monotonic = monotonic()
        total_seconds = max(0.001, deadline_seconds if deadline_seconds is not None else settings.local_model_timeout_seconds)
        local_deadline_monotonic = local_started_monotonic + total_seconds
        local_attempt = ProviderAttempt(
            attempt_id=uuid4().hex,
            turn_id=turn_id,
            provider=getattr(self.local, "provider", "ollama"),
            model_name=settings.local_model_name,
            stage="local",
            status="running",
            failure_kind=None,
            route_reason="local_started",
            started_at=local_started_at,
            finished_at=None,
            deadline_at=local_started_at + timedelta(seconds=total_seconds),
            elapsed_ms=0,
        )
        emit(ProviderLifecycleEvent("local_started", local_attempt))
        local_cancel = ProviderCancellation()

        def consume_local(cancel_token: ProviderCancellation) -> list[str]:
            stream = self.local.stream_chat
            iterator = stream(task_type, prompt, cancel_token=cancel_token) if _accepts_cancel_token(stream) else stream(task_type, prompt)
            chunks: list[str] = []
            try:
                for chunk in iterator:
                    if cancel_token.cancelled:
                        raise ProviderCancelledError("local attempt cancelled")
                    if chunk:
                        chunks.append(str(chunk))
            finally:
                close = getattr(iterator, "close", None)
                if callable(close):
                    close()
            return chunks

        local_error: BaseException | None = None
        local_chunks: list[str] = []
        try:
            outcome = await _run_cancellable_worker(
                consume_local,
                request_cancel=request_cancel,
                attempt_cancel=local_cancel,
                deadline_monotonic=local_deadline_monotonic,
                monotonic=monotonic,
                poll_seconds=poll_seconds,
            )
            if outcome.error is not None:
                raise outcome.error
            local_chunks = outcome.value or []
            if not local_chunks:
                raise ValueError("local stream returned empty content")
        except Exception as exc:
            local_error = exc

        local_finished_at = datetime.now(timezone.utc)
        local_failure_kind = normalize_interactive_failure(local_error) if local_error is not None else None
        local_status = "cancelled" if local_failure_kind == "cancelled" else "timed_out" if local_failure_kind == "timeout" else "failed" if local_error is not None else "succeeded"
        local_reason = {
            None: "local_stream_success",
            "cancelled": "client_cancelled",
            "timeout": "local_timeout",
            "unavailable": "local_unavailable",
            "request_error": "local_request_error",
            "response_error": "local_response_failure",
        }.get(local_failure_kind, "local_provider_error")
        local_attempt = replace(
            local_attempt,
            status=local_status,
            failure_kind=local_failure_kind,
            route_reason=local_reason,
            finished_at=local_finished_at,
            elapsed_ms=max(0, int((monotonic() - local_started_monotonic) * 1000)),
        )
        attempts.append(local_attempt)

        if local_error is None:
            text = "".join(local_chunks)
            result = ModelResult(True, None, local_attempt.provider, local_attempt.model_name, duration_ms=local_attempt.elapsed_ms, text=text, confidence=0.75, route_reason="local_stream_success")
            self._record(result, task_type, policy.get("risk", "low"), len(prompt))
            return ProviderExecutionResult(turn_id, True, text, result.provider, result.model_name, result.route_reason or "local_stream_success", None, None, tuple(attempts))

        emit(ProviderLifecycleEvent("local_failed", local_attempt))
        if local_failure_kind == "cancelled":
            return ProviderExecutionResult(turn_id, False, None, local_attempt.provider, local_attempt.model_name, "client_cancelled", "cancelled", "request cancelled", tuple(attempts))

        local_result = ModelResult(False, None, local_attempt.provider, local_attempt.model_name, error=redact_sensitive(str(local_error)), duration_ms=local_attempt.elapsed_ms, route_reason=local_reason, failure_kind=local_failure_kind)
        eligible_failure = local_failure_kind in {"timeout", "unavailable"}
        if policy.get("fallback_provider") != "cloud" or not eligible_failure:
            self._record(local_result, task_type, policy.get("risk", "low"), len(prompt))
            return ProviderExecutionResult(turn_id, False, None, local_result.provider, local_result.model_name, local_reason, local_failure_kind, local_result.error, tuple(attempts))
        if self.cloud is None:
            local_result.error = f"local model unavailable; cloud unavailable: {local_result.error or 'unknown'}"
            local_result.route_reason = "cloud_disabled"
            self._record(local_result, task_type, policy.get("risk", "low"), len(prompt))
            return ProviderExecutionResult(turn_id, False, None, local_result.provider, local_result.model_name, "cloud_disabled", "unavailable", local_result.error, tuple(attempts))
        if not self._budget_available():
            local_result.error = "local model unavailable; cloud budget exceeded"
            local_result.route_reason = "cloud_budget_blocked"
            self._record(local_result, task_type, policy.get("risk", "low"), len(prompt))
            return ProviderExecutionResult(turn_id, False, None, local_result.provider, local_result.model_name, "cloud_budget_blocked", "budget", local_result.error, tuple(attempts))
        if self.classify_risk(prompt) != "low":
            local_result.error = "local model unavailable; cloud fallback blocked by privacy policy"
            local_result.route_reason = "cloud_privacy_blocked"
            self._record(local_result, task_type, policy.get("risk", "low"), len(prompt))
            return ProviderExecutionResult(turn_id, False, None, local_result.provider, local_result.model_name, "cloud_privacy_blocked", "permission", local_result.error, tuple(attempts))

        cloud_started_at = datetime.now(timezone.utc)
        cloud_started_monotonic = monotonic()
        cloud_attempt = ProviderAttempt(
            attempt_id=uuid4().hex,
            turn_id=turn_id,
            provider=getattr(self.cloud, "provider", "cloud"),
            model_name=settings.cloud_model_name,
            stage="cloud",
            status="running",
            failure_kind=None,
            route_reason="cloud_started",
            started_at=cloud_started_at,
            finished_at=None,
            deadline_at=None,
            elapsed_ms=0,
        )
        emit(ProviderLifecycleEvent("cloud_started", cloud_attempt))
        cloud_cancel = ProviderCancellation()

        def call_cloud(cancel_token: ProviderCancellation) -> ModelResult:
            cloud_chat = self.cloud.chat
            return cloud_chat(task_type, prompt, cancel_token=cancel_token) if _accepts_cancel_token(cloud_chat) else cloud_chat(task_type, prompt)

        try:
            cloud_outcome = await _run_cancellable_worker(
                call_cloud,
                request_cancel=request_cancel,
                attempt_cancel=cloud_cancel,
                deadline_monotonic=None,
                monotonic=monotonic,
                poll_seconds=poll_seconds,
            )
            if cloud_outcome.error is not None:
                raise cloud_outcome.error
            cloud_result = cloud_outcome.value
        except BaseException as exc:
            cloud_failure_kind = normalize_interactive_failure(exc)
            cloud_attempt = replace(cloud_attempt, status="cancelled" if cloud_failure_kind == "cancelled" else "failed", failure_kind=cloud_failure_kind, route_reason="client_cancelled" if cloud_failure_kind == "cancelled" else "cloud_provider_error", finished_at=datetime.now(timezone.utc), elapsed_ms=max(0, int((monotonic() - cloud_started_monotonic) * 1000)))
            attempts.append(cloud_attempt)
            if cloud_failure_kind == "cancelled":
                return ProviderExecutionResult(turn_id, False, None, cloud_attempt.provider, cloud_attempt.model_name, "client_cancelled", "cancelled", "request cancelled", tuple(attempts))
            failed = ModelResult(False, None, cloud_attempt.provider, cloud_attempt.model_name, error=redact_sensitive(str(exc)), duration_ms=cloud_attempt.elapsed_ms, route_reason="cloud_provider_error", failure_kind=cloud_failure_kind)
            self._record(failed, task_type, policy.get("risk", "low"), len(prompt), upgraded=True)
            return ProviderExecutionResult(turn_id, False, None, failed.provider, failed.model_name, failed.route_reason or "cloud_provider_error", cloud_failure_kind, failed.error, tuple(attempts))

        if not isinstance(cloud_result, ModelResult):
            cloud_result = ModelResult(False, None, cloud_attempt.provider, cloud_attempt.model_name, error="cloud provider returned invalid result", failure_kind="response_error")
        cloud_result.fallback_used = True
        cloud_failure_kind = None if cloud_result.success and cloud_result.text else (cloud_result.failure_kind or normalize_interactive_failure(cloud_result.error))
        cloud_result.route_reason = "local_first_local_unavailable_cloud_fallback" if cloud_failure_kind is None else "cloud_provider_error"
        cloud_attempt = replace(cloud_attempt, status="succeeded" if cloud_failure_kind is None else "failed", failure_kind=cloud_failure_kind, route_reason=cloud_result.route_reason, finished_at=datetime.now(timezone.utc), elapsed_ms=max(0, int((monotonic() - cloud_started_monotonic) * 1000)))
        attempts.append(cloud_attempt)
        self._record(cloud_result, task_type, policy.get("risk", "low"), len(prompt), upgraded=True)
        if cloud_result.success and cloud_result.text:
            return ProviderExecutionResult(turn_id, True, cloud_result.text, cloud_result.provider, cloud_result.model_name, cloud_result.route_reason, None, None, tuple(attempts))
        return ProviderExecutionResult(turn_id, False, None, cloud_result.provider, cloud_result.model_name, "cloud_provider_error", cloud_failure_kind or "provider_error", cloud_result.error, tuple(attempts))

    async def _execute_cloud_stream(
        self,
        task_type: str,
        prompt: str,
        *,
        turn_id: str,
        policy: dict[str, Any],
        request_cancel: ProviderCancellation,
        emit: Callable[[ProviderLifecycleEvent], None],
        monotonic: Callable[[], float],
        poll_seconds: float,
    ) -> ProviderExecutionResult:
        """Execute a cloud-only stream without creating a local attempt."""
        if self.cloud is None:
            error = "cloud model is disabled or not configured"
            return ProviderExecutionResult(turn_id, False, None, "router", "none", "cloud_disabled", "unavailable", error, ())
        if not self._budget_available():
            error = "cloud budget exceeded"
            return ProviderExecutionResult(turn_id, False, None, "router", "none", "cloud_budget_blocked", "budget", error, ())

        started_at = datetime.now(timezone.utc)
        started_monotonic = monotonic()
        attempt = ProviderAttempt(
            attempt_id=uuid4().hex,
            turn_id=turn_id,
            provider=getattr(self.cloud, "provider", "cloud"),
            model_name=settings.cloud_model_name,
            stage="cloud",
            status="running",
            failure_kind=None,
            route_reason="cloud_started",
            started_at=started_at,
            finished_at=None,
            deadline_at=None,
            elapsed_ms=0,
        )
        emit(ProviderLifecycleEvent("cloud_started", attempt))
        attempt_cancel = ProviderCancellation()

        def call_cloud(cancel_token: ProviderCancellation) -> ModelResult:
            cloud_chat = self.cloud.chat
            return cloud_chat(task_type, prompt, cancel_token=cancel_token) if _accepts_cancel_token(cloud_chat) else cloud_chat(task_type, prompt)

        try:
            outcome = await _run_cancellable_worker(
                call_cloud,
                request_cancel=request_cancel,
                attempt_cancel=attempt_cancel,
                deadline_monotonic=None,
                monotonic=monotonic,
                poll_seconds=poll_seconds,
            )
            if outcome.error is not None:
                raise outcome.error
            cloud_result = outcome.value
        except BaseException as exc:
            failure_kind = normalize_interactive_failure(exc)
            finished_at = datetime.now(timezone.utc)
            attempt = replace(
                attempt,
                status="cancelled" if failure_kind == "cancelled" else "failed",
                failure_kind=failure_kind,
                route_reason="client_cancelled" if failure_kind == "cancelled" else "cloud_provider_error",
                finished_at=finished_at,
                elapsed_ms=max(0, int((monotonic() - started_monotonic) * 1000)),
            )
            failed = ModelResult(False, None, attempt.provider, attempt.model_name, error="request cancelled" if failure_kind == "cancelled" else redact_sensitive(str(exc)), duration_ms=attempt.elapsed_ms, route_reason=attempt.route_reason, failure_kind=failure_kind)
            if failure_kind != "cancelled":
                self._record(failed, task_type, policy.get("risk", "low"), len(prompt), upgraded=False)
            return ProviderExecutionResult(turn_id, False, None, attempt.provider, attempt.model_name, attempt.route_reason or "cloud_provider_error", failure_kind, failed.error, (attempt,))

        if not isinstance(cloud_result, ModelResult):
            cloud_result = ModelResult(False, None, attempt.provider, attempt.model_name, error="cloud provider returned invalid result", failure_kind="response_error")
        failure_kind = None if cloud_result.success and cloud_result.text else (cloud_result.failure_kind or normalize_interactive_failure(cloud_result.error))
        cloud_result.route_reason = policy.get("reason", "cloud_only") if failure_kind is None else "cloud_provider_error"
        attempt = replace(
            attempt,
            status="succeeded" if failure_kind is None else "failed",
            failure_kind=failure_kind,
            route_reason=cloud_result.route_reason,
            finished_at=datetime.now(timezone.utc),
            elapsed_ms=max(0, int((monotonic() - started_monotonic) * 1000)),
        )
        self._record(cloud_result, task_type, policy.get("risk", "low"), len(prompt), upgraded=False)
        if cloud_result.success and cloud_result.text:
            return ProviderExecutionResult(turn_id, True, cloud_result.text, cloud_result.provider, cloud_result.model_name, cloud_result.route_reason, None, None, (attempt,))
        return ProviderExecutionResult(turn_id, False, None, cloud_result.provider, cloud_result.model_name, cloud_result.route_reason or "cloud_provider_error", failure_kind or "provider_error", cloud_result.error, (attempt,))

    def run_structured(self, task_type: str, prompt: str, required_keys: set[str], confirmed: bool = False) -> ModelResult:
        policy = self.task_policy(task_type)
        if policy["requires_confirmation"] and not confirmed:
            return ModelResult(False, None, "router", "none", "cloud confirmation required")
        if policy["provider"] == "cloud":
            if self.cloud is None:
                return ModelResult(False, None, "router", "none", "cloud model is disabled or not configured")
            if not self._budget_available():
                return ModelResult(False, None, "router", "none", "cloud budget exceeded")
            try:
                result = self.cloud.structured_output(prompt, {"required": sorted(required_keys)})
            except Exception as exc:
                result = ModelResult(False, None, getattr(self.cloud, "provider", "cloud"), settings.cloud_model_name, redact_sensitive(str(exc)), failure_kind="provider_error")
            result.route_reason = policy["reason"]
            self._record(result, task_type, policy["risk"], len(prompt))
            return result
        attempts = max(0, settings.model_max_retries) + 1
        result = ModelResult(False, None, "ollama", settings.local_model_name, "local structured output unavailable")
        for attempt in range(attempts):
            try:
                result = self.local.structured_output(prompt, {"required": sorted(required_keys)})
            except Exception as exc:
                result = ModelResult(False, None, "ollama", settings.local_model_name, redact_sensitive(str(exc)))
            result.retry_count = attempt
            if result.success:
                result.route_reason = f"{task_type}_local_success"
                self._record(result, task_type, policy["risk"], len(prompt))
                return result
            if settings.model_retry_backoff_seconds > 0 and attempt < attempts - 1:
                time.sleep(settings.model_retry_backoff_seconds * (attempt + 1))
        if policy.get("fallback_provider") == "cloud" and self.cloud is not None and self._budget_available() and self.classify_risk(prompt) == "low":
            cloud_result = self.cloud.structured_output(prompt, {"required": sorted(required_keys)})
            cloud_result.retry_count = result.retry_count
            cloud_result.fallback_used = True
            cloud_result.route_reason = f"{task_type}_cloud_fallback"
            self._record(cloud_result, task_type, policy["risk"], len(prompt), upgraded=True)
            return cloud_result
        result.route_reason = f"{task_type}_structured_failure"
        self._record(result, task_type, policy["risk"], len(prompt))
        return result

    def _budget_available(self) -> bool:
        with SessionLocal() as db:
            today_calls = db.scalar(select(func.count(ModelCallLog.id)).where(ModelCallLog.provider == "zhiapi", func.date(ModelCallLog.created_at) == func.current_date())) or 0
            today_cost = db.scalar(select(func.coalesce(func.sum(ModelCallLog.estimated_cost), 0.0)).where(ModelCallLog.provider == "zhiapi", func.date(ModelCallLog.created_at) == func.current_date())) or 0.0
        return today_calls < settings.daily_cloud_call_limit and float(today_cost) + 0.0001 <= settings.daily_cost_limit

    def _record(self, result: ModelResult, task_type: str, risk: str, input_length: int, upgraded: bool = False) -> None:
        with SessionLocal() as db:
            text = getattr(result, "text", None)
            confidence = getattr(result, "confidence", None)
            route_reason = getattr(result, "route_reason", None)
            output_length = len(text or "") if text else len(json.dumps(result.data, ensure_ascii=False)) if result.data else 0
            input_tokens = getattr(result, "_input_tokens", None)
            output_tokens = getattr(result, "_output_tokens", None)
            total_tokens = getattr(result, "_total_tokens", None)
            if input_tokens is None:
                input_tokens = estimate_tokens(text) if text else estimate_tokens(json.dumps(result.data, ensure_ascii=False)) if result.data else 1
            if output_tokens is None:
                output_tokens = estimate_tokens(text or (json.dumps(result.data, ensure_ascii=False) if result.data else None))
            usage_available = getattr(result, "_input_tokens", None) is not None or getattr(result, "_output_tokens", None) is not None or getattr(result, "_total_tokens", None) is not None
            if total_tokens is None:
                total_tokens = input_tokens + output_tokens
            token_source = "actual" if usage_available else "estimated"
            billing_source = "provider_usage_rate" if result.provider == "zhiapi" and usage_available else "local_no_charge" if result.provider == "ollama" else "estimated_rate"
            estimated_cost = round((input_tokens * settings.cloud_input_price_per_1k + output_tokens * settings.cloud_output_price_per_1k) / 1000, 6) if result.provider == "zhiapi" else 0.0
            db.add(ModelCallLog(task_type=task_type, risk_level=risk, provider=result.provider, model_name=result.model_name, upgraded=upgraded, input_length=input_length, output_length=output_length, input_tokens=input_tokens, output_tokens=output_tokens, total_tokens=total_tokens, token_source=token_source, billing_source=billing_source, duration_ms=result.duration_ms, estimated_cost=estimated_cost, success=result.success, confidence=confidence, route_reason=route_reason, retry_count=getattr(result, "retry_count", 0), fallback_used=getattr(result, "fallback_used", False)))
            db.commit()

    def model_health(self) -> dict[str, Any]:
        cloud_enabled = bool(settings.cloud_model_enabled)
        cloud_configured = self.cloud is not None
        cloud_available = bool(self.cloud and self.cloud.health_check())
        return {
            "local": {"provider": "ollama", "model": settings.local_model_name, "available": self.local.health_check()},
            "cloud": {"provider": "zhiapi", "model": settings.cloud_model_name, "enabled": cloud_enabled, "configured": cloud_configured, "available": cloud_available},
        }

    def parse_daily_log(self, raw_text: str) -> ModelResult:
        key = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
        cached = self._cache.get(key)
        if cached and time.monotonic() - cached[0] <= max(0, settings.model_cache_ttl_seconds):
            return cached[1]
        if cached:
            self._cache.pop(key, None)
        risk = self.classify_risk(raw_text)
        if settings.model_routing_mode == "cloud_only":
            if self.cloud is None:
                return ModelResult(False, None, "router", "none", "cloud model is disabled or not configured", route_reason="cloud_disabled", failure_kind="unavailable")
            if not self._budget_available():
                return ModelResult(False, None, "router", "none", "cloud budget exceeded", route_reason="cloud_budget_blocked", failure_kind="budget")
            try:
                result = self.cloud.structured_log(raw_text)
            except Exception as exc:
                result = ModelResult(False, None, getattr(self.cloud, "provider", "cloud"), settings.cloud_model_name, redact_sensitive(str(exc)), failure_kind="provider_error")
            result.route_reason = "已配置为所有任务直接使用云端" if result.success else "cloud_provider_error"
            self._record(result, "daily_log_parse", risk, len(raw_text))
            if result.success:
                self._cache[key] = (time.monotonic(), result)
            return result
        attempts = max(0, settings.model_max_retries) + 1
        result = ModelResult(False, None, "ollama", settings.local_model_name, "local structured output unavailable")
        for attempt in range(attempts):
            try:
                result = self.local.structured_log(raw_text)
            except Exception as exc:
                result = ModelResult(False, None, "ollama", settings.local_model_name, redact_sensitive(str(exc)))
            result.retry_count = attempt
            if result.success:
                break
            if settings.model_retry_backoff_seconds > 0 and attempt < attempts - 1:
                time.sleep(settings.model_retry_backoff_seconds * (attempt + 1))
        self._record(result, "daily_log_parse", risk, len(raw_text))
        if result.success:
            self._cache[key] = (time.monotonic(), result)
            return result
        if self.should_use_cloud(raw_text):
            if not self._budget_available():
                result.error = "local parsing failed and cloud budget exceeded; deterministic fallback used"
                result.route_reason = "daily_log_local_failure_budget_blocked_deterministic_fallback"
                result.data = self._deterministic_daily_log()
                result.success = True
                result.provider = "deterministic"
                result.model_name = "rule_based"
                result.fallback_used = True
                result.route_reason = "daily_log_deterministic_fallback"
                self._record(result, "daily_log_parse", risk, len(raw_text), upgraded=False)
                self._cache[key] = (time.monotonic(), result)
                return result
            cloud_result = self.cloud.structured_log(raw_text)
            cloud_result.fallback_used = True
            cloud_result.retry_count += result.retry_count
            self._record(cloud_result, "daily_log_parse", risk, len(raw_text), upgraded=True)
            if cloud_result.success:
                self._cache[key] = (time.monotonic(), cloud_result)
                return cloud_result
            result.data = self._deterministic_daily_log()
            result.success = True
            result.provider = "deterministic"
            result.model_name = "rule_based"
            result.error = "local and cloud structured parsing failed; deterministic fallback used"
            result.fallback_used = True
            result.route_reason = "daily_log_deterministic_fallback"
            self._record(result, "daily_log_parse", risk, len(raw_text), upgraded=False)
            self._cache[key] = (time.monotonic(), result)
            return result
        result.data = self._deterministic_daily_log()
        result.success = True
        result.provider = "deterministic"
        result.model_name = "rule_based"
        result.error = "local structured parsing unavailable; deterministic fallback used"
        result.fallback_used = True
        result.route_reason = "daily_log_deterministic_fallback"
        self._record(result, "daily_log_parse", risk, len(raw_text), upgraded=False)
        self._cache[key] = (time.monotonic(), result)
        return result


router = ModelRouter()
__all__ = ["ModelResult", "OllamaAdapter", "CloudAdapter", "ModelRouter", "router", "redact_sensitive", "validate_structured_data"]
