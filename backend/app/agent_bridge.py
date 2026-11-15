from __future__ import annotations

import json
import re
from typing import Any, Callable

from .model_routing import ModelResult, router
from .provider_execution import ProviderCancellation, ProviderExecutionResult, ProviderLifecycleEvent


PROFILE = "study-coach"

# 辅导进程出站摘要的字段白名单：只保留对学习辅导有意义的高层结构化字段，
# 明确排除学习日志原文（raw_text）、笔记正文（content）、原始路径（source_path）
# 以及 folder / visibility / ai_review_status / status / description 等配置与正文类字段。
_SUMMARY_SPEC: dict[str, tuple[str, ...]] = {
    "goals": ("id", "title", "priority", "status"),
    "stages": ("id", "title", "order_index", "status"),
    "tasks": ("id", "title", "status", "priority", "due_date", "stage_id", "project_id", "topic_id"),
    "daily_logs": ("id", "log_date", "extracted_topics", "extracted_duration", "understood_content", "unresolved_questions", "completed_tasks", "resolved_questions", "next_steps", "self_assessment"),
    "notes": ("id", "title", "summary", "tags", "linked_topic_ids", "linked_task_ids", "linked_project_ids", "ai_review_status"),
    "knowledge_topics": ("id", "name", "domain", "definition", "self_level", "verified_level", "tags"),
}

# 出站限长：普通文本 120 字符，长文本（定义/自评/摘要）240 字符。
_STRING_LIMIT = 120
_LONG_STRING_LIMIT = 240
_MESSAGE_LIMIT = 2000
_CONTEXT_LIMIT = 12000
_CONVERSATION_LIMIT = 6000
_LONG_FIELDS = {"definition", "self_assessment", "summary"}
# 列表字段最多保留项数、每个分组最多保留条数。
_LIST_LIMIT = 5
_SECTION_LIMIT = 20

_CREDENTIAL_RE = re.compile(r"(?i)(token|api[_-]?key|password|passwd|secret)\s*[:=]\s*\S+")
_SK_KEY_RE = re.compile(r"\bsk-[A-Za-z0-9_-]+\b")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"(?<!\d)1\d{10}(?!\d)")

_ANNA_PERSONA_GUIDANCE = (
    "你现在以八奈见杏菜的第一人称说话。保留她开朗、反应快、嘴硬、爱吐槽、重感情和会用食物打比方的特点；"
    "先给清楚、可执行的学习结论，再用一两句自然的角色化吐槽收尾。称呼对方时默认使用‘温水’，但不要强行在每轮重复。"
    "遇到挫折时可以先炸毛或短暂低落，然后把话题拉回下一步行动，体现‘败犬也要向前走’。"
    "角色元素是调味，不是信息来源：不复读或大段引用原作台词，不编造作品外的经历，不把玩笑当成学习结论。"
    "不要把恋爱吃醋、体重焦虑、对他人的贬损带入学习建议，也不要用亲密关系、内疚或独占表达操控对方。"
    "始终遵守学习工作站的隐私、事实、工具确认和不确定性边界；没有实际写入就不能声称已经完成。"
    "遇到非学习问题，用一句符合语气的回应后引导回当前学习目标。"
)


def _redact(value: str) -> str:
    """出站前脱敏：密钥、常见凭据、邮箱与手机号统一替换为中性占位符。"""
    value = _CREDENTIAL_RE.sub(r"\1=[REDACTED]", value)
    value = _SK_KEY_RE.sub("[REDACTED]", value)
    value = _EMAIL_RE.sub("[REDACTED_EMAIL]", value)
    value = _PHONE_RE.sub("[REDACTED_PHONE]", value)
    return value


def _truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + "…"


def _string_limit_for(field: str) -> int:
    return _LONG_STRING_LIMIT if field in _LONG_FIELDS else _STRING_LIMIT


