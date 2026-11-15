from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .models import ModelCallLog, ProviderBillImport, ProviderBillSync, utcnow


_ALLOWED_LINE_KEYS = {
    "call_id",
    "model_name",
    "amount",
    "cost",
    "currency",
    "occurred_at",
}


def current_period() -> tuple[date, date]:
    today = date.today()
    if today.month == 12:
        next_month = date(today.year + 1, 1, 1)
    else:
        next_month = date(today.year, today.month + 1, 1)
    return today.replace(day=1), next_month - timedelta(days=1)


def _safe_line(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise ValueError("供应商账单明细必须为对象")
    line = {key: item[key] for key in _ALLOWED_LINE_KEYS if key in item}
    amount = line.get("amount", line.get("cost"))
    try:
        amount_value = float(amount)
    except (TypeError, ValueError) as exc:
        raise ValueError("供应商账单金额无效") from exc
    if amount_value < 0:
        raise ValueError("供应商账单金额不能为负数")
    line["amount"] = round(amount_value, 6)
    if line.get("call_id") is not None:
        try:
            line["call_id"] = int(line["call_id"])
        except (TypeError, ValueError):
            line["call_id"] = None
    line["model_name"] = str(line.get("model_name") or "")
    line["currency"] = str(line.get("currency") or "CNY")
    line["occurred_at"] = str(line.get("occurred_at") or "")
    return line


def normalize_bill_payload(payload: Any, provider: str, source_name: str, period_start: date, period_end: date) -> dict[str, Any]:
    if isinstance(payload, list):
        raw_lines = payload
        envelope: dict[str, Any] = {}
    elif isinstance(payload, dict):
        envelope = payload
        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        raw_lines = data.get("lines") if isinstance(data, dict) else None
        if raw_lines is None and isinstance(data, dict):
            raw_lines = data.get("items")
    else:
        raise ValueError("供应商账单响应必须是 JSON 对象或数组")
    if not isinstance(raw_lines, list):
        raise ValueError("供应商账单响应缺少 lines 或 items 数组")
    lines = [_safe_line(item) for item in raw_lines]
    return {
        "provider": provider,
        "source_name": str(envelope.get("source_name") or source_name)[:240],
        "period_start": str(envelope.get("period_start") or period_start),
        "period_end": str(envelope.get("period_end") or period_end),
        "currency": str(envelope.get("currency") or "CNY")[:12],
        "lines": lines,
    }


class ProviderBillingClient:
    def fetch(self, period_start: date, period_end: date) -> dict[str, Any]:
        if not settings.provider_billing_enabled:
            raise RuntimeError("供应商账单自动拉取未启用")
        if not settings.provider_billing_url or not settings.provider_billing_api_key:
            raise RuntimeError("供应商账单自动拉取缺少本地配置")
        params = {
            "provider": settings.provider_billing_provider,
            "period_start": str(period_start),
            "period_end": str(period_end),
        }
        try:
            response = httpx.get(
                settings.provider_billing_url,
                params=params,
                headers={"Authorization": f"Bearer {settings.provider_billing_api_key}", "Accept": "application/json"},
                timeout=settings.provider_billing_timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise RuntimeError("供应商账单接口请求失败") from exc
        return normalize_bill_payload(
            payload,
            settings.provider_billing_provider,
            f"auto:{period_start}:{period_end}",
            period_start,
            period_end,
        )


def import_normalized_bill(payload: dict[str, Any], db: Session) -> ProviderBillImport:
    provider = str(payload["provider"])
    lines = payload["lines"]
    calls = {row.id: row for row in db.scalars(select(ModelCallLog).where(ModelCallLog.provider == provider))}
    matched_amount = 0.0
    matched_count = 0
    for index, line in enumerate(lines, start=1):
        matched = calls.get(line.get("call_id")) if line.get("call_id") is not None else None
        if matched and (not line.get("model_name") or line["model_name"] == matched.model_name):
            line["line"] = index
            line["matched_call_id"] = matched.id
            matched_amount += line["amount"]
            matched_count += 1
        else:
            line["line"] = index
            line["matched_call_id"] = None
    total = round(sum(line["amount"] for line in lines), 6)
    record = ProviderBillImport(
        provider=provider,
        period_start=date.fromisoformat(str(payload["period_start"])) if payload.get("period_start") else None,
        period_end=date.fromisoformat(str(payload["period_end"])) if payload.get("period_end") else None,
        source_name=payload.get("source_name", "auto"),
        currency=payload.get("currency", "CNY"),
        total_amount=total,
        matched_amount=round(matched_amount, 6),
        unmatched_amount=round(total - matched_amount, 6),
        line_count=len(lines),
        matched_count=matched_count,
        unmatched_count=len(lines) - matched_count,
        lines=lines,
    )
    db.add(record)
    db.flush()
    return record


def run_bill_sync(db: Session, period_start: date, period_end: date) -> ProviderBillSync:
    sync = ProviderBillSync(
        provider=settings.provider_billing_provider,
        period_start=period_start,
        period_end=period_end,
        status="running",
        max_attempts=settings.provider_billing_max_retries + 1,
        started_at=utcnow(),
        last_attempt_at=utcnow(),
    )
    db.add(sync)
    db.commit()
    db.refresh(sync)
    client = ProviderBillingClient()
    last_error = "供应商账单同步失败"
    for attempt in range(1, sync.max_attempts + 1):
        sync.attempts = attempt
        sync.last_attempt_at = utcnow()
        db.commit()
        try:
            payload = normalize_bill_payload(
                client.fetch(period_start, period_end),
                settings.provider_billing_provider,
                f"auto:{period_start}:{period_end}",
                period_start,
                period_end,
            )
            record = import_normalized_bill(payload, db)
            sync.status = "succeeded"
            sync.bill_import_id = record.id
            sync.source_name = record.source_name
            sync.line_count = record.line_count
            sync.completed_at = utcnow()
            sync.error = None
            db.commit()
            db.refresh(sync)
            return sync
        except (RuntimeError, ValueError) as exc:
            last_error = str(exc)
            db.rollback()
            if attempt < sync.max_attempts:
                continue
    sync.status = "failed"
    sync.error = last_error
    sync.completed_at = utcnow()
    db.commit()
    db.refresh(sync)
    return sync
