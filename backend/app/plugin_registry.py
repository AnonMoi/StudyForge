"""Safe, declaration-only local plugin registry.

Plugins may register model-backed commands, but v1 never imports plugin code,
loads arbitrary browser scripts, writes files, or mutates learning records.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy.orm import Session

from .file_import import ApplicationState
from .models import utcnow

PLUGIN_STATE_KEY = "plugins_registry"
_ID_RE = re.compile(r"^[a-z][a-z0-9._-]{1,63}$")
_TASK_RE = re.compile(r"^[a-z][a-z0-9_-]{1,59}$")
_ALLOWED_PERMISSIONS = {"model_task"}


def _state(db: Session) -> ApplicationState:
    state = db.get(ApplicationState, PLUGIN_STATE_KEY)
    if state is None:
        state = ApplicationState(key=PLUGIN_STATE_KEY, value={"plugins": {}})
        db.add(state)
        db.flush()
    if not isinstance(state.value, dict) or not isinstance(state.value.get("plugins"), dict):
        state.value = {"plugins": {}}
    return state


def normalize_manifest(raw: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("插件 manifest 必须是 JSON 对象")
    plugin_id = str(raw.get("id", "")).strip().lower()
    name = str(raw.get("name", "")).strip()
    version = str(raw.get("version", "")).strip()
    description = str(raw.get("description", "")).strip()
    if not _ID_RE.fullmatch(plugin_id):
        raise ValueError("插件 id 只能包含小写字母、数字、点、下划线和短横线")
    if not name or len(name) > 120 or not version or len(version) > 40:
        raise ValueError("插件 name 和 version 必须有效")
    if len(description) > 1000:
        raise ValueError("插件 description 不能超过 1000 个字符")
    permissions = raw.get("permissions", ["model_task"])
    if not isinstance(permissions, list) or any(str(item) not in _ALLOWED_PERMISSIONS for item in permissions):
        raise ValueError("插件只能申请 model_task 权限")
    commands = raw.get("commands", [])
    if not isinstance(commands, list) or len(commands) > 20:
        raise ValueError("插件 commands 必须是最多 20 项的数组")
    normalized_commands: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in commands:
        if not isinstance(item, dict):
            raise ValueError("插件命令必须是对象")
        command_id = str(item.get("id", "")).strip().lower()
        title = str(item.get("title", "")).strip()
        task_type = str(item.get("task_type", "")).strip().lower()
        prompt_template = str(item.get("prompt_template", "")).strip()
        if not _ID_RE.fullmatch(command_id) or command_id in seen:
            raise ValueError("插件命令 id 无效或重复")
        if not title or len(title) > 160 or not _TASK_RE.fullmatch(task_type):
            raise ValueError("插件命令 title 或 task_type 无效")
        if not prompt_template or len(prompt_template) > 8000:
            raise ValueError("插件命令 prompt_template 必须在 1 到 8000 个字符之间")
        seen.add(command_id)
        normalized_commands.append({
            "id": command_id,
            "title": title,
            "description": str(item.get("description", "")).strip()[:500],
            "task_type": task_type,
            "prompt_template": prompt_template,
            "requires_confirmation": True,
        })
    return {
        "api_version": "1",
        "id": plugin_id,
        "name": name,
        "version": version,
        "description": description,
        "permissions": [str(item) for item in permissions],
        "commands": normalized_commands,
    }


def list_plugins(db: Session) -> list[dict[str, Any]]:
    state = _state(db)
    rows = []
    for item in state.value["plugins"].values():
        if isinstance(item, dict) and isinstance(item.get("manifest"), dict):
            rows.append({**item, "manifest": dict(item["manifest"])})
    return sorted(rows, key=lambda item: (str(item["manifest"].get("name", "")), str(item["manifest"].get("id", ""))))


def get_plugin(db: Session, plugin_id: str) -> dict[str, Any] | None:
    return _state(db).value["plugins"].get(plugin_id)


def install_plugin(db: Session, manifest: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    normalized = normalize_manifest(manifest)
    state = _state(db)
    plugins = dict(state.value["plugins"])
    existing = plugins.get(normalized["id"])
    record = {
        "manifest": normalized,
        "enabled": bool(existing.get("enabled", True)) if isinstance(existing, dict) else True,
        "installed_at": existing.get("installed_at") if isinstance(existing, dict) else utcnow().isoformat(),
        "updated_at": utcnow().isoformat(),
        "source": "local_manifest",
    }
    plugins[normalized["id"]] = record
    state.value = {"plugins": plugins}
    db.commit()
    return record, existing is not None


def set_plugin_enabled(db: Session, plugin_id: str, enabled: bool) -> dict[str, Any] | None:
    state = _state(db)
    record = state.value["plugins"].get(plugin_id)
    if not isinstance(record, dict):
        return None
    record = dict(record)
    record["enabled"] = enabled
    record["updated_at"] = utcnow().isoformat()
    plugins = dict(state.value["plugins"]); plugins[plugin_id] = record
    state.value = {"plugins": plugins}
    db.commit()
    return record


def remove_plugin(db: Session, plugin_id: str) -> bool:
    state = _state(db)
    plugins = dict(state.value["plugins"])
    if plugin_id not in plugins:
        return False
    del plugins[plugin_id]
    state.value = {"plugins": plugins}
    db.commit()
    return True


def find_command(record: dict[str, Any], command_id: str) -> dict[str, Any] | None:
    manifest = record.get("manifest") if isinstance(record, dict) else None
    commands = manifest.get("commands", []) if isinstance(manifest, dict) else []
    return next((item for item in commands if isinstance(item, dict) and item.get("id") == command_id), None)


__all__ = ["find_command", "get_plugin", "install_plugin", "list_plugins", "normalize_manifest", "remove_plugin", "set_plugin_enabled"]
