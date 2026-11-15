from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class AppError(Exception):
    message: str
    code: str = "APP_ERROR"
    status_code: int = 400
    fields: list[dict[str, Any]] | None = None

    def __post_init__(self) -> None:
        super().__init__(self.message)


class ResourceNotFoundError(AppError):
    def __init__(self, message: str) -> None:
        super().__init__(message=message, code="NOT_FOUND", status_code=404)


class ConflictError(AppError):
    def __init__(self, message: str) -> None:
        super().__init__(message=message, code="CONFLICT", status_code=409)


class PermissionDeniedError(AppError):
    def __init__(self, message: str) -> None:
        super().__init__(message=message, code="FORBIDDEN", status_code=403)


def error_payload(
    *,
    code: str,
    message: str,
    status_code: int,
    request_id: str,
    fields: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "error": {
            "code": code,
            "message": message,
            "status": status_code,
            "request_id": request_id,
        },
        # 保留 detail 兼容现有客户端，同时新增结构化 error 对象。
        "detail": message,
        "request_id": request_id,
    }
    if fields:
        payload["error"]["fields"] = fields
    return payload


__all__ = [
    "AppError",
    "ConflictError",
    "PermissionDeniedError",
    "ResourceNotFoundError",
    "error_payload",
]
