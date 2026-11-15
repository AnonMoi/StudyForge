from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import JSON, DateTime, Integer, Text, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .db import Base, get_db
from .models import AuditLog, CapabilityProfile, LearningProject, utcnow
from .notes_models import KnowledgeTopic

router = APIRouter()


class JobAnalysis(Base):
    __tablename__ = "job_analyses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(240))
    source_text: Mapped[str] = mapped_column(Text, default="")
    source_hash: Mapped[str] = mapped_column(String(64), index=True)
    extracted_skills: Mapped[list[Any]] = mapped_column(JSON, default=list)
    matched_topics: Mapped[list[Any]] = mapped_column(JSON, default=list)
    matched_capabilities: Mapped[list[Any]] = mapped_column(JSON, default=list)
    project_evidence: Mapped[list[Any]] = mapped_column(JSON, default=list)
    gaps: Mapped[list[Any]] = mapped_column(JSON, default=list)
    recommendations: Mapped[list[Any]] = mapped_column(JSON, default=list)
    confidence: Mapped[float] = mapped_column(default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class JobAnalysisRequest(BaseModel):
    title: str = Field(default="目标岗位", min_length=1, max_length=240)
    description: str = Field(min_length=20, max_length=30000)
    confirmed: bool = False


def _audit(db: Session, action: str, row: JobAnalysis, before: dict[str, Any] | None = None) -> None:
    db.add(AuditLog(entity_type="job_analysis", entity_id=row.id, action=action, before_data=before, after_data=_read(row)))


def _read(row: JobAnalysis) -> dict[str, Any]:
    return {
        "id": row.id,
        "title": row.title,
        "source_hash": row.source_hash,
        "extracted_skills": row.extracted_skills or [],
        "matched_topics": row.matched_topics or [],
        "matched_capabilities": row.matched_capabilities or [],
        "project_evidence": row.project_evidence or [],
        "gaps": row.gaps or [],
        "recommendations": row.recommendations or [],
        "confidence": row.confidence,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


SKILL_CATALOG: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Python", ("python",)),
    ("JavaScript", ("javascript", "js")),
    ("TypeScript", ("typescript", "ts")),
    ("Java", ("java",)),
    ("C++", ("c++", "cpp")),
    ("SQL", ("sql",)),
    ("FastAPI", ("fastapi",)),
    ("React", ("react",)),
    ("Node.js", ("node.js", "nodejs", "node")),
    ("Docker", ("docker",)),
    ("Linux", ("linux",)),
    ("Git", ("git",)),
    ("GitHub Actions", ("github actions", "ci/cd", "cicd")),
    ("REST API", ("rest api", "restful", "api 设计")),
    ("数据结构与算法", ("数据结构", "算法", "data structures", "algorithms")),
    ("数据库", ("数据库", "database", "mysql", "postgresql", "sqlite")),
    ("机器学习", ("机器学习", "machine learning")),
    ("深度学习", ("深度学习", "deep learning", "pytorch", "tensorflow")),
    ("数据分析", ("数据分析", "data analysis", "pandas", "numpy")),
    ("LLM 与 AI Agent", ("llm", "大模型", "ai agent", "agent", "提示词")),
    ("测试", ("测试", "testing", "pytest", "单元测试")),
    ("云计算", ("云计算", "cloud", "aws", "azure", "aliyun")),
)


def _contains(text: str, phrase: str) -> bool:
    if re.fullmatch(r"[a-z0-9+#. /-]+", phrase):
        return re.search(rf"(?<![a-z0-9]){re.escape(phrase)}(?![a-z0-9])", text, re.IGNORECASE) is not None
    return phrase.casefold() in text.casefold()


def _analyze(db: Session, title: str, description: str) -> dict[str, Any]:
    normalized = " ".join(description.split())
    lowered = normalized.casefold()
    extracted = [canonical for canonical, aliases in SKILL_CATALOG if any(_contains(lowered, alias) for alias in aliases)]

    topics: list[dict[str, Any]] = []
    for topic in db.scalars(select(KnowledgeTopic).order_by(KnowledgeTopic.name)):
        searchable = " ".join([topic.name, topic.domain, topic.definition, *(topic.tags or [])])
        overlap = [skill for skill in extracted if _contains(searchable.casefold(), skill.casefold())]
        if overlap or _contains(lowered, topic.name):
            topics.append({"id": topic.id, "name": topic.name, "verified_level": topic.verified_level, "matched_skills": overlap, "reason": "岗位描述中的技能与本地知识主题存在关键词重合"})

    capabilities: list[dict[str, Any]] = []
    for profile in db.scalars(select(CapabilityProfile).order_by(CapabilityProfile.name)):
        searchable = " ".join([profile.name, profile.description])
        overlap = [skill for skill in extracted if _contains(searchable.casefold(), skill.casefold())]
        if overlap or _contains(lowered, profile.name):
            capabilities.append({"id": profile.id, "name": profile.name, "level": profile.level, "confidence": profile.confidence, "matched_skills": overlap})

    projects: list[dict[str, Any]] = []
    evidenced: set[str] = set()
    for project in db.scalars(select(LearningProject).order_by(LearningProject.updated_at.desc(), LearningProject.id.desc())):
        searchable = " ".join([project.title, project.description, *(project.skills or []), *(project.outcomes or [])])
        overlap = [skill for skill in extracted if _contains(searchable.casefold(), skill.casefold())]
        if overlap:
            evidenced.update(overlap)
            projects.append({"id": project.id, "title": project.title, "status": project.status, "matched_skills": overlap, "outcomes": project.outcomes or []})

    gaps = [skill for skill in extracted if skill not in evidenced and not any(skill in item.get("matched_skills", []) for item in capabilities)]
    recommendations = [f"为“{skill}”补充一条可复核证据，例如练习、项目里程碑或技术说明。" for skill in gaps[:8]]
    if topics and any(item.get("verified_level", 0) < 3 for item in topics):
        recommendations.append("优先复习与岗位要求重合、但验证等级较低的知识主题。")
    if not extracted:
        recommendations.append("岗位描述未匹配到内置技能词表，请人工补充关键词后再次分析。")
    confidence = min(0.95, 0.45 + min(len(extracted), 8) * 0.06 + (0.12 if projects else 0.0))
    return {"title": title, "source_hash": hashlib.sha256(normalized.encode("utf-8")).hexdigest(), "extracted_skills": extracted, "matched_topics": topics, "matched_capabilities": capabilities, "project_evidence": projects, "gaps": gaps, "recommendations": recommendations, "confidence": round(confidence, 2)}


@router.post("/job-analyses")
def analyze_job(payload: JobAnalysisRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    title = payload.title.strip()
    description = payload.description.strip()
    analysis = _analyze(db, title, description)
    if not payload.confirmed:
        return {"requires_confirmation": True, "analysis": analysis, "warning": "分析只使用你粘贴的岗位描述和本地学习证据；确认后才会保存，不会自动把岗位要求写入能力等级。"}
    row = JobAnalysis(title=title, source_text=description, **{key: analysis[key] for key in ("source_hash", "extracted_skills", "matched_topics", "matched_capabilities", "project_evidence", "gaps", "recommendations", "confidence")})
    db.add(row)
    db.flush()
    _audit(db, "confirm", row)
    db.commit()
    db.refresh(row)
    return {"requires_confirmation": False, "analysis": _read(row), "status": "saved"}


@router.get("/job-analyses")
def list_job_analyses(limit: int = 30, db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    rows = list(db.scalars(select(JobAnalysis).order_by(JobAnalysis.created_at.desc(), JobAnalysis.id.desc()).limit(max(1, min(limit, 100)))))
    return [_read(row) for row in rows]


@router.get("/job-analyses/{analysis_id}")
def get_job_analysis(analysis_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    row = db.get(JobAnalysis, analysis_id)
    if not row:
        raise HTTPException(status_code=404, detail="岗位分析不存在")
    return _read(row)