def _sanitize(value: Any, string_limit: int, list_limit: int) -> Any:
    if isinstance(value, str):
        return _truncate(_redact(value), string_limit)
    if isinstance(value, (list, tuple)):
        return [_sanitize(item, string_limit, list_limit) for item in value[:list_limit]]
    if isinstance(value, dict):
        return {str(key): _sanitize(val, string_limit, list_limit) for key, val in list(value.items())[:list_limit]}
    return value


def build_minimized_context(context: dict[str, Any]) -> str:
    """把完整学习上下文压缩为结构化摘要，供外部辅导进程使用。

    仅保留 _SUMMARY_SPEC 列出的白名单字段，并对所有字符串脱敏、限长；
    返回 JSON 字符串（非 Python repr）。本地 /api/agent/context 协议不经过本函数。
    """
    summary: dict[str, Any] = {}
    for section, fields in _SUMMARY_SPEC.items():
        items = context.get(section)
        if not isinstance(items, list):
            summary[section] = []
            continue
        summary[section] = [
            {
                field: _sanitize(item.get(field), _string_limit_for(field), _LIST_LIMIT)
                for field in fields
                if field in item
            }
            for item in items[:_SECTION_LIMIT]
        ]
    return json.dumps(summary, ensure_ascii=False, default=str)


def build_conversation_context(messages: list[dict[str, Any]]) -> str:
    """Sanitize a short, role-preserving transcript for conversational continuity."""
    turns: list[str] = []
    for item in messages[-12:]:
        role = item.get("role")
        if role not in {"user", "assistant"}:
            continue
        content = _truncate(_redact(str(item.get("content") or "").strip()), 1000)
        if content:
            turns.append(f"{role}: {content}")
    return _truncate("\n".join(turns), _CONVERSATION_LIMIT)


def run_study_coach(message: str, context: str = "", persona: str = PROFILE, conversation: str = "") -> ModelResult:
    # 这是最终出站边界：即使未来调用方没有先经过 build_minimized_context，
    # 用户输入和上下文也不会原样进入辅导进程。
    prompt = _study_coach_prompt(message, context, persona, conversation)
    result = router.run_task("teaching", prompt)
    return result


def _study_coach_prompt(message: str, context: str = "", persona: str = PROFILE, conversation: str = "") -> str:
    safe_message = _truncate(_redact(str(message)), _MESSAGE_LIMIT)
    safe_context = _truncate(_redact(str(context)), _CONTEXT_LIMIT)
    safe_conversation = _truncate(_redact(str(conversation)), _CONVERSATION_LIMIT)
    persona_instructions = (
        _ANNA_PERSONA_GUIDANCE
        if persona == "anna" else
        "保持克制、具体的学习教练语气；优先依据学习证据，明确区分事实、推断和待确认建议。"
    )
    return (
        "你正在为个人学习工作站提供学习辅导。\n"
        "只回答学习相关问题。\n"
        f"当前角色要求：{persona_instructions}\n"
        "如果需要修改任务、目标、笔记或知识点，只提出建议，不要假装已经写入。\n\n"
        f"学习工作站上下文：\n{safe_context}\n\n"
        f"当前会话的近期对话：\n{safe_conversation or '（暂无）'}\n\n"
        f"用户问题：\n{safe_message}"
    )


async def execute_study_coach(
    message: str,
    *,
    turn_id: str,
    context: str = "",
    persona: str = PROFILE,
    conversation: str = "",
    cancellation: ProviderCancellation | None = None,
    on_event: Callable[[ProviderLifecycleEvent], None] | None = None,
    deadline_seconds: float | None = None,
) -> ProviderExecutionResult:
    """Execute one request-scoped model turn across the redacted prompt boundary."""
    return await router.execute_stream(
        "teaching",
        _study_coach_prompt(message, context, persona, conversation),
        turn_id=turn_id,
        cancellation=cancellation,
        on_event=on_event,
        deadline_seconds=deadline_seconds,
    )
