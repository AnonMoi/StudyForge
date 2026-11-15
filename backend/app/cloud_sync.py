"""Explicit WebDAV transport for already-encrypted sync bundles."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote, urlsplit

import httpx

from .config import settings


class CloudSyncError(RuntimeError):
    pass


def cloud_sync_configured() -> bool:
    return bool(
        settings.cloud_sync_enabled
        and settings.cloud_sync_provider == "webdav"
        and settings.cloud_sync_url
        and settings.cloud_sync_username
        and settings.cloud_sync_password
    )


class WebDavSyncProvider:
    def __init__(self, base_url: str | None = None, username: str | None = None, password: str | None = None, path: str | None = None, timeout: float | None = None):
        self.base_url = (base_url or settings.cloud_sync_url).rstrip("/")
        self.username = username if username is not None else settings.cloud_sync_username
        self.password = password if password is not None else settings.cloud_sync_password
        self.path = path or settings.cloud_sync_path
        self.timeout = timeout if timeout is not None else settings.cloud_sync_timeout_seconds

    @property
    def resource_url(self) -> str:
        parsed = urlsplit(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise CloudSyncError("云同步地址必须是不含账号信息和查询参数的 HTTP/HTTPS 地址")
        try:
            _ = parsed.port
        except ValueError as exc:
            raise CloudSyncError("云同步地址端口无效") from exc
        if any(segment in {"", ".", ".."} for segment in parsed.path.replace("\\", "/").split("/") if segment):
            raise CloudSyncError("云同步基础地址路径无效")
        raw_path = str(self.path or "").replace("\\", "/")
        segments = raw_path.split("/")
        if not raw_path or any(segment in {"", ".", ".."} for segment in segments):
            raise CloudSyncError("云同步路径无效")
        safe_path = "/".join(quote(segment, safe="") for segment in segments)
        return f"{self.base_url.rstrip('/')}/{safe_path}"

    def upload(self, bundle: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(bundle, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if len(body) > settings.max_request_body_bytes:
            raise CloudSyncError("云端同步包超过本地请求体大小限制")
        try:
            with httpx.Client(auth=(self.username, self.password), timeout=self.timeout, follow_redirects=False, trust_env=False) as client:
                response = client.put(self.resource_url, content=body, headers={"Content-Type": "application/json"})
        except httpx.HTTPError as exc:
            raise CloudSyncError("云同步服务暂时不可用") from exc
        if response.status_code not in range(200, 300):
            raise CloudSyncError(f"云同步上传失败：HTTP {response.status_code}")
        return {"status": "uploaded", "remote_url": self.resource_url}

    def download(self) -> dict[str, Any] | None:
        try:
            with httpx.Client(auth=(self.username, self.password), timeout=self.timeout, follow_redirects=False, trust_env=False) as client:
                response = client.get(self.resource_url, headers={"Accept": "application/json"})
        except httpx.HTTPError as exc:
            raise CloudSyncError("云同步服务暂时不可用") from exc
        if response.status_code == 404:
            return None
        if response.status_code not in range(200, 300):
            raise CloudSyncError(f"云同步下载失败：HTTP {response.status_code}")
        if len(response.content) > settings.max_request_body_bytes:
            raise CloudSyncError("云同步包超过本地请求体大小限制")
        try:
            bundle = response.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise CloudSyncError("云端同步包不是有效 JSON") from exc
        if not isinstance(bundle, dict):
            raise CloudSyncError("云端同步包格式无效")
        return bundle


__all__ = ["CloudSyncError", "WebDavSyncProvider", "cloud_sync_configured"]
