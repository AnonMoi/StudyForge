from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Callable

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .config import settings
from .db import Base, get_db
from .models import AuditLog, LearningProject, utcnow


GITHUB_REPOSITORY_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}/[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$")
GITHUB_MAX_COMMIT_LIMIT = 100


class GitHubRepository(Base):
    __tablename__ = "github_repositories"
    __table_args__ = (UniqueConstraint("project_id", "full_name", name="uq_github_repositories_project_full_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("learning_projects.id", ondelete="CASCADE"))
    owner: Mapped[str] = mapped_column(String(120))
    name: Mapped[str] = mapped_column(String(120))
    full_name: Mapped[str] = mapped_column(String(240))
    html_url: Mapped[str] = mapped_column(String(2048), default="")
    default_branch: Mapped[str] = mapped_column(String(240), default="main")
    private: Mapped[bool] = mapped_column(Boolean, default=False)
    description: Mapped[str] = mapped_column(Text, default="")
    last_synced_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class GitHubCommit(Base):
    __tablename__ = "github_commits"
    __table_args__ = (UniqueConstraint("repository_id", "sha", name="uq_github_commits_repository_sha"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    repository_id: Mapped[int] = mapped_column(ForeignKey("github_repositories.id", ondelete="CASCADE"))
    sha: Mapped[str] = mapped_column(String(64))
    message: Mapped[str] = mapped_column(Text, default="")
    author_name: Mapped[str] = mapped_column(String(240), default="")
    author_login: Mapped[str] = mapped_column(String(120), default="")
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    html_url: Mapped[str] = mapped_column(String(2048), default="")
    additions: Mapped[int] = mapped_column(Integer, default=0)
    deletions: Mapped[int] = mapped_column(Integer, default=0)
    changed_files: Mapped[int] = mapped_column(Integer, default=0)
    files: Mapped[list[Any]] = mapped_column(JSON, default=list)
    analysis_status: Mapped[str] = mapped_column(String(40), default="pending_confirmation")
    analysis: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    analysis_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class GitHubLinkRequest(BaseModel):
    repository: str = Field(min_length=3, max_length=240)
    confirmed: bool = False


class GitHubSyncRequest(BaseModel):
    confirmed: bool = False
    limit: int = Field(default=30, ge=1, le=GITHUB_MAX_COMMIT_LIMIT)


class GitHubAnalysisRequest(BaseModel):
    confirmed: bool = False


router = APIRouter()


def _audit(db: Session, entity_type: str, entity_id: int, action: str, before: dict[str, Any] | None, after: dict[str, Any] | None) -> None:
    safe_before = json.loads(json.dumps(before, ensure_ascii=False, default=str)) if before is not None else None
    safe_after = json.loads(json.dumps(after, ensure_ascii=False, default=str)) if after is not None else None
    db.add(AuditLog(entity_type=entity_type, entity_id=entity_id, action=action, before_data=safe_before, after_data=safe_after))
    db.commit()


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _repository_identifier(value: str) -> tuple[str, str, str]:
    repository = value.strip().strip("/")
    if not GITHUB_REPOSITORY_PATTERN.fullmatch(repository):
        raise HTTPException(status_code=422, detail="GitHub 仓库必须使用 owner/repository 格式")
    owner, name = repository.split("/", 1)
    return owner, name, repository


def _github_get(path: str, params: dict[str, Any] | None = None) -> Any:
    if not settings.github_enabled:
        raise HTTPException(status_code=503, detail="GitHub 集成已在服务端配置中关闭")
    base_url = settings.github_api_base_url.rstrip("/")
    if not base_url.startswith(("http://", "https://")):
        raise HTTPException(status_code=503, detail="GitHub API 地址配置无效")
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "LearningWorkstation/0.1"}
    if settings.github_token:
        headers["Authorization"] = f"Bearer {settings.github_token}"
    try:
        response = httpx.get(f"{base_url}{path}", params=params, headers=headers, timeout=settings.github_timeout_seconds, trust_env=False)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="GitHub 请求失败，请检查网络或稍后重试") from exc
    if response.status_code == 404:
        raise HTTPException(status_code=404, detail="GitHub 仓库不存在，或当前 Token 没有访问权限")
    if response.status_code in {401, 403}:
        raise HTTPException(status_code=502, detail="GitHub 拒绝访问，请检查 Token 权限或 API 限流状态")
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"GitHub API 返回 HTTP {response.status_code}")
    try:
        return response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="GitHub 返回了无法解析的响应") from exc


def _repository_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    owner = str((payload.get("owner") or {}).get("login") or "").strip()
    full_name = str(payload.get("full_name") or "").strip()
    if not owner and "/" in full_name:
        owner = full_name.split("/", 1)[0]
    name = str(payload.get("name") or (full_name.split("/", 1)[1] if "/" in full_name else "")).strip()
    if not owner or not name or not GITHUB_REPOSITORY_PATTERN.fullmatch(f"{owner}/{name}"):
        raise HTTPException(status_code=502, detail="GitHub 仓库响应缺少有效标识")
    return {"owner": owner, "name": name, "full_name": f"{owner}/{name}", "html_url": str(payload.get("html_url") or ""), "default_branch": str(payload.get("default_branch") or "main"), "private": bool(payload.get("private", False)), "description": str(payload.get("description") or "")[:5000]}


def _repository_read(row: GitHubRepository, commit_count: int = 0) -> dict[str, Any]:
    return {"id": row.id, "project_id": row.project_id, "owner": row.owner, "name": row.name, "full_name": row.full_name, "html_url": row.html_url, "default_branch": row.default_branch, "private": row.private, "description": row.description, "last_synced_sha": row.last_synced_sha, "last_sync_at": row.last_sync_at, "commit_count": commit_count, "created_at": row.created_at, "updated_at": row.updated_at}


def _normalize_commit(payload: dict[str, Any]) -> dict[str, Any]:
    commit = payload.get("commit") or {}
    author = commit.get("author") or {}
    files = []
    for item in payload.get("files") or []:
        filename = str(item.get("filename") or "").strip()
        if not filename:
            continue
        files.append({"filename": filename[:1024], "status": str(item.get("status") or "modified")[:30], "additions": int(item.get("additions") or 0), "deletions": int(item.get("deletions") or 0), "changes": int(item.get("changes") or 0)})
    stats = payload.get("stats") or {}
    return {"sha": str(payload.get("sha") or "")[:64], "message": str(commit.get("message") or "")[:20000], "author_name": str(author.get("name") or "")[:240], "author_login": str((payload.get("author") or {}).get("login") or "")[:120], "committed_at": _parse_datetime((commit.get("committer") or {}).get("date") or author.get("date")), "html_url": str(payload.get("html_url") or ""), "additions": int(stats.get("additions") or 0), "deletions": int(stats.get("deletions") or 0), "changed_files": int(payload.get("files_count") or len(files)), "files": files}


def _commit_read(row: GitHubCommit) -> dict[str, Any]:
    return {"id": row.id, "repository_id": row.repository_id, "sha": row.sha, "short_sha": row.sha[:7], "message": row.message, "author_name": row.author_name, "author_login": row.author_login, "committed_at": row.committed_at, "html_url": row.html_url, "additions": row.additions, "deletions": row.deletions, "changed_files": row.changed_files, "files": row.files or [], "analysis_status": row.analysis_status, "analysis": row.analysis or {}, "analysis_confirmed": row.analysis_confirmed, "imported_at": row.imported_at}


def _get_project(db: Session, project_id: int) -> LearningProject:
    project = db.get(LearningProject, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    return project


def _get_repository(db: Session, project_id: int, repository_id: int) -> GitHubRepository:
    _get_project(db, project_id)
    row = db.get(GitHubRepository, repository_id)
    if not row or row.project_id != project_id:
        raise HTTPException(status_code=404, detail="GitHub 仓库关联不存在")
    return row


def _analyze_commit(commit: dict[str, Any]) -> dict[str, Any]:
    files = commit.get("files") or []
    areas: set[str] = set()
    extension_counts: dict[str, int] = {}
    test_files = 0
    doc_files = 0
    for item in files:
        filename = str(item.get("filename") or "")
        lowered = filename.lower()
        extension = "." + lowered.rsplit(".", 1)[1] if "." in lowered.rsplit("/", 1)[-1] else "[none]"
        extension_counts[extension] = extension_counts.get(extension, 0) + 1
        if "/test" in lowered or lowered.startswith("test/") or "_test." in lowered or ".spec." in lowered:
            test_files += 1
            areas.add("tests")
        if lowered.endswith((".md", ".rst", ".txt")) or lowered.rsplit("/", 1)[-1].startswith("readme"):
            doc_files += 1
            areas.add("documentation")
        if lowered.endswith((".py", ".go", ".java", ".rs", ".sql")):
            areas.add("backend")
        if lowered.endswith((".js", ".jsx", ".ts", ".tsx", ".css", ".html")):
            areas.add("frontend")
        if lowered.endswith((".yml", ".yaml", ".json", ".toml", ".ini")) or ".github/" in lowered:
            areas.add("configuration")
    if not areas:
        areas.add("other")
    changed_files = int(commit.get("changed_files") or len(files))
    additions = int(commit.get("additions") or 0)
    deletions = int(commit.get("deletions") or 0)
    recommendations = []
    if test_files == 0 and ("backend" in areas or "frontend" in areas):
        recommendations.append("为本次代码改动补充一个可重复运行的测试或验收证据")
    if changed_files > 20 or additions + deletions > 500:
        recommendations.append("把较大的提交拆成更小的主题提交，便于复盘和回滚")
    if doc_files == 0:
        recommendations.append("为外部行为或架构变化补充一条简短文档说明")
    return {"summary": f"提交涉及 {changed_files} 个文件，新增 {additions} 行，删除 {deletions} 行。", "areas": sorted(areas), "signals": {"changed_files": changed_files, "additions": additions, "deletions": deletions, "test_files": test_files, "documentation_files": doc_files, "extension_counts": extension_counts}, "learning_points": [f"复盘 {area} 变更的设计取舍与验证方式" for area in sorted(areas)[:4]], "recommendations": recommendations, "confidence": 0.75}


@router.post("/projects/{project_id}/github/link")
def link_github_repository(project_id: int, payload: GitHubLinkRequest, db: Session = Depends(get_db)):
    _get_project(db, project_id)
    owner, name, full_name = _repository_identifier(payload.repository)
    metadata = _repository_from_payload(_github_get(f"/repos/{owner}/{name}"))
    if metadata["full_name"] != full_name:
        raise HTTPException(status_code=502, detail="GitHub 返回的仓库标识与请求不一致")
    existing = db.scalar(select(GitHubRepository).where(GitHubRepository.project_id == project_id, GitHubRepository.full_name == full_name))
    if not payload.confirmed:
        return {"requires_confirmation": True, "repository": {**metadata, "already_linked": existing is not None}, "warning": "确认后只保存仓库元数据和后续同步的提交元数据，不上传仓库源码，也不会修改 GitHub 仓库。"}
    if existing:
        row = existing
        row.owner = metadata["owner"]; row.name = metadata["name"]; row.html_url = metadata["html_url"]; row.default_branch = metadata["default_branch"]; row.private = metadata["private"]; row.description = metadata["description"]
        action = "update"
    else:
        row = GitHubRepository(project_id=project_id, **metadata)
        db.add(row)
        db.flush()
        action = "link"
    _audit(db, "github_repository", row.id, action, None, _repository_read(row))
    return {"requires_confirmation": False, "repository": _repository_read(row), "status": "linked"}


@router.get("/projects/{project_id}/github")
def list_github_repositories(project_id: int, db: Session = Depends(get_db)):
    _get_project(db, project_id)
    rows = list(db.scalars(select(GitHubRepository).where(GitHubRepository.project_id == project_id).order_by(GitHubRepository.id)))
    return {"repositories": [_repository_read(row, db.scalar(select(func.count(GitHubCommit.id)).where(GitHubCommit.repository_id == row.id)) or 0) for row in rows]}


@router.post("/projects/{project_id}/github/{repository_id}/sync")
def sync_github_repository(project_id: int, repository_id: int, payload: GitHubSyncRequest, db: Session = Depends(get_db)):
    repository = _get_repository(db, project_id, repository_id)
    raw_commits = _github_get(f"/repos/{repository.full_name}/commits", {"sha": repository.default_branch, "per_page": payload.limit})
    if not isinstance(raw_commits, list):
        raise HTTPException(status_code=502, detail="GitHub 提交列表响应格式无效")
    normalized = [_normalize_commit(item) for item in raw_commits if isinstance(item, dict)]
    normalized = [item for item in normalized if item["sha"]]
    existing_shas = {row.sha for row in db.scalars(select(GitHubCommit).where(GitHubCommit.repository_id == repository.id))}
    new_commits = [item for item in normalized if item["sha"] not in existing_shas]
    if not payload.confirmed:
        return {"requires_confirmation": True, "repository_id": repository.id, "fetched_commits": len(normalized), "new_commits": len(new_commits), "commits": [{**item, "short_sha": item["sha"][:7]} for item in normalized], "warning": "确认后只保存提交元数据和文件名统计，不保存 patch 或源码内容。"}
    synced = 0
    reused = 0
    for item in normalized:
        row = db.scalar(select(GitHubCommit).where(GitHubCommit.repository_id == repository.id, GitHubCommit.sha == item["sha"]))
        if row:
            reused += 1
            continue
        db.add(GitHubCommit(repository_id=repository.id, **item))
        synced += 1
    repository.last_synced_sha = normalized[0]["sha"] if normalized else repository.last_synced_sha
    repository.last_sync_at = utcnow()
    db.flush()
    _audit(db, "github_repository", repository.id, "sync", None, {"fetched_commits": len(normalized), "synced_commits": synced, "reused_commits": reused, "last_synced_sha": repository.last_synced_sha})
    return {"requires_confirmation": False, "repository_id": repository.id, "fetched_commits": len(normalized), "synced_commits": synced, "reused_commits": reused, "status": "synced"}


@router.get("/projects/{project_id}/github/{repository_id}/commits")
def list_github_commits(project_id: int, repository_id: int, limit: int = 50, db: Session = Depends(get_db)):
    repository = _get_repository(db, project_id, repository_id)
    rows = list(db.scalars(select(GitHubCommit).where(GitHubCommit.repository_id == repository.id).order_by(GitHubCommit.committed_at.desc(), GitHubCommit.id.desc()).limit(max(1, min(limit, 200)))))
    return {"repository": _repository_read(repository, len(rows)), "commits": [_commit_read(row) for row in rows]}


@router.post("/projects/{project_id}/github/commits/{commit_id}/analyze")
def analyze_github_commit(project_id: int, commit_id: int, payload: GitHubAnalysisRequest, db: Session = Depends(get_db)):
    _get_project(db, project_id)
    commit = db.get(GitHubCommit, commit_id)
    if not commit:
        raise HTTPException(status_code=404, detail="GitHub 提交不存在")
    repository = db.get(GitHubRepository, commit.repository_id)
    if not repository or repository.project_id != project_id:
        raise HTTPException(status_code=404, detail="GitHub 提交不属于该项目")
    analysis = _analyze_commit(_commit_read(commit))
    if not payload.confirmed:
        return {"requires_confirmation": True, "commit_id": commit.id, "analysis": analysis, "warning": "分析结果是学习建议，不会自动提升能力等级或修改项目状态。确认后仅保存这份分析记录。"}
    commit.analysis = analysis
    commit.analysis_status = "confirmed"
    commit.analysis_confirmed = True
    db.flush()
    _audit(db, "github_commit", commit.id, "analyze_confirm", None, analysis)
    return {"requires_confirmation": False, "commit_id": commit.id, "analysis": analysis, "analysis_confirmed": True, "status": "confirmed"}
