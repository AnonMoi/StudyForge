import asyncio
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import logging
import threading
import time
import difflib
from typing import Any
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Request, status
from contextlib import asynccontextmanager
from fastapi.exceptions import RequestValidationError

from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response, StreamingResponse
from html import escape
import re
from sqlalchemy import func, inspect as sa_inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .errors import AppError, error_payload

from .config import masked_key, settings, validate_runtime_config
from .db import SessionLocal, get_db, init_db
from . import agent_bridge
from .model_routing import router, validate_structured_data
from .scheduler import acknowledge_learning_reminder, list_learning_reminders, refresh_learning_reminders, run_learning_scheduler, scheduler_status
from . import push_notifications
from .push_notifications import list_push_subscriptions, remove_push_subscription, send_test_notification, upsert_push_subscription
from .models import AgentChangeBatch, AgentPlanProposal, AuditLog, BackupMergeBatch, BackupSnapshot, BlogDraft, CapabilityAssessment, CapabilityEvidence, CapabilityProfile, CodeRun, DailyLog, DailyLogReview, KnowledgeGraphLayout, LearningGoal, LearningProject, LearningStage, LearningReport, ModelCallLog, PracticeAttempt, PracticeExercise, ProjectMilestone, ProviderBillImport, ProviderBillSync, ReportFeedback, RestoreBatch, ReviewCard, ReviewHistory, StudyTask, TaskTimeEntry, TaskVerification, TeachingAttempt, TeachingSession, UserProfile, WeeklyPlan, utcnow
from .provider_billing import current_period, run_bill_sync
from .notes_models import KnowledgeTopic, KnowledgeTopicRelation, Note, NoteVersion
from .agent_models import ChatMessage
from .conversation_service import TurnConflictError, conversation_service
from .provider_execution import ProviderAttempt, ProviderCancellation, ProviderLifecycleEvent
from .file_import import ApplicationState, AuthorizedDirectory, FileAnalysis, FileImport, ImportedFile, WebResource, _read_imported_content, _read_web_content, recover_scan_jobs, router as file_import_router
from .practice_routes import router as practice_router
from .github_integration import GitHubCommit, GitHubRepository, router as github_router
from .job_analysis import JobAnalysis, router as job_analysis_router
from .cloud_sync import CloudSyncError, WebDavSyncProvider, cloud_sync_configured
from .native_notifications import is_native_notifications_available, send_test_native_notification
from .plugin_registry import find_command, get_plugin, install_plugin, list_plugins, normalize_manifest, remove_plugin, set_plugin_enabled
from .sync_service import create_sync_bundle, decrypt_sync_bundle
from .schemas import (
    DashboardRead,
    AgentChatRequest,
    AgentChatResponse,
    DailyLogCreate,
    DailyLogRead,
    DailyLogUpdate,
    ReviewCreate,
    ReviewScheduleRequest,
    ReviewRead,
    GoalCreate,
    GoalRead,
    GoalUpdate,
    ProjectCreate,
    ProjectRead,
    ProjectUpdate,
    ParseRequest,
    StageCreate,
    StageRead,
    StageUpdate,
    TaskCreate,
    TaskRead,
    TaskUpdate,
    TaskImpactPreviewRequest,
    TaskImpactPreviewRead,
    NoteCreate,
    NoteRead,
    NoteUpdate,
    TopicCreate,
    TopicRead,
    TopicUpdate,
    SettingsUpdate,
    SetupInitializeRequest,
    UserProfileRead,
    UserProfileUpdate,
    TopicRelationCreate,
    TopicRelationRead,
    ChatMessageRead,
    ReviewUpdate,
    BackupRestoreRequest,
    SyncBundleRequest,
    SyncExportRequest,
    PushSubscriptionCreate,
    PushSubscriptionDelete,
    PushTestRequest,
    CloudSyncRequest,
    PluginCommandRequest,
    PluginDeleteRequest,
    PluginInstallRequest,
    PluginToggleRequest,
    AgentChangeRevertRequest,
    AgentTaskRequest,
    AgentTaskResponse,
    AgentChangeRequest,
    AgentChangeResponse,
    AgentPlanProposalRequest,
    AgentPlanProposalResponse,
    GlobalSearchResponse,
    SearchResultItem,
    NoteVersionRead,
    BlogDraftGenerateRequest,
    BlogDraftRead,
    ReviewCardAnswer,
    ReviewCardBulkAction,
    ReviewCardCreate,
    ReviewCardRead,
    ReviewCardUpdate,
    ReviewHistoryRead,
    ReviewStatsRead,
    WeeklyPlanCreate,
    WeeklyPlanRead,
    WeeklyPlanUpdate,
    ReportGenerateRequest,
    ReportFeedbackCreate,
    ReportFeedbackRead,
    ReportRead,
    GraphLayoutUpdate,
    REPORT_TYPES,
    NoteVersionDiff,
    NoteVersionRestoreRequest,
    NoteAgentAnalyzeRequest,
    TeachingAttemptCreate,
    TeachingAnswerRequest,
    TeachingAttemptRead,
    TeachingSessionCreate,
    TeachingSessionRead,
    TeachingGenerateRequest,
    TASK_STATUSES,
    TaskVerificationCreate,
    TaskVerificationRead,
    TopicVerificationCreate,
    TaskTimeEntryRead,
    TaskTimerRead,
    CapabilityAssessmentRead,
    CodeRunCreate,
    CodeRunRead,
    PracticeAttemptCreate,
    PracticeAttemptRead,
    PracticeExerciseCreate,
    PracticeExerciseRead,
    ProjectMilestoneCreate,
    ProjectMilestoneRead,
    ProjectMilestoneUpdate,
)

logger = logging.getLogger("learning_workstation.api")
if not logger.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
    )


LEARNING_SCHEDULER_STOP = threading.Event()
LEARNING_SCHEDULER_THREAD: threading.Thread | None = None


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global LEARNING_SCHEDULER_THREAD
    runtime_config = validate_runtime_config(settings)
    if settings.app_env in {"staging", "production"} and not runtime_config["valid"]:
        raise RuntimeError(f"运行配置校验失败：{'；'.join(runtime_config['errors'])}")
    init_db()
    recover_scan_jobs()
    with SessionLocal() as db:
        state = db.get(ApplicationState, "model_settings")
        if state:
            for key, value in (state.value or {}).items():
                if key in SettingsUpdate.model_fields:
                    setattr(settings, key, value)
            router.refresh_adapters()
    LEARNING_SCHEDULER_STOP.clear()
    LEARNING_SCHEDULER_THREAD = threading.Thread(
        target=run_learning_scheduler,
        args=(LEARNING_SCHEDULER_STOP, settings.learning_scheduler_interval_seconds),
        name="learning-reminder-scheduler",
        daemon=True,
    )
    LEARNING_SCHEDULER_THREAD.start()
    logger.info(json.dumps({"event": "application_started", "service": "learning-workstation"}, ensure_ascii=False))
    try:
        yield
    finally:
        LEARNING_SCHEDULER_STOP.set()
        if LEARNING_SCHEDULER_THREAD:
            LEARNING_SCHEDULER_THREAD.join(timeout=2)
        logger.info(json.dumps({"event": "application_stopped", "service": "learning-workstation"}, ensure_ascii=False))


app = FastAPI(title="Learning Workstation API", version="0.1.0", lifespan=lifespan)
app.include_router(file_import_router, prefix="/api")
app.include_router(practice_router, prefix="/api")
app.include_router(github_router, prefix="/api")
app.include_router(job_analysis_router, prefix="/api")
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)


@app.middleware("http")
async def request_context_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID", "").strip()[:120] or uuid4().hex
    request.state.request_id = request_id
    started = time.perf_counter()
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            too_large = int(content_length) > settings.max_request_body_bytes
        except ValueError:
            too_large = False
        if too_large:
            response = JSONResponse(
                status_code=413,
                content=error_payload(code="PAYLOAD_TOO_LARGE", message="请求体超过本地服务允许的大小", status_code=413, request_id=request_id),
                headers={"X-Request-ID": request_id},
            )
            return response
    try:
        response = await call_next(request)
    except Exception:
        logger.exception(json.dumps({
            "event": "request_failed",
            "method": request.method,
            "path": request.url.path,
            "request_id": request_id,
        }, ensure_ascii=False))
        raise
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    logger.info(json.dumps({
        "event": "request_completed",
        "method": request.method,
        "path": request.url.path,
        "status": response.status_code,
        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        "request_id": request_id,
    }, ensure_ascii=False))
    return response


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    request_id = getattr(request.state, "request_id", "") or request.headers.get("X-Request-ID", "") or uuid4().hex
    return JSONResponse(
        status_code=exc.status_code,
        content=error_payload(code=exc.code, message=exc.message, status_code=exc.status_code, request_id=request_id, fields=exc.fields),
        headers={"X-Request-ID": request_id},
    )


@app.exception_handler(StarletteHTTPException)
async def http_error_handler(request: Request, exc: StarletteHTTPException):
    request_id = getattr(request.state, "request_id", "") or request.headers.get("X-Request-ID", "") or uuid4().hex
    detail = exc.detail if isinstance(exc.detail, str) else "请求失败"
    code = {400: "BAD_REQUEST", 401: "UNAUTHORIZED", 403: "FORBIDDEN", 404: "NOT_FOUND", 409: "CONFLICT", 413: "PAYLOAD_TOO_LARGE", 422: "VALIDATION_ERROR"}.get(exc.status_code, "HTTP_ERROR")
    return JSONResponse(status_code=exc.status_code, content=error_payload(code=code, message=detail, status_code=exc.status_code, request_id=request_id), headers={"X-Request-ID": request_id})


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    request_id = getattr(request.state, "request_id", "") or request.headers.get("X-Request-ID", "") or uuid4().hex
    fields = [{"loc": list(item.get("loc", [])), "message": str(item.get("msg", "输入无效")), "type": item.get("type", "validation_error")} for item in exc.errors()]
    return JSONResponse(status_code=422, content=error_payload(code="VALIDATION_ERROR", message="请求参数校验失败", status_code=422, request_id=request_id, fields=fields), headers={"X-Request-ID": request_id})


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception):
    request_id = getattr(request.state, "request_id", "") or request.headers.get("X-Request-ID", "") or uuid4().hex
    logger.exception(json.dumps({"event": "unhandled_exception", "path": request.url.path, "request_id": request_id}, ensure_ascii=False))
    return JSONResponse(status_code=500, content=error_payload(code="INTERNAL_ERROR", message="服务内部错误，请稍后重试", status_code=500, request_id=request_id), headers={"X-Request-ID": request_id})


def _audit(db: Session, entity_type: str, entity_id: int | None, action: str, before: dict[str, Any] | None, after: dict[str, Any] | None) -> None:
    safe_before = json.loads(json.dumps(before, ensure_ascii=False, default=str)) if before is not None else None
    safe_after = json.loads(json.dumps(after, ensure_ascii=False, default=str)) if after is not None else None
    db.add(AuditLog(entity_type=entity_type, entity_id=entity_id, action=action, before_data=safe_before, after_data=safe_after))
    db.commit()


def _create_agent_batch(
    db: Session,
    operation: str,
    entries: list[dict[str, Any]],
    changes: dict[str, Any] | None = None,
) -> AgentChangeBatch:
    batch = AgentChangeBatch(
        operation=operation,
        status="executed",
        changes=[changes or {}],
        before_data=[
            {"entity_type": entry["entity_type"], "entity_id": entry["entity_id"], "data": entry.get("before")}
            for entry in entries
        ],
        after_data=[
            {"entity_type": entry["entity_type"], "entity_id": entry["entity_id"], "data": entry.get("after"), "created": bool(entry.get("created"))}
            for entry in entries
        ],
    )
    db.add(batch)
    db.commit()
    db.refresh(batch)
    return batch


@app.get("/api/audits")
def list_audits(limit: int = 100, entity_type: str | None = None, db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    query = select(AuditLog)
    if entity_type:
        query = query.where(AuditLog.entity_type == entity_type)
    rows = list(db.scalars(query.order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(max(1, min(limit, 500)))))
    return [{"id": row.id, "entity_type": row.entity_type, "entity_id": row.entity_id, "action": row.action, "before_data": row.before_data, "after_data": row.after_data, "created_at": row.created_at} for row in rows]
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    # Development previews often use an ephemeral Vite port. Keep this regex
    # limited to loopback origins and never enable it for staging/production.
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$" if settings.app_env == "development" else None,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "learning-workstation", "version": "0.1.0"}


@app.get("/api/ready")
def readiness(db: Session = Depends(get_db)) -> dict[str, Any]:
    runtime_config = validate_runtime_config(settings)
    try:
        db.execute(select(1))
        if settings.app_env in {"staging", "production"} and not runtime_config["valid"]:
            return JSONResponse(status_code=503, content={"status": "not_ready", "checks": {"database": "ok", "migrations": "ok", "configuration": "error"}, "configuration": runtime_config})
        return {"status": "ready", "checks": {"database": "ok", "migrations": "ok", "configuration": "ok"}, "configuration": runtime_config}
    except Exception as exc:
        logger.exception("readiness check failed")
        return JSONResponse(status_code=503, content={"status": "not_ready", "checks": {"database": "error", "migrations": "unknown"}, "error": str(exc)[:160]})


@app.get("/api/runtime/status")
def runtime_status() -> dict[str, Any]:
    """Expose process-local worker state without leaking configuration secrets."""
    thread = LEARNING_SCHEDULER_THREAD
    scheduler = scheduler_status()
    return {
        "scheduler": {
            **scheduler,
            "thread_alive": bool(thread and thread.is_alive()),
            "interval_seconds": settings.learning_scheduler_interval_seconds,
        },
        "api_workers": settings.api_workers,
    }


@app.get("/api/config/validate")
def validate_config() -> dict[str, Any]:
    return validate_runtime_config(settings)


@app.get("/api/models/health")
def model_health() -> dict[str, Any]:
    return router.model_health()


@app.get("/api/models/calls")
def model_calls(limit: int = 50, db: Session = Depends(get_db)) -> dict[str, Any]:
    rows = list(db.scalars(select(ModelCallLog).order_by(ModelCallLog.created_at.desc(), ModelCallLog.id.desc()).limit(max(1, min(limit, 200)))))
    return {"total": len(rows), "calls": [{"id": row.id, "task_type": row.task_type, "risk_level": row.risk_level, "provider": row.provider, "model_name": row.model_name, "upgraded": row.upgraded, "input_length": row.input_length, "output_length": row.output_length, "input_tokens": row.input_tokens, "output_tokens": row.output_tokens, "total_tokens": row.total_tokens, "duration_ms": row.duration_ms, "estimated_cost": row.estimated_cost, "billing_source": row.billing_source, "success": row.success, "confidence": row.confidence, "route_reason": row.route_reason, "retry_count": row.retry_count, "fallback_used": row.fallback_used, "token_source": row.token_source, "created_at": row.created_at} for row in rows]}


@app.get("/api/models/budget")
def model_budget(db: Session = Depends(get_db)) -> dict[str, Any]:
    calls_used = db.scalar(select(func.count(ModelCallLog.id)).where(ModelCallLog.provider == "zhiapi", func.date(ModelCallLog.created_at) == func.current_date())) or 0
    cost_used = db.scalar(select(func.coalesce(func.sum(ModelCallLog.estimated_cost), 0.0)).where(ModelCallLog.provider == "zhiapi", func.date(ModelCallLog.created_at) == func.current_date())) or 0.0
    token_used = db.scalar(select(func.coalesce(func.sum(ModelCallLog.total_tokens), 0)).where(ModelCallLog.provider == "zhiapi", func.date(ModelCallLog.created_at) == func.current_date())) or 0
    return {"daily_call_limit": settings.daily_cloud_call_limit, "calls_used": int(calls_used), "remaining_calls": max(0, settings.daily_cloud_call_limit - int(calls_used)), "cost_limit": settings.daily_cost_limit, "cost_used": float(cost_used), "remaining_cost": max(0.0, settings.daily_cost_limit - float(cost_used)), "tokens_used": int(token_used), "input_price_per_1k": settings.cloud_input_price_per_1k, "output_price_per_1k": settings.cloud_output_price_per_1k}


def _parse_bill_line(item: dict[str, Any], index: int) -> dict[str, Any]:
    provider = str(item.get("provider") or "").strip()
    amount = float(item.get("amount") or item.get("cost") or 0)
    call_id = item.get("call_id")
    if not provider or amount < 0:
        raise HTTPException(status_code=422, detail=f"账单第 {index} 行缺少 provider 或金额无效")
    return {"line": index, "provider": provider, "amount": round(amount, 6), "currency": str(item.get("currency") or "CNY"), "call_id": int(call_id) if call_id is not None and str(call_id).isdigit() else None, "model_name": str(item.get("model_name") or ""), "occurred_at": str(item.get("occurred_at") or "")}


@app.post("/api/models/bills/import")
def import_provider_bill(payload: dict[str, Any], db: Session = Depends(get_db)) -> dict[str, Any]:
    provider = str(payload.get("provider") or "").strip()
    raw_lines = payload.get("lines")
    if not provider or not isinstance(raw_lines, list) or not raw_lines:
        raise HTTPException(status_code=422, detail="需要 provider 和非空 lines 账单明细")
    lines = [_parse_bill_line({"provider": provider, **item}, index) for index, item in enumerate(raw_lines, start=1) if isinstance(item, dict)]
    if len(lines) != len(raw_lines):
        raise HTTPException(status_code=422, detail="账单明细必须全部为对象")
    calls = {row.id: row for row in db.scalars(select(ModelCallLog).where(ModelCallLog.provider == provider))}
    matched_amount = 0.0
    matched_count = 0
    for line in lines:
        matched = calls.get(line["call_id"]) if line["call_id"] is not None else None
        if matched and (not line["model_name"] or line["model_name"] == matched.model_name):
            line["matched_call_id"] = matched.id
            matched_amount += line["amount"]
            matched_count += 1
        else:
            line["matched_call_id"] = None
    total = round(sum(line["amount"] for line in lines), 6)
    record = ProviderBillImport(provider=provider, period_start=payload.get("period_start"), period_end=payload.get("period_end"), source_name=str(payload.get("source_name") or "manual"), currency=str(payload.get("currency") or "CNY"), total_amount=total, matched_amount=round(matched_amount, 6), unmatched_amount=round(total - matched_amount, 6), line_count=len(lines), matched_count=matched_count, unmatched_count=len(lines) - matched_count, lines=lines)
    db.add(record)
    db.commit()
    db.refresh(record)
    return {"id": record.id, "provider": provider, "total_amount": record.total_amount, "matched_amount": record.matched_amount, "unmatched_amount": record.unmatched_amount, "line_count": record.line_count, "matched_count": record.matched_count, "unmatched_count": record.unmatched_count, "currency": record.currency, "source_name": record.source_name}


@app.get("/api/models/bills")
def list_provider_bills(limit: int = 20, db: Session = Depends(get_db)) -> dict[str, Any]:
    rows = list(db.scalars(select(ProviderBillImport).order_by(ProviderBillImport.created_at.desc(), ProviderBillImport.id.desc()).limit(max(1, min(limit, 100)))))
    return {"total": len(rows), "bills": [{"id": row.id, "provider": row.provider, "period_start": row.period_start, "period_end": row.period_end, "source_name": row.source_name, "currency": row.currency, "total_amount": row.total_amount, "matched_amount": row.matched_amount, "unmatched_amount": row.unmatched_amount, "line_count": row.line_count, "matched_count": row.matched_count, "unmatched_count": row.unmatched_count, "created_at": row.created_at} for row in rows]}


@app.get("/api/models/bills/syncs")
def list_provider_bill_syncs(limit: int = 20, db: Session = Depends(get_db)) -> dict[str, Any]:
    rows = list(db.scalars(select(ProviderBillSync).order_by(ProviderBillSync.created_at.desc(), ProviderBillSync.id.desc()).limit(max(1, min(limit, 100)))))
    return {"total": len(rows), "syncs": [{"id": row.id, "provider": row.provider, "period_start": row.period_start, "period_end": row.period_end, "status": row.status, "attempts": row.attempts, "max_attempts": row.max_attempts, "source_name": row.source_name, "line_count": row.line_count, "bill_import_id": row.bill_import_id, "error": row.error, "started_at": row.started_at, "last_attempt_at": row.last_attempt_at, "completed_at": row.completed_at, "created_at": row.created_at} for row in rows]}


@app.post("/api/models/bills/sync")
def sync_provider_bill(payload: dict[str, Any] | None = None, db: Session = Depends(get_db)) -> dict[str, Any]:
    payload = payload or {}
    default_start, default_end = current_period()
    try:
        period_start = date.fromisoformat(str(payload.get("period_start") or default_start))
        period_end = date.fromisoformat(str(payload.get("period_end") or default_end))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="账单周期必须是 YYYY-MM-DD") from exc
    if period_start > period_end:
        raise HTTPException(status_code=422, detail="账单周期起始日期不能晚于结束日期")
    sync = run_bill_sync(db, period_start, period_end)
    return {"id": sync.id, "provider": sync.provider, "period_start": sync.period_start, "period_end": sync.period_end, "status": sync.status, "attempts": sync.attempts, "max_attempts": sync.max_attempts, "source_name": sync.source_name, "line_count": sync.line_count, "bill_import_id": sync.bill_import_id, "error": sync.error, "started_at": sync.started_at, "last_attempt_at": sync.last_attempt_at, "completed_at": sync.completed_at, "created_at": sync.created_at}


@app.get("/api/setup/status")
def setup_status(db: Session = Depends(get_db)) -> dict[str, Any]:
    state = db.get(ApplicationState, "onboarding")
    state_value = state.value if state else {}
    profile = db.get(UserProfile, 1)
    profile_confirmed = bool(profile and profile.profile_confirmed)
    completed = bool(state_value.get("completed"))
    directory_count = int(db.scalar(select(func.count(AuthorizedDirectory.id)).where(AuthorizedDirectory.active.is_(True))) or 0)
    return {"completed": completed, "requires_onboarding": not completed, "profile_confirmed": profile_confirmed, "first_plan_generated": bool(state_value.get("first_plan_generated")), "authorized_directory_count": directory_count, "privacy": {"local_data_default": True, "cloud_transfer_requires_permission": True, "directory_access_requires_explicit_authorization": True}}


def _profile_preview(payload: UserProfileUpdate) -> dict[str, Any]:
    return {**payload.model_dump(mode="json"), "profile_confirmed": True}


def _initial_plan_preview(profile: UserProfileUpdate) -> dict[str, Any]:
    goal_title = profile.long_term_goal.strip() or "建立可迁移的计算机基础"
    capability_targets = list(dict.fromkeys(profile.weak_capabilities or profile.unverified_skills or ["计算机基础"]))[:12]
    return {
        "goal_title": goal_title,
        "goal_description": f"基于用户画像建立长期学习主线：{goal_title}",
        "stage_title": "基础能力诊断与共同底座",
        "capability_targets": capability_targets,
        "task_title": "完成首次学习基线诊断",
        "task_description": "用一次解释、一个最小练习或一份可复核输出，确认当前基础能力并记录证据。",
        "acceptance_criteria": "提交一份可复核的解释、练习结果或项目证据，并记录仍需补强的知识点。",
    }


@app.get("/api/user-profile", response_model=UserProfileRead)
def get_user_profile(db: Session = Depends(get_db)) -> UserProfile:
    profile = db.get(UserProfile, 1)
    if profile is None:
        profile = UserProfile(id=1)
        db.add(profile)
        db.commit()
        db.refresh(profile)
    return profile


@app.put("/api/user-profile", response_model=UserProfileRead)
def update_user_profile(payload: UserProfileUpdate, db: Session = Depends(get_db)) -> UserProfile:
    profile = db.get(UserProfile, 1)
    if profile is None:
        profile = UserProfile(id=1)
        db.add(profile)
        db.flush()
    before = UserProfileRead.model_validate(profile).model_dump(mode="json")
    for field, value in payload.model_dump().items():
        setattr(profile, field, value)
    profile.profile_confirmed = True
    db.commit()
    db.refresh(profile)
    _audit(db, "user_profile", profile.id, "update", before, UserProfileRead.model_validate(profile).model_dump(mode="json"))
    return profile


@app.post("/api/setup/initialize")
def initialize_setup(payload: SetupInitializeRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    profile_preview = _profile_preview(payload.profile)
    plan_preview = _initial_plan_preview(payload.profile)
    if not payload.confirmed:
        return {"executed": False, "requires_confirmation": True, "profile_preview": profile_preview, "plan_preview": plan_preview}

    profile = db.get(UserProfile, 1)
    if profile is None:
        profile = UserProfile(id=1)
        db.add(profile)
    for field, value in payload.profile.model_dump().items():
        setattr(profile, field, value)
    profile.profile_confirmed = True
    created_goal_id = created_stage_id = created_task_id = None
    if payload.create_initial_plan:
        goal = db.scalar(select(LearningGoal).where(LearningGoal.title == plan_preview["goal_title"]).order_by(LearningGoal.id))
        if goal is None:
            goal = LearningGoal(title=plan_preview["goal_title"], description=plan_preview["goal_description"], priority=1, status="active")
            db.add(goal)
            db.flush()
            created_goal_id = goal.id
        stage = db.scalar(select(LearningStage).where(LearningStage.goal_id == goal.id, LearningStage.title == plan_preview["stage_title"]).order_by(LearningStage.id))
        if stage is None:
            stage = LearningStage(goal_id=goal.id, title=plan_preview["stage_title"], capability_targets=plan_preview["capability_targets"], prerequisites=[], order_index=0, status="active")
            db.add(stage)
            db.flush()
            created_stage_id = stage.id
        task = db.scalar(select(StudyTask).where(StudyTask.source == "onboarding", StudyTask.stage_id == stage.id).order_by(StudyTask.id))
        if task is None:
            task = StudyTask(title=plan_preview["task_title"], description=plan_preview["task_description"], stage_id=stage.id, priority=1, estimated_minutes=45, due_date=date.today(), status="not_started", acceptance_criteria=plan_preview["acceptance_criteria"], source="onboarding", task_type="diagnostic", expected_outcome="形成首次能力基线和下一步学习证据")
            db.add(task)
            db.flush()
            created_task_id = task.id

    state = db.get(ApplicationState, "onboarding")
    if state is None:
        state = ApplicationState(key="onboarding", value={})
        db.add(state)
    state.value = {**(state.value or {}), "completed": True, "profile_confirmed": True, "first_plan_generated": bool(payload.create_initial_plan), "completed_at": utcnow().isoformat()}
    db.commit()
    return {"executed": True, "requires_confirmation": False, "profile": UserProfileRead.model_validate(profile).model_dump(mode="json"), "created_goal_id": created_goal_id, "created_stage_id": created_stage_id, "created_task_id": created_task_id, "first_plan_generated": bool(payload.create_initial_plan), "setup": setup_status(db)}


@app.post("/api/setup/complete")
def complete_setup(db: Session = Depends(get_db)) -> dict[str, Any]:
    state = db.get(ApplicationState, "onboarding")
    if state is None:
        state = ApplicationState(key="onboarding", value={})
        db.add(state)
    state.value = {**(state.value or {}), "completed": True, "completed_at": utcnow().isoformat()}
    db.commit()
    return setup_status(db)


def _settings_payload() -> dict[str, Any]:
    return {
        "local_model": settings.local_model_name,
        "cloud_model": settings.cloud_model_name,
        "cloud_enabled": settings.cloud_model_enabled,
        "cloud_key_configured": bool(settings.cloud_model_api_key),
        "cloud_key_masked": masked_key(settings.cloud_model_api_key),
        "model_routing_mode": settings.model_routing_mode,
        "daily_cloud_call_limit": settings.daily_cloud_call_limit,
        "daily_cost_limit": settings.daily_cost_limit,
        "max_tokens_per_request": settings.max_tokens_per_request,
        "local_confidence_threshold": settings.local_confidence_threshold,
        "cloud_input_price_per_1k": settings.cloud_input_price_per_1k,
        "cloud_output_price_per_1k": settings.cloud_output_price_per_1k,
        "report_model_enhancement_enabled": settings.report_model_enhancement_enabled,
        "github_enabled": settings.github_enabled,
        "github_token_configured": bool(settings.github_token),
        "github_api_base_url": settings.github_api_base_url,
        "web_push_enabled": bool(settings.web_push_enabled and settings.web_push_vapid_public_key and settings.web_push_vapid_private_key),
        "web_push_public_key": settings.web_push_vapid_public_key if settings.web_push_enabled else "",
        "native_notifications_enabled": bool(settings.native_notifications_enabled),
        "native_notifications_available": is_native_notifications_available(),
        "cloud_sync_enabled": cloud_sync_configured(),
        "cloud_sync_provider": settings.cloud_sync_provider,
    }


@app.get("/api/settings")
def get_settings(db: Session = Depends(get_db)) -> dict[str, Any]:
    state = db.get(ApplicationState, "model_settings")
    return {**_settings_payload(), "persisted_at": state.updated_at if state else None}


@app.put("/api/settings")
def update_settings(payload: SettingsUpdate, db: Session = Depends(get_db)) -> dict[str, Any]:
    allowed = set(SettingsUpdate.model_fields)
    values = {key: value for key, value in payload.model_dump(exclude_unset=True).items() if key in allowed}
    if not values:
        return _settings_payload()
    if values.get("native_notifications_enabled") and not is_native_notifications_available():
        raise HTTPException(status_code=409, detail="当前系统不支持 Windows 原生通知或 PowerShell 不可用")
    before = _settings_payload()
    for key, value in values.items():
        setattr(settings, key, value)
    router.refresh_adapters()
    state = db.get(ApplicationState, "model_settings")
    if state is None:
        state = ApplicationState(key="model_settings", value={})
        db.add(state)
    state.value = {key: getattr(settings, key) for key in allowed}
    db.commit()
    after = _settings_payload()
    _audit(db, "application_settings", 0, "update", before, after)
    return {**after, "warning": "云端模型只有在 API 密钥已配置时才会实际可用" if settings.cloud_model_enabled and not settings.cloud_model_api_key else None}


@app.get("/api/settings/public")
def public_settings() -> dict[str, Any]:
    return _settings_payload()


@app.get("/api/push/config")
def push_config(db: Session = Depends(get_db)) -> dict[str, Any]:
    configured = bool(push_notifications.PUSH_DEPENDENCY_AVAILABLE and settings.web_push_enabled and settings.web_push_vapid_public_key and settings.web_push_vapid_private_key)
    return {"enabled": configured, "dependency_available": push_notifications.PUSH_DEPENDENCY_AVAILABLE, "public_key": settings.web_push_vapid_public_key if configured else "", "subscription_count": len(list_push_subscriptions(db))}


@app.post("/api/push/subscriptions")
def register_push_subscription(payload: PushSubscriptionCreate, db: Session = Depends(get_db)) -> dict[str, Any]:
    if not (settings.web_push_enabled and settings.web_push_vapid_public_key and settings.web_push_vapid_private_key):
        raise HTTPException(status_code=409, detail="后台推送未配置，请先在后端配置 VAPID 密钥")
    try:
        item = upsert_push_subscription(db, payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"registered": True, "subscription_id": item["id"], "subscription_count": len(list_push_subscriptions(db))}


@app.delete("/api/push/subscriptions")
def unregister_push_subscription(payload: PushSubscriptionDelete, db: Session = Depends(get_db)) -> dict[str, Any]:
    return {"removed": remove_push_subscription(db, payload.endpoint), "subscription_count": len(list_push_subscriptions(db))}


@app.post("/api/push/test")
def test_push_notifications(payload: PushTestRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    configured = bool(push_notifications.PUSH_DEPENDENCY_AVAILABLE and settings.web_push_enabled and settings.web_push_vapid_public_key and settings.web_push_vapid_private_key)
    if not payload.confirmed:
        return {"requires_confirmation": True, "enabled": configured, "subscription_count": len(list_push_subscriptions(db))}
    if not configured:
        raise HTTPException(status_code=409, detail="后台推送未配置，请先在后端配置 VAPID 密钥")
    return {"requires_confirmation": False, **send_test_notification(db)}


@app.get("/api/native-notifications/status")
def native_notifications_status() -> dict[str, Any]:
    available = is_native_notifications_available()
    return {
        "enabled": bool(settings.native_notifications_enabled),
        "available": available,
        "configured": bool(settings.native_notifications_enabled and available),
        "warning": None if available else "当前系统不支持 Windows 原生通知或 PowerShell 不可用",
    }


@app.post("/api/native-notifications/test")
def test_native_notifications(payload: PushTestRequest) -> dict[str, Any]:
    available = is_native_notifications_available()
    if not payload.confirmed:
        return {"requires_confirmation": True, "enabled": bool(settings.native_notifications_enabled), "available": available}
    if not settings.native_notifications_enabled:
        raise HTTPException(status_code=409, detail="Windows 原生通知未启用")
    if not available:
        raise HTTPException(status_code=409, detail="当前系统不支持 Windows 原生通知或 PowerShell 不可用")
    return {"requires_confirmation": False, **send_test_native_notification()}


def _agent_context(db: Session) -> dict[str, Any]:
    return {
        "goals": [GoalRead.model_validate(item).model_dump(mode="json") for item in db.scalars(select(LearningGoal))],
        "stages": [StageRead.model_validate(item).model_dump(mode="json") for item in db.scalars(select(LearningStage))],
        "tasks": [TaskRead.model_validate(item).model_dump(mode="json") for item in db.scalars(select(StudyTask))],
        "daily_logs": [DailyLogRead.model_validate(item).model_dump(mode="json") for item in db.scalars(select(DailyLog).order_by(DailyLog.log_date.desc()).limit(20))],
        "notes": [NoteRead.model_validate(item).model_dump(mode="json") for item in db.scalars(select(Note).order_by(Note.updated_at.desc()).limit(20))],
        "knowledge_topics": [TopicRead.model_validate(item).model_dump(mode="json") for item in db.scalars(select(KnowledgeTopic).order_by(KnowledgeTopic.name))],
    }


@app.get("/api/agent/context")
def agent_context(db: Session = Depends(get_db)) -> dict[str, Any]:
    return _agent_context(db)


def _conversation_snapshot(db: Session, session_id: str) -> str:
    messages = conversation_service.completed_context_messages(db, session_id=session_id)
    return agent_bridge.build_conversation_context([{"role": item.role, "content": item.content} for item in messages])


def _turn_conflict(exc: TurnConflictError, turn_id: str) -> AppError:
    return AppError(message=str(exc), code=exc.code, status_code=409, fields=[{"request_id": turn_id, "turn_id": turn_id}])


def _sse_event(event: str, turn_id: str, **payload: Any) -> str:
    data = {"request_id": turn_id, "turn_id": turn_id, **payload}
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _attempt_payload(attempt: ProviderAttempt) -> dict[str, Any]:
    return {
        "attempt_id": attempt.attempt_id,
        "provider": attempt.provider,
        "model_name": attempt.model_name,
        "stage": attempt.stage,
        "attempt_status": attempt.status,
        "failure_kind": attempt.failure_kind,
        "route_reason": attempt.route_reason,
        "started_at": attempt.started_at.isoformat(),
        "finished_at": attempt.finished_at.isoformat() if attempt.finished_at else None,
        "deadline_at": attempt.deadline_at.isoformat() if attempt.deadline_at else None,
        "elapsed_ms": attempt.elapsed_ms,
    }


def _agent_output_metadata(message: str, response: str) -> dict[str, Any]:
    if re.search(r"(创建|修改|删除|批量|调整|写入|导入|生成任务|转为任务)", message):
        output_type = "operation"
    elif re.search(r"(什么|为什么|怎么|如何|解释|区别|原理|吗[？?]?$|[？?]$)", message.strip()):
        output_type = "explain"
    else:
        output_type = "suggestion"
    title = next((line.strip(" -*#") for line in response.splitlines() if line.strip()), "学习教练结论")[:120]
    actions = [
        {"operation": "create_note", "label": "保存为笔记草稿", "payload": {"title": title, "content": response, "summary": "来自 AI 教练的待确认结论"}},
        {"operation": "create_task", "label": "转为学习任务", "payload": {"title": title, "description": response, "expected_outcome": "完成后提交可复核证据"}},
        {"operation": "create_topic", "label": "保存为知识点", "payload": {"name": title[:80], "definition": response}},
    ]
    return {
        "output_type": output_type,
        "basis": ["用户问题", "当前学习上下文摘要"],
        "uncertainty": "这是基于当前上下文生成的回答或建议，不是用户已确认事实；转换前请检查内容和影响。",
        "actions": actions,
    }


@app.get("/api/agent/history/{session_id}", response_model=list[ChatMessageRead])
def agent_history(session_id: str, db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    return [
        {
            "id": message.id,
            "session_id": message.session_id,
            "turn_id": message.turn_id,
            "request_id": message.turn_id,
            "persona": message.persona,
            "role": message.role,
            "status": message.status,
            "turn_status": turn.status if turn else None,
            "provider": turn.provider if turn else None,
            "model_name": turn.model_name if turn else None,
            "route_reason": turn.route_reason if turn else None,
            "failure_kind": turn.failure_kind if turn else None,
            "content": message.content,
            "created_at": message.created_at,
        }
        for message, turn in conversation_service.history_messages(db, session_id=session_id)
    ]


@app.post("/api/agent/chat", response_model=AgentChatResponse)
def agent_chat(payload: AgentChatRequest, db: Session = Depends(get_db)) -> AgentChatResponse:
    turn_id = payload.request_id or uuid4().hex
    try:
        begun = conversation_service.begin_turn(db, request_id=turn_id, session_id=payload.session_id, persona=payload.persona, message=payload.message)
    except TurnConflictError as exc:
        raise _turn_conflict(exc, turn_id) from exc
    if not begun.owns_execution:
        response = begun.assistant_content or ""
        return AgentChatResponse(success=True, response=response, session_id=payload.session_id, request_id=turn_id, turn_id=turn_id, provider=begun.turn.provider or "existing-turn", model_name=begun.turn.model_name or "persisted", route_reason=begun.turn.route_reason or "idempotent_replay", **_agent_output_metadata(payload.message, response))
    result = None
    try:
        conversation = _conversation_snapshot(db, payload.session_id)
        minimized = agent_bridge.build_minimized_context(_agent_context(db))
        result = agent_bridge.run_study_coach(payload.message, context=minimized, persona=payload.persona, conversation=conversation)
        response = (result.text or "").strip()
        if not result.success or not response:
            raise RuntimeError((result.error or "学习教练返回了空响应")[-1000:])
        conversation_service.complete_turn(db, turn_id=turn_id, response=response, provider=result.provider, model_name=result.model_name, route_reason=result.route_reason)
        return AgentChatResponse(success=True, response=response, session_id=payload.session_id, request_id=turn_id, turn_id=turn_id, provider=result.provider, model_name=result.model_name, route_reason=result.route_reason, **_agent_output_metadata(payload.message, response))
    except Exception as exc:
        conversation_service.fail_turn(db, turn_id=turn_id, provider=result.provider if result else "router", model_name=result.model_name if result else "unknown", route_reason=result.route_reason if result else "failure", failure_kind=result.failure_kind if result else "provider_error")
        return AgentChatResponse(success=False, error=str(exc), session_id=payload.session_id, request_id=turn_id, turn_id=turn_id, provider=result.provider if result else "router", model_name=result.model_name if result else "unknown", route_reason=result.route_reason if result else "failure")


@app.post("/api/agent/chat/stream")
async def agent_chat_stream(payload: AgentChatRequest, request: Request, db: Session = Depends(get_db)) -> StreamingResponse:
    turn_id = payload.request_id or uuid4().hex
    try:
        begun = conversation_service.begin_turn(db, request_id=turn_id, session_id=payload.session_id, persona=payload.persona, message=payload.message)
    except TurnConflictError as exc:
        raise _turn_conflict(exc, turn_id) from exc
    if not begun.owns_execution:
        replay = begun.assistant_content or ""

        async def replay_events():
            yield _sse_event("accepted", turn_id, session_id=payload.session_id, persona=payload.persona, replayed=True)
            metadata = _agent_output_metadata(payload.message, replay)
            metadata.update({"provider": begun.turn.provider or "existing-turn", "model_name": begun.turn.model_name or "persisted", "route_reason": begun.turn.route_reason or "idempotent_replay", "replay_reason": "idempotent_replay"})
            yield _sse_event("meta", turn_id, **metadata)
            yield _sse_event("token", turn_id, chunk=replay)
            yield _sse_event("completed", turn_id, session_id=payload.session_id, status="completed", replayed=True)
            yield _sse_event("done", turn_id, session_id=payload.session_id, status="completed", replayed=True)

        return StreamingResponse(replay_events(), media_type="text/event-stream")
    try:
        conversation = _conversation_snapshot(db, payload.session_id)
        minimized = agent_bridge.build_minimized_context(_agent_context(db))
    except Exception as exc:
        conversation_service.fail_turn(db, turn_id=turn_id)
        setup_error = f"调用失败：{exc}"
    else:
        setup_error = None

    async def events():
        if setup_error:
            yield _sse_event("accepted", turn_id, session_id=payload.session_id, persona=payload.persona)
            yield _sse_event("failed", turn_id, code="TURN_SETUP_FAILED", message="杏菜暂时没能接住这条消息，请稍后再试。", status="failed", failure_kind="provider_error", route_reason="turn_setup_failed")
            yield _sse_event("error", turn_id, code="TURN_SETUP_FAILED", message="杏菜暂时没能接住这条消息，请稍后再试。")
            yield _sse_event("done", turn_id, session_id=payload.session_id, status="failed")
            return
        cancellation = ProviderCancellation()
        lifecycle_events: asyncio.Queue[ProviderLifecycleEvent] = asyncio.Queue()

        def observe(event: ProviderLifecycleEvent) -> None:
            lifecycle_events.put_nowait(event)

        execution = asyncio.create_task(agent_bridge.execute_study_coach(
            payload.message,
            turn_id=turn_id,
            context=minimized,
            persona=payload.persona,
            conversation=conversation,
            cancellation=cancellation,
            on_event=observe,
        ))
        yield _sse_event("accepted", turn_id, session_id=payload.session_id, persona=payload.persona)
        try:
            while not execution.done():
                while not lifecycle_events.empty():
                    lifecycle = lifecycle_events.get_nowait()
                    logger.info(json.dumps({"event": "provider_attempt", "request_id": turn_id, "turn_id": turn_id, "persona": payload.persona, **_attempt_payload(lifecycle.attempt)}, ensure_ascii=False))
                    yield _sse_event(lifecycle.event, turn_id, **_attempt_payload(lifecycle.attempt))
                if await request.is_disconnected():
                    cancellation.cancel()
                    await execution
                    conversation_service.cancel_turn(db, turn_id=turn_id)
                    return
                await asyncio.sleep(0.02)
            while not lifecycle_events.empty():
                lifecycle = lifecycle_events.get_nowait()
                logger.info(json.dumps({"event": "provider_attempt", "request_id": turn_id, "turn_id": turn_id, "persona": payload.persona, **_attempt_payload(lifecycle.attempt)}, ensure_ascii=False))
                yield _sse_event(lifecycle.event, turn_id, **_attempt_payload(lifecycle.attempt))
            result = await execution
            if result.failure_kind == "cancelled":
                conversation_service.cancel_turn(db, turn_id=turn_id)
                yield _sse_event("cancelled", turn_id, status="cancelled", failure_kind="cancelled", route_reason=result.route_reason)
                yield _sse_event("done", turn_id, session_id=payload.session_id, status="cancelled")
                return
            if not result.success or not result.text:
                conversation_service.fail_turn(db, turn_id=turn_id, provider=result.provider, model_name=result.model_name, route_reason=result.route_reason, failure_kind=result.failure_kind)
                yield _sse_event("failed", turn_id, code="TURN_FAILED", message="杏菜暂时没能完成这次回复，请重试。", status="failed", provider=result.provider, model_name=result.model_name, route_reason=result.route_reason, failure_kind=result.failure_kind)
                yield _sse_event("error", turn_id, code="TURN_FAILED", message="杏菜暂时没能完成这次回复，请重试。")
                yield _sse_event("done", turn_id, session_id=payload.session_id, status="failed")
                return
            response = result.text.strip()
            completed = conversation_service.complete_turn(db, turn_id=turn_id, response=response, provider=result.provider, model_name=result.model_name, route_reason=result.route_reason)
            if not completed:
                yield _sse_event("cancelled", turn_id, status="cancelled", failure_kind="cancelled", route_reason="terminal_transition_lost")
                yield _sse_event("done", turn_id, session_id=payload.session_id, status="cancelled")
                return
            metadata = _agent_output_metadata(payload.message, response)
            metadata.update({"provider": result.provider, "model_name": result.model_name, "route_reason": result.route_reason})
            yield _sse_event("meta", turn_id, **metadata)
            yield _sse_event("token", turn_id, chunk=response)
            yield _sse_event("completed", turn_id, session_id=payload.session_id, status="completed", provider=result.provider, model_name=result.model_name, route_reason=result.route_reason)
            yield _sse_event("done", turn_id, session_id=payload.session_id, status="completed")
        except asyncio.CancelledError:
            cancellation.cancel()
            conversation_service.cancel_turn(db, turn_id=turn_id)
            raise
        except Exception as exc:
            cancellation.cancel()
            conversation_service.fail_turn(db, turn_id=turn_id, route_reason="orchestration_error", failure_kind="provider_error")
            logger.warning("agent chat turn failed request_id=%s session_id=%s persona=%s status=failed error=%s", turn_id, payload.session_id, payload.persona, str(exc)[-500:])
            yield _sse_event("failed", turn_id, code="TURN_FAILED", message="杏菜暂时没能完成这次回复，请重试。", status="failed", failure_kind="provider_error", route_reason="orchestration_error")
            yield _sse_event("error", turn_id, code="TURN_FAILED", message="杏菜暂时没能完成这次回复，请重试。")
            yield _sse_event("done", turn_id, session_id=payload.session_id, status="failed")
        finally:
            if not execution.done():
                cancellation.cancel()
                conversation_service.cancel_turn(db, turn_id=turn_id)

    return StreamingResponse(events(), media_type="text/event-stream")


@app.post("/api/agent/task", response_model=AgentTaskResponse)
def agent_task(payload: AgentTaskRequest) -> AgentTaskResponse:
    policy = router.task_policy(payload.task_type)
    if policy["requires_confirmation"] and not payload.confirmed:
        return AgentTaskResponse(success=False, task_type=payload.task_type, provider="router", model_name="none", error="该任务需要确认后才能调用云端模型", requires_confirmation=True)
    result = router.run_task(payload.task_type, payload.prompt, confirmed=payload.confirmed)
    return AgentTaskResponse(success=result.success, task_type=payload.task_type, provider=result.provider, model_name=result.model_name, response=result.text, data=result.data, error=result.error)


@app.get("/api/plugins")
def plugins(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    return list_plugins(db)


@app.post("/api/plugins/install")
def plugin_install(payload: PluginInstallRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    try:
        manifest = normalize_manifest(payload.manifest)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not payload.confirmed:
        return {
            "requires_confirmation": True,
            "manifest": manifest,
            "already_installed": get_plugin(db, manifest["id"]) is not None,
            "warning": "插件只能注册模型任务命令，不会加载代码、写文件或修改学习数据。",
        }
    record, updated = install_plugin(db, manifest)
    _audit(db, "plugin", None, "update" if updated else "install", None, {
        "plugin_id": manifest["id"],
        "version": manifest["version"],
        "command_count": len(manifest["commands"]),
    })
    return {"installed": True, "updated": updated, "plugin": record}


@app.patch("/api/plugins/{plugin_id}")
def plugin_toggle(plugin_id: str, payload: PluginToggleRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    record = set_plugin_enabled(db, plugin_id, payload.enabled)
    if record is None:
        raise HTTPException(status_code=404, detail="插件不存在")
    _audit(db, "plugin", None, "enable" if payload.enabled else "disable", None, {
        "plugin_id": plugin_id,
        "enabled": payload.enabled,
    })
    return {"plugin": record}


@app.delete("/api/plugins/{plugin_id}")
def plugin_delete(plugin_id: str, payload: PluginDeleteRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    record = get_plugin(db, plugin_id)
    if record is None:
        raise HTTPException(status_code=404, detail="插件不存在")
    if not payload.confirmed:
        manifest = record.get("manifest", {}) if isinstance(record, dict) else {}
        return {
            "requires_confirmation": True,
            "plugin_id": plugin_id,
            "name": manifest.get("name", plugin_id),
            "warning": "卸载只会移除插件注册信息，不会删除学习数据。",
        }
    removed = remove_plugin(db, plugin_id)
    if removed:
        _audit(db, "plugin", None, "delete", {"plugin_id": plugin_id}, None)
    return {"deleted": removed, "plugin_id": plugin_id}


@app.post("/api/plugins/{plugin_id}/commands/{command_id}/run")
def plugin_command_run(plugin_id: str, command_id: str, payload: PluginCommandRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    record = get_plugin(db, plugin_id)
    if record is None:
        raise HTTPException(status_code=404, detail="插件不存在")
    if not record.get("enabled", False):
        raise HTTPException(status_code=409, detail="插件已停用")
    command = find_command(record, command_id)
    if command is None:
        raise HTTPException(status_code=404, detail="插件命令不存在")
    prompt = str(command["prompt_template"]).replace("{{input}}", payload.user_input)
    policy = router.task_policy(command["task_type"])
    preview = {
        "plugin_id": plugin_id,
        "command_id": command_id,
        "title": command["title"],
        "task_type": command["task_type"],
        "policy": policy,
        "input_length": len(payload.user_input),
        "requires_confirmation": True,
        "warning": "确认后将按当前模型路由策略调用模型；用户输入不会写入审计日志。",
    }
    if not payload.confirmed:
        return preview
    result = router.run_task(command["task_type"], prompt, confirmed=True)
    _audit(db, "plugin_command", None, "run", None, {
        "plugin_id": plugin_id,
        "command_id": command_id,
        "task_type": command["task_type"],
        "provider": result.provider,
        "model_name": result.model_name,
        "success": result.success,
        "input_length": len(payload.user_input),
    })
    return {
        **preview,
        "requires_confirmation": False,
        "success": result.success,
        "provider": result.provider,
        "model_name": result.model_name,
        "response": result.text,
        "data": result.data,
        "error": result.error,
    }


def _plan_proposal_response(proposal: AgentPlanProposal, *, executed: bool = False, result: dict[str, Any] | None = None, error: str | None = None, batch_id: int | None = None) -> AgentPlanProposalResponse:
    return AgentPlanProposalResponse(
        proposal_id=proposal.id,
        status=proposal.status,
        reason=proposal.reason,
        signal_summary=proposal.signal_summary or {},
        impact=proposal.impact or {},
        changes=proposal.changes or [],
        requires_confirmation=proposal.status == "pending",
        executed=executed,
        result=result,
        batch_id=batch_id,
        error=error,
    )


@app.post("/api/agent/plan-adjustment/propose", response_model=AgentPlanProposalResponse)
def propose_plan_adjustment(payload: AgentPlanProposalRequest, db: Session = Depends(get_db)) -> AgentPlanProposalResponse:
    today = date.today()
    open_statuses = {"not_started", "in_progress", "pending_verification", "needs_review", "paused", "adjusted"}
    tasks = list(db.scalars(select(StudyTask).order_by(StudyTask.priority, StudyTask.due_date, StudyTask.id)))
    overdue = [task for task in tasks if task.status in open_statuses and task.due_date is not None and task.due_date < today]
    due_today = [task for task in tasks if task.status in open_statuses and task.due_date == today]
    due_review_count = int(db.scalar(select(func.count(DailyLogReview.id)).where(DailyLogReview.review_date <= today, DailyLogReview.status != "completed")) or 0)
    pending_log_count = int(db.scalar(select(func.count(DailyLog.id)).where(DailyLog.structured_status != "confirmed")) or 0)

    changes: list[dict[str, Any]] = []
    for index, task in enumerate(overdue[:payload.max_changes]):
        # Spread overdue work across the first few days instead of moving every item onto today.
        target_date = today + timedelta(days=index // 2)
        changes.append({
            "entity_type": "task",
            "task_id": task.id,
            "title": task.title,
            "reason": "任务已逾期，按当前执行容量重新安排",
            "before": {"due_date": task.due_date.isoformat() if task.due_date else None, "priority": task.priority},
            "after": {"due_date": target_date.isoformat(), "priority": min(task.priority, 2)},
        })

    remaining = payload.max_changes - len(changes)
    if remaining > 0 and len(due_today) > 3:
        overloaded = sorted(due_today[3:], key=lambda task: (task.priority, task.id), reverse=True)
        for index, task in enumerate(overloaded[:remaining]):
            target_date = today + timedelta(days=1 + index // 2)
            changes.append({
                "entity_type": "task",
                "task_id": task.id,
                "title": task.title,
                "reason": "今日任务数量偏高，避免计划过载",
                "before": {"due_date": task.due_date.isoformat() if task.due_date else None, "priority": task.priority},
                "after": {"due_date": target_date.isoformat(), "priority": task.priority},
            })

    signal_summary = {
        "generated_on": today.isoformat(),
        "lookahead_days": payload.lookahead_days,
        "overdue_task_count": len(overdue),
        "overdue_task_ids": [task.id for task in overdue],
        "today_open_task_count": len(due_today),
        "due_review_count": due_review_count,
        "pending_log_count": pending_log_count,
    }
    estimated_before = sum(int(item["before"].get("estimated_minutes") or 0) for item in changes)
    estimated_after = sum(int(item["after"].get("estimated_minutes") or 0) for item in changes)
    impact = {
        "affected_tasks": len(changes),
        "affected_reviews": due_review_count,
        "pending_logs": pending_log_count,
        "estimated_minutes_delta": estimated_after - estimated_before,
        "date_shifted_tasks": sum(item["before"].get("due_date") != item["after"].get("due_date") for item in changes),
        "priority_changed_tasks": sum(item["before"].get("priority") != item["after"].get("priority") for item in changes),
    }
    proposal = AgentPlanProposal(
        status="pending",
        reason=payload.reason.strip() or "根据当前学习信号调整近期计划",
        signal_summary=signal_summary,
        changes=changes,
        impact=impact,
    )
    db.add(proposal)
    db.commit()
    db.refresh(proposal)
    return _plan_proposal_response(proposal)


@app.post("/api/agent/plan-adjustment/{proposal_id}/execute", response_model=AgentPlanProposalResponse)
def execute_plan_adjustment(proposal_id: int, payload: dict[str, Any], db: Session = Depends(get_db)) -> AgentPlanProposalResponse:
    proposal = db.get(AgentPlanProposal, proposal_id)
    if not proposal:
        raise HTTPException(status_code=404, detail="计划调整提案不存在")
    if not bool(payload.get("confirmed", False)):
        return _plan_proposal_response(proposal, error="该计划调整需要确认后才能执行")
    if proposal.status != "pending":
        return _plan_proposal_response(proposal, executed=proposal.status in {"executed", "partially_executed"}, result={"status": proposal.status}, error="该提案已经处理过")

    applied: list[int] = []
    skipped: list[dict[str, Any]] = []
    audit_rows: list[tuple[int, dict[str, Any], dict[str, Any]]] = []
    batch_entries: list[dict[str, Any]] = []
    for change in proposal.changes or []:
        if change.get("operation") == "create":
            after = change.get("after") or {}
            title = str(after.get("title") or "").strip()
            if not title:
                skipped.append({"operation": "create", "reason": "新任务缺少标题"})
                continue
            due_value = after.get("due_date")
            try:
                due_date = date.fromisoformat(str(due_value)) if due_value else None
            except ValueError:
                skipped.append({"operation": "create", "title": title, "reason": "截止日期格式无效"})
                continue
            task = StudyTask(
                title=title,
                description=str(after.get("description") or ""),
                priority=max(1, min(5, int(after.get("priority") or 3))),
                estimated_minutes=max(0, int(after.get("estimated_minutes") or 30)),
                due_date=due_date,
                source="report_feedback",
                task_type=str(after.get("task_type") or "practice"),
            )
            db.add(task)
            db.flush()
            after_data = TaskRead.model_validate(task).model_dump(mode="json")
            applied.append(task.id)
            batch_entries.append({"entity_type": "task", "entity_id": task.id, "before": None, "after": after_data, "operation": "create"})
            audit_rows.append((task.id, {}, {"proposal_id": proposal.id, **change, "created_task_id": task.id}))
            continue
        task_id = change.get("task_id")
        task = db.get(StudyTask, task_id) if isinstance(task_id, int) else None
        if task is None:
            skipped.append({"task_id": task_id, "reason": "任务不存在"})
            continue
        before = change.get("before") or {}
        current_due = task.due_date.isoformat() if task.due_date else None
        if current_due != before.get("due_date") or task.priority != before.get("priority"):
            skipped.append({"task_id": task.id, "reason": "任务已被其他操作修改"})
            continue
        before_data = TaskRead.model_validate(task).model_dump(mode="json")
        after = change.get("after") or {}
        if "due_date" in after:
            task.due_date = date.fromisoformat(str(after["due_date"])) if after["due_date"] else None
        if "priority" in after:
            task.priority = int(after["priority"])
        applied.append(task.id)
        after_data = TaskRead.model_validate(task).model_dump(mode="json")
        batch_entries.append({"entity_type": "task", "entity_id": task.id, "before": before_data, "after": after_data})
        audit_rows.append((task.id, before_data, {"proposal_id": proposal.id, **change}))

    proposal.status = "executed" if not skipped else ("partially_executed" if applied else "conflict")
    proposal.executed_at = datetime.now(timezone.utc)
    db.commit()
    for task_id, before_data, after_data in audit_rows:
        _audit(db, "task", task_id, "agent_plan_adjustment", before_data, after_data)
    _audit(db, "agent_plan_proposal", proposal.id, "execute", {"status": "pending", "changes": proposal.changes or []}, {"status": proposal.status, "applied_task_ids": applied, "skipped": skipped})
    batch = _create_agent_batch(db, "report_feedback" if proposal.signal_summary.get("report_id") else "plan_adjustment", batch_entries, {"proposal_id": proposal.id}) if batch_entries else None
    result = {"applied_task_ids": applied, "skipped": skipped, "applied": len(applied), "skipped_count": len(skipped)}
    return _plan_proposal_response(proposal, executed=bool(applied) or not proposal.changes, result=result, batch_id=batch.id if batch else None)


@app.post("/api/agent/change", response_model=AgentChangeResponse)
def agent_change(payload: AgentChangeRequest, db: Session = Depends(get_db)) -> AgentChangeResponse:
    allowed = {"create_task", "complete_task", "reopen_task", "create_note", "update_note", "create_topic", "update_topic", "create_project", "update_project", "create_review", "bulk_update_tasks"}
    if payload.operation not in allowed:
        return AgentChangeResponse(success=False, operation=payload.operation, preview={}, error="不支持的结构化操作")
    if payload.operation == "create_note":
        title = str(payload.payload.get("title", "")).strip()
        preview = {"operation": payload.operation, "title": title, "folder": payload.payload.get("folder", "Inbox"), "visibility": "private"}
        if not title:
            return AgentChangeResponse(success=False, operation=payload.operation, preview=preview, error="创建笔记需要 title")
        if not payload.confirmed:
            return AgentChangeResponse(success=True, operation=payload.operation, preview=preview)
        note = Note(title=title, content=str(payload.payload.get("content", "")), summary=str(payload.payload.get("summary", "")), tags=payload.payload.get("tags", []), folder=str(payload.payload.get("folder", "Inbox")), linked_topic_ids=payload.payload.get("linked_topic_ids", []), linked_task_ids=payload.payload.get("linked_task_ids", []), linked_project_ids=payload.payload.get("linked_project_ids", []), status="draft")
        db.add(note); db.commit(); db.refresh(note)
        result = NoteRead.model_validate(note).model_dump(mode="json")
        _audit(db, "note", note.id, "agent_create", None, result)
        batch = _create_agent_batch(db, payload.operation, [{"entity_type": "note", "entity_id": note.id, "before": None, "after": result, "created": True}], payload.payload)
        return AgentChangeResponse(success=True, operation=payload.operation, preview=preview, executed=True, result=result, batch_id=batch.id)
    if payload.operation == "update_note":
        note_id = payload.payload.get("note_id")
        note = db.get(Note, note_id) if isinstance(note_id, int) else None
        if not note:
            return AgentChangeResponse(success=False, operation=payload.operation, preview={}, error="笔记不存在")
        changes = {key: value for key, value in payload.payload.items() if key in {"title", "content", "summary", "tags", "folder", "status"}}
        preview = {"operation": payload.operation, "note_id": note.id, "changes": changes}
        if not payload.confirmed:
            return AgentChangeResponse(success=True, operation=payload.operation, preview=preview)
        before = NoteRead.model_validate(note).model_dump(mode="json")
        for key, value in changes.items(): setattr(note, key, value)
        db.commit(); db.refresh(note)
        result = NoteRead.model_validate(note).model_dump(mode="json")
        _audit(db, "note", note.id, "agent_update", before, result)
        batch = _create_agent_batch(db, payload.operation, [{"entity_type": "note", "entity_id": note.id, "before": before, "after": result}], changes)
        return AgentChangeResponse(success=True, operation=payload.operation, preview=preview, executed=True, result=result, batch_id=batch.id)
    if payload.operation == "create_topic":
        name = str(payload.payload.get("name", "")).strip()
        preview = {"operation": payload.operation, "name": name, "domain": payload.payload.get("domain", "待整理")}
        if not name:
            return AgentChangeResponse(success=False, operation=payload.operation, preview=preview, error="创建知识主题需要 name")
        if not payload.confirmed:
            return AgentChangeResponse(success=True, operation=payload.operation, preview=preview)
        topic = KnowledgeTopic(name=name, domain=str(payload.payload.get("domain", "待整理")), definition=str(payload.payload.get("definition", "")), tags=payload.payload.get("tags", []), prerequisites=payload.payload.get("prerequisites", []))
        db.add(topic); db.commit(); db.refresh(topic)
        result = TopicRead.model_validate(topic).model_dump(mode="json")
        _audit(db, "knowledge_topic", topic.id, "agent_create", None, result)
        batch = _create_agent_batch(db, payload.operation, [{"entity_type": "knowledge_topic", "entity_id": topic.id, "before": None, "after": result, "created": True}], payload.payload)
        return AgentChangeResponse(success=True, operation=payload.operation, preview=preview, executed=True, result=result, batch_id=batch.id)
    if payload.operation == "create_project":
        title = str(payload.payload.get("title", "")).strip()
        preview = {"operation": payload.operation, "title": title, "status": payload.payload.get("status", "active")}
        if not title:
            return AgentChangeResponse(success=False, operation=payload.operation, preview=preview, error="创建项目需要 title")
        if not payload.confirmed:
            return AgentChangeResponse(success=True, operation=payload.operation, preview=preview)
        project = LearningProject(title=title, description=str(payload.payload.get("description", "")), status=str(payload.payload.get("status", "active")), skills=payload.payload.get("skills", []), outcomes=payload.payload.get("outcomes", []), milestones=payload.payload.get("milestones", []))
        db.add(project); db.commit(); db.refresh(project)
        result = ProjectRead.model_validate(project).model_dump(mode="json")
        _audit(db, "project", project.id, "agent_create", None, result)
        batch = _create_agent_batch(db, payload.operation, [{"entity_type": "project", "entity_id": project.id, "before": None, "after": result, "created": True}], payload.payload)
        return AgentChangeResponse(success=True, operation=payload.operation, preview=preview, executed=True, result=result, batch_id=batch.id)
    if payload.operation == "create_review":
        log_id = payload.payload.get("daily_log_id")
        review_date = payload.payload.get("review_date")
        if not isinstance(log_id, int) or not db.get(DailyLog, log_id) or not review_date:
            return AgentChangeResponse(success=False, operation=payload.operation, preview={}, error="创建复习需要有效的 daily_log_id 和 review_date")
        preview = {"operation": payload.operation, "daily_log_id": log_id, "review_date": review_date, "topic_id": payload.payload.get("topic_id")}
        if not payload.confirmed:
            return AgentChangeResponse(success=True, operation=payload.operation, preview=preview)
        review = DailyLogReview(daily_log_id=log_id, review_date=date.fromisoformat(str(review_date)), note=str(payload.payload.get("note", "")), topic_id=payload.payload.get("topic_id"))
        db.add(review); db.commit(); db.refresh(review)
        result = ReviewRead.model_validate(review).model_dump(mode="json")
        _audit(db, "review", review.id, "agent_create", None, result)
        batch = _create_agent_batch(db, payload.operation, [{"entity_type": "review", "entity_id": review.id, "before": None, "after": result, "created": True}], payload.payload)
        return AgentChangeResponse(success=True, operation=payload.operation, preview=preview, executed=True, result=result, batch_id=batch.id)
    if payload.operation == "bulk_update_tasks":
        task_ids = [value for value in payload.payload.get("task_ids", []) if isinstance(value, int)]
        changes = {key: value for key, value in payload.payload.items() if key in {"status", "priority", "project_id", "topic_id"}}
        tasks = list(db.scalars(select(StudyTask).where(StudyTask.id.in_(task_ids)))) if task_ids else []
        preview = {"operation": payload.operation, "task_ids": [task.id for task in tasks], "changes": changes}
        if not payload.confirmed:
            return AgentChangeResponse(success=True, operation=payload.operation, preview=preview)
        if "status" in changes:
            if changes["status"] in {"completed", "mastered", "needs_review"}:
                raise HTTPException(status_code=409, detail="任务终态必须通过带证据的验收流程提交")
            for task in tasks:
                _ensure_task_transition(task.status, changes["status"])
        if "project_id" in changes and changes["project_id"] is not None and not db.get(LearningProject, changes["project_id"]):
            return AgentChangeResponse(success=False, operation=payload.operation, preview=preview, error="项目不存在")
        if "topic_id" in changes and changes["topic_id"] is not None and not db.get(KnowledgeTopic, changes["topic_id"]):
            return AgentChangeResponse(success=False, operation=payload.operation, preview=preview, error="知识主题不存在")
        entries = []
        for task in tasks:
            before = TaskRead.model_validate(task).model_dump(mode="json")
            for key, value in changes.items():
                if key == "status":
                    _apply_task_status(task, value)
                else:
                    setattr(task, key, value)
            db.flush()
            after = TaskRead.model_validate(task).model_dump(mode="json")
            entries.append({"entity_type": "task", "entity_id": task.id, "before": before, "after": after})
            _audit(db, "task", task.id, "agent_bulk_update", before, after)
        db.commit()
        batch = _create_agent_batch(db, payload.operation, entries, changes)
        return AgentChangeResponse(success=True, operation=payload.operation, preview=preview, executed=True, result={"updated": len(tasks)}, batch_id=batch.id)
    if payload.operation == "create_task":
        title = str(payload.payload.get("title", "")).strip()
        if not title:
            return AgentChangeResponse(success=False, operation=payload.operation, preview={}, error="创建任务需要 title")
        stage_value = payload.payload.get("stage_id")
        stage_id = stage_value if isinstance(stage_value, int) else None
        estimated_value = payload.payload.get("estimated_minutes", 30)
        try:
            estimated_minutes = max(1, min(1440, int(estimated_value)))
        except (TypeError, ValueError):
            estimated_minutes = 30
        due_value = payload.payload.get("due_date")
        try:
            due_date = date.fromisoformat(str(due_value)) if due_value else None
        except ValueError:
            due_date = None
        preview = {"operation": payload.operation, "title": title, "stage_id": stage_value, "status": "not_started"}
        if stage_id is not None and not db.get(LearningStage, stage_id):
            preview["impact"] = {"impact_level": "high", "requires_confirmation": True, "recommendations": ["指定阶段不存在，确认前请重新选择有效阶段。"]}
        else:
            impact = _task_impact_preview(TaskImpactPreviewRequest(title=title, stage_id=stage_id, topic_id=payload.payload.get("topic_id") if isinstance(payload.payload.get("topic_id"), int) else None, project_id=payload.payload.get("project_id") if isinstance(payload.payload.get("project_id"), int) else None, due_date=due_date, week_key=str(payload.payload.get("week_key")) if payload.payload.get("week_key") else None, estimated_minutes=estimated_minutes, task_type=str(payload.payload.get("task_type", "practice"))), db)
            preview["impact"] = impact.model_dump(mode="json")
        if not payload.confirmed:
            return AgentChangeResponse(success=True, operation=payload.operation, preview=preview)
        if stage_value is not None and not isinstance(stage_value, int):
            return AgentChangeResponse(success=False, operation=payload.operation, preview=preview, error="stage_id 必须是整数")
        if stage_id is not None and not db.get(LearningStage, stage_id):
            return AgentChangeResponse(success=False, operation=payload.operation, preview=preview, error="阶段不存在")
        task = StudyTask(title=title, description=str(payload.payload.get("description", "")), stage_id=stage_id, status="not_started", source="agent")
        db.add(task); db.commit(); db.refresh(task)
        result = TaskRead.model_validate(task).model_dump(mode="json")
        _audit(db, "task", task.id, "agent_create", None, result)
        batch = _create_agent_batch(db, payload.operation, [{"entity_type": "task", "entity_id": task.id, "before": None, "after": result, "created": True}], payload.payload)
        return AgentChangeResponse(success=True, operation=payload.operation, preview=preview, executed=True, result=result, batch_id=batch.id)
    task_id = payload.payload.get("task_id")
    task = db.get(StudyTask, task_id) if isinstance(task_id, int) else None
    if not task:
        return AgentChangeResponse(success=False, operation=payload.operation, preview={}, error="任务不存在")
    next_status = "completed" if payload.operation == "complete_task" else "not_started"
    preview = {"operation": payload.operation, "task_id": task.id, "title": task.title, "from_status": task.status, "to_status": next_status}
    if not payload.confirmed:
        return AgentChangeResponse(success=True, operation=payload.operation, preview=preview)
    if payload.operation == "complete_task":
        evidence = str(payload.payload.get("evidence", "")).strip()
        if not evidence:
            return AgentChangeResponse(success=False, operation=payload.operation, preview=preview, error="完成任务必须提供可复核证据")
    before = TaskRead.model_validate(task).model_dump(mode="json")
    if payload.operation == "complete_task":
        _apply_task_status(task, next_status)
        verification = TaskVerification(task_id=task.id, target_status=next_status, evidence=str(payload.payload.get("evidence")).strip(), note=str(payload.payload.get("note", "")), actual_minutes=payload.payload.get("actual_minutes"), verified_at=utcnow())
        task.last_verified_at = verification.verified_at
        db.add(verification)
    else:
        _apply_task_status(task, next_status)
    db.commit(); db.refresh(task)
    result = TaskRead.model_validate(task).model_dump(mode="json")
    _audit(db, "task", task.id, f"agent_{payload.operation}", before, result)
    batch = _create_agent_batch(db, payload.operation, [{"entity_type": "task", "entity_id": task.id, "before": before, "after": result}], payload.payload)
    return AgentChangeResponse(success=True, operation=payload.operation, preview=preview, executed=True, result=result, batch_id=batch.id)


@app.post("/api/agent/change-batches/{batch_id}/revert")
def revert_agent_change_batch(batch_id: int, payload: AgentChangeRevertRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    batch = db.get(AgentChangeBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Agent 变更批次不存在")
    entries = list(batch.after_data or [])
    preview = {"operation": batch.operation, "affected": len(entries), "status": batch.status}
    if not payload.confirmed:
        return {"reverted": False, "requires_confirmation": True, "preview": preview, "warning": "撤销前会检查当前记录是否仍保持 Agent 变更后的状态；发生冲突的记录会跳过"}
    if batch.status == "reverted":
        return {"reverted": True, "already_reverted": True, "batch_id": batch.id, "preview": preview}
    model_map = {"task": StudyTask, "note": Note, "knowledge_topic": KnowledgeTopic, "project": LearningProject, "review": DailyLogReview, "review_card": ReviewCard, "daily_log": DailyLog}
    schema_map = {"task": TaskRead, "note": NoteRead, "knowledge_topic": TopicRead, "project": ProjectRead, "review": ReviewRead, "review_card": ReviewCardRead, "daily_log": DailyLogRead}
    before_by_entity = {(item.get("entity_type"), item.get("entity_id")): item.get("data") for item in (batch.before_data or [])}
    reverted: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    deleted: list[dict[str, Any]] = []
    for after_item in entries:
        entity_type = after_item.get("entity_type")
        entity_id = after_item.get("entity_id")
        model = model_map.get(entity_type)
        schema = schema_map.get(entity_type)
        row = db.get(model, entity_id) if model and isinstance(entity_id, int) else None
        if row is None or schema is None:
            conflicts.append({"entity_type": entity_type, "entity_id": entity_id, "reason": "记录不存在"})
            continue
        current = schema.model_validate(row).model_dump(mode="json")
        expected = after_item.get("data")
        if after_item.get("created") and isinstance(expected, dict):
            mismatch = next((field for field, value in expected.items() if field in current and current[field] != value), None)
        else:
            mismatch = None if current == expected else "__all__"
        if mismatch:
            conflicts.append({"entity_type": entity_type, "entity_id": entity_id, "reason": "记录已被其他操作修改"})
            continue
        before = before_by_entity.get((entity_type, entity_id))
        if after_item.get("created"):
            db.delete(row)
            deleted.append({"entity_type": entity_type, "entity_id": entity_id})
            continue
        if before is None:
            conflicts.append({"entity_type": entity_type, "entity_id": entity_id, "reason": "缺少变更前状态"})
            continue
        for field, value in before.items():
            if field in {"id", "created_at", "updated_at"} or not hasattr(row, field):
                continue
            if field in {"due_date", "review_date", "log_date"} and isinstance(value, str):
                value = date.fromisoformat(value)
            setattr(row, field, value)
        reverted.append({"entity_type": entity_type, "entity_id": entity_id})
    batch.status = "reverted" if not conflicts else ("partially_reverted" if reverted or deleted else "revert_conflict")
    batch.reverted_at = datetime.now(timezone.utc)
    if batch.operation == "import_confirm":
        for change in batch.changes or []:
            for analysis_id in change.get("file_analysis_ids", []):
                analysis = db.get(FileAnalysis, analysis_id)
                if analysis is not None:
                    db.delete(analysis)
    db.commit()
    _audit(db, "agent_change_batch", batch.id, "revert", {"operation": batch.operation}, {"reverted": reverted, "deleted": deleted, "conflicts": conflicts})
    return {"reverted": bool(reverted or deleted) and not conflicts, "partially_reverted": bool(reverted or deleted) and bool(conflicts), "batch_id": batch.id, "reverted_count": len(reverted), "deleted_count": len(deleted), "conflicts": conflicts}


@app.post("/api/goals", response_model=GoalRead, status_code=status.HTTP_201_CREATED)
def create_goal(payload: GoalCreate, db: Session = Depends(get_db)) -> LearningGoal:
    goal = LearningGoal(**payload.model_dump())
    db.add(goal)
    db.commit()
    db.refresh(goal)
    _audit(db, "goal", goal.id, "create", None, GoalRead.model_validate(goal).model_dump(mode="json"))
    return goal


@app.post("/api/projects", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
def create_project(payload: ProjectCreate, db: Session = Depends(get_db)):
    from .models import LearningProject
    if payload.authorized_directory_id is not None:
        directory = db.get(AuthorizedDirectory, payload.authorized_directory_id)
        if directory is None or not directory.active:
            raise HTTPException(status_code=422, detail="项目关联的授权目录不存在或已撤销")
    project = LearningProject(**payload.model_dump())
    db.add(project); db.commit(); db.refresh(project)
    _audit(db, "project", project.id, "create", None, ProjectRead.model_validate(project).model_dump(mode="json"))
    return project


@app.get("/api/projects", response_model=list[ProjectRead])
def list_projects(db: Session = Depends(get_db)):
    from .models import LearningProject
    return list(db.scalars(select(LearningProject).order_by(LearningProject.updated_at.desc(), LearningProject.id.desc())))


@app.patch("/api/projects/{project_id}", response_model=ProjectRead)
def update_project(project_id: int, payload: ProjectUpdate, db: Session = Depends(get_db)):
    from .models import LearningProject
    project = db.get(LearningProject, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    before = ProjectRead.model_validate(project).model_dump(mode="json")
    changes = payload.model_dump(exclude_unset=True)
    if "authorized_directory_id" in changes and changes["authorized_directory_id"] is not None:
        directory = db.get(AuthorizedDirectory, changes["authorized_directory_id"])
        if directory is None or not directory.active:
            raise HTTPException(status_code=422, detail="项目关联的授权目录不存在或已撤销")
    for field, value in changes.items(): setattr(project, field, value)
    db.commit(); db.refresh(project)
    _audit(db, "project", project.id, "update", before, ProjectRead.model_validate(project).model_dump(mode="json"))
    return project


@app.delete("/api/projects/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(project_id: int, db: Session = Depends(get_db)):
    from .models import LearningProject
    project = db.get(LearningProject, project_id)
    if not project: raise HTTPException(status_code=404, detail="项目不存在")
    db.delete(project); db.commit(); _audit(db, "project", project_id, "delete", None, None)


@app.get("/api/goals", response_model=list[GoalRead])
def list_goals(db: Session = Depends(get_db)) -> list[LearningGoal]:
    return list(db.scalars(select(LearningGoal).order_by(LearningGoal.priority, LearningGoal.id)))


@app.patch("/api/goals/{goal_id}", response_model=GoalRead)
def update_goal(goal_id: int, payload: GoalUpdate, db: Session = Depends(get_db)) -> LearningGoal:
    goal = db.get(LearningGoal, goal_id)
    if not goal:
        raise HTTPException(status_code=404, detail="目标不存在")
    before = GoalRead.model_validate(goal).model_dump(mode="json")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(goal, field, value)
    db.commit(); db.refresh(goal)
    _audit(db, "goal", goal.id, "update", before, GoalRead.model_validate(goal).model_dump(mode="json"))
    return goal


@app.delete("/api/goals/{goal_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_goal(goal_id: int, db: Session = Depends(get_db)) -> None:
    goal = db.get(LearningGoal, goal_id)
    if not goal:
        raise HTTPException(status_code=404, detail="目标不存在")
    db.delete(goal); db.commit(); _audit(db, "goal", goal_id, "delete", None, None)


@app.post("/api/goals/{goal_id}/stages", response_model=StageRead, status_code=status.HTTP_201_CREATED)
def create_stage(goal_id: int, payload: StageCreate, db: Session = Depends(get_db)) -> LearningStage:
    goal = db.get(LearningGoal, goal_id)
    if not goal:
        raise HTTPException(status_code=404, detail="目标不存在")
    stage = LearningStage(goal_id=goal_id, **payload.model_dump())
    db.add(stage)
    db.commit()
    db.refresh(stage)
    _audit(db, "stage", stage.id, "create", None, StageRead.model_validate(stage).model_dump(mode="json"))
    return stage


@app.get("/api/stages", response_model=list[StageRead])
def list_stages(db: Session = Depends(get_db)) -> list[LearningStage]:
    return list(db.scalars(select(LearningStage).order_by(LearningStage.order_index, LearningStage.id)))


@app.patch("/api/stages/{stage_id}", response_model=StageRead)
def update_stage(stage_id: int, payload: StageUpdate, db: Session = Depends(get_db)) -> LearningStage:
    stage = db.get(LearningStage, stage_id)
    if not stage:
        raise HTTPException(status_code=404, detail="阶段不存在")
    before = StageRead.model_validate(stage).model_dump(mode="json")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(stage, field, value)
    db.commit(); db.refresh(stage)
    _audit(db, "stage", stage.id, "update", before, StageRead.model_validate(stage).model_dump(mode="json"))
    return stage


@app.delete("/api/stages/{stage_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_stage(stage_id: int, db: Session = Depends(get_db)) -> None:
    stage = db.get(LearningStage, stage_id)
    if not stage:
        raise HTTPException(status_code=404, detail="阶段不存在")
    db.delete(stage); db.commit(); _audit(db, "stage", stage_id, "delete", None, None)


TASK_STATUS_TRANSITIONS: dict[str, set[str]] = {
    "not_started": {"in_progress", "completed", "mastered", "paused", "adjusted"},
    "in_progress": {"pending_verification", "paused", "adjusted", "not_started"},
    "pending_verification": {"completed", "needs_review", "mastered", "in_progress"},
    "completed": {"needs_review", "mastered", "in_progress", "not_started"},
    "needs_review": {"in_progress", "pending_verification", "mastered", "paused", "not_started"},
    "mastered": {"needs_review", "in_progress", "not_started"},
    "paused": {"not_started", "in_progress", "adjusted"},
    "adjusted": {"not_started", "in_progress", "paused"},
}


def _ensure_task_transition(current: str, target: str) -> None:
    if current == target:
        return
    if target not in TASK_STATUS_TRANSITIONS.get(current, set()):
        raise HTTPException(status_code=409, detail=f"任务状态不能从 {current} 变更为 {target}")


def _apply_task_status(task: StudyTask, target: str) -> None:
    """Apply a validated status transition and keep lifecycle timestamps coherent."""
    _ensure_task_transition(task.status, target)
    task.status = target
    if target in {"completed", "mastered"}:
        if task.completed_at is None:
            task.completed_at = utcnow()
    elif target in {"not_started", "in_progress", "pending_verification", "paused", "adjusted"}:
        task.completed_at = None
    if target != "needs_review":
        task.next_review_date = None
    else:
        task.next_review_date = date.today()


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _entry_elapsed(entry: TaskTimeEntry, now: datetime | None = None) -> int:
    if entry.status != "running":
        return max(0, int(entry.duration_seconds or 0))
    end = now or utcnow()
    return max(0, int((_aware(end) - _aware(entry.started_at)).total_seconds()))


def _timer_state(task: StudyTask, db: Session, now: datetime | None = None) -> dict[str, Any]:
    current = now or utcnow()
    entries = list(db.scalars(select(TaskTimeEntry).where(TaskTimeEntry.task_id == task.id).order_by(TaskTimeEntry.started_at, TaskTimeEntry.id)))
    active = next((entry for entry in entries if entry.status == "running"), None)
    accumulated = sum(_entry_elapsed(entry, current) for entry in entries if entry is not active)
    elapsed = _entry_elapsed(active, current) if active else 0
    state = "running" if active else (
        "paused" if any(entry.status == "paused" for entry in entries) and not any(entry.status == "stopped" for entry in entries)
        else "stopped"
    )
    return TaskTimerRead(
        task_id=task.id,
        state=state,
        active_entry_id=active.id if active else None,
        elapsed_seconds=elapsed,
        accumulated_seconds=accumulated + elapsed,
        actual_minutes=task.actual_minutes,
        updated_at=active.updated_at if active else (entries[-1].updated_at if entries else None),
    ).model_dump(mode="json")


def _sync_task_actual_minutes(task: StudyTask, db: Session, now: datetime | None = None) -> int:
    total_seconds = sum(_entry_elapsed(entry, now) for entry in db.scalars(select(TaskTimeEntry).where(TaskTimeEntry.task_id == task.id)))
    task.actual_minutes = total_seconds // 60
    return total_seconds


def _task_impact_preview(payload: TaskImpactPreviewRequest, db: Session) -> TaskImpactPreviewRead:
    stage = db.get(LearningStage, payload.stage_id) if payload.stage_id is not None else None
    if payload.stage_id is not None and stage is None:
        raise HTTPException(status_code=404, detail="阶段不存在")
    topic = db.get(KnowledgeTopic, payload.topic_id) if payload.topic_id is not None else None
    if payload.topic_id is not None and topic is None:
        raise HTTPException(status_code=404, detail="知识主题不存在")
    project = db.get(LearningProject, payload.project_id) if payload.project_id is not None else None
    if payload.project_id is not None and project is None:
        raise HTTPException(status_code=404, detail="项目不存在")

    week_key = payload.week_key or (payload.due_date.isoformat() if payload.due_date else date.today().isoformat())
    active_statuses = {"not_started", "in_progress", "pending_verification", "paused", "adjusted", "needs_review"}
    scheduled_tasks = [
        task for task in db.scalars(select(StudyTask))
        if task.status in active_statuses
        and (task.week_key == week_key or (payload.due_date is not None and task.due_date == payload.due_date))
    ]
    existing_minutes = sum(task.estimated_minutes or 0 for task in scheduled_tasks)
    after_minutes = existing_minutes + payload.estimated_minutes

    prerequisites: list[str] = []
    if stage is not None:
        prerequisites.extend(str(item).strip() for item in (stage.prerequisites or []) if str(item).strip())
    if topic is not None:
        prerequisite_ids = [item for item in (topic.prerequisites or []) if isinstance(item, int)]
        prerequisite_topics = {item.id: item.name for item in db.scalars(select(KnowledgeTopic).where(KnowledgeTopic.id.in_(prerequisite_ids)))} if prerequisite_ids else {}
        prerequisites.extend(prerequisite_topics.get(item, f"知识主题 #{item}") for item in prerequisite_ids)
    prerequisites = list(dict.fromkeys(prerequisites))

    relation = {
        "goal": {"id": stage.goal.id, "title": stage.goal.title} if stage is not None and stage.goal is not None else None,
        "stage": {"id": stage.id, "title": stage.title} if stage is not None else None,
        "topic": {"id": topic.id, "name": topic.name} if topic is not None else None,
        "project": {"id": project.id, "title": project.title} if project is not None else None,
    }
    recommendations: list[str] = []
    if stage is None:
        recommendations.append("这是未关联阶段的临时任务；确认它不会偏离当前长期目标后再加入计划。")
    if not prerequisites:
        recommendations.append("没有读取到明确前置知识；完成后请补充可复核的解释、练习或产出证据。")
    if after_minutes > 600:
        recommendations.append("当前周计划预计用时超过 10 小时，建议拆分任务或调整优先级。")
    elif after_minutes > 360:
        recommendations.append("当前周计划负荷偏高，建议确认本任务是否比已有任务更重要。")
    if payload.task_type == "practice":
        recommendations.append("实践任务建议填写验收标准，并在完成后提交代码、测试或运行结果。")
    elif payload.task_type == "reading":
        recommendations.append("阅读任务建议绑定笔记或复习卡片，避免只有输入没有可验证产出。")

    impact_level = "high" if after_minutes > 600 else "medium" if stage is None or after_minutes > 360 else "low"
    return TaskImpactPreviewRead(
        title=payload.title.strip(),
        relation=relation,
        prerequisites=prerequisites,
        schedule_impact={
            "week_key": week_key,
            "existing_active_task_count": len(scheduled_tasks),
            "existing_estimated_minutes": existing_minutes,
            "task_estimated_minutes": payload.estimated_minutes,
            "after_estimated_minutes": after_minutes,
        },
        impact_level=impact_level,
        recommendations=recommendations,
    )


@app.post("/api/tasks/impact-preview", response_model=TaskImpactPreviewRead)
def preview_task_impact(payload: TaskImpactPreviewRequest, db: Session = Depends(get_db)) -> TaskImpactPreviewRead:
    return _task_impact_preview(payload, db)


@app.post("/api/tasks", response_model=TaskRead, status_code=status.HTTP_201_CREATED)
def create_task(payload: TaskCreate, db: Session = Depends(get_db)) -> StudyTask:
    if payload.stage_id is not None and not db.get(LearningStage, payload.stage_id):
        raise HTTPException(status_code=404, detail="阶段不存在")
    if payload.project_id is not None and not db.get(LearningProject, payload.project_id):
        raise HTTPException(status_code=404, detail="项目不存在")
    if payload.topic_id is not None and not db.get(KnowledgeTopic, payload.topic_id):
        raise HTTPException(status_code=404, detail="知识主题不存在")
    task = StudyTask(**payload.model_dump())
    db.add(task)
    db.commit()
    db.refresh(task)
    _audit(db, "task", task.id, "create", None, TaskRead.model_validate(task).model_dump(mode="json"))
    return task


@app.get("/api/tasks", response_model=list[TaskRead])
def list_tasks(db: Session = Depends(get_db)) -> list[StudyTask]:
    return list(db.scalars(select(StudyTask).order_by(StudyTask.due_date, StudyTask.priority, StudyTask.id)))


@app.get("/api/tasks/{task_id}/notes", response_model=list[NoteRead])
def list_task_notes(task_id: int, db: Session = Depends(get_db)) -> list[Note]:
    if not db.get(StudyTask, task_id):
        raise HTTPException(status_code=404, detail="任务不存在")
    notes = list(db.scalars(select(Note).order_by(Note.updated_at.desc(), Note.id.desc())))
    return [note for note in notes if task_id in (note.linked_task_ids or [])]


@app.patch("/api/tasks/{task_id}", response_model=TaskRead)
def update_task(task_id: int, payload: TaskUpdate, db: Session = Depends(get_db)) -> StudyTask:
    task = db.get(StudyTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    changes = payload.model_dump(exclude_unset=True)
    if "status" in changes:
        if changes["status"] in {"completed", "mastered", "needs_review"}:
            raise HTTPException(status_code=409, detail="任务终态必须通过带证据的验收接口提交")
        _ensure_task_transition(task.status, changes["status"])
    if "stage_id" in changes and changes["stage_id"] is not None and not db.get(LearningStage, changes["stage_id"]):
        raise HTTPException(status_code=404, detail="阶段不存在")
    if "project_id" in changes and changes["project_id"] is not None and not db.get(LearningProject, changes["project_id"]):
        raise HTTPException(status_code=404, detail="项目不存在")
    if "topic_id" in changes and changes["topic_id"] is not None and not db.get(KnowledgeTopic, changes["topic_id"]):
        raise HTTPException(status_code=404, detail="知识主题不存在")
    before = TaskRead.model_validate(task).model_dump(mode="json")
    for field, value in changes.items():
        if field == "status":
            _apply_task_status(task, value)
        else:
            setattr(task, field, value)
    db.commit()
    db.refresh(task)
    _audit(db, "task", task.id, "status_transition" if "status" in changes else "update", before, TaskRead.model_validate(task).model_dump(mode="json"))
    return task


@app.get("/api/tasks/{task_id}/verifications", response_model=list[TaskVerificationRead])
def list_task_verifications(task_id: int, db: Session = Depends(get_db)) -> list[TaskVerification]:
    if not db.get(StudyTask, task_id):
        raise HTTPException(status_code=404, detail="任务不存在")
    return list(db.scalars(select(TaskVerification).where(TaskVerification.task_id == task_id).order_by(TaskVerification.verified_at.desc(), TaskVerification.id.desc())))


@app.post("/api/tasks/{task_id}/verify", response_model=TaskRead)
def verify_task(task_id: int, payload: TaskVerificationCreate, db: Session = Depends(get_db)) -> StudyTask:
    task = db.get(StudyTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    _ensure_task_transition(task.status, payload.target_status)
    before = TaskRead.model_validate(task).model_dump(mode="json")
    verification = TaskVerification(task_id=task.id, **payload.model_dump())
    db.add(verification)
    _apply_task_status(task, payload.target_status)
    task.last_verified_at = utcnow()
    if payload.actual_minutes is not None:
        task.actual_minutes = payload.actual_minutes
    db.commit()
    db.refresh(task)
    _audit(db, "task", task.id, "verify", before, {"task": TaskRead.model_validate(task).model_dump(mode="json"), "verification_id": verification.id})
    return task


@app.get("/api/tasks/{task_id}/timer", response_model=TaskTimerRead)
def get_task_timer(task_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    task = db.get(StudyTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return _timer_state(task, db)


@app.get("/api/tasks/{task_id}/time-entries", response_model=list[TaskTimeEntryRead])
def list_task_time_entries(task_id: int, db: Session = Depends(get_db)) -> list[TaskTimeEntry]:
    if not db.get(StudyTask, task_id):
        raise HTTPException(status_code=404, detail="任务不存在")
    return list(db.scalars(select(TaskTimeEntry).where(TaskTimeEntry.task_id == task_id).order_by(TaskTimeEntry.started_at.desc(), TaskTimeEntry.id.desc())))


@app.post("/api/tasks/{task_id}/timer/start", response_model=TaskTimerRead)
def start_task_timer(task_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    task = db.get(StudyTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    active = db.scalar(select(TaskTimeEntry).where(TaskTimeEntry.task_id == task_id, TaskTimeEntry.status == "running"))
    if active:
        raise HTTPException(status_code=409, detail="任务已经在计时中")
    paused = db.scalar(select(TaskTimeEntry).where(TaskTimeEntry.task_id == task_id, TaskTimeEntry.status == "paused"))
    if paused:
        raise HTTPException(status_code=409, detail="任务存在已暂停计时，请使用继续计时")
    now = utcnow()
    entry = TaskTimeEntry(task_id=task_id, started_at=now, status="running")
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return _timer_state(task, db, now)


@app.post("/api/tasks/{task_id}/timer/pause", response_model=TaskTimerRead)
def pause_task_timer(task_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    task = db.get(StudyTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    entry = db.scalar(select(TaskTimeEntry).where(TaskTimeEntry.task_id == task_id, TaskTimeEntry.status == "running"))
    if not entry:
        raise HTTPException(status_code=409, detail="任务当前没有活动计时")
    now = utcnow()
    entry.duration_seconds = _entry_elapsed(entry, now)
    entry.paused_at = now
    entry.status = "paused"
    entry.updated_at = now
    _sync_task_actual_minutes(task, db, now)
    db.commit()
    return _timer_state(task, db, now)


@app.post("/api/tasks/{task_id}/timer/resume", response_model=TaskTimerRead)
def resume_task_timer(task_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    task = db.get(StudyTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if db.scalar(select(TaskTimeEntry).where(TaskTimeEntry.task_id == task_id, TaskTimeEntry.status == "running")):
        raise HTTPException(status_code=409, detail="任务已经在计时中")
    paused = db.scalar(select(TaskTimeEntry).where(TaskTimeEntry.task_id == task_id, TaskTimeEntry.status == "paused").order_by(TaskTimeEntry.paused_at.desc(), TaskTimeEntry.id.desc()))
    if not paused:
        raise HTTPException(status_code=409, detail="任务没有可继续的暂停计时")
    now = utcnow()
    entry = TaskTimeEntry(task_id=task_id, started_at=now, status="running")
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return _timer_state(task, db, now)


@app.post("/api/tasks/{task_id}/timer/stop", response_model=TaskTimerRead)
def stop_task_timer(task_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    task = db.get(StudyTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    now = utcnow()
    active = db.scalar(select(TaskTimeEntry).where(TaskTimeEntry.task_id == task_id, TaskTimeEntry.status == "running"))
    if active:
        active.duration_seconds = _entry_elapsed(active, now)
        active.ended_at = now
        active.status = "stopped"
        active.updated_at = now
        paused_entries = list(db.scalars(select(TaskTimeEntry).where(TaskTimeEntry.task_id == task_id, TaskTimeEntry.status == "paused")))
        for paused in paused_entries:
            paused.ended_at = now
            paused.status = "stopped"
            paused.updated_at = now
    else:
        paused_entries = list(db.scalars(select(TaskTimeEntry).where(TaskTimeEntry.task_id == task_id, TaskTimeEntry.status == "paused")))
        if paused_entries:
            for paused in paused_entries:
                paused.ended_at = now
                paused.status = "stopped"
                paused.updated_at = now
        elif db.scalar(select(TaskTimeEntry).where(TaskTimeEntry.task_id == task_id, TaskTimeEntry.status == "stopped")):
            raise HTTPException(status_code=409, detail="任务计时已经结束")
        else:
            raise HTTPException(status_code=409, detail="任务尚未开始计时")
    _sync_task_actual_minutes(task, db, now)
    db.commit()
    return _timer_state(task, db, now)


@app.delete("/api/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_task(task_id: int, db: Session = Depends(get_db)) -> None:
    task = db.get(StudyTask, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    db.delete(task)
    db.commit()


@app.get("/api/weekly-plans", response_model=list[WeeklyPlanRead])
def list_weekly_plans(limit: int = 20, db: Session = Depends(get_db)) -> list[WeeklyPlan]:
    return list(db.scalars(select(WeeklyPlan).order_by(WeeklyPlan.week_key.desc()).limit(max(1, min(limit, 100)))))


@app.get("/api/weekly-plans/{week_key}/summary")
def weekly_plan_summary(week_key: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    plan = db.scalar(select(WeeklyPlan).where(WeeklyPlan.week_key == week_key))
    tasks = list(db.scalars(select(StudyTask).where(StudyTask.week_key == week_key)))
    logs = list(db.scalars(select(DailyLog).where(DailyLog.log_date >= date.fromisoformat(week_key), DailyLog.log_date < date.fromisoformat(week_key) + timedelta(days=7))))
    outputs = sum(len(log.extracted_outputs or []) for log in logs)
    completed = sum(task.status in {"completed", "mastered"} for task in tasks)
    task_ids = {task.id for task in tasks}
    timer_seconds = {
        task_id: sum(_entry_elapsed(entry) for entry in db.scalars(select(TaskTimeEntry).where(TaskTimeEntry.task_id == task_id)))
        for task_id in task_ids
    }
    actual_minutes = sum(
        (timer_seconds[task.id] // 60) if timer_seconds[task.id] else (task.actual_minutes or 0)
        for task in tasks
    )
    return {
        "plan": WeeklyPlanRead.model_validate(plan).model_dump(mode="json") if plan else None,
        "task_count": len(tasks),
        "completed_count": completed,
        "completion_rate": round(completed / len(tasks) * 100, 1) if tasks else 0,
        "estimated_minutes": sum(task.estimated_minutes or 0 for task in tasks),
        "actual_minutes": actual_minutes,
        "log_count": len(logs),
        "output_count": outputs,
        "tasks": [TaskRead.model_validate(task).model_dump(mode="json") for task in tasks],
    }


@app.post("/api/weekly-plans", response_model=WeeklyPlanRead, status_code=status.HTTP_201_CREATED)
def create_weekly_plan(payload: WeeklyPlanCreate, db: Session = Depends(get_db)) -> WeeklyPlan:
    if db.scalar(select(WeeklyPlan).where(WeeklyPlan.week_key == payload.week_key)):
        raise HTTPException(status_code=409, detail="该周计划已存在")
    if payload.goal_id is not None and not db.get(LearningGoal, payload.goal_id):
        raise HTTPException(status_code=404, detail="目标不存在")
    if payload.project_id is not None and not db.get(LearningProject, payload.project_id):
        raise HTTPException(status_code=404, detail="项目不存在")
    plan = WeeklyPlan(**payload.model_dump())
    db.add(plan)
    db.commit()
    db.refresh(plan)
    _audit(db, "weekly_plan", plan.id, "create", None, WeeklyPlanRead.model_validate(plan).model_dump(mode="json"))
    return plan


@app.patch("/api/weekly-plans/{plan_id}", response_model=WeeklyPlanRead)
def update_weekly_plan(plan_id: int, payload: WeeklyPlanUpdate, db: Session = Depends(get_db)) -> WeeklyPlan:
    plan = db.get(WeeklyPlan, plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="周计划不存在")
    changes = payload.model_dump(exclude_unset=True)
    if "goal_id" in changes and changes["goal_id"] is not None and not db.get(LearningGoal, changes["goal_id"]):
        raise HTTPException(status_code=404, detail="目标不存在")
    if "project_id" in changes and changes["project_id"] is not None and not db.get(LearningProject, changes["project_id"]):
        raise HTTPException(status_code=404, detail="项目不存在")
    before = WeeklyPlanRead.model_validate(plan).model_dump(mode="json")
    for field, value in changes.items():
        setattr(plan, field, value)
    db.commit()
    db.refresh(plan)
    _audit(db, "weekly_plan", plan.id, "update", before, WeeklyPlanRead.model_validate(plan).model_dump(mode="json"))
    return plan


@app.get("/api/weekly-plans/{week_key}", response_model=WeeklyPlanRead)
def get_weekly_plan(week_key: str, db: Session = Depends(get_db)) -> WeeklyPlan:
    plan = db.scalar(select(WeeklyPlan).where(WeeklyPlan.week_key == week_key))
    if not plan:
        raise HTTPException(status_code=404, detail="周计划不存在")
    return plan


def _report_period(report_type: str, payload: ReportGenerateRequest) -> tuple[date, date]:
    today = date.today()
    if payload.period_start and payload.period_end:
        if payload.period_end < payload.period_start:
            raise HTTPException(status_code=422, detail="报告结束日期不能早于开始日期")
        return payload.period_start, payload.period_end
    if report_type == "daily":
        start = payload.period_start or today
        return start, payload.period_end or start
    if report_type == "weekly":
        start = payload.period_start or today - timedelta(days=today.weekday())
        return start, payload.period_end or start + timedelta(days=6)
    start = payload.period_start or today - timedelta(days=29)
    return start, payload.period_end or today


def _report_evidence(label: str, value: Any, source_type: str = "statistics") -> dict[str, Any]:
    return {"fact": label, "value": value, "source_type": source_type, "confidence": 1.0}


def _build_report_snapshot(report_type: str, period_start: date, period_end: date, stage_id: int | None, db: Session) -> dict[str, Any]:
    tasks = list(db.scalars(select(StudyTask).where(StudyTask.due_date >= period_start, StudyTask.due_date <= period_end)))
    logs = list(db.scalars(select(DailyLog).where(DailyLog.log_date >= period_start, DailyLog.log_date <= period_end)))
    reviews = list(db.scalars(select(DailyLogReview).where(DailyLogReview.review_date >= period_start, DailyLogReview.review_date <= period_end)))
    attempts = list(db.scalars(select(TeachingAttempt).where(TeachingAttempt.created_at >= datetime.combine(period_start, datetime.min.time(), tzinfo=timezone.utc), TeachingAttempt.created_at < datetime.combine(period_end + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc))))
    if stage_id is not None:
        tasks = [task for task in tasks if task.stage_id == stage_id]
    topic_counts: dict[str, int] = {}
    for log in logs:
        for topic in log.extracted_topics or []:
            topic_counts[str(topic)] = topic_counts.get(str(topic), 0) + 1
    status_counts = {status_name: sum(task.status == status_name for task in tasks) for status_name in TASK_STATUSES}
    completed = sum(task.status in {"completed", "mastered"} for task in tasks)
    return {
        "report_type": report_type,
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "stage_id": stage_id,
        "task_count": len(tasks),
        "completed_tasks": completed,
        "completion_rate": round(completed / len(tasks) * 100, 1) if tasks else 0.0,
        "task_status_counts": status_counts,
        "study_minutes": sum(log.extracted_duration or 0 for log in logs) + sum(task.actual_minutes or 0 for task in tasks),
        "log_count": len(logs),
        "output_count": sum(len(log.extracted_outputs or []) for log in logs),
        "understood_count": sum(len(log.understood_content or []) for log in logs),
        "unresolved_count": sum(len(log.unresolved_questions or []) for log in logs),
        "review_count": len(reviews),
        "review_completed": sum(review.status == "completed" for review in reviews),
        "review_quality": round(sum(review.quality for review in reviews if review.quality is not None) / len([review for review in reviews if review.quality is not None]), 2) if any(review.quality is not None for review in reviews) else None,
        "teaching_attempts": len(attempts),
        "teaching_average_score": round(sum(attempt.score for attempt in attempts if attempt.score is not None) / len([attempt for attempt in attempts if attempt.score is not None]), 2) if any(attempt.score is not None for attempt in attempts) else None,
        "topic_counts": topic_counts,
        "tasks": [{"id": task.id, "title": task.title, "status": task.status, "due_date": task.due_date.isoformat() if task.due_date else None, "topic_id": task.topic_id} for task in tasks],
        "logs": [{"id": log.id, "date": log.log_date.isoformat(), "topics": log.extracted_topics or [], "outputs": log.extracted_outputs or [], "unresolved_questions": log.unresolved_questions or []} for log in logs],
    }


def _deterministic_report(report_type: str, snapshot: dict[str, Any], stage: LearningStage | None = None) -> dict[str, Any]:
    unfinished = [item for item in snapshot["tasks"] if item["status"] not in {"completed", "mastered"}]
    weak_points: list[dict[str, Any]] = []
    for topic, count in sorted(snapshot["topic_counts"].items(), key=lambda item: (-item[1], item[0]))[:5]:
        weak_points.append({"point": topic, "reason": "学习记录中反复出现，仍需结合输出或练习验证", "evidence_count": count, "confidence": 0.65})
    if snapshot["review_quality"] is not None and snapshot["review_quality"] < 3:
        weak_points.append({"point": "复习质量", "reason": "复习平均质量低于 3/5", "value": snapshot["review_quality"], "confidence": 0.9})
    if snapshot["teaching_average_score"] is not None and snapshot["teaching_average_score"] < 60:
        weak_points.append({"point": "教学练习", "reason": "教学作答平均分低于 60", "value": snapshot["teaching_average_score"], "confidence": 0.9})
    achievements = []
    if snapshot["completed_tasks"]:
        achievements.append(f"完成 {snapshot['completed_tasks']} 项任务")
    if snapshot["output_count"]:
        achievements.append(f"形成 {snapshot['output_count']} 项学习产出")
    if snapshot["study_minutes"]:
        achievements.append(f"累计学习 {snapshot['study_minutes']} 分钟")
    recommendations = []
    if unfinished:
        recommendations.append({"action": "优先处理未完成任务", "reason": f"当前有 {len(unfinished)} 项任务未完成", "requires_confirmation": True})
    if snapshot["unresolved_count"]:
        recommendations.append({"action": "为未解决问题安排一次短练习或教学追问", "reason": f"记录了 {snapshot['unresolved_count']} 个未解决问题", "requires_confirmation": True})
    if not recommendations:
        recommendations.append({"action": "保持当前节奏并补充可验证产出", "reason": "当前窗口未发现明确阻塞信号", "requires_confirmation": False})
    title_map = {"daily": "每日学习总结", "weekly": "学习周报", "stage": "阶段学习报告", "bottleneck": "学习瓶颈分析"}
    if report_type == "bottleneck":
        summary = f"本窗口识别到 {len(weak_points)} 个需要关注的信号；结论基于已保存的任务、日志、复习和教学证据。"
    else:
        summary = f"本窗口累计学习 {snapshot['study_minutes']} 分钟，完成 {snapshot['completed_tasks']}/{snapshot['task_count']} 项任务，产生 {snapshot['output_count']} 项产出。"
    if stage:
        summary = f"阶段“{stage.title}”：" + summary
    return {"title": title_map[report_type], "summary": summary, "evidence": [_report_evidence("学习时长（分钟）", snapshot["study_minutes"]), _report_evidence("完成任务数", snapshot["completed_tasks"]), _report_evidence("学习产出数", snapshot["output_count"]), _report_evidence("学习日志数", snapshot["log_count"])], "achievements": achievements, "unfinished_items": unfinished, "weak_points": weak_points, "recommendations": recommendations, "proposed_changes": [{"type": "plan_adjustment", "description": item["action"], "requires_confirmation": item["requires_confirmation"]} for item in recommendations if item.get("requires_confirmation")], "confidence": 1.0, "generation_mode": "deterministic"}


def _report_payload(row: LearningReport) -> dict[str, Any]:
    return ReportRead.model_validate(row).model_dump(mode="json")


def _report_section_key(item: Any, section: str) -> str:
    if isinstance(item, dict):
        fields = {
            "evidence": ("fact", "name", "title"),
            "weak_points": ("point", "title", "name"),
            "recommendations": ("action", "title", "name"),
        }.get(section, ("title", "name", "action", "point", "fact"))
        for field in fields:
            value = str(item.get(field) or "").strip()
            if value:
                return value
    return json.dumps(item, ensure_ascii=False, sort_keys=True, default=str)


def _compare_report_section(left_items: list[Any], right_items: list[Any], section: str) -> dict[str, Any]:
    left_map = {_report_section_key(item, section): item for item in left_items}
    right_map = {_report_section_key(item, section): item for item in right_items}
    changed = [
        {"key": key, "left": left_map[key], "right": right_map[key]}
        for key in sorted(set(left_map) & set(right_map))
        if left_map[key] != right_map[key]
    ]
    return {
        "added": [right_map[key] for key in sorted(set(right_map) - set(left_map))],
        "removed": [left_map[key] for key in sorted(set(left_map) - set(right_map))],
        "changed": changed,
    }


@app.post("/api/reports/{report_type}/generate", response_model=ReportRead)
def generate_report(report_type: str, payload: ReportGenerateRequest | None = None, db: Session = Depends(get_db)) -> LearningReport:
    if report_type not in REPORT_TYPES:
        raise HTTPException(status_code=404, detail="不支持的报告类型")
    payload = payload or ReportGenerateRequest()
    period_start, period_end = _report_period(report_type, payload)
    if payload.stage_id is not None and not db.get(LearningStage, payload.stage_id):
        raise HTTPException(status_code=404, detail="学习阶段不存在")
    existing = db.scalar(select(LearningReport).where(LearningReport.report_type == report_type, LearningReport.period_start == period_start, LearningReport.period_end == period_end, LearningReport.stage_id == payload.stage_id).order_by(LearningReport.version.desc(), LearningReport.id.desc()))
    version = (existing.version + 1) if existing and payload.force_new_version else (existing.version if existing else 1)
    if existing and not payload.force_new_version:
        return existing
    snapshot = _build_report_snapshot(report_type, period_start, period_end, payload.stage_id, db)
    stage = db.get(LearningStage, payload.stage_id) if payload.stage_id else None
    content = _deterministic_report(report_type, snapshot, stage)
    model_result = None
    if settings.report_model_enhancement_enabled:
        model_prompt = json.dumps({"report_type": report_type, "period_start": period_start.isoformat(), "period_end": period_end.isoformat(), "snapshot": snapshot}, ensure_ascii=False)
        model_result = router.run_structured("knowledge_analysis", "根据以下学习证据生成报告 JSON。只能使用证据，不得虚构。字段必须包含 title、summary、evidence、achievements、unfinished_items、weak_points、recommendations、proposed_changes、confidence。\n" + model_prompt, {"title", "summary", "evidence", "achievements", "unfinished_items", "weak_points", "recommendations", "proposed_changes", "confidence"})
    if model_result and model_result.success and model_result.data:
        try:
            content = validate_structured_data(model_result.data, {"title", "summary", "evidence", "achievements", "unfinished_items", "weak_points", "recommendations", "proposed_changes", "confidence"})
            content["generation_mode"] = "model"
            content["confidence"] = min(1.0, max(0.0, float(content.get("confidence", model_result.confidence or 0.65))))
        except ValueError:
            content = _deterministic_report(report_type, snapshot, stage)
            content["generation_mode"] = "deterministic_fallback"
    else:
        content["generation_mode"] = "deterministic_fallback" if model_result and model_result.fallback_used else "deterministic"
    row = LearningReport(report_type=report_type, period_start=period_start, period_end=period_end, stage_id=payload.stage_id, version=version, source_snapshot=snapshot, status="generated", model_provider=model_result.provider if model_result else None, model_name=model_result.model_name if model_result else None, retry_count=model_result.retry_count if model_result else 0, fallback_used=model_result.fallback_used if model_result else False, **content)
    db.add(row); db.commit(); db.refresh(row)
    _audit(db, "learning_report", row.id, "generate", None, _report_payload(row))
    return row


@app.get("/api/reports", response_model=list[ReportRead])
def list_reports(report_type: str | None = None, limit: int = 50, db: Session = Depends(get_db)) -> list[LearningReport]:
    query = select(LearningReport).order_by(LearningReport.created_at.desc(), LearningReport.id.desc()).limit(max(1, min(limit, 200)))
    if report_type:
        if report_type not in REPORT_TYPES:
            raise HTTPException(status_code=422, detail="不支持的报告类型")
        query = query.where(LearningReport.report_type == report_type)
    return list(db.scalars(query))


@app.get("/api/reports/compare")
def compare_reports(left_id: int, right_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    left = db.get(LearningReport, left_id)
    right = db.get(LearningReport, right_id)
    if not left or not right:
        raise HTTPException(status_code=404, detail="比较所需的报告不存在")
    if left.report_type != right.report_type or left.stage_id != right.stage_id:
        raise HTTPException(status_code=422, detail="只能比较同一类型和阶段的报告版本")
    return {
        "report_type": left.report_type,
        "left": {"id": left.id, "version": left.version, "period_start": left.period_start, "period_end": left.period_end, "created_at": left.created_at},
        "right": {"id": right.id, "version": right.version, "period_start": right.period_start, "period_end": right.period_end, "created_at": right.created_at},
        "changes": {
            "evidence": _compare_report_section(left.evidence or [], right.evidence or [], "evidence"),
            "weak_points": _compare_report_section(left.weak_points or [], right.weak_points or [], "weak_points"),
            "recommendations": _compare_report_section(left.recommendations or [], right.recommendations or [], "recommendations"),
            "summary_changed": left.summary != right.summary,
            "confidence": {"left": left.confidence, "right": right.confidence, "delta": round(right.confidence - left.confidence, 4)},
        },
    }


@app.get("/api/reports/{report_id}", response_model=ReportRead)
def get_report(report_id: int, db: Session = Depends(get_db)) -> LearningReport:
    row = db.get(LearningReport, report_id)
    if not row:
        raise HTTPException(status_code=404, detail="报告不存在")
    return row


@app.get("/api/reports/{report_id}/feedback", response_model=list[ReportFeedbackRead])
def list_report_feedback(report_id: int, db: Session = Depends(get_db)) -> list[ReportFeedback]:
    if not db.get(LearningReport, report_id):
        raise HTTPException(status_code=404, detail="报告不存在")
    return list(db.scalars(select(ReportFeedback).where(ReportFeedback.report_id == report_id).order_by(ReportFeedback.created_at.desc(), ReportFeedback.id.desc())))


@app.get("/api/reports/{report_id}/feedback/effects")
def report_feedback_effects(report_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    if not db.get(LearningReport, report_id):
        raise HTTPException(status_code=404, detail="报告不存在")
    feedback_rows = list(db.scalars(select(ReportFeedback).where(ReportFeedback.report_id == report_id).order_by(ReportFeedback.created_at.desc(), ReportFeedback.id.desc())))
    proposals = [
        proposal for proposal in db.scalars(select(AgentPlanProposal).order_by(AgentPlanProposal.created_at.desc(), AgentPlanProposal.id.desc()))
        if int((proposal.signal_summary or {}).get("report_id", -1)) == report_id
    ]
    proposal_by_feedback = {int((proposal.signal_summary or {}).get("feedback_id", -1)): proposal for proposal in proposals}
    batches = list(db.scalars(select(AgentChangeBatch).where(AgentChangeBatch.operation == "report_feedback").order_by(AgentChangeBatch.created_at.desc(), AgentChangeBatch.id.desc())))
    batch_by_proposal = {
        int((batch.changes[0] or {}).get("proposal_id")): batch
        for batch in batches
        if batch.changes and isinstance(batch.changes[0], dict) and str((batch.changes[0] or {}).get("proposal_id", "")).isdigit()
    }
    feedback: list[dict[str, Any]] = []
    for row in feedback_rows:
        item = ReportFeedbackRead.model_validate(row).model_dump(mode="json")
        proposal = proposal_by_feedback.get(row.id)
        batch = batch_by_proposal.get(proposal.id) if proposal else None
        item.update({
            "proposal_id": proposal.id if proposal else None,
            "proposal_status": proposal.status if proposal else None,
            "proposal_executed_at": proposal.executed_at.isoformat() if proposal and proposal.executed_at else None,
            "batch_id": batch.id if batch else None,
            "applied_count": len(batch.after_data or []) if batch else 0,
        })
        feedback.append(item)
    summary = {
        "total_feedback": len(feedback_rows),
        "feedback_by_type": {"helpful": 0, "not_helpful": 0, "accepted": 0, "rejected": 0, "adjusted": 0},
        "proposals_total": len(proposals),
        "proposal_status": {"pending": 0, "executed": 0, "partially_executed": 0, "conflict": 0, "rejected": 0},
    }
    for row in feedback_rows:
        if row.feedback_type in summary["feedback_by_type"]:
            summary["feedback_by_type"][row.feedback_type] += 1
        proposal = proposal_by_feedback.get(row.id)
        if proposal and proposal.status in summary["proposal_status"]:
            summary["proposal_status"][proposal.status] += 1
    return {"report_id": report_id, "summary": summary, "feedback": feedback}


@app.post("/api/reports/{report_id}/feedback", response_model=ReportFeedbackRead, status_code=status.HTTP_201_CREATED)
def create_report_feedback(report_id: int, payload: ReportFeedbackCreate, db: Session = Depends(get_db)) -> ReportFeedback:
    report = db.get(LearningReport, report_id)
    if not report:
        raise HTTPException(status_code=404, detail="报告不存在")
    feedback = ReportFeedback(report_id=report_id, **payload.model_dump())
    db.add(feedback)
    db.flush()
    proposal = None
    if payload.feedback_type in {"accepted", "adjusted", "rejected"}:
        raw_changes = ([payload.proposed_change] if payload.proposed_change else [item for item in (report.recommendations or []) if isinstance(item, dict)] + [item for item in (report.proposed_changes or []) if isinstance(item, dict)])
        proposed_changes: list[dict[str, Any]] = []
        for item in raw_changes:
            task_id = item.get("task_id")
            task = db.get(StudyTask, int(task_id)) if str(task_id).isdigit() else None
            if task is not None:
                proposed_changes.append({
                    "entity_type": "task",
                    "operation": "update",
                    "task_id": task.id,
                    "title": task.title,
                    "reason": str(item.get("reason") or item.get("action") or "根据报告反馈调整任务"),
                    "before": {"due_date": task.due_date.isoformat() if task.due_date else None, "priority": task.priority},
                    "after": {key: item[key] for key in ("due_date", "priority") if key in item},
                })
                continue
            title = str(item.get("title") or item.get("action") or "").strip()
            if title:
                proposed_changes.append({
                    "entity_type": "task",
                    "operation": "create",
                    "reason": str(item.get("reason") or "报告反馈建议"),
                    "after": {
                        "title": title[:200],
                        "description": str(item.get("description") or item.get("reason") or "根据报告反馈创建的学习任务")[:5000],
                        "priority": int(item.get("priority") or 2),
                        "estimated_minutes": int(item.get("estimated_minutes") or 30),
                        "due_date": str(item.get("due_date") or (date.today() + timedelta(days=1))),
                        "source": "report_feedback",
                        "task_type": str(item.get("task_type") or "practice"),
                    },
                })
        proposal = AgentPlanProposal(
            status="pending" if payload.feedback_type != "rejected" else "rejected",
            reason=f"报告 #{report.id} 反馈：{payload.feedback_type}。{payload.note}".strip(),
            signal_summary={"report_id": report.id, "feedback_id": feedback.id, "feedback_type": payload.feedback_type},
            changes=proposed_changes,
            impact={"report_id": report.id, "feedback_id": feedback.id, "requires_confirmation": payload.feedback_type != "rejected"},
            executed_at=utcnow() if payload.feedback_type == "rejected" else None,
        )
        db.add(proposal)
        db.flush()
        feedback.proposed_change = {**(payload.proposed_change or {}), "plan_proposal_id": proposal.id, "report_id": report.id, "feedback_type": payload.feedback_type}
    db.commit(); db.refresh(feedback)
    _audit(db, "learning_report", report_id, "feedback", None, ReportFeedbackRead.model_validate(feedback).model_dump(mode="json"))
    return feedback


@app.get("/api/reports/{report_id}/proposals", response_model=list[AgentPlanProposalResponse])
def list_report_proposals(report_id: int, db: Session = Depends(get_db)) -> list[AgentPlanProposalResponse]:
    if not db.get(LearningReport, report_id):
        raise HTTPException(status_code=404, detail="报告不存在")
    rows = db.scalars(select(AgentPlanProposal).where(AgentPlanProposal.signal_summary["report_id"].as_integer() == report_id).order_by(AgentPlanProposal.created_at.desc(), AgentPlanProposal.id.desc()))
    return [_plan_proposal_response(row) for row in rows]


@app.get("/api/reports/{report_id}/export/{file_format}")
def export_report(report_id: int, file_format: str, db: Session = Depends(get_db)) -> Response:
    row = db.get(LearningReport, report_id)
    if not row:
        raise HTTPException(status_code=404, detail="报告不存在")
    if file_format not in {"json", "txt", "md", "html"}:
        raise HTTPException(status_code=422, detail="不支持的导出格式")
    data = _report_payload(row)
    if file_format == "json":
        return JSONResponse(data, headers={"Content-Disposition": f'attachment; filename="learning-report-{row.id}.json"'})
    lines = [f"# {row.title}", f"周期：{row.period_start} 至 {row.period_end}", "", row.summary, "", "## 证据"]
    lines.extend(f"- {item.get('fact')}: {item.get('value')}" for item in row.evidence if isinstance(item, dict))
    lines.append("\n## 成就")
    lines.extend(f"- {item}" for item in row.achievements)
    lines.append("\n## 未完成事项")
    lines.extend(f"- {item.get('title', item)}" if isinstance(item, dict) else f"- {item}" for item in row.unfinished_items)
    lines.append("\n## 薄弱点")
    lines.extend(f"- {item.get('point')}: {item.get('reason')}" if isinstance(item, dict) else f"- {item}" for item in row.weak_points)
    lines.append("\n## 建议（需用户确认后执行）")
    lines.extend(f"- {item.get('action', item)}" if isinstance(item, dict) else f"- {item}" for item in row.recommendations)
    markdown = "\n".join(lines)
    if file_format == "md":
        return Response(markdown, media_type="text/markdown; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="learning-report-{row.id}.md"'})
    if file_format == "txt":
        return PlainTextResponse(markdown.replace("#", ""), headers={"Content-Disposition": f'attachment; filename="learning-report-{row.id}.txt"'})
    html = f"<article><h1>{escape(row.title)}</h1><p>{escape(row.summary)}</p><pre>{escape(markdown)}</pre></article>"
    return HTMLResponse(html, headers={"Content-Disposition": f'attachment; filename="learning-report-{row.id}.html"'})


@app.post("/api/daily-logs/parse")
def parse_daily_log(payload: ParseRequest) -> dict[str, Any]:
    result = router.parse_daily_log(payload.raw_text)
    return {
        "success": result.success,
        "raw_text": payload.raw_text,
        "structured_status": "pending_review" if result.success else "parse_failed",
        "data": result.data or {},
        "provider": result.provider,
        "model_name": result.model_name,
        "error": result.error,
        "duration_ms": result.duration_ms,
    }


@app.post("/api/daily-logs", response_model=DailyLogRead, status_code=status.HTTP_201_CREATED)
def create_daily_log(payload: DailyLogCreate, db: Session = Depends(get_db)) -> DailyLog:
    parsed = None
    # Saving the raw record must stay fast and reliable. Parsing is exposed as
    # a separate preview action so a slow/offline model can never block it.
    parse_fields = ("extracted_topics", "extracted_duration", "extracted_outputs", "understood_content", "unresolved_questions", "completed_tasks", "resolved_questions", "next_steps", "self_assessment")
    if payload.confirm and all(getattr(payload, field) is None for field in parse_fields):
        parsed = router.parse_daily_log(payload.raw_text)

    values = payload.model_dump(exclude={"confirm"})
    values["log_date"] = values["log_date"] or date.today()
    ai_extracted = dict(payload.ai_extracted or {})
    if parsed and parsed.success:
        data = parsed.data or {}
        ai_extracted = dict(data)
        values.update(
            extracted_topics=payload.extracted_topics if payload.extracted_topics is not None else data.get("topics", []),
            extracted_duration=payload.extracted_duration if payload.extracted_duration is not None else data.get("duration_minutes"),
            extracted_outputs=payload.extracted_outputs if payload.extracted_outputs is not None else data.get("outputs", []),
            understood_content=payload.understood_content if payload.understood_content is not None else data.get("understood", []),
            unresolved_questions=payload.unresolved_questions if payload.unresolved_questions is not None else data.get("unresolved_questions", []),
            completed_tasks=payload.completed_tasks if payload.completed_tasks is not None else data.get("completed_tasks", []),
            resolved_questions=payload.resolved_questions if payload.resolved_questions is not None else data.get("resolved_questions", []),
            next_steps=payload.next_steps if payload.next_steps is not None else data.get("next_steps", []),
            self_assessment=payload.self_assessment if payload.self_assessment is not None else data.get("self_assessment"),
        )
    else:
        values.update(
            extracted_topics=values.get("extracted_topics") or [],
            extracted_outputs=values.get("extracted_outputs") or [],
            understood_content=values.get("understood_content") or [],
            unresolved_questions=values.get("unresolved_questions") or [],
            completed_tasks=values.get("completed_tasks") or [],
            resolved_questions=values.get("resolved_questions") or [],
            next_steps=values.get("next_steps") or [],
        )

    values.pop("confirm", None)
    values.pop("confirmed_fields", None)
    values.pop("field_sources", None)
    values["ai_extracted"] = ai_extracted
    if values.get("project_id") is not None and not db.get(LearningProject, values["project_id"]):
        raise HTTPException(status_code=404, detail="项目不存在")
    for topic_id in values.get("topic_ids") or []:
        if not db.get(KnowledgeTopic, topic_id):
            raise HTTPException(status_code=404, detail="关联知识主题不存在")
    for note_id in values.get("note_ids") or []:
        if not db.get(Note, note_id):
            raise HTTPException(status_code=404, detail="关联笔记不存在")
    structured_fields = ("extracted_topics", "extracted_duration", "extracted_outputs", "understood_content", "unresolved_questions", "completed_tasks", "resolved_questions", "next_steps", "self_assessment")
    confirmed_fields = [field for field in structured_fields if getattr(payload, field, None) is not None]
    values["confirmed_fields"] = confirmed_fields if payload.confirm else []
    values["field_sources"] = {field: "user_confirmed" for field in confirmed_fields}
    for field in structured_fields:
        if field not in values["field_sources"] and ai_extracted:
            values["field_sources"][field] = "ai_suggested"
    values["structured_status"] = "confirmed" if payload.confirm and confirmed_fields else "pending_review"
    log = DailyLog(**values)
    db.add(log)
    db.commit()
    db.refresh(log)
    _audit(db, "daily_log", log.id, "create", None, DailyLogRead.model_validate(log).model_dump(mode="json"))
    return log


@app.get("/api/daily-logs", response_model=list[DailyLogRead])
def list_daily_logs(db: Session = Depends(get_db)) -> list[DailyLog]:
    return list(db.scalars(select(DailyLog).order_by(DailyLog.log_date.desc(), DailyLog.id.desc())))


@app.patch("/api/daily-logs/{log_id}", response_model=DailyLogRead)
def update_daily_log(log_id: int, payload: DailyLogUpdate, db: Session = Depends(get_db)) -> DailyLog:
    log = db.get(DailyLog, log_id)
    if not log:
        raise HTTPException(status_code=404, detail="学习记录不存在")
    before = DailyLogRead.model_validate(log).model_dump(mode="json")
    changes = payload.model_dump(exclude_unset=True)
    confirm = changes.pop("confirm", None)
    structured_fields = {"extracted_topics", "extracted_duration", "extracted_outputs", "understood_content", "unresolved_questions", "completed_tasks", "resolved_questions", "next_steps", "self_assessment"}
    confirmed_fields = set(log.confirmed_fields or [])
    sources = dict(log.field_sources or {})
    for field, value in changes.items():
        setattr(log, field, value)
        if field in structured_fields:
            confirmed_fields.add(field)
            sources[field] = "user_confirmed"
    if log.project_id is not None and not db.get(LearningProject, log.project_id):
        raise HTTPException(status_code=404, detail="项目不存在")
    for topic_id in log.topic_ids or []:
        if not db.get(KnowledgeTopic, topic_id):
            raise HTTPException(status_code=404, detail="关联知识主题不存在")
    for note_id in log.note_ids or []:
        if not db.get(Note, note_id):
            raise HTTPException(status_code=404, detail="关联笔记不存在")
    log.confirmed_fields = sorted(confirmed_fields)
    log.field_sources = sources
    if confirm is True and log.confirmed_fields:
        log.structured_status = "confirmed"
    elif confirm is False:
        log.structured_status = "pending_review"
    db.commit()
    db.refresh(log)
    _audit(db, "daily_log", log.id, "update", before, DailyLogRead.model_validate(log).model_dump(mode="json"))
    return log


@app.post("/api/daily-logs/{log_id}/reviews", response_model=ReviewRead, status_code=status.HTTP_201_CREATED)
def create_review(log_id: int, payload: ReviewCreate, db: Session = Depends(get_db)) -> DailyLogReview:
    if not db.get(DailyLog, log_id):
        raise HTTPException(status_code=404, detail="学习记录不存在")
    if payload.topic_id is not None and not db.get(KnowledgeTopic, payload.topic_id):
        raise HTTPException(status_code=404, detail="知识主题不存在")
    review = DailyLogReview(daily_log_id=log_id, **payload.model_dump())
    db.add(review)
    db.commit()
    db.refresh(review)
    _audit(db, "review", review.id, "create", None, ReviewRead.model_validate(review).model_dump(mode="json"))
    return review


@app.get("/api/daily-logs/{log_id}/reviews", response_model=list[ReviewRead])
def list_reviews(log_id: int, db: Session = Depends(get_db)) -> list[DailyLogReview]:
    if not db.get(DailyLog, log_id):
        raise HTTPException(status_code=404, detail="学习记录不存在")
    return list(db.scalars(select(DailyLogReview).where(DailyLogReview.daily_log_id == log_id).order_by(DailyLogReview.review_date, DailyLogReview.id)))


@app.get("/api/reviews/due", response_model=list[ReviewRead])
def due_reviews(db: Session = Depends(get_db)) -> list[DailyLogReview]:
    return list(db.scalars(select(DailyLogReview).where(DailyLogReview.review_date <= date.today(), DailyLogReview.status != "completed").order_by(DailyLogReview.review_date, DailyLogReview.id)))


@app.post("/api/reviews/schedule")
def schedule_reviews(payload: ReviewScheduleRequest | None = None, db: Session = Depends(get_db)) -> dict[str, Any]:
    payload = payload or ReviewScheduleRequest()
    today = date.today()
    end_date = today + timedelta(days=payload.lookahead_days)
    recommendations: list[dict[str, Any]] = []
    logs = list(db.scalars(select(DailyLog).where(DailyLog.log_date <= end_date).order_by(DailyLog.log_date.desc(), DailyLog.id.desc())))
    for log in logs:
        reviews = list(db.scalars(select(DailyLogReview).where(DailyLogReview.daily_log_id == log.id).order_by(DailyLogReview.id.desc())))
        latest = reviews[0] if reviews else None
        if latest and latest.status != "completed":
            continue
        review_date = max(today, log.log_date + timedelta(days=1)) if latest is None else max(today, latest.review_date)
        if review_date > end_date or any(item.review_date == review_date and item.status != "completed" for item in reviews):
            continue
        recommendations.append({
            "daily_log_id": log.id,
            "review_date": review_date.isoformat(),
            "topic_id": (log.topic_ids or [None])[0] if log.topic_ids else None,
            "note": "回忆今天的关键理解、一个例子和仍未解决的问题。",
            "reason": "该学习记录尚未安排下一次复盘。",
        })
        if len(recommendations) >= payload.max_items:
            break
    if not payload.confirmed:
        return {"executed": False, "requires_confirmation": bool(recommendations), "lookahead_days": payload.lookahead_days, "recommendations": recommendations, "created_reviews": []}
    created: list[DailyLogReview] = []
    for item in recommendations:
        review = DailyLogReview(
            daily_log_id=item["daily_log_id"],
            review_date=date.fromisoformat(item["review_date"]),
            topic_id=item["topic_id"],
            note=item["note"],
        )
        db.add(review)
        created.append(review)
    db.commit()
    for review in created:
        db.refresh(review)
        _audit(db, "review", review.id, "schedule", None, ReviewRead.model_validate(review).model_dump(mode="json"))
    return {"executed": True, "requires_confirmation": False, "lookahead_days": payload.lookahead_days, "recommendations": recommendations, "created_reviews": [ReviewRead.model_validate(item).model_dump(mode="json") for item in created]}


@app.get("/api/reminders")
def get_learning_reminders(status_filter: str = "pending", limit: int = 30, db: Session = Depends(get_db)) -> dict[str, Any]:
    if status_filter not in {"pending", "acknowledged", "all"}:
        raise HTTPException(status_code=422, detail="提醒状态必须是 pending、acknowledged 或 all")
    reminders = list_learning_reminders(db, status_filter, limit)
    return {"reminders": reminders, "pending_count": sum(item.get("status") == "pending" for item in reminders)}


@app.post("/api/reminders/refresh")
def refresh_learning_reminder_endpoint(db: Session = Depends(get_db)) -> dict[str, Any]:
    refresh_learning_reminders(db)
    return {"refreshed_at": utcnow(), "reminders": list_learning_reminders(db, "pending", 100)}


@app.post("/api/reminders/{reminder_id}/acknowledge")
def acknowledge_learning_reminder_endpoint(reminder_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    reminder = acknowledge_learning_reminder(db, reminder_id)
    if reminder is None:
        raise HTTPException(status_code=404, detail="提醒不存在")
    _audit(db, "reminder", None, "acknowledge", {"status": "pending"}, reminder)
    return reminder


@app.patch("/api/reviews/{review_id}", response_model=ReviewRead)
def update_review(review_id: int, payload: ReviewUpdate, db: Session = Depends(get_db)) -> DailyLogReview:
    review = db.get(DailyLogReview, review_id)
    if not review:
        raise HTTPException(status_code=404, detail="复习记录不存在")
    if payload.topic_id is not None and not db.get(KnowledgeTopic, payload.topic_id):
        raise HTTPException(status_code=404, detail="知识主题不存在")
    before = ReviewRead.model_validate(review).model_dump(mode="json")
    review.status = payload.status
    if payload.topic_id is not None:
        review.topic_id = payload.topic_id
    if payload.quality is not None:
        quality = payload.quality
        review.quality = quality
        if quality < 3:
            review.repetitions = 0
            review.interval_days = 1
        else:
            review.repetitions += 1
            if review.repetitions == 1:
                review.interval_days = 1
            elif review.repetitions == 2:
                review.interval_days = 6
            else:
                review.interval_days = max(1, round(review.interval_days * review.ease_factor))
            review.ease_factor = max(1.3, review.ease_factor + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02)))
        review.review_date = date.today() + timedelta(days=review.interval_days)
        if review.topic_id:
            topic = db.get(KnowledgeTopic, review.topic_id)
            if topic:
                topic.verified_level = max(topic.verified_level, min(8, topic.verified_level + (1 if quality >= 3 else 0)))
                topic.last_reviewed_at = datetime.now(timezone.utc)
                topic.next_review_at = datetime.now(timezone.utc) + timedelta(days=review.interval_days)
    db.commit(); db.refresh(review)
    _audit(db, "review", review.id, "update", before, ReviewRead.model_validate(review).model_dump(mode="json"))
    return review


@app.post("/api/notes", response_model=NoteRead, status_code=status.HTTP_201_CREATED)
def create_note(payload: NoteCreate, db: Session = Depends(get_db)) -> Note:
    for topic_id in payload.linked_topic_ids:
        if not db.get(KnowledgeTopic, topic_id):
            raise HTTPException(status_code=404, detail="关联知识主题不存在")
    for task_id in payload.linked_task_ids:
        if not db.get(StudyTask, task_id):
            raise HTTPException(status_code=404, detail="关联任务不存在")
    for project_id in payload.linked_project_ids:
        if not db.get(LearningProject, project_id):
            raise HTTPException(status_code=404, detail="关联项目不存在")
    note = Note(**payload.model_dump())
    db.add(note)
    db.flush()
    db.add(NoteVersion(note_id=note.id, version_number=1, title=note.title, content=note.content, summary=note.summary, tags=list(note.tags or []), change_note="初始版本"))
    db.commit()
    db.refresh(note)
    _audit(db, "note", note.id, "create", None, NoteRead.model_validate(note).model_dump(mode="json"))
    return note


@app.patch("/api/notes/{note_id}", response_model=NoteRead)
def update_note(note_id: int, payload: NoteUpdate, db: Session = Depends(get_db)) -> Note:
    note = db.get(Note, note_id)
    if not note:
        raise HTTPException(status_code=404, detail="笔记不存在")
    before = NoteRead.model_validate(note).model_dump(mode="json")
    changes = payload.model_dump(exclude_unset=True)
    if changes:
        current_version = db.scalar(select(func.max(NoteVersion.version_number)).where(NoteVersion.note_id == note.id)) or 0
        db.add(NoteVersion(note_id=note.id, version_number=int(current_version) + 1, title=note.title, content=note.content, summary=note.summary, tags=list(note.tags or []), change_note="更新前快照"))
    for topic_id in changes.get("linked_topic_ids", []):
        if not db.get(KnowledgeTopic, topic_id):
            raise HTTPException(status_code=404, detail="关联知识主题不存在")
    for task_id in changes.get("linked_task_ids") or []:
        if not db.get(StudyTask, task_id):
            raise HTTPException(status_code=404, detail="关联任务不存在")
    for project_id in changes.get("linked_project_ids") or []:
        if not db.get(LearningProject, project_id):
            raise HTTPException(status_code=404, detail="关联项目不存在")
    for field, value in changes.items():
        setattr(note, field, value)
    db.commit()
    db.refresh(note)
    _audit(db, "note", note.id, "update", before, NoteRead.model_validate(note).model_dump(mode="json"))
    return note


@app.get("/api/notes/{note_id}/versions", response_model=list[NoteVersionRead])
def list_note_versions(note_id: int, db: Session = Depends(get_db)) -> list[NoteVersion]:
    if not db.get(Note, note_id):
        raise HTTPException(status_code=404, detail="笔记不存在")
    return list(db.scalars(select(NoteVersion).where(NoteVersion.note_id == note_id).order_by(NoteVersion.version_number.desc())))


def _line_diff(before: str, after: str) -> dict[str, Any]:
    before_lines = before.splitlines()
    after_lines = after.splitlines()
    opcodes = difflib.SequenceMatcher(a=before_lines, b=after_lines, autojunk=False).get_opcodes()
    hunks: list[dict[str, Any]] = []
    for tag, before_start, before_end, after_start, after_end in opcodes:
        if tag == "equal":
            continue
        hunks.append({
            "kind": tag,
            "before_start": before_start + 1,
            "before_count": before_end - before_start,
            "after_start": after_start + 1,
            "after_count": after_end - after_start,
            "before_lines": before_lines[before_start:before_end],
            "after_lines": after_lines[after_start:after_end],
        })
    return {
        "before_line_count": len(before_lines),
        "after_line_count": len(after_lines),
        "hunks": hunks,
    }


@app.get("/api/notes/{note_id}/versions/diff", response_model=NoteVersionDiff)
def diff_note_versions(note_id: int, from_version: int, to_version: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    if not db.get(Note, note_id):
        raise HTTPException(status_code=404, detail="笔记不存在")
    versions = list(db.scalars(select(NoteVersion).where(NoteVersion.note_id == note_id, NoteVersion.version_number.in_([from_version, to_version]))))
    by_number = {item.version_number: item for item in versions}
    if len(by_number) != 2:
        raise HTTPException(status_code=404, detail="笔记版本不存在")
    left = by_number[from_version]
    latest_version = max(by_number)
    right: Any = db.get(Note, note_id) if to_version == latest_version else by_number[to_version]
    fields: dict[str, dict[str, Any]] = {}
    for field in ("title", "content", "summary", "tags"):
        before, after = getattr(left, field), getattr(right, field)
        if before != after:
            fields[field] = {"before": before, "after": after}
    return {
        "note_id": note_id,
        "from_version": from_version,
        "to_version": to_version,
        "fields": fields,
        "content_diff": _line_diff(left.content, right.content),
    }


@app.post("/api/notes/{note_id}/versions/{version_number}/restore", response_model=NoteRead)
def restore_note_version(note_id: int, version_number: int, payload: NoteVersionRestoreRequest | None = None, db: Session = Depends(get_db)) -> Note:
    note = db.get(Note, note_id)
    version = db.scalar(select(NoteVersion).where(NoteVersion.note_id == note_id, NoteVersion.version_number == version_number))
    if not note or not version:
        raise HTTPException(status_code=404, detail="笔记版本不存在")
    request = payload or NoteVersionRestoreRequest(confirmed=True)
    if not request.confirmed:
        raise HTTPException(status_code=409, detail="版本恢复需要确认")
    allowed = {"title", "content", "summary", "tags"}
    fields = [field for field in request.fields if field in allowed]
    if not fields:
        raise HTTPException(status_code=422, detail="至少选择一个可恢复字段")
    current_version = db.scalar(select(func.max(NoteVersion.version_number)).where(NoteVersion.note_id == note.id)) or 0
    db.add(NoteVersion(note_id=note.id, version_number=int(current_version) + 1, title=note.title, content=note.content, summary=note.summary, tags=list(note.tags or []), change_note=f"字段级恢复前版本 {version_number}: {', '.join(fields)}"))
    for field in fields:
        setattr(note, field, list(getattr(version, field) or []) if field == "tags" else getattr(version, field))
    db.commit()
    db.refresh(note)
    return note


@app.get("/api/notes", response_model=list[NoteRead])
def list_notes(q: str | None = None, include_archived: bool = False, db: Session = Depends(get_db)) -> list[Note]:
    notes = list(db.scalars(select(Note).order_by(Note.updated_at.desc(), Note.id.desc())))
    if not include_archived:
        notes = [note for note in notes if note.status != "archived"]
    if q and q.strip():
        needle = q.casefold().strip()
        notes = [note for note in notes if needle in " ".join([note.title, note.content, note.summary, *(note.tags or [])]).casefold()]
    return notes


@app.post("/api/notes/{note_id}/archive", response_model=NoteRead)
def archive_note(note_id: int, db: Session = Depends(get_db)) -> Note:
    note = db.get(Note, note_id)
    if not note:
        raise HTTPException(status_code=404, detail="笔记不存在")
    note.status = "archived"
    db.commit()
    db.refresh(note)
    return note


@app.delete("/api/notes/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_note(note_id: int, db: Session = Depends(get_db)) -> None:
    note = db.get(Note, note_id)
    if not note:
        raise HTTPException(status_code=404, detail="笔记不存在")
    db.delete(note)
    db.commit()


_NOTE_AGENT_APPLY_FIELDS = {"title", "summary", "tags"}


def _note_quality_score(note: Note, review: dict[str, Any]) -> int:
    content = (note.content or "").strip()
    score = 20
    if content:
        score += 20
    if len(content) >= 160:
        score += 15
    if "```" in content:
        score += 15
    if "#" in content:
        score += 10
    if note.tags:
        score += 10
    if note.summary:
        score += 10
    if review.get("technical_issues"):
        score -= min(15, len(review["technical_issues"]) * 5)
    return max(0, min(100, score))


def _deterministic_note_review(note: Note, notes: list[Note], instruction: str) -> dict[str, Any]:
    content = (note.content or "").strip()
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", content) if part.strip()]
    first = paragraphs[0] if paragraphs else ""
    summary = note.summary.strip() if note.summary else first.replace("#", "").strip()[:240]
    headings = [line.lstrip("# ").strip() for line in content.splitlines() if line.lstrip().startswith("#")]
    known_tags = ["Python", "FastAPI", "Flask", "SQL", "SQLite", "HTTP", "Git", "Linux", "算法", "机器学习", "AI Agent", "React", "TypeScript"]
    suggested_tags = list(dict.fromkeys([*(str(tag).strip() for tag in (note.tags or []) if str(tag).strip()), *(tag for tag in known_tags if tag.casefold() in content.casefold())]))[:12]
    if not suggested_tags and headings:
        suggested_tags = headings[:3]
    terms = set(re.findall(r"[A-Za-z][A-Za-z0-9+#.-]{2,}|[\u4e00-\u9fff]{2,8}", f"{note.title} {content}".casefold()))
    related: list[int] = []
    for candidate in notes:
        if candidate.id == note.id:
            continue
        candidate_terms = set(re.findall(r"[A-Za-z][A-Za-z0-9+#.-]{2,}|[\u4e00-\u9fff]{2,8}", f"{candidate.title} {candidate.summary} {' '.join(candidate.tags or [])}".casefold()))
        if terms and len(terms & candidate_terms) >= 1:
            related.append(candidate.id)
    review_questions = []
    if headings:
        review_questions.append(f"你能解释“{headings[0]}”的核心原理和适用边界吗？")
    if "```" in content:
        review_questions.append("这段代码的输入、输出、异常路径和测试证据是什么？")
    if not review_questions:
        review_questions.append("你能用一个新例子复述这篇笔记的核心结论吗？")
    technical_issues = []
    if "TODO" in content or "待补充" in content or "???" in content:
        technical_issues.append("笔记中存在待补充标记，发布或复习前需要完成核对。")
    missing_prerequisites = []
    if "FastAPI" in content and "HTTP" not in content and "REST" not in content:
        missing_prerequisites.append("HTTP/REST 基础")
    if "SQL" in content and "数据库" not in content and "database" not in content.casefold():
        missing_prerequisites.append("数据库基本概念")
    review = {
        "suggested_title": note.title.strip() or "未命名学习笔记",
        "summary": summary,
        "suggested_tags": suggested_tags,
        "technical_issues": technical_issues,
        "missing_prerequisites": missing_prerequisites,
        "related_note_ids": related[:8],
        "review_questions": review_questions[:5],
        "quality_score": 0,
        "quality_dimensions": {"completeness": 0, "structure": 0, "verifiability": 0, "reviewability": 0},
        "instruction": instruction,
    }
    review["quality_score"] = _note_quality_score(note, review)
    review["quality_dimensions"] = {
        "completeness": min(100, 35 + (25 if content else 0) + (20 if note.summary else 0) + (20 if note.tags else 0)),
        "structure": min(100, 35 + (35 if headings else 0) + (30 if "```" in content else 0)),
        "verifiability": min(100, 40 + (30 if "```" in content else 0) + (20 if note.linked_task_ids else 0) + (10 if note.linked_topic_ids else 0)),
        "reviewability": min(100, 50 + (25 if review_questions else 0) + (25 if summary else 0)),
    }
    return review


def _normalize_note_review(data: dict[str, Any], note: Note, notes: list[Note], instruction: str) -> dict[str, Any]:
    fallback = _deterministic_note_review(note, notes, instruction)
    if not isinstance(data, dict):
        return fallback
    result = dict(fallback)
    for key in ("suggested_title", "summary"):
        if isinstance(data.get(key), str) and data[key].strip():
            result[key] = data[key].strip()[:5000 if key == "summary" else 200]
    for key in ("suggested_tags", "technical_issues", "missing_prerequisites", "review_questions"):
        if isinstance(data.get(key), list):
            result[key] = [str(item).strip() for item in data[key] if str(item).strip()][:12]
    if isinstance(data.get("related_note_ids"), list):
        valid_ids = {item.id for item in notes if item.id != note.id}
        result["related_note_ids"] = [int(item) for item in data["related_note_ids"] if str(item).isdigit() and int(item) in valid_ids][:8]
    if isinstance(data.get("quality_score"), (int, float)):
        result["quality_score"] = max(0, min(100, int(data["quality_score"])))
    if isinstance(data.get("quality_dimensions"), dict):
        result["quality_dimensions"] = {str(key): max(0, min(100, int(value))) for key, value in data["quality_dimensions"].items() if isinstance(value, (int, float))}
    return result


@app.post("/api/notes/{note_id}/agent/analyze")
def analyze_note_with_agent(note_id: int, payload: NoteAgentAnalyzeRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    note = db.get(Note, note_id)
    if not note:
        raise HTTPException(status_code=404, detail="笔记不存在")
    notes = list(db.scalars(select(Note).where(Note.status != "archived").order_by(Note.updated_at.desc(), Note.id.desc()).limit(100)))
    required = {"suggested_title", "summary", "suggested_tags", "technical_issues", "missing_prerequisites", "related_note_ids", "review_questions", "quality_score", "quality_dimensions"}
    prompt = (
        "请只输出 JSON，分析一篇个人学习笔记。不要虚构事实，区分建议与已验证事实。"
        "字段必须包含 suggested_title、summary、suggested_tags、technical_issues、missing_prerequisites、"
        "related_note_ids、review_questions、quality_score、quality_dimensions。"
        f"\n用户要求：{payload.instruction}\n笔记标题：{note.title}\n笔记标签：{note.tags or []}\n笔记正文：\n{(note.content or '')[:16000]}"
    )
    result = router.run_structured("format_note", prompt, required)
    review = _normalize_note_review(result.data or {}, note, notes, payload.instruction) if result.success else _deterministic_note_review(note, notes, payload.instruction)
    review.update({"provider": result.provider if result.success else "deterministic", "model_name": result.model_name if result.success else "rule_based", "generation_mode": "model" if result.success else "deterministic", "generated_at": utcnow().isoformat()})
    if not payload.confirmed:
        return {"executed": False, "requires_confirmation": True, "note_id": note.id, "review": review, "warning": "分析结果只作为建议；确认后才会保存分析结果或应用标题、摘要和标签。"}
    fields = [field for field in payload.apply_fields if field in _NOTE_AGENT_APPLY_FIELDS]
    before = NoteRead.model_validate(note).model_dump(mode="json")
    if fields:
        current_version = db.scalar(select(func.max(NoteVersion.version_number)).where(NoteVersion.note_id == note.id)) or 0
        db.add(NoteVersion(note_id=note.id, version_number=int(current_version) + 1, title=note.title, content=note.content, summary=note.summary, tags=list(note.tags or []), change_note=f"笔记 Agent 应用字段：{', '.join(fields)}"))
    if "title" in fields:
        note.title = str(review["suggested_title"])
    if "summary" in fields:
        note.summary = str(review["summary"])
    if "tags" in fields:
        note.tags = list(review["suggested_tags"])
    note.ai_review = review
    note.ai_review_status = "reviewed"
    db.commit()
    db.refresh(note)
    after = NoteRead.model_validate(note).model_dump(mode="json")
    _audit(db, "note", note.id, "agent_review", before, after)
    return {"executed": True, "requires_confirmation": False, "note_id": note.id, "review": review, "applied_fields": fields, "note": after, "warning": "笔记正文未被 Agent 覆盖；应用的元数据已建立版本快照。"}


@app.get("/api/notes/quality-summary")
def note_quality_summary(db: Session = Depends(get_db)) -> dict[str, Any]:
    notes = list(db.scalars(select(Note).where(Note.status != "archived")))
    reviewed = [note for note in notes if note.ai_review_status == "reviewed" and isinstance(note.ai_review, dict)]
    scores = [int(note.ai_review.get("quality_score")) for note in reviewed if isinstance(note.ai_review.get("quality_score"), (int, float))]
    return {"total_notes": len(notes), "reviewed_notes": len(reviewed), "unreviewed_notes": len(notes) - len(reviewed), "average_quality_score": round(sum(scores) / len(scores), 1) if scores else None, "quality_scores": [{"note_id": note.id, "title": note.title, "score": note.ai_review.get("quality_score")} for note in reviewed]}


def _deterministic_blog_draft(note: Note, instruction: str) -> tuple[str, str]:
    title = note.title.strip() or "学习笔记整理"
    summary = (note.summary or "").strip()
    content = (note.content or "").strip()
    tags = [str(tag).strip() for tag in (note.tags or []) if str(tag).strip()]
    excerpt = summary or content.replace("#", "").replace("\n", " ").strip()[:180]
    sections = [f"# {title}", "", "> 本草稿由学习笔记整理生成，发布前请人工核对事实、代码和结论。", ""]
    if excerpt:
        sections.extend(["## 摘要", excerpt, ""])
    sections.extend(["## 学习内容", content or "原笔记尚未记录正文，请在发布前补充。", ""])
    if tags:
        sections.extend(["## 关键词", "、".join(tags), ""])
    sections.extend(["## 实践与思考", "原笔记未提供独立的实践结论，请补充可复现的示例、结果或限制。", "", "## 发布前检查", "- 核对技术事实和版本信息。", "- 补充可运行的示例、输入输出和验证结果。", "- 删除不希望公开的内部信息。"])
    return "\n".join(sections), excerpt


@app.post("/api/notes/{note_id}/blog-drafts/generate")
def generate_blog_draft(note_id: int, payload: BlogDraftGenerateRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    note = db.get(Note, note_id)
    if not note:
        raise HTTPException(status_code=404, detail="笔记不存在")
    content, excerpt = _deterministic_blog_draft(note, payload.instruction)
    version = db.scalar(select(func.max(NoteVersion.version_number)).where(NoteVersion.note_id == note.id))
    preview = {
        "source_note_id": note.id,
        "source_version": int(version) if version is not None else None,
        "title": note.title.strip() or "学习笔记整理",
        "content": content,
        "excerpt": excerpt,
        "generation_mode": "deterministic",
        "model_provider": None,
        "model_name": None,
        "instruction": payload.instruction,
        "warning": "只生成独立草稿，不会覆盖原笔记或自动发布。",
    }
    if not payload.confirmed:
        return {"executed": False, "requires_confirmation": True, "preview": preview}
    draft = BlogDraft(
        source_note_id=note.id,
        source_version=int(version) if version is not None else None,
        title=preview["title"],
        content=content,
        excerpt=excerpt,
        status="draft",
        generation_mode="deterministic",
        source_snapshot={"note_id": note.id, "version": preview["source_version"], "title": note.title, "summary": note.summary, "tags": list(note.tags or []), "content": note.content},
    )
    db.add(draft)
    db.flush()
    result = BlogDraftRead.model_validate(draft).model_dump(mode="json")
    _audit(db, "blog_draft", draft.id, "generate", None, result)
    return {"executed": True, "requires_confirmation": False, "draft": result}


@app.get("/api/notes/{note_id}/blog-drafts", response_model=list[BlogDraftRead])
def list_blog_drafts(note_id: int, db: Session = Depends(get_db)) -> list[BlogDraft]:
    if not db.get(Note, note_id):
        raise HTTPException(status_code=404, detail="笔记不存在")
    return list(db.scalars(select(BlogDraft).where(BlogDraft.source_note_id == note_id).order_by(BlogDraft.updated_at.desc(), BlogDraft.id.desc())))


@app.get("/api/blog-drafts/{draft_id}", response_model=BlogDraftRead)
def get_blog_draft(draft_id: int, db: Session = Depends(get_db)) -> BlogDraft:
    draft = db.get(BlogDraft, draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="博客草稿不存在")
    return draft


def _blog_draft_export(draft: BlogDraft, fmt: str) -> Response:
    filename = f"blog-draft-{draft.id}"
    if fmt == "md":
        return Response(draft.content, media_type="text/markdown", headers={"Content-Disposition": f'attachment; filename="{filename}.md"'})
    if fmt == "txt":
        return PlainTextResponse(draft.content, headers={"Content-Disposition": f'attachment; filename="{filename}.txt"'})
    if fmt == "html":
        rendered = escape(draft.content)
        rendered = re.sub(r"^# (.+)$", r"<h1>\1</h1>", rendered, flags=re.MULTILINE)
        rendered = re.sub(r"^## (.+)$", r"<h2>\1</h2>", rendered, flags=re.MULTILINE)
        rendered = "<p>" + rendered.replace("\n\n", "</p><p>") + "</p>"
        body = f"<!doctype html><html><head><meta charset=\"utf-8\"><title>{escape(draft.title)}</title></head><body>{rendered}</body></html>"
        return HTMLResponse(body, headers={"Content-Disposition": f'attachment; filename="{filename}.html"'})
    raise HTTPException(status_code=422, detail="导出格式必须是 md、txt 或 html")


@app.get("/api/blog-drafts/{draft_id}/export/{fmt}")
def export_blog_draft(draft_id: int, fmt: str, db: Session = Depends(get_db)) -> Response:
    draft = db.get(BlogDraft, draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="博客草稿不存在")
    return _blog_draft_export(draft, fmt)


def _note_export(note: Note, fmt: str) -> Response:
    if fmt == "md":
        fmt = "markdown"
    if fmt == "markdown":
        body = f"# {note.title}\n\n"
        if note.summary:
            body += f"> {note.summary}\n\n"
        if note.tags:
            body += f"标签：{', '.join(note.tags)}\n\n"
        body += note.content
        return Response(body, media_type="text/markdown", headers={"Content-Disposition": f'attachment; filename="note-{note.id}.md"'})
    if fmt == "txt":
        body = f"{note.title}\n\n"
        if note.summary:
            body += f"{note.summary}\n\n"
        body += note.content
        return PlainTextResponse(body, headers={"Content-Disposition": f'attachment; filename="note-{note.id}.txt"'})
    if fmt == "html":
        rendered = re.sub(r"^# (.+)$", r"<h1>\1</h1>", escape(note.content), flags=re.MULTILINE)
        rendered = "<p>" + rendered.replace("\n\n", "</p><p>") + "</p>"
        body = f"<!doctype html><html><head><meta charset=\"utf-8\"><title>{escape(note.title)}</title></head><body><h1>{escape(note.title)}</h1>{rendered}</body></html>"
        return HTMLResponse(body, headers={"Content-Disposition": f'attachment; filename="note-{note.id}.html"'})
    raise HTTPException(status_code=422, detail="导出格式必须是 markdown、txt 或 html")


@app.get("/api/notes/{note_id}/export/{fmt}")
def export_note(note_id: int, fmt: str, db: Session = Depends(get_db)) -> Response:
    note = db.get(Note, note_id)
    if not note:
        raise HTTPException(status_code=404, detail="笔记不存在")
    return _note_export(note, fmt)


@app.get("/api/notes/{note_id}/export")
def export_note_query(note_id: int, format: str = "markdown", db: Session = Depends(get_db)) -> Response:
    note = db.get(Note, note_id)
    if not note:
        raise HTTPException(status_code=404, detail="笔记不存在")
    return _note_export(note, format)


@app.get("/api/review-cards", response_model=list[ReviewCardRead])
def list_review_cards(include_completed: bool = False, include_deleted: bool = False, db: Session = Depends(get_db)) -> list[ReviewCard]:
    query = select(ReviewCard).order_by(ReviewCard.due_date, ReviewCard.id)
    if not include_completed:
        query = query.where(ReviewCard.status != "archived")
    if not include_deleted:
        query = query.where(ReviewCard.status != "deleted")
    return list(db.scalars(query))


@app.get("/api/review-cards/due", response_model=list[ReviewCardRead])
def due_review_cards(db: Session = Depends(get_db)) -> list[ReviewCard]:
    return list(db.scalars(select(ReviewCard).where(ReviewCard.status == "active", ReviewCard.due_date <= date.today()).order_by(ReviewCard.due_date, ReviewCard.id)))


@app.get("/api/review-cards/stats", response_model=ReviewStatsRead)
def review_card_stats(db: Session = Depends(get_db)) -> dict[str, Any]:
    cards = list(db.scalars(select(ReviewCard).where(ReviewCard.status != "deleted")))
    history = list(db.scalars(select(ReviewHistory)))
    qualities = [item.quality for item in history]
    return {
        "total_cards": len(cards),
        "active_cards": sum(card.status == "active" for card in cards),
        "due_cards": sum(card.status == "active" and card.due_date <= date.today() for card in cards),
        "archived_cards": sum(card.status == "archived" for card in cards),
        "review_count": len(history),
        "average_quality": round(sum(qualities) / len(qualities), 2) if qualities else None,
        "mastered_cards": sum(card.status == "active" and card.repetitions >= 5 and card.ease_factor >= 2.5 for card in cards),
    }


@app.get("/api/review-cards/errors")
def review_card_errors(limit: int = 50, db: Session = Depends(get_db)) -> dict[str, Any]:
    cards = list(db.scalars(select(ReviewCard).where(ReviewCard.error_count > 0).order_by(ReviewCard.error_count.desc(), ReviewCard.updated_at.desc()).limit(max(1, min(limit, 200)))))
    by_type: dict[str, int] = {}
    for card in cards:
        key = card.error_type or "未分类"
        by_type[key] = by_type.get(key, 0) + card.error_count
    return {"total_cards": len(cards), "total_errors": sum(by_type.values()), "by_type": by_type, "cards": [ReviewCardRead.model_validate(card).model_dump(mode="json") for card in cards]}


@app.post("/api/review-cards", response_model=ReviewCardRead, status_code=status.HTTP_201_CREATED)
def create_review_card(payload: ReviewCardCreate, db: Session = Depends(get_db)) -> ReviewCard:
    if payload.topic_id is not None and not db.get(KnowledgeTopic, payload.topic_id):
        raise HTTPException(status_code=404, detail="知识主题不存在")
    if payload.source_note_id is not None and not db.get(Note, payload.source_note_id):
        raise HTTPException(status_code=404, detail="来源笔记不存在")
    card = ReviewCard(**payload.model_dump())
    db.add(card)
    db.commit()
    db.refresh(card)
    _audit(db, "review_card", card.id, "create", None, ReviewCardRead.model_validate(card).model_dump(mode="json"))
    return card


@app.patch("/api/review-cards/{card_id}", response_model=ReviewCardRead)
def update_review_card(card_id: int, payload: ReviewCardUpdate, db: Session = Depends(get_db)) -> ReviewCard:
    card = db.get(ReviewCard, card_id)
    if not card or card.status == "deleted":
        raise HTTPException(status_code=404, detail="复习卡片不存在")
    before = ReviewCardRead.model_validate(card).model_dump(mode="json")
    values = payload.model_dump(exclude_unset=True)
    for field, value in values.items():
        setattr(card, field, value)
    db.commit()
    db.refresh(card)
    _audit(db, "review_card", card.id, "update", before, ReviewCardRead.model_validate(card).model_dump(mode="json"))
    return card


@app.post("/api/review-cards/bulk", response_model=list[ReviewCardRead])
def bulk_review_card_action(payload: ReviewCardBulkAction, db: Session = Depends(get_db)) -> list[ReviewCard]:
    cards = list(db.scalars(select(ReviewCard).where(ReviewCard.id.in_(payload.card_ids))))
    if len(cards) != len(set(payload.card_ids)):
        raise HTTPException(status_code=404, detail="部分复习卡片不存在")
    status_value = {"archive": "archived", "restore": "active", "delete": "deleted"}[payload.action]
    before = {card.id: ReviewCardRead.model_validate(card).model_dump(mode="json") for card in cards}
    for card in cards:
        card.status = status_value
    db.commit()
    for card in cards:
        _audit(db, "review_card", card.id, f"bulk_{payload.action}", before[card.id], ReviewCardRead.model_validate(card).model_dump(mode="json"))
    return cards


@app.post("/api/review-cards/{card_id}/archive", response_model=ReviewCardRead)
def archive_review_card(card_id: int, db: Session = Depends(get_db)) -> ReviewCard:
    card = db.get(ReviewCard, card_id)
    if not card or card.status == "deleted":
        raise HTTPException(status_code=404, detail="复习卡片不存在")
    card.status = "archived"
    db.commit()
    db.refresh(card)
    return card


@app.delete("/api/review-cards/{card_id}", response_model=ReviewCardRead)
def delete_review_card(card_id: int, db: Session = Depends(get_db)) -> ReviewCard:
    card = db.get(ReviewCard, card_id)
    if not card:
        raise HTTPException(status_code=404, detail="复习卡片不存在")
    before = ReviewCardRead.model_validate(card).model_dump(mode="json")
    card.status = "deleted"
    db.commit()
    db.refresh(card)
    _audit(db, "review_card", card.id, "delete", before, ReviewCardRead.model_validate(card).model_dump(mode="json"))
    return card


@app.get("/api/review-cards/{card_id}/history", response_model=list[ReviewHistoryRead])
def review_card_history(card_id: int, db: Session = Depends(get_db)) -> list[ReviewHistory]:
    if not db.get(ReviewCard, card_id):
        raise HTTPException(status_code=404, detail="复习卡片不存在")
    return list(db.scalars(select(ReviewHistory).where(ReviewHistory.card_id == card_id).order_by(ReviewHistory.reviewed_at.desc(), ReviewHistory.id.desc())))


@app.post("/api/review-cards/generate")
def generate_review_cards(note_id: int, confirmed: bool = False, db: Session = Depends(get_db)) -> dict[str, Any]:
    note = db.get(Note, note_id)
    if not note:
        raise HTTPException(status_code=404, detail="笔记不存在")
    existing = list(db.scalars(select(ReviewCard).where(ReviewCard.source_note_id == note_id)))
    if existing:
        return {"executed": False, "reused": True, "cards": [ReviewCardRead.model_validate(card).model_dump(mode="json") for card in existing], "preview": []}
    paragraphs = [part.strip() for part in re.split(r"\n{2,}", note.content or "") if part.strip()]
    candidates = paragraphs[:5] or [note.summary or note.title]
    preview: list[dict[str, Any]] = []
    for index, paragraph in enumerate(candidates, start=1):
        front = f"请用自己的话解释《{note.title}》中的第 {index} 个要点。"
        preview.append({"front": front, "back": paragraph[:10000], "hint": "先回忆概念、关键步骤和一个例子。", "source_note_id": note_id})
    if not confirmed:
        return {"executed": False, "requires_confirmation": True, "cards": [], "preview": preview}
    cards: list[ReviewCard] = []
    entries: list[dict[str, Any]] = []
    for item in preview:
        card = ReviewCard(front=item["front"], back=item["back"], hint=item["hint"], source_note_id=note_id)
        db.add(card)
        db.flush()
        cards.append(card)
        entries.append({"entity_type": "review_card", "entity_id": card.id, "before": None, "after": ReviewCardRead.model_validate(card).model_dump(mode="json"), "created": True})
    batch = AgentChangeBatch(operation="review_card_generate", status="executed", changes=[{"note_id": note_id}], before_data=[{"entity_type": item["entity_type"], "entity_id": item["entity_id"], "data": None} for item in entries], after_data=[{"entity_type": item["entity_type"], "entity_id": item["entity_id"], "data": item["after"], "created": True} for item in entries])
    db.add(batch)
    db.commit()
    for card in cards:
        db.refresh(card)
    _audit(db, "review_card", note_id, "generate", None, {"batch_id": batch.id, "card_ids": [card.id for card in cards]})
    return {"executed": True, "batch_id": batch.id, "cards": [ReviewCardRead.model_validate(card).model_dump(mode="json") for card in cards], "preview": preview}


@app.post("/api/review-cards/{card_id}/answer", response_model=ReviewCardRead)
def answer_review_card(card_id: int, payload: ReviewCardAnswer, db: Session = Depends(get_db)) -> ReviewCard:
    card = db.get(ReviewCard, card_id)
    if not card:
        raise HTTPException(status_code=404, detail="复习卡片不存在")
    if card.status != "active":
        raise HTTPException(status_code=409, detail="只有 active 状态的卡片可以复习")
    quality = payload.quality
    if quality < 3:
        card.error_count += 1
        card.error_type = payload.error_type or card.error_type or "回忆失败"
        card.last_error_note = payload.error_note.strip()
    today = date.today()
    before = {"interval": card.interval_days, "ease": card.ease_factor, "repetitions": card.repetitions, "due": card.due_date}
    card.last_quality = quality
    if quality < 3:
        card.repetitions = 0
        card.interval_days = 1
        card.ease_factor = max(1.3, card.ease_factor - 0.2)
    else:
        card.repetitions += 1
        if card.repetitions == 1:
            card.interval_days = 1
        elif card.repetitions == 2:
            card.interval_days = 6
        else:
            card.interval_days = max(1, round(card.interval_days * card.ease_factor))
        card.ease_factor = max(1.3, card.ease_factor + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02)))
    card.due_date = today + timedelta(days=card.interval_days)
    db.add(ReviewHistory(card_id=card.id, quality=quality, interval_before=before["interval"], interval_after=card.interval_days, ease_before=before["ease"], ease_after=card.ease_factor, repetitions_before=before["repetitions"], repetitions_after=card.repetitions, due_before=before["due"], due_after=card.due_date, error_type=payload.error_type if quality < 3 else None, error_note=payload.error_note.strip() if quality < 3 else ""))
    db.commit()
    db.refresh(card)
    _audit(db, "review_card", card.id, "answer", {"quality": before.get("quality"), **before}, ReviewCardRead.model_validate(card).model_dump(mode="json"))
    return card


def _validate_teaching_links(db: Session, topic_id: int | None, task_id: int | None, stage_id: int | None) -> None:
    if topic_id is not None and not db.get(KnowledgeTopic, topic_id):
        raise HTTPException(status_code=404, detail="知识主题不存在")
    if task_id is not None and not db.get(StudyTask, task_id):
        raise HTTPException(status_code=404, detail="学习任务不存在")
    if stage_id is not None and not db.get(LearningStage, stage_id):
        raise HTTPException(status_code=404, detail="学习阶段不存在")


def _teaching_attempt_payload(attempt: TeachingAttempt) -> dict[str, Any]:
    return TeachingAttemptRead.model_validate(attempt).model_dump(mode="json")


@app.get("/api/teaching/sessions", response_model=list[TeachingSessionRead])
def list_teaching_sessions(limit: int = 20, db: Session = Depends(get_db)) -> list[TeachingSession]:
    return list(db.scalars(select(TeachingSession).order_by(TeachingSession.updated_at.desc(), TeachingSession.id.desc()).limit(max(1, min(limit, 100)))))


@app.post("/api/teaching/sessions", response_model=TeachingSessionRead, status_code=status.HTTP_201_CREATED)
def create_teaching_session(payload: TeachingSessionCreate, db: Session = Depends(get_db)) -> TeachingSession:
    _validate_teaching_links(db, payload.topic_id, payload.task_id, payload.stage_id)
    session = TeachingSession(**payload.model_dump())
    db.add(session)
    db.commit()
    db.refresh(session)
    _audit(db, "teaching_session", session.id, "create", None, TeachingSessionRead.model_validate(session).model_dump(mode="json"))
    return session


@app.post("/api/teaching/sessions/{session_id}/generate", response_model=TeachingSessionRead)
def generate_teaching_material(session_id: int, payload: TeachingGenerateRequest, db: Session = Depends(get_db)) -> TeachingSession:
    session = db.get(TeachingSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="教学会话不存在")
    context_parts = [f"主题：{session.title}", f"已有讲解：{session.explanation}", f"用户要求：{payload.instruction}"]
    if session.topic_id:
        topic = db.get(KnowledgeTopic, session.topic_id)
        if topic:
            context_parts.append(f"主题定义：{topic.definition}")
    result = router.run_task("teaching", "\n".join(context_parts), confirmed=payload.confirmed)
    if not result.success:
        raise HTTPException(status_code=503, detail=result.error or "教学内容生成失败")
    generated = result.text or ""
    session.explanation = generated[:12000]
    if not session.attempts:
        interview_mode = session.title.startswith("模拟面试 · ")
        if interview_mode:
            prompt = f"请结合你为“{session.title.removeprefix('模拟面试 · ')}”岗位准备的一个真实项目或学习经历，说明背景、关键技术决策、结果，以及一次复盘。"
            rubric = ["背景与目标", "技术决策", "结果证据", "复盘与改进"]
            phase = "interview"
        else:
            prompt = f"请用自己的话解释：{session.title}"
            rubric = ["核心定义", "关键机制", "具体例子"]
            phase = "practice"
        db.add(TeachingAttempt(session=session, topic_id=session.topic_id, task_id=session.task_id, stage_id=session.stage_id, phase=phase, prompt=prompt, expected_answer=session.explanation, rubric=rubric))
    session.updated_at = utcnow()
    db.commit()
    db.refresh(session)
    return session


@app.get("/api/teaching/sessions/{session_id}", response_model=TeachingSessionRead)
def get_teaching_session(session_id: int, db: Session = Depends(get_db)) -> TeachingSession:
    session = db.get(TeachingSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="教学会话不存在")
    return session


@app.post("/api/teaching/sessions/{session_id}/attempts", response_model=TeachingAttemptRead, status_code=status.HTTP_201_CREATED)
def create_teaching_attempt(session_id: int, payload: TeachingAttemptCreate, db: Session = Depends(get_db)) -> TeachingAttempt:
    session = db.get(TeachingSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="教学会话不存在")
    _validate_teaching_links(db, payload.topic_id or session.topic_id, payload.task_id or session.task_id, payload.stage_id or session.stage_id)
    attempt = TeachingAttempt(session_id=session_id, topic_id=payload.topic_id if payload.topic_id is not None else session.topic_id, task_id=payload.task_id if payload.task_id is not None else session.task_id, stage_id=payload.stage_id if payload.stage_id is not None else session.stage_id, phase=payload.phase, prompt=payload.prompt, expected_answer=payload.expected_answer, rubric=payload.rubric)
    db.add(attempt)
    session.updated_at = utcnow()
    db.commit()
    db.refresh(attempt)
    _audit(db, "teaching_attempt", attempt.id, "create", None, TeachingAttemptRead.model_validate(attempt).model_dump(mode="json"))
    return attempt


@app.post("/api/teaching/sessions/{session_id}/attempts/{attempt_id}/answer", response_model=TeachingAttemptRead)
def answer_teaching_attempt(session_id: int, attempt_id: int, payload: TeachingAnswerRequest, db: Session = Depends(get_db)) -> TeachingAttempt:
    attempt = db.get(TeachingAttempt, attempt_id)
    if not attempt or attempt.session_id != session_id:
        raise HTTPException(status_code=404, detail="教学练习不存在")
    if attempt.evaluated_at is not None:
        raise HTTPException(status_code=409, detail="该练习已经评价，不能重复作答")
    before = TeachingAttemptRead.model_validate(attempt).model_dump(mode="json")
    attempt.user_answer = payload.user_answer.strip()
    attempt.answered_at = utcnow()
    db.commit()
    db.refresh(attempt)
    _audit(db, "teaching_attempt", attempt.id, "answer", before, TeachingAttemptRead.model_validate(attempt).model_dump(mode="json"))
    return attempt


def _evaluate_teaching_attempt(attempt: TeachingAttempt) -> dict[str, Any]:
    answer = attempt.user_answer.strip()
    expected = attempt.expected_answer.strip()
    rubric = [str(item) for item in (attempt.rubric or [])]
    if not answer:
        return {"score": 0, "confidence": 1.0, "covered_rubric": [], "missing_rubric": rubric, "misconceptions": ["未作答"], "error_type": "未作答", "feedback": "请先用自己的话回答问题，再进行评价。", "recommendation": "重新阅读讲解后，用一个最小例子解释该主题。", "source": "local_deterministic"}
    expected_tokens = {token.casefold() for token in re.findall(r"[A-Za-z0-9_一-龥]{2,}", expected)}
    answer_tokens = {token.casefold() for token in re.findall(r"[A-Za-z0-9_一-龥]{2,}", answer)}
    overlap = len(expected_tokens & answer_tokens) / max(1, len(expected_tokens)) if expected else 0.0
    covered = [item for item in rubric if any(token.casefold() in answer.casefold() for token in re.findall(r"[A-Za-z0-9_一-龥]{2,}", item))]
    missing = [item for item in rubric if item not in covered]
    score = 5 if overlap >= 0.75 else 4 if overlap >= 0.5 else 3 if overlap >= 0.25 else 2
    error_type = None if score >= 4 else ("关键概念遗漏" if score == 3 else "概念理解不足")
    feedback = "回答覆盖了主要要点。下一步尝试解释一个边界情况或反例。" if score >= 4 else "回答与参考要点的重合较少。请回到定义和关键步骤，重新组织答案。"
    recommendation = "一周后安排一次间隔复习，巩固迁移能力。" if score >= 4 else "已标记为薄弱点，建议创建复习卡片并在 1 天内重试。"
    return {"score": score, "confidence": round(min(0.95, 0.55 + overlap * 0.4), 2), "covered_rubric": covered, "missing_rubric": missing, "misconceptions": [error_type] if error_type else [], "error_type": error_type, "feedback": feedback, "recommendation": recommendation, "source": "local_deterministic"}


def _validate_structured_teaching_evaluation(data: Any, attempt: TeachingAttempt) -> dict[str, Any] | None:
    if not isinstance(data, dict):
        return None
    score = data.get("score")
    confidence = data.get("confidence")
    required = ("covered_rubric", "missing_rubric", "misconceptions", "feedback", "recommendation")
    if not isinstance(score, int) or score < 0 or score > 5 or not isinstance(confidence, (int, float)) or not 0 <= float(confidence) <= 1:
        return None
    if any(not isinstance(data.get(key), list) for key in required[:3]) or any(not isinstance(data.get(key), str) or not data.get(key).strip() for key in required[3:]):
        return None
    error_type = data.get("error_type")
    if error_type is not None and not isinstance(error_type, str):
        return None
    return {"score": score, "confidence": float(confidence), "covered_rubric": [str(item) for item in data["covered_rubric"]][:20], "missing_rubric": [str(item) for item in data["missing_rubric"]][:20], "misconceptions": [str(item) for item in data["misconceptions"]][:20], "error_type": error_type, "feedback": data["feedback"][:5000], "recommendation": data["recommendation"][:5000], "source": "structured_model"}


@app.post("/api/teaching/sessions/{session_id}/attempts/{attempt_id}/evaluate", response_model=TeachingAttemptRead)
def evaluate_teaching_attempt(session_id: int, attempt_id: int, db: Session = Depends(get_db)) -> TeachingAttempt:
    attempt = db.get(TeachingAttempt, attempt_id)
    if not attempt or attempt.session_id != session_id:
        raise HTTPException(status_code=404, detail="教学练习不存在")
    if not attempt.user_answer.strip():
        raise HTTPException(status_code=409, detail="请先提交作答内容")
    attempt_pk = attempt.id
    local_evaluation = _evaluate_teaching_attempt(attempt)
    evaluation = local_evaluation
    safe_prompt = json.dumps({"question": attempt.prompt[:4000], "reference_answer": attempt.expected_answer[:6000], "rubric": [str(item)[:200] for item in (attempt.rubric or [])][:20], "user_answer": attempt.user_answer[:6000]}, ensure_ascii=False)
    model_result = router.run_task("teaching_evaluation", "请只返回 JSON。评价用户回答，字段必须包含 score(0-5整数)、confidence(0-1数字)、covered_rubric(字符串数组)、missing_rubric(字符串数组)、misconceptions(字符串数组)、error_type(字符串或null)、feedback(字符串)、recommendation(字符串)。不要补充 JSON 之外的内容。\n" + safe_prompt)
    model_data = model_result.data
    if model_data is None and model_result.text:
        try:
            model_data = json.loads(model_result.text)
        except (TypeError, ValueError, json.JSONDecodeError):
            model_data = None
    structured = _validate_structured_teaching_evaluation(model_data, attempt)
    if structured and structured["score"] < 4 and not structured["error_type"]:
        # A weak answer must remain actionable even when a local model omits
        # the optional error label from an otherwise valid response.
        structured["error_type"] = local_evaluation["error_type"] or "关键概念遗漏"
    if structured and structured["confidence"] >= 0.65:
        evaluation = structured
    refreshed_attempt = db.get(TeachingAttempt, attempt_pk)
    if refreshed_attempt is not None:
        attempt = refreshed_attempt
    attempt.score = evaluation["score"]
    attempt.error_type = evaluation["error_type"]
    attempt.feedback = evaluation["feedback"]
    attempt.recommendation = evaluation["recommendation"]
    attempt.evaluation_source = evaluation["source"]
    attempt.evaluation_confidence = evaluation["confidence"]
    attempt.evaluation_details = {"covered_rubric": evaluation["covered_rubric"], "missing_rubric": evaluation["missing_rubric"], "misconceptions": evaluation["misconceptions"]}
    attempt.evaluated_at = utcnow()
    if evaluation["score"] < 4 and not attempt.review_card_id:
        card = ReviewCard(front=attempt.prompt, back=attempt.expected_answer or attempt.feedback, hint="先回忆定义、关键步骤和一个例子。", topic_id=attempt.topic_id)
        db.add(card)
        db.flush()
        attempt.review_card_id = card.id
    session = db.get(TeachingSession, session_id)
    if session:
        session.status = "completed" if all(item.evaluated_at is not None for item in session.attempts) else "active"
        session.updated_at = utcnow()
    db.commit()
    db.refresh(attempt)
    _audit(db, "teaching_attempt", attempt.id, "evaluate", None, TeachingAttemptRead.model_validate(attempt).model_dump(mode="json"))
    return attempt


@app.get("/api/teaching/sessions/{session_id}/recommendations")
def teaching_recommendations(session_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    session = db.get(TeachingSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="教学会话不存在")
    attempts = list(db.scalars(select(TeachingAttempt).where(TeachingAttempt.session_id == session_id).order_by(TeachingAttempt.id)))
    weak = [item for item in attempts if item.score is not None and item.score < 4]
    return {"session_id": session_id, "weak_attempts": [_teaching_attempt_payload(item) for item in weak], "review_card_ids": [item.review_card_id for item in weak if item.review_card_id], "recommendations": [item.recommendation for item in weak if item.recommendation]}


@app.post("/api/knowledge-topics", response_model=TopicRead, status_code=status.HTTP_201_CREATED)
def create_topic(payload: TopicCreate, db: Session = Depends(get_db)) -> KnowledgeTopic:
    topic = KnowledgeTopic(**payload.model_dump())
    db.add(topic)
    db.commit()
    db.refresh(topic)
    _audit(db, "knowledge_topic", topic.id, "create", None, TopicRead.model_validate(topic).model_dump(mode="json"))
    return topic


@app.patch("/api/knowledge-topics/{topic_id}", response_model=TopicRead)
def update_topic(topic_id: int, payload: TopicUpdate, db: Session = Depends(get_db)) -> KnowledgeTopic:
    topic = db.get(KnowledgeTopic, topic_id)
    if not topic:
        raise HTTPException(status_code=404, detail="知识主题不存在")
    before = TopicRead.model_validate(topic).model_dump(mode="json")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(topic, field, value)
    db.commit()
    db.refresh(topic)
    _audit(db, "knowledge_topic", topic.id, "update", before, TopicRead.model_validate(topic).model_dump(mode="json"))
    return topic


@app.post("/api/knowledge-topics/{topic_id}/verify", response_model=TopicRead)
def verify_topic(topic_id: int, payload: TopicVerificationCreate, db: Session = Depends(get_db)) -> KnowledgeTopic:
    topic = db.get(KnowledgeTopic, topic_id)
    if not topic:
        raise HTTPException(status_code=404, detail="知识主题不存在")
    before = TopicRead.model_validate(topic).model_dump(mode="json")
    evidence = list(topic.evidence or [])
    evidence.append({
        "source_type": payload.source_type,
        "evidence": payload.evidence.strip(),
        "verified_level": payload.verified_level,
        "created_at": utcnow().isoformat(),
    })
    topic.verified_level = payload.verified_level
    topic.evidence = evidence
    topic.last_reviewed_at = utcnow()
    db.commit()
    db.refresh(topic)
    _audit(db, "knowledge_topic", topic.id, "verify", before, TopicRead.model_validate(topic).model_dump(mode="json"))
    return topic


@app.get("/api/knowledge-topics", response_model=list[TopicRead])
def list_topics(q: str | None = None, tag: str | None = None, db: Session = Depends(get_db)) -> list[KnowledgeTopic]:
    topics = list(db.scalars(select(KnowledgeTopic).order_by(KnowledgeTopic.domain, KnowledgeTopic.name)))
    if q and q.strip():
        needle = q.casefold().strip()
        topics = [topic for topic in topics if needle in " ".join((topic.name, topic.domain, topic.definition)).casefold()]
    if tag and tag.strip():
        needle = tag.casefold().strip()
        topics = [topic for topic in topics if any(needle == item.casefold() for item in (topic.tags or []))]
    return topics


@app.post("/api/knowledge-topics/{topic_id}/relations", response_model=TopicRelationRead, status_code=status.HTTP_201_CREATED)
def create_topic_relation(topic_id: int, payload: TopicRelationCreate, db: Session = Depends(get_db)) -> KnowledgeTopicRelation:
    if topic_id == payload.target_topic_id:
        raise HTTPException(status_code=422, detail="知识主题不能关联自身")
    if not db.get(KnowledgeTopic, topic_id) or not db.get(KnowledgeTopic, payload.target_topic_id):
        raise HTTPException(status_code=404, detail="知识主题不存在")
    existing = db.scalar(select(KnowledgeTopicRelation).where(KnowledgeTopicRelation.source_topic_id == topic_id, KnowledgeTopicRelation.target_topic_id == payload.target_topic_id, KnowledgeTopicRelation.relation_type == payload.relation_type))
    if existing:
        raise HTTPException(status_code=409, detail="知识关系已存在")
    relation = KnowledgeTopicRelation(source_topic_id=topic_id, **payload.model_dump())
    db.add(relation)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="知识关系已存在")
    db.refresh(relation)
    _audit(db, "knowledge_relation", relation.id, "create", None, TopicRelationRead.model_validate(relation).model_dump(mode="json"))
    return relation


@app.get("/api/knowledge-topics/{topic_id}/relations", response_model=list[TopicRelationRead])
def list_topic_relations(topic_id: int, db: Session = Depends(get_db)) -> list[KnowledgeTopicRelation]:
    if not db.get(KnowledgeTopic, topic_id):
        raise HTTPException(status_code=404, detail="知识主题不存在")
    return list(db.scalars(select(KnowledgeTopicRelation).where(KnowledgeTopicRelation.source_topic_id == topic_id).order_by(KnowledgeTopicRelation.id)))


@app.delete("/api/knowledge-relations/{relation_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_topic_relation(relation_id: int, db: Session = Depends(get_db)) -> None:
    relation = db.get(KnowledgeTopicRelation, relation_id)
    if not relation:
        raise HTTPException(status_code=404, detail="知识关系不存在")
    before = TopicRelationRead.model_validate(relation).model_dump(mode="json")
    db.delete(relation)
    db.commit()
    _audit(db, "knowledge_relation", relation_id, "delete", before, None)


@app.get("/api/knowledge-graph/layout")
def get_knowledge_graph_layout(db: Session = Depends(get_db)) -> dict[str, Any]:
    layout = db.scalar(select(KnowledgeGraphLayout).order_by(KnowledgeGraphLayout.id))
    if not layout:
        return {"node_positions": {}, "zoom": 1.0, "updated_at": None}
    return {"node_positions": layout.node_positions or {}, "zoom": layout.zoom, "updated_at": layout.updated_at}


@app.put("/api/knowledge-graph/layout")
def update_knowledge_graph_layout(payload: GraphLayoutUpdate, db: Session = Depends(get_db)) -> dict[str, Any]:
    layout = db.scalar(select(KnowledgeGraphLayout).order_by(KnowledgeGraphLayout.id))
    if layout is None:
        layout = KnowledgeGraphLayout(node_positions=payload.node_positions, zoom=payload.zoom)
        db.add(layout)
    else:
        layout.node_positions = payload.node_positions
        layout.zoom = payload.zoom
    db.commit(); db.refresh(layout)
    return {"node_positions": layout.node_positions or {}, "zoom": layout.zoom, "updated_at": layout.updated_at}


@app.get("/api/knowledge-graph")
def knowledge_graph(job_direction: str | None = None, db: Session = Depends(get_db)) -> dict[str, Any]:
    topics = list(db.scalars(select(KnowledgeTopic).order_by(KnowledgeTopic.name)))
    relations = list(db.scalars(select(KnowledgeTopicRelation).order_by(KnowledgeTopicRelation.id)))
    tasks = list(db.scalars(select(StudyTask)))
    notes = list(db.scalars(select(Note)))
    degrees: dict[int, int] = {topic.id: 0 for topic in topics}
    for relation in relations:
        degrees[relation.source_topic_id] = degrees.get(relation.source_topic_id, 0) + 1
        degrees[relation.target_topic_id] = degrees.get(relation.target_topic_id, 0) + 1
    topic_practice = {topic.id: sum(task.topic_id == topic.id for task in tasks) for topic in topics}
    topic_notes = {topic.id: sum(topic.id in (note.linked_topic_ids or []) for note in notes) for topic in topics}
    profile = db.scalar(select(UserProfile).order_by(UserProfile.id))
    directions = [str(item).strip() for item in (profile.target_job_directions if profile else []) if str(item).strip()]
    selected_direction = job_direction.strip() if job_direction and job_direction.strip() else (directions[0] if directions else None)
    direction_keywords = {
        "后端开发": {"python", "fastapi", "flask", "http", "web", "数据库", "sql", "操作系统", "linux", "git", "测试", "并发"},
        "数据开发": {"python", "sql", "数据库", "pandas", "etl", "linux", "spark", "数据结构", "数据分析"},
        "ai agent": {"python", "llm", "agent", "api", "工具调用", "结构化输出", "rag", "机器学习", "模型"},
    }
    direction_key = (selected_direction or "").casefold()
    keywords = direction_keywords.get(direction_key, {direction_key} if direction_key else set())
    relevant_topics = [topic for topic in topics if keywords and any(keyword.casefold() in " ".join([topic.name, topic.domain, *(topic.tags or [])]).casefold() for keyword in keywords)]
    direction_gaps = [{"topic_id": topic.id, "name": topic.name, "reason": "验证等级低" if topic.verified_level < 4 else "缺少实践证据" if topic_practice[topic.id] == 0 else "缺少关联笔记"} for topic in relevant_topics if topic.verified_level < 4 or topic_practice[topic.id] == 0 or topic_notes[topic.id] == 0]
    return {
        "nodes": [{"id": topic.id, "name": topic.name, "domain": topic.domain, "verified_level": topic.verified_level, "degree": degrees.get(topic.id, 0), "practice_count": topic_practice[topic.id], "note_count": topic_notes[topic.id], "weak": topic.verified_level < 4, "orphan": degrees.get(topic.id, 0) == 0} for topic in topics],
        "edges": [TopicRelationRead.model_validate(relation).model_dump(mode="json") for relation in relations],
        "analysis": {
            "weak_topics": [topic.name for topic in topics if topic.verified_level < 4],
            "orphan_topics": [topic.name for topic in topics if degrees.get(topic.id, 0) == 0],
            "learned_without_practice": [topic.name for topic in topics if topic.verified_level >= 4 and topic_practice[topic.id] == 0],
            "practice_without_notes": [topic.name for topic in topics if topic_practice[topic.id] > 0 and topic_notes[topic.id] == 0],
            "prerequisite_gaps": [topic.name for topic in topics if topic.prerequisites and any(degrees.get(prerequisite, 0) == 0 for prerequisite in topic.prerequisites)],
            "job_direction": selected_direction,
            "job_directions": directions,
            "job_relevant_topics": [topic.name for topic in relevant_topics],
            "job_direction_gaps": direction_gaps,
        },
    }


@app.get("/api/capabilities")
def list_capabilities(db: Session = Depends(get_db)) -> dict[str, Any]:
    profiles = list(db.scalars(select(CapabilityProfile).order_by(CapabilityProfile.level, CapabilityProfile.name)))
    return {"profiles": [{"id": item.id, "name": item.name, "description": item.description, "level": item.level, "confidence": item.confidence, "evidence_count": item.evidence_count, "last_assessed_at": item.last_assessed_at, "evidence": item.evidence or []} for item in profiles]}


@app.post("/api/capabilities/assess")
def assess_capabilities(db: Session = Depends(get_db)) -> dict[str, Any]:
    tasks = list(db.scalars(select(StudyTask)))
    logs = list(db.scalars(select(DailyLog)))
    projects = list(db.scalars(select(LearningProject)))
    topics = list(db.scalars(select(KnowledgeTopic)))
    attempts = list(db.scalars(select(TeachingAttempt)))
    practice_exercises = {item.id: item for item in db.scalars(select(PracticeExercise))}
    practice_attempts = list(db.scalars(select(PracticeAttempt)))
    code_runs = list(db.scalars(select(CodeRun)))
    cards = {card.id: card for card in db.scalars(select(ReviewCard))}
    names = sorted({name for stage in db.scalars(select(LearningStage)) for name in (stage.capability_targets or [])} | {topic.domain for topic in topics if topic.domain})
    if not names:
        names = ["计算机基础", "工程实践", "问题解决"]
    now = datetime.now(timezone.utc)
    results = []
    verified_task_ids = {item.task_id for item in db.scalars(select(TaskVerification))}
    for name in names:
        needle = name.casefold()
        task_evidence = [task for task in tasks if needle in task.title.casefold() or needle in task.description.casefold()]
        log_evidence = [log for log in logs if log.structured_status == "confirmed" and any(needle in str(topic).casefold() for topic in (log.extracted_topics or []))]
        project_evidence = [
            project for project in projects
            if any(
                isinstance(milestone, dict)
                and str(milestone.get("status", "")).casefold() in {"completed", "done", "已完成"}
                and str(milestone.get("evidence", "")).strip()
                and needle in str(milestone.get("title", milestone.get("name", ""))).casefold()
                for milestone in (project.milestones or [])
            )
        ]
        topic_evidence = [topic for topic in topics if (needle == str(topic.domain or "").casefold() or needle in topic.name.casefold()) and bool(topic.evidence)]
        teaching_evidence = [attempt for attempt in attempts if any(needle in str(value or "").casefold() for value in (attempt.prompt, attempt.expected_answer, attempt.feedback))]
        practice_evidence = [attempt for attempt in practice_attempts if (exercise := practice_exercises.get(attempt.exercise_id)) and (exercise.topic_id in {topic.id for topic in topics if needle == str(topic.domain or "").casefold() or needle in topic.name.casefold()} or needle in f"{exercise.title} {exercise.prompt}".casefold())]
        code_evidence = [run for run in code_runs if run.exercise_id in {item.exercise_id for item in practice_evidence} and run.status == "completed"]
        evidence_rows = (
            [("task", item.id, 1.0 if item.status in {"completed", "mastered"} else 0.3, item.updated_at) for item in task_evidence if item.id in verified_task_ids]
            + [("daily_log", item.id, 0.25, item.updated_at) for item in log_evidence]
            + [("project_milestone", item.id, 1.0, item.updated_at) for item in project_evidence]
            + [("topic", item.id, min(1.0, item.verified_level / 8), item.updated_at) for item in topic_evidence]
            + [("teaching_attempt", item.id, (item.score or 0) / 5, item.evaluated_at or item.created_at) for item in teaching_evidence if item.score is not None]
            + [("practice_attempt", item.id, 1.0 if item.passed else 0.2, item.created_at) for item in practice_evidence]
            + [("code_run", item.id, 0.7, item.created_at) for item in code_evidence]
        )
        evidence_count = len(evidence_rows)
        completed = sum(task.status in {"completed", "mastered"} and task.id in verified_task_ids for task in task_evidence)
        teaching_score = sum(row[2] for row in evidence_rows if row[0] == "teaching_attempt")
        practice_score = sum(row[2] for row in evidence_rows if row[0] == "practice_attempt")
        level = min(8.0, round(completed * 1.5 + len(project_evidence) * 1.0 + len(log_evidence) * 0.25 + len(topic_evidence) * 0.5 + teaching_score * 0.5 + practice_score * 0.75 + len(code_evidence) * 0.35, 2))
        profile = db.scalar(select(CapabilityProfile).where(CapabilityProfile.name == name))
        if profile is None:
            profile = CapabilityProfile(name=name, description="基于任务、日志、项目、知识主题和教学作答证据自动汇总")
            db.add(profile); db.flush()
        previous_level = float(profile.level or 0.0)
        db.query(CapabilityEvidence).filter(CapabilityEvidence.capability_id == profile.id).delete(synchronize_session=False)
        profile.level = level
        profile.confidence = round(min(1.0, evidence_count / 8), 2)
        profile.evidence_count = evidence_count
        profile.last_assessed_at = now
        profile.evidence = [{"source_type": source_type, "source_id": source_id, "score": score} for source_type, source_id, score, _created_at in evidence_rows]
        for source_type, source_id, score, created_at in evidence_rows:
            db.add(CapabilityEvidence(capability_id=profile.id, source_type=source_type, source_id=source_id, score=score, note="自动评估证据", created_at=created_at or now))
        db.add(CapabilityAssessment(capability_id=profile.id, previous_level=previous_level, new_level=profile.level, evidence_count=evidence_count, evidence_snapshot=profile.evidence or [], trigger="manual"))
        results.append({"id": profile.id, "name": profile.name, "level": profile.level, "confidence": profile.confidence, "evidence_count": profile.evidence_count})
    db.commit()
    return {"assessed_at": now, "profiles": results}



def _search_snippet(value: str, query: str, limit: int = 180) -> str:
    text = " ".join(str(value or "").split())
    if not text:
        return ""
    needle = query.casefold()
    position = text.casefold().find(needle)
    if position < 0:
        return text[:limit]
    start = max(0, position - 55)
    end = min(len(text), position + len(query) + 110)
    prefix = "…" if start else ""
    suffix = "…" if end < len(text) else ""
    return f"{prefix}{text[start:end]}{suffix}"


def _search_item(kind: str, item_id: int, title: str, subtitle: str, searchable: str, query: str, route: str) -> SearchResultItem | None:
    if query.casefold() not in searchable.casefold():
        return None
    return SearchResultItem(id=item_id, title=title, subtitle=subtitle, snippet=_search_snippet(searchable, query), route=route, kind=kind)


@app.get("/api/search", response_model=GlobalSearchResponse)
def global_search(q: str = "", limit: int = 8, db: Session = Depends(get_db)) -> GlobalSearchResponse:
    query = q.strip()
    if not query:
        return GlobalSearchResponse(query="", total=0, results=[], grouped={})
    per_kind_limit = max(1, min(limit, 20))
    grouped: dict[str, list[SearchResultItem]] = {}

    def add(kind: str, item: SearchResultItem | None) -> None:
        if item is not None and len(grouped.setdefault(kind, [])) < per_kind_limit:
            grouped[kind].append(item)

    for item in db.scalars(select(StudyTask).order_by(StudyTask.updated_at.desc(), StudyTask.id.desc())):
        add("tasks", _search_item("tasks", item.id, item.title, f"任务 · {item.status}", f"{item.title} {item.description} {item.acceptance_criteria}", query, "plan"))
    for item in db.scalars(select(DailyLog).order_by(DailyLog.log_date.desc(), DailyLog.id.desc())):
        topics = "、".join(str(value) for value in item.extracted_topics or [])
        add("daily_logs", _search_item("daily_logs", item.id, item.raw_text[:72] or "学习记录", f"{item.log_date} · 学习记录", f"{item.raw_text} {topics}", query, "logs"))
    for item in db.scalars(select(Note).order_by(Note.updated_at.desc(), Note.id.desc())):
        tags = "、".join(item.tags or [])
        add("notes", _search_item("notes", item.id, item.title, f"笔记 · {item.folder}", f"{item.title} {item.summary} {item.content} {tags}", query, "notes"))
    for item in db.scalars(select(KnowledgeTopic).order_by(KnowledgeTopic.updated_at.desc(), KnowledgeTopic.id.desc())):
        tags = "、".join(item.tags or [])
        add("topics", _search_item("topics", item.id, item.name, f"知识主题 · {item.domain}", f"{item.name} {item.domain} {item.definition} {tags}", query, "knowledge"))
    for item in db.scalars(select(LearningProject).order_by(LearningProject.updated_at.desc(), LearningProject.id.desc())):
        skills = "、".join(item.skills or [])
        outcomes = "、".join(item.outcomes or [])
        add("projects", _search_item("projects", item.id, item.title, f"项目 · {item.status}", f"{item.title} {item.description} {skills} {outcomes}", query, "projects"))
    for item in db.scalars(select(ImportedFile).order_by(ImportedFile.imported_at.desc(), ImportedFile.id.desc())):
        add("imports", _search_item("imports", item.id, item.relative_path, "导入文件", f"{item.relative_path} {_read_imported_content(item)}", query, "imports"))
    for item in db.scalars(select(WebResource).order_by(WebResource.created_at.desc(), WebResource.id.desc())):
        add("imports", _search_item("imports", item.id, item.title or item.final_url, "网页资料", f"{item.title} {item.final_url} {_read_web_content(item)}", query, "imports"))
    for item in db.scalars(select(GitHubCommit).order_by(GitHubCommit.committed_at.desc(), GitHubCommit.id.desc())):
        add("projects", _search_item("projects", item.id, item.message.splitlines()[0][:120] or item.sha[:7], "GitHub 提交", f"{item.message} {item.sha} {item.author_name} {item.author_login}", query, "projects"))

    results = [item for items in grouped.values() for item in items]
    return GlobalSearchResponse(query=query, total=len(results), results=results, grouped=grouped)


@app.get("/api/dashboard", response_model=DashboardRead)
def dashboard(db: Session = Depends(get_db)) -> dict[str, Any]:
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    recent_start = today - timedelta(days=6)
    previous_start = today - timedelta(days=13)
    previous_end = recent_start - timedelta(days=1)
    tasks = list(db.scalars(select(StudyTask).where(StudyTask.due_date == today, StudyTask.status.not_in(["completed", "mastered"])).order_by(StudyTask.priority, StudyTask.id)))
    logs = list(db.scalars(select(DailyLog).order_by(DailyLog.log_date.desc(), DailyLog.id.desc()).limit(5)))
    goal = db.scalar(select(LearningGoal).where(LearningGoal.status == "active").order_by(LearningGoal.priority, LearningGoal.id))
    stage = None
    if goal:
        stage = db.scalar(select(LearningStage).where(LearningStage.goal_id == goal.id, LearningStage.status == "active").order_by(LearningStage.order_index, LearningStage.id))
    week_logs = list(db.scalars(select(DailyLog).where(DailyLog.log_date >= week_start)))
    weekly_minutes = sum(log.extracted_duration or 0 for log in week_logs)
    output_count = sum(len(log.extracted_outputs or []) for log in week_logs)
    pending = sum(log.structured_status == "pending_review" for log in db.scalars(select(DailyLog)))
    due = list(db.scalars(select(DailyLogReview).where(DailyLogReview.review_date <= today, DailyLogReview.status != "completed").order_by(DailyLogReview.review_date, DailyLogReview.id).limit(8)))
    weak_capabilities = [
        {"id": item.id, "name": item.name, "level": item.level, "confidence": item.confidence, "evidence_count": item.evidence_count}
        for item in db.scalars(select(CapabilityProfile).where((CapabilityProfile.level < 3) | (CapabilityProfile.confidence < 0.5)).order_by(CapabilityProfile.level, CapabilityProfile.confidence, CapabilityProfile.name).limit(6))
    ]
    active_projects = list(db.scalars(select(LearningProject).where(LearningProject.status.in_(["active", "in_progress"])).order_by(LearningProject.updated_at.desc(), LearningProject.id.desc()).limit(6)))
    recent_notes = list(db.scalars(select(Note).where(Note.status != "archived").order_by(Note.updated_at.desc(), Note.id.desc()).limit(6)))
    recent_logs = list(db.scalars(select(DailyLog).where(DailyLog.log_date >= recent_start)))
    previous_logs = list(db.scalars(select(DailyLog).where(DailyLog.log_date >= previous_start, DailyLog.log_date <= previous_end)))
    recent_tasks = list(db.scalars(select(StudyTask).where(StudyTask.completed_at.is_not(None), StudyTask.completed_at >= datetime.combine(recent_start, datetime.min.time(), tzinfo=timezone.utc))))
    previous_tasks = list(db.scalars(select(StudyTask).where(StudyTask.completed_at.is_not(None), StudyTask.completed_at >= datetime.combine(previous_start, datetime.min.time(), tzinfo=timezone.utc), StudyTask.completed_at < datetime.combine(recent_start, datetime.min.time(), tzinfo=timezone.utc))))
    recent_note_count = int(db.scalar(select(func.count(Note.id)).where(Note.created_at >= datetime.combine(recent_start, datetime.min.time(), tzinfo=timezone.utc))) or 0)
    previous_note_count = int(db.scalar(select(func.count(Note.id)).where(Note.created_at >= datetime.combine(previous_start, datetime.min.time(), tzinfo=timezone.utc), Note.created_at < datetime.combine(recent_start, datetime.min.time(), tzinfo=timezone.utc))) or 0)
    recent_minutes = sum(log.extracted_duration or 0 for log in recent_logs) + sum(task.actual_minutes or 0 for task in recent_tasks)
    previous_minutes = sum(log.extracted_duration or 0 for log in previous_logs) + sum(task.actual_minutes or 0 for task in previous_tasks)
    recent_evidence = sum(len(log.extracted_outputs or []) + len(log.understood_content or []) for log in recent_logs) + len(recent_tasks) + recent_note_count
    previous_evidence = sum(len(log.extracted_outputs or []) + len(log.understood_content or []) for log in previous_logs) + len(previous_tasks) + previous_note_count
    if recent_evidence == 0 and recent_minutes == 0:
        progress_status = "no_recent_activity"
        progress_summary = "最近 7 天还没有可识别的学习产出或验证记录。"
    elif recent_evidence > previous_evidence or recent_minutes > previous_minutes:
        progress_status = "progress"
        progress_summary = "最近 7 天产生了新的学习证据，继续保持并优先完成一个可验证输出。"
    elif recent_evidence < previous_evidence and recent_minutes < previous_minutes:
        progress_status = "slower"
        progress_summary = "最近 7 天仍有学习记录，但投入和可验证产出低于前 7 天。"
    else:
        progress_status = "steady"
        progress_summary = "最近 7 天保持了学习节奏，暂未观察到明显的增减变化。"
    progress_signal = {"status": progress_status, "summary": progress_summary, "window_days": 7, "recent_minutes": recent_minutes, "previous_minutes": previous_minutes, "recent_evidence_count": recent_evidence, "previous_evidence_count": previous_evidence, "recent_completed_tasks": len(recent_tasks), "recent_notes": recent_note_count, "basis": ["学习日志时长与产出", "已验收任务", "新增笔记"]}
    suggestions: list[dict[str, Any]] = []
    if due:
        suggestions.append({"type": "review", "priority": "优先", "title": f"有 {len(due)} 个知识点该复习了", "detail": "先做一轮短复习，再开始今天的新内容。", "route": "reviews"})
    if weak_capabilities:
        suggestions.append({"type": "capability", "priority": "建议", "title": f"{weak_capabilities[0]['name']}还需要多练一练", "detail": "找一道小练习动手做，完成后再回来看看有没有变化。", "route": "capabilities"})
    if not tasks:
        suggestions.append({"type": "planning", "priority": "建议", "title": "今天还没有安排任务", "detail": "从当前阶段挑一件半小时内能完成的小事。", "route": "plan"})
    if pending:
        suggestions.append({"type": "log", "priority": "稍后", "title": f"有 {pending} 条学习记录还没整理完", "detail": "把主题、做出的内容和没解决的问题补完整，之后回看会更方便。", "route": "logs"})
    return {"today_tasks": tasks, "recent_logs": logs, "current_goal": goal, "current_stage": stage, "weekly_minutes": weekly_minutes, "output_count": output_count, "pending_review_count": pending, "due_reviews": due, "weak_capabilities": weak_capabilities, "active_projects": active_projects, "recent_notes": recent_notes, "agent_suggestions": suggestions[:6], "progress_signal": progress_signal}


@app.get("/api/exports/json")
def export_json(db: Session = Depends(get_db)) -> JSONResponse:
    return JSONResponse(_full_backup(db))


def _readable_export_markdown(db: Session) -> str:
    lines = ["# 学习工作站导出", "", f"生成时间：{datetime.now(timezone.utc).isoformat()}", ""]
    goals = list(db.scalars(select(LearningGoal).order_by(LearningGoal.priority, LearningGoal.id)))
    stages = list(db.scalars(select(LearningStage).order_by(LearningStage.goal_id, LearningStage.order_index, LearningStage.id)))
    tasks = list(db.scalars(select(StudyTask).order_by(StudyTask.due_date, StudyTask.priority, StudyTask.id)))
    logs = list(db.scalars(select(DailyLog).order_by(DailyLog.log_date.desc(), DailyLog.id.desc())))
    notes = list(db.scalars(select(Note).order_by(Note.updated_at.desc(), Note.id.desc())))
    topics = list(db.scalars(select(KnowledgeTopic).order_by(KnowledgeTopic.name, KnowledgeTopic.id)))
    projects = list(db.scalars(select(LearningProject).order_by(LearningProject.updated_at.desc(), LearningProject.id.desc())))

    lines.extend(["## 学习目标与阶段", ""])
    if not goals:
        lines.append("暂无学习目标。\n")
    for goal in goals:
        lines.extend([f"### {goal.title}", "", goal.description or "暂无描述", "", f"状态：{goal.status} · 优先级：P{goal.priority}", ""])
        for stage in [item for item in stages if item.goal_id == goal.id]:
            lines.append(f"- 阶段：{stage.title}（{stage.status}）")
            if stage.capability_targets:
                lines.append(f"  - 能力目标：{'、'.join(stage.capability_targets)}")
        lines.append("")

    lines.extend(["## 任务", ""])
    if not tasks:
        lines.append("暂无任务。\n")
    for task in tasks:
        due = task.due_date.isoformat() if task.due_date else "未排期"
        lines.append(f"- [{task.status}] {task.title}（{due}，P{task.priority}，预计 {task.estimated_minutes or '—'} 分钟）")
        if task.expected_outcome:
            lines.append(f"  - 预期结果：{task.expected_outcome}")
        if task.acceptance_criteria:
            lines.append(f"  - 验收标准：{task.acceptance_criteria}")
    lines.append("")

    lines.extend(["## 学习记录", ""])
    if not logs:
        lines.append("暂无学习记录。\n")
    for log in logs:
        lines.extend([f"### {log.log_date.isoformat()} · 学习记录 #{log.id}", "", log.raw_text or "", ""])
        if log.extracted_topics:
            lines.append(f"主题：{'、'.join(str(item) for item in log.extracted_topics)}")
        if log.extracted_duration is not None:
            lines.append(f"学习时长：{log.extracted_duration} 分钟")
        if log.extracted_outputs:
            lines.append(f"产出：{'、'.join(str(item) for item in log.extracted_outputs)}")
        if log.unresolved_questions:
            lines.append(f"未解决问题：{'、'.join(str(item) for item in log.unresolved_questions)}")
        lines.append("")

    lines.extend(["## 笔记", ""])
    if not notes:
        lines.append("暂无笔记。\n")
    for note in notes:
        lines.extend([f"### {note.title}", "", f"状态：{note.status} · 文件夹：{note.folder or '未分类'}"])
        if note.tags:
            lines.append(f"标签：{', '.join(note.tags)}")
        if note.summary:
            lines.extend(["", f"> {note.summary}"])
        lines.extend(["", note.content or "", ""])

    lines.extend(["## 知识主题", ""])
    if not topics:
        lines.append("暂无知识主题。\n")
    for topic in topics:
        lines.append(f"- **{topic.name}**（{topic.domain or '未分类'}，自评 {topic.self_level}，验证等级 {topic.verified_level}/8）")
        if topic.definition:
            lines.append(f"  - 定义：{topic.definition}")
        if topic.tags:
            lines.append(f"  - 标签：{'、'.join(topic.tags)}")
    lines.append("")

    lines.extend(["## 项目", ""])
    if not projects:
        lines.append("暂无项目。\n")
    for project in projects:
        lines.extend([f"### {project.title}", "", project.description or "暂无描述", "", f"状态：{project.status}"])
        if project.skills:
            lines.append(f"技能：{'、'.join(project.skills)}")
        if project.outcomes:
            lines.append(f"成果：{'、'.join(project.outcomes)}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _readable_export_text(markdown: str) -> str:
    text = re.sub(r"^#{1,6}\s*", "", markdown, flags=re.MULTILINE)
    text = re.sub(r"^\s*[-*+]\s+", "- ", text, flags=re.MULTILINE)
    text = text.replace("**", "").replace("`", "")
    return text


def _readable_export_html(markdown: str) -> str:
    html_lines: list[str] = []
    in_list = False
    in_code = False
    for raw_line in markdown.splitlines():
        line = raw_line.strip()
        if line.startswith("```"):
            if in_code:
                html_lines.append("</code></pre>")
            else:
                html_lines.append("<pre><code>")
            in_code = not in_code
            continue
        if in_code:
            html_lines.append(escape(raw_line))
            continue
        if line.startswith("# ") or line.startswith("## ") or line.startswith("### "):
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            level = len(line) - len(line.lstrip("#"))
            html_lines.append(f"<h{level}>{escape(line[level + 1:])}</h{level}>")
        elif line.startswith("- "):
            if not in_list:
                html_lines.append("<ul>")
                in_list = True
            html_lines.append(f"<li>{escape(line[2:])}</li>")
        elif not line:
            if in_list:
                html_lines.append("</ul>")
                in_list = False
        else:
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            html_lines.append(f"<p>{escape(line)}</p>")
    if in_list:
        html_lines.append("</ul>")
    if in_code:
        html_lines.append("</code></pre>")
    body = "\n".join(html_lines)
    return f'<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>学习工作站导出</title><style>body{{max-width:900px;margin:40px auto;padding:0 20px;font:16px/1.75 system-ui,sans-serif;color:#20252b}}pre{{overflow:auto;background:#f3f5f7;padding:16px}}li{{margin:4px 0}}</style></head><body>{body}</body></html>'


@app.get("/api/exports/{file_format}")
def export_readable(file_format: str, db: Session = Depends(get_db)) -> Response:
    normalized = file_format.lower()
    if normalized not in {"md", "markdown", "txt", "html"}:
        raise HTTPException(status_code=422, detail="导出格式必须是 md、markdown、txt 或 html")
    markdown = _readable_export_markdown(db)
    if normalized in {"md", "markdown"}:
        return Response(markdown, media_type="text/markdown", headers={"Content-Disposition": 'attachment; filename="learning-workstation.md"'})
    if normalized == "txt":
        return PlainTextResponse(_readable_export_text(markdown), headers={"Content-Disposition": 'attachment; filename="learning-workstation.txt"'})
    return HTMLResponse(_readable_export_html(markdown), headers={"Content-Disposition": 'attachment; filename="learning-workstation.html"'})


def _full_backup(db: Session) -> dict[str, Any]:
    return {
        "goals": [GoalRead.model_validate(item).model_dump(mode="json") for item in db.scalars(select(LearningGoal))],
        "stages": [StageRead.model_validate(item).model_dump(mode="json") for item in db.scalars(select(LearningStage))],
        "tasks": [TaskRead.model_validate(item).model_dump(mode="json") for item in db.scalars(select(StudyTask))],
        "task_time_entries": [TaskTimeEntryRead.model_validate(item).model_dump(mode="json") for item in db.scalars(select(TaskTimeEntry))],
        "task_verifications": [TaskVerificationRead.model_validate(item).model_dump(mode="json") for item in db.scalars(select(TaskVerification))],
        "daily_logs": [DailyLogRead.model_validate(item).model_dump(mode="json") for item in db.scalars(select(DailyLog))],
        "notes": [NoteRead.model_validate(item).model_dump(mode="json") for item in db.scalars(select(Note))],
        "blog_drafts": [
            {
                "id": item.id,
                "source_note_id": item.source_note_id,
                "source_version": item.source_version,
                "title": item.title,
                "content": item.content,
                "excerpt": item.excerpt,
                "status": item.status,
                "generation_mode": item.generation_mode,
                "model_provider": item.model_provider,
                "model_name": item.model_name,
                "source_snapshot": item.source_snapshot or {},
                "created_at": item.created_at.isoformat() if item.created_at else None,
                "updated_at": item.updated_at.isoformat() if item.updated_at else None,
            }
            for item in db.scalars(select(BlogDraft))
        ],
        "knowledge_topics":  [TopicRead.model_validate(item).model_dump(mode="json") for item in db.scalars(select(KnowledgeTopic))],
        "knowledge_relations": [
            {
                "id": item.id,
                "source_topic_id": item.source_topic_id,
                "target_topic_id": item.target_topic_id,
                "relation_type": item.relation_type,
            }
            for item in db.scalars(select(KnowledgeTopicRelation))
        ],
        "projects": [ProjectRead.model_validate(item).model_dump(mode="json") for item in db.scalars(select(LearningProject))],
        "project_milestones": [ProjectMilestoneRead.model_validate(item).model_dump(mode="json") for item in db.scalars(select(ProjectMilestone))],
        "reviews": [ReviewRead.model_validate(item).model_dump(mode="json") for item in db.scalars(select(DailyLogReview))],
        "weekly_plans": [WeeklyPlanRead.model_validate(item).model_dump(mode="json") for item in db.scalars(select(WeeklyPlan))],
        "learning_reports": [_report_payload(item) for item in db.scalars(select(LearningReport))],
        "review_cards": [ReviewCardRead.model_validate(item).model_dump(mode="json") for item in db.scalars(select(ReviewCard))],
        "review_history": [ReviewHistoryRead.model_validate(item).model_dump(mode="json") for item in db.scalars(select(ReviewHistory))],
        "teaching_sessions": [TeachingSessionRead.model_validate(item).model_dump(mode="json") for item in db.scalars(select(TeachingSession))],
        "teaching_attempts": [TeachingAttemptRead.model_validate(item).model_dump(mode="json") for item in db.scalars(select(TeachingAttempt))],
        "capabilities": [{"id": item.id, "name": item.name, "description": item.description, "level": item.level, "confidence": item.confidence, "evidence_count": item.evidence_count, "last_assessed_at": item.last_assessed_at.isoformat() if item.last_assessed_at else None, "evidence": item.evidence or []} for item in db.scalars(select(CapabilityProfile))],
        "capability_assessments": [CapabilityAssessmentRead.model_validate(item).model_dump(mode="json") for item in db.scalars(select(CapabilityAssessment))],
        "practice_exercises": [PracticeExerciseRead.model_validate(item).model_dump(mode="json") for item in db.scalars(select(PracticeExercise))],
        "practice_attempts": [PracticeAttemptRead.model_validate(item).model_dump(mode="json") for item in db.scalars(select(PracticeAttempt))],
        "code_runs": [CodeRunRead.model_validate(item).model_dump(mode="json") for item in db.scalars(select(CodeRun))],
        "authorized_directories": [
            {
                "id": item.id,
                "path": item.path,
                "label": item.label,
                "active": item.active,
                "local_analysis": item.local_analysis,
                "cloud_transfer": item.cloud_transfer,
                "write_access": item.write_access,
                "excluded_extensions": item.excluded_extensions or [],
                "authorized_at": item.authorized_at.isoformat() if item.authorized_at else None,
                "revoked_at": item.revoked_at.isoformat() if item.revoked_at else None,
                "last_scanned_at": item.last_scanned_at.isoformat() if item.last_scanned_at else None,
                "scan_enabled": item.scan_enabled,
            }
            for item in db.scalars(select(AuthorizedDirectory))
        ],
        "file_imports": [
            {
                "id": item.id,
                "directory_id": item.directory_id,
                "files": item.files or [],
                "excluded": item.excluded or {},
                "files_scanned": item.files_scanned,
                "created_at": item.created_at.isoformat() if item.created_at else None,
            }
            for item in db.scalars(select(FileImport))
        ],
        "imported_files": [
            {
                "id": item.id,
                "import_id": item.import_id,
                "relative_path": item.relative_path,
                "sha256": item.sha256,
                "size": item.size,
                "mime_type": item.mime_type,
                "content_status": item.content_status,
                "raw_file_path": item.raw_file_path,
                "content_file_path": item.content_file_path,
                "index_file_path": item.index_file_path,
                "content_sha256": item.content_sha256,
                "index_sha256": item.index_sha256,
                "index_status": item.index_status,
                "last_verified_at": item.last_verified_at.isoformat() if item.last_verified_at else None,
                "imported_at": item.imported_at.isoformat() if item.imported_at else None,
            }
            for item in db.scalars(select(ImportedFile))
        ],
        "file_analyses": [
            {
                "id": item.id,
                "imported_file_id": item.imported_file_id,
                "provider": item.provider,
                "model_name": item.model_name,
                "analysis_version": item.analysis_version,
                "status": item.status,
                "result_file_path": item.result_file_path,
                "result_sha256": item.result_sha256,
                "confirmed": item.confirmed,
                "created_at": item.created_at.isoformat() if item.created_at else None,
                "confirmed_at": item.confirmed_at.isoformat() if item.confirmed_at else None,
            }
            for item in db.scalars(select(FileAnalysis))
        ],
        "web_resources": [
            {
                "id": item.id,
                "url": item.url,
                "final_url": item.final_url,
                "title": item.title,
                "sha256": item.sha256,
                "size": item.size,
                "mime_type": item.mime_type,
                "content_status": item.content_status,
                "parse_error": item.parse_error,
                "raw_file_path": item.raw_file_path,
                "content_file_path": item.content_file_path,
                "index_file_path": item.index_file_path,
                "content_sha256": item.content_sha256,
                "index_sha256": item.index_sha256,
                "index_status": item.index_status,
                "fetched_at": item.fetched_at.isoformat() if item.fetched_at else None,
                "confirmed_at": item.confirmed_at.isoformat() if item.confirmed_at else None,
                "created_at": item.created_at.isoformat() if item.created_at else None,
            }
            for item in db.scalars(select(WebResource))
        ],
        "github_repositories": [
            {
                "id": item.id,
                "project_id": item.project_id,
                "owner": item.owner,
                "name": item.name,
                "full_name": item.full_name,
                "html_url": item.html_url,
                "default_branch": item.default_branch,
                "private": item.private,
                "description": item.description,
                "last_synced_sha": item.last_synced_sha,
                "last_sync_at": item.last_sync_at.isoformat() if item.last_sync_at else None,
                "created_at": item.created_at.isoformat() if item.created_at else None,
                "updated_at": item.updated_at.isoformat() if item.updated_at else None,
            }
            for item in db.scalars(select(GitHubRepository))
        ],
        "github_commits": [
            {
                "id": item.id,
                "repository_id": item.repository_id,
                "sha": item.sha,
                "message": item.message,
                "author_name": item.author_name,
                "author_login": item.author_login,
                "committed_at": item.committed_at.isoformat() if item.committed_at else None,
                "html_url": item.html_url,
                "additions": item.additions,
                "deletions": item.deletions,
                "changed_files": item.changed_files,
                "files": item.files or [],
                "analysis_status": item.analysis_status,
                "analysis": item.analysis or {},
                "analysis_confirmed": item.analysis_confirmed,
                "imported_at": item.imported_at.isoformat() if item.imported_at else None,
            }
            for item in db.scalars(select(GitHubCommit))
        ],
        "job_analyses": [
            {
                "id": item.id,
                "title": item.title,
                "source_text": item.source_text,
                "source_hash": item.source_hash,
                "extracted_skills": item.extracted_skills or [],
                "matched_topics": item.matched_topics or [],
                "matched_capabilities": item.matched_capabilities or [],
                "project_evidence": item.project_evidence or [],
                "gaps": item.gaps or [],
                "recommendations": item.recommendations or [],
                "confidence": item.confidence,
                "created_at": item.created_at.isoformat() if item.created_at else None,
                "updated_at": item.updated_at.isoformat() if item.updated_at else None,
            }
            for item in db.scalars(select(JobAnalysis))
        ],
        "chat_messages": [
            {"id": item.id, "session_id": item.session_id, "role": item.role, "content": item.content, "created_at": item.created_at.isoformat() if item.created_at else None}
            for item in db.scalars(select(ChatMessage))
        ],
        "model_calls": [
            {
                "id": item.id,
                "task_type": item.task_type,
                "risk_level": item.risk_level,
                "provider": item.provider,
                "model_name": item.model_name,
                "upgraded": item.upgraded,
                "input_length": item.input_length,
                "output_length": item.output_length,
                "input_tokens": item.input_tokens,
                "output_tokens": item.output_tokens,
                "total_tokens": item.total_tokens,
                "token_source": item.token_source,
                "duration_ms": item.duration_ms,
                "estimated_cost": item.estimated_cost,
                "success": item.success,
                "confidence": item.confidence,
                "route_reason": item.route_reason,
                "created_at": item.created_at.isoformat() if item.created_at else None,
            }
            for item in db.scalars(select(ModelCallLog))
        ],
    }


BACKUP_KEYS = (
    "goals",
    "stages",
    "tasks",
    "task_time_entries",
    "task_verifications",
    "daily_logs",
    "notes",
    "blog_drafts",
    "knowledge_topics",
    "knowledge_relations",
    "projects",
    "project_milestones",
    "reviews",
    "weekly_plans",
    "learning_reports",
    "review_cards",
    "review_history",
    "teaching_sessions",
    "teaching_attempts",
    "authorized_directories",
    "capabilities",
    "capability_assessments",
    "practice_exercises",
    "practice_attempts",
    "code_runs",
    "file_imports",
    "imported_files",
    "file_analyses",
    "web_resources",
    "github_repositories",
    "github_commits",
    "job_analyses",
    "chat_messages",
    "model_calls",
)


def _backup_summary(backup: dict[str, Any]) -> dict[str, int]:
    return {key: len(backup.get(key) or []) for key in BACKUP_KEYS}


def _backup_hash(backup: dict[str, Any]) -> str:
    encoded = json.dumps(backup, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _canonical_snapshot_value(value: Any) -> Any:
    """Normalize ORM values for stable restore-conflict comparisons."""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {
            str(key): _canonical_snapshot_value(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_canonical_snapshot_value(item) for item in value]
    return value


def _restore_row_snapshot(row: Any) -> dict[str, Any]:
    """Capture scalar state so restore undo never deletes a later-modified row."""
    mapper = sa_inspect(row).mapper
    return {
        column.key: _canonical_snapshot_value(getattr(row, column.key))
        for column in mapper.columns
    }


def _restore_snapshot_matches(row: Any, expected: dict[str, Any]) -> bool:
    current = _restore_row_snapshot(row)
    canonical_expected = _canonical_snapshot_value(expected or {})
    return json.dumps(current, ensure_ascii=False, sort_keys=True, default=str) == json.dumps(canonical_expected, ensure_ascii=False, sort_keys=True, default=str)


@app.get("/api/backup/json")
def backup_json(db: Session = Depends(get_db)) -> JSONResponse:
    return JSONResponse(_full_backup(db))


@app.post("/api/backup/snapshots")
def create_backup_snapshot(payload: dict[str, Any] | None = None, db: Session = Depends(get_db)) -> dict[str, Any]:
    payload = payload or {}
    backup = payload.get("backup") if isinstance(payload.get("backup"), dict) else _full_backup(db)
    label = str(payload.get("label") or "手动快照").strip()[:200]
    source = str(payload.get("source") or "local").strip()[:40]
    digest = _backup_hash(backup)
    existing = db.scalar(select(BackupSnapshot).where(BackupSnapshot.sha256 == digest))
    if existing:
        return {"created": False, "reused": True, "snapshot": {"id": existing.id, "label": existing.label, "source": existing.source, "sha256": existing.sha256, "summary": existing.summary, "created_at": existing.created_at}}
    snapshot = BackupSnapshot(label=label, source=source, sha256=digest, payload=backup, summary=_backup_summary(backup))
    db.add(snapshot); db.commit(); db.refresh(snapshot)
    return {"created": True, "reused": False, "snapshot": {"id": snapshot.id, "label": snapshot.label, "source": snapshot.source, "sha256": snapshot.sha256, "summary": snapshot.summary, "created_at": snapshot.created_at}}


@app.get("/api/backup/snapshots")
def list_backup_snapshots(limit: int = 30, db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    rows = list(db.scalars(select(BackupSnapshot).order_by(BackupSnapshot.created_at.desc(), BackupSnapshot.id.desc()).limit(max(1, min(limit, 100)))))
    return [{"id": row.id, "label": row.label, "source": row.source, "sha256": row.sha256, "summary": row.summary or {}, "created_at": row.created_at} for row in rows]


@app.get("/api/backup/snapshots/{snapshot_id}")
def get_backup_snapshot(snapshot_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    row = db.get(BackupSnapshot, snapshot_id)
    if not row:
        raise HTTPException(status_code=404, detail="备份版本不存在")
    return {"id": row.id, "label": row.label, "source": row.source, "sha256": row.sha256, "summary": row.summary or {}, "payload": row.payload or {}, "created_at": row.created_at}


def _backup_diff(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    keys = BACKUP_KEYS
    diff: dict[str, Any] = {}
    for key in keys:
        before = left.get(key) or []
        after = right.get(key) or []
        before_keys = {json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":")) for item in before}
        after_keys = {json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":")) for item in after}
        diff[key] = {"added": len(after_keys - before_keys), "removed": len(before_keys - after_keys), "unchanged": len(before_keys & after_keys)}
    return diff


def _decrypt_sync_payload(payload: SyncBundleRequest) -> dict[str, Any]:
    try:
        return decrypt_sync_bundle(payload.bundle, payload.passphrase)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _sync_preview(backup: dict[str, Any], db: Session) -> dict[str, Any]:
    invalid = [key for key, value in backup.items() if key in BACKUP_KEYS and not isinstance(value, list)]
    if invalid:
        raise HTTPException(status_code=422, detail=f"同步包字段必须是数组: {', '.join(invalid)}")
    current = _full_backup(db)
    counts = _backup_summary(backup)
    return {
        "format": "learning-workstation-sync-v1",
        "preview": counts,
        "diff": _backup_diff(current, backup),
        "strategy": "append",
        "requires_confirmation": True,
        "warning": "确认后仅追加目标设备不存在的记录，重复记录会跳过；不会覆盖或删除目标设备数据，文件化导入引用需要目标设备自行确认可用。",
    }


@app.post("/api/sync/export")
def export_sync_bundle(payload: SyncExportRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    backup = _full_backup(db)
    summary = _backup_summary(backup)
    bundle = create_sync_bundle(backup, payload.passphrase, summary)
    _audit(db, "sync_bundle", None, "export", None, {"format": bundle["format"], "summary": summary})
    return {"bundle": bundle, "summary": summary, "warning": "同步包已加密；请通过安全渠道传输，并在其他设备上使用同一口令预览后确认。"}


@app.post("/api/sync/preview")
def preview_sync_bundle(payload: SyncBundleRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    return _sync_preview(_decrypt_sync_payload(payload), db)


@app.post("/api/sync/apply")
def apply_sync_bundle(payload: SyncBundleRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    backup = _decrypt_sync_payload(payload)
    if not payload.confirmed:
        return _sync_preview(backup, db)
    result = restore_backup(BackupRestoreRequest(backup=backup, confirmed=True), db)
    batch_id = result.get("restore_batch_id")
    _audit(db, "sync_bundle", batch_id, "apply", None, {"format": "learning-workstation-sync-v1", "restored_counts": result.get("restored_counts", {}), "skipped_counts": result.get("skipped_counts", {})})
    return {"sync_applied": True, "strategy": "append", **result}


@app.get("/api/sync/cloud/status")
def cloud_sync_status() -> dict[str, Any]:
    return {"configured": cloud_sync_configured(), "provider": settings.cloud_sync_provider, "path": settings.cloud_sync_path, "warning": "云端只保存加密同步包，不支持自动覆盖本地数据。"}


@app.post("/api/sync/cloud/push")
def cloud_sync_push(payload: CloudSyncRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    if not cloud_sync_configured():
        raise HTTPException(status_code=409, detail="云同步未配置，请先配置 WebDAV 地址和凭据")
    backup = _full_backup(db)
    summary = _backup_summary(backup)
    bundle = create_sync_bundle(backup, payload.passphrase, summary)
    if not payload.confirmed:
        return {"requires_confirmation": True, "summary": summary, "bundle_sha256": bundle["payload_sha256"], "warning": "确认后会将加密同步包上传并替换远端同一路径的旧同步包，不会修改本地数据。"}
    try:
        result = WebDavSyncProvider().upload(bundle)
    except CloudSyncError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    _audit(db, "cloud_sync", None, "push", None, {"provider": settings.cloud_sync_provider, "summary": summary, "bundle_sha256": bundle["payload_sha256"]})
    return {"requires_confirmation": False, "uploaded": True, "summary": summary, "bundle_sha256": bundle["payload_sha256"], **result}


@app.post("/api/sync/cloud/pull")
def cloud_sync_pull(payload: CloudSyncRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    if not cloud_sync_configured():
        raise HTTPException(status_code=409, detail="云同步未配置，请先配置 WebDAV 地址和凭据")
    try:
        bundle = WebDavSyncProvider().download()
    except CloudSyncError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if bundle is None:
        raise HTTPException(status_code=404, detail="云端还没有同步包")
    backup = _decrypt_sync_payload(SyncBundleRequest(bundle=bundle, passphrase=payload.passphrase))
    if not payload.confirmed:
        return {"remote": True, **_sync_preview(backup, db)}
    result = restore_backup(BackupRestoreRequest(backup=backup, confirmed=True), db)
    _audit(db, "cloud_sync", result.get("restore_batch_id"), "pull", None, {"provider": settings.cloud_sync_provider, "restored_counts": result.get("restored_counts", {}), "skipped_counts": result.get("skipped_counts", {})})
    return {"remote": True, "sync_applied": True, "strategy": "append", **result}


def _entity_match_key(key: str, item: dict[str, Any]) -> str:
    """Stable identity key used to pair records across two backups."""
    if key == "knowledge_topics":
        return str(item.get("name", ""))
    if key == "authorized_directories":
        return str(item.get("path", ""))
    if key == "capabilities":
        return str(item.get("name", ""))
    if key == "practice_exercises":
        return str(item.get("title", ""))
    if key == "web_resources":
        return f"{item.get('url', '')}|{item.get('sha256', '')}"
    return str(item.get("id", ""))


@app.get("/api/backup/diff")
def compare_backup_snapshots(left_id: int, right_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    left = db.get(BackupSnapshot, left_id)
    right = db.get(BackupSnapshot, right_id)
    if not left or not right:
        raise HTTPException(status_code=404, detail="比较的备份版本不存在")
    return {"left": {"id": left.id, "label": left.label, "created_at": left.created_at}, "right": {"id": right.id, "label": right.label, "created_at": right.created_at}, "diff": _backup_diff(left.payload or {}, right.payload or {})}


@app.get("/api/backup/diff/fields")
def compare_backup_fields(left_id: int, right_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Field-level diff between two snapshots: per record and per changed field."""
    left = db.get(BackupSnapshot, left_id)
    right = db.get(BackupSnapshot, right_id)
    if not left or not right:
        raise HTTPException(status_code=404, detail="比较的备份版本不存在")
    keys = BACKUP_KEYS
    records: dict[str, Any] = {}
    summary: dict[str, Any] = {}
    for key in keys:
        before_items = {_entity_match_key(key, item): item for item in (left.payload or {}).get(key) or []}
        after_items = {_entity_match_key(key, item): item for item in (right.payload or {}).get(key) or []}
        records[key] = []
        for match_key in sorted(set(before_items) | set(after_items)):
            old_item = before_items.get(match_key)
            new_item = after_items.get(match_key)
            if old_item is not None and new_item is None:
                records[key].append({"match_key": match_key, "kind": "removed", "label": old_item.get("title") or old_item.get("name") or match_key, "fields": None})
            elif old_item is None and new_item is not None:
                records[key].append({"match_key": match_key, "kind": "added", "label": new_item.get("title") or new_item.get("name") or match_key, "fields": None})
            else:
                fields = []
                for field in sorted(set(old_item) | set(new_item)):
                    if field == "updated_at":
                        continue
                    if old_item.get(field) != new_item.get(field):
                        fields.append({"field": field, "before": old_item.get(field), "after": new_item.get(field)})
                if fields:
                    records[key].append({"match_key": match_key, "kind": "changed", "label": new_item.get("title") or new_item.get("name") or match_key, "fields": fields})
        changed_records = sum(1 for item in records[key] if item["kind"] == "changed")
        summary[key] = {"added": sum(1 for item in records[key] if item["kind"] == "added"), "removed": sum(1 for item in records[key] if item["kind"] == "removed"), "changed": changed_records, "unchanged": len(set(before_items) & set(after_items)) - changed_records}
    return {"left": {"id": left.id, "label": left.label, "created_at": left.created_at}, "right": {"id": right.id, "label": right.label, "created_at": right.created_at}, "summary": summary, "records": records}


def _restore_items(backup: dict[str, Any], db: Session) -> dict[str, Any]:
    goal_ids: dict[int, int] = {}
    stage_ids: dict[int, int] = {}
    topic_ids: dict[int, int] = {}
    project_ids: dict[int, int] = {}
    note_ids: dict[int, int] = {}
    log_ids: dict[int, int] = {}
    teaching_session_ids: dict[int, int] = {}
    task_ids: dict[int, int] = {}
    review_card_ids: dict[int, int] = {}
    directory_ids: dict[int, int] = {}
    github_repository_ids: dict[int, int] = {}
    milestone_ids: dict[int, int] = {}
    capability_ids: dict[int, int] = {}
    exercise_ids: dict[int, int] = {}
    skipped = {key: 0 for key in BACKUP_KEYS}
    restored = {key: 0 for key in BACKUP_KEYS}
    created_ids: dict[str, list[int]] = {key: [] for key in BACKUP_KEYS}

    existing_goals = {(item.title, item.description): item for item in db.scalars(select(LearningGoal))}
    for item in backup.get("goals") or []:
        title = str(item.get("title", "")).strip()
        if not title:
            raise HTTPException(status_code=422, detail="备份中的目标缺少 title")
        key = (title, item.get("description", ""))
        goal = existing_goals.get(key)
        if goal is None:
            goal = LearningGoal(title=title, description=item.get("description", ""), priority=item.get("priority", 3), status=item.get("status", "active"))
            db.add(goal); db.flush(); existing_goals[key] = goal; restored["goals"] += 1; created_ids["goals"].append(goal.id)
        else:
            skipped["goals"] += 1
        if item.get("id") is not None: goal_ids[item["id"]] = goal.id

    existing_stages = {(item.goal_id, item.title): item for item in db.scalars(select(LearningStage))}
    for item in backup.get("stages") or []:
        goal_id = goal_ids.get(item.get("goal_id"))
        if not goal_id or not item.get("title"):
            skipped["stages"] += 1; continue
        key = (goal_id, item["title"])
        stage = existing_stages.get(key)
        if stage is None:
            stage = LearningStage(goal_id=goal_id, title=item["title"], capability_targets=item.get("capability_targets", []), prerequisites=item.get("prerequisites", []), order_index=item.get("order_index", 0), status=item.get("status", "active"))
            db.add(stage); db.flush(); existing_stages[key] = stage; restored["stages"] += 1; created_ids["stages"].append(stage.id)
        else: skipped["stages"] += 1
        if item.get("id") is not None: stage_ids[item["id"]] = stage.id

    # Restore referenced base entities before dependent records so every foreign key
    # can be remapped even when source and destination integer IDs differ.
    existing_projects = {(item.title, item.description): item for item in db.scalars(select(LearningProject))}
    for item in backup.get("projects") or []:
        if not item.get("title"):
            skipped["projects"] += 1
            continue
        key = (item["title"], item.get("description", ""))
        project = existing_projects.get(key)
        if project is None:
            project = LearningProject(title=key[0], description=key[1], status=item.get("status", "active"), skills=item.get("skills", []), outcomes=item.get("outcomes", []), milestones=item.get("milestones", []))
            db.add(project); db.flush(); existing_projects[key] = project; restored["projects"] += 1; created_ids["projects"].append(project.id)
        else:
            skipped["projects"] += 1
        if item.get("id") is not None:
            project_ids[item["id"]] = project.id

    existing_github_repositories = {(item.project_id, item.full_name): item for item in db.scalars(select(GitHubRepository))}
    for item in backup.get("github_repositories") or []:
        project_id = project_ids.get(item.get("project_id"))
        full_name = str(item.get("full_name", "")).strip()
        if not project_id or not full_name:
            skipped["github_repositories"] += 1
            continue
        key = (project_id, full_name)
        repository = existing_github_repositories.get(key)
        if repository is None:
            repository = GitHubRepository(project_id=project_id, owner=item.get("owner", ""), name=item.get("name", ""), full_name=full_name, html_url=item.get("html_url", ""), default_branch=item.get("default_branch", "main"), private=bool(item.get("private", False)), description=item.get("description", ""), last_synced_sha=item.get("last_synced_sha"), last_sync_at=_parse_datetime(item.get("last_sync_at")), created_at=_parse_datetime(item.get("created_at")) or utcnow(), updated_at=_parse_datetime(item.get("updated_at")) or utcnow())
            db.add(repository); db.flush(); existing_github_repositories[key] = repository; restored["github_repositories"] += 1; created_ids["github_repositories"].append(repository.id)
        else:
            skipped["github_repositories"] += 1
        if item.get("id") is not None:
            github_repository_ids[item["id"]] = repository.id

    existing_github_commits = {(item.repository_id, item.sha): item for item in db.scalars(select(GitHubCommit))}
    for item in backup.get("github_commits") or []:
        repository_id = github_repository_ids.get(item.get("repository_id"))
        sha = str(item.get("sha", "")).strip()
        if not repository_id or not sha:
            skipped["github_commits"] += 1
            continue
        key = (repository_id, sha)
        commit = existing_github_commits.get(key)
        if commit is None:
            commit = GitHubCommit(repository_id=repository_id, sha=sha, message=item.get("message", ""), author_name=item.get("author_name", ""), author_login=item.get("author_login", ""), committed_at=_parse_datetime(item.get("committed_at")), html_url=item.get("html_url", ""), additions=item.get("additions", 0), deletions=item.get("deletions", 0), changed_files=item.get("changed_files", 0), files=item.get("files", []), analysis_status=item.get("analysis_status", "pending_confirmation"), analysis=item.get("analysis", {}), analysis_confirmed=bool(item.get("analysis_confirmed", False)), imported_at=_parse_datetime(item.get("imported_at")) or utcnow())
            db.add(commit); db.flush(); existing_github_commits[key] = commit; restored["github_commits"] += 1; created_ids["github_commits"].append(commit.id)
        else:
            skipped["github_commits"] += 1

    existing_job_analyses = {(item.title, item.source_hash): item for item in db.scalars(select(JobAnalysis))}
    for item in backup.get("job_analyses") or []:
        title = str(item.get("title", "")).strip()
        source_hash = str(item.get("source_hash", "")).strip()
        if not title or not source_hash:
            skipped["job_analyses"] += 1
            continue
        key = (title, source_hash)
        analysis = existing_job_analyses.get(key)
        if analysis is None:
            analysis = JobAnalysis(title=title, source_text=item.get("source_text", ""), source_hash=source_hash, extracted_skills=item.get("extracted_skills", []), matched_topics=item.get("matched_topics", []), matched_capabilities=item.get("matched_capabilities", []), project_evidence=item.get("project_evidence", []), gaps=item.get("gaps", []), recommendations=item.get("recommendations", []), confidence=item.get("confidence", 0.0), created_at=_parse_datetime(item.get("created_at")) or utcnow(), updated_at=_parse_datetime(item.get("updated_at")) or utcnow())
            db.add(analysis); db.flush(); existing_job_analyses[key] = analysis; restored["job_analyses"] += 1; created_ids["job_analyses"].append(analysis.id)
        else:
            skipped["job_analyses"] += 1

    existing_milestones = {(item.project_id, item.title, item.due_date): item for item in db.scalars(select(ProjectMilestone))}
    for item in backup.get("project_milestones") or []:
        project_id = project_ids.get(item.get("project_id"))
        due_date = date.fromisoformat(item["due_date"]) if isinstance(item.get("due_date"), str) else item.get("due_date")
        if not project_id or not item.get("title"):
            skipped["project_milestones"] += 1
            continue
        key = (project_id, str(item["title"]), due_date)
        milestone = existing_milestones.get(key)
        if milestone is None:
            milestone = ProjectMilestone(project_id=project_id, title=key[1], description=item.get("description", ""), status=item.get("status", "pending"), due_date=due_date, order_index=item.get("order_index", 0), evidence=item.get("evidence", ""), completed_at=_parse_datetime(item.get("completed_at")), created_at=_parse_datetime(item.get("created_at")) or utcnow(), updated_at=_parse_datetime(item.get("updated_at")) or utcnow())
            db.add(milestone); db.flush(); existing_milestones[key] = milestone; restored["project_milestones"] += 1; created_ids["project_milestones"].append(milestone.id)
        else:
            skipped["project_milestones"] += 1
        if item.get("id") is not None:
            milestone_ids[item["id"]] = milestone.id

    existing_topics = {item.name: item for item in db.scalars(select(KnowledgeTopic))}
    for item in backup.get("knowledge_topics") or []:
        if not item.get("name"):
            skipped["knowledge_topics"] += 1
            continue
        topic = existing_topics.get(item["name"])
        if topic is None:
            topic = KnowledgeTopic(name=item["name"], domain=item.get("domain", "待整理"), definition=item.get("definition", ""), self_level=item.get("self_level", "有印象"), verified_level=item.get("verified_level", 0), tags=item.get("tags", []), prerequisites=item.get("prerequisites", []), evidence=item.get("evidence", []), last_reviewed_at=_parse_datetime(item.get("last_reviewed_at")), next_review_at=_parse_datetime(item.get("next_review_at")))
            db.add(topic); db.flush(); existing_topics[topic.name] = topic; restored["knowledge_topics"] += 1; created_ids["knowledge_topics"].append(topic.id)
        else:
            skipped["knowledge_topics"] += 1
        if item.get("id") is not None:
            topic_ids[item["id"]] = topic.id

    existing_notes = {(item.title, item.content): item for item in db.scalars(select(Note))}
    for item in backup.get("notes") or []:
        if not item.get("title"):
            skipped["notes"] += 1
            continue
        key = (item["title"], item.get("content", ""))
        note = existing_notes.get(key)
        if note is None:
            note = Note(title=key[0], content=key[1], summary=item.get("summary", ""), tags=item.get("tags", []), folder=item.get("folder", "Inbox"), source_path=item.get("source_path"), visibility=item.get("visibility", "private"), ai_review_status=item.get("ai_review_status", "not_reviewed"), ai_review=item.get("ai_review", {}), linked_topic_ids=[], linked_task_ids=[], linked_project_ids=[], status=item.get("status", "draft"))
            db.add(note); db.flush(); existing_notes[key] = note; restored["notes"] += 1; created_ids["notes"].append(note.id)
        else:
            skipped["notes"] += 1
        if item.get("id") is not None:
            note_ids[item["id"]] = note.id

    existing_drafts = {(item.source_note_id, item.source_version, item.title, item.content): item for item in db.scalars(select(BlogDraft))}
    for item in backup.get("blog_drafts") or []:
        source_note_id = note_ids.get(item.get("source_note_id")) if item.get("source_note_id") is not None else None
        if not source_note_id or not item.get("title"):
            skipped["blog_drafts"] += 1
            continue
        key = (source_note_id, item.get("source_version"), str(item.get("title")), str(item.get("content", "")))
        draft = existing_drafts.get(key)
        if draft is None:
            draft = BlogDraft(source_note_id=source_note_id, source_version=item.get("source_version"), title=key[2], content=key[3], excerpt=item.get("excerpt", ""), status=item.get("status", "draft"), generation_mode=item.get("generation_mode", "deterministic"), model_provider=item.get("model_provider"), model_name=item.get("model_name"), source_snapshot=item.get("source_snapshot", {}), created_at=_parse_datetime(item.get("created_at")) or utcnow(), updated_at=_parse_datetime(item.get("updated_at")) or utcnow())
            db.add(draft); db.flush(); existing_drafts[key] = draft; restored["blog_drafts"] += 1; created_ids["blog_drafts"].append(draft.id)
        else:
            skipped["blog_drafts"] += 1

    existing_tasks = {(item.title, item.stage_id, item.due_date): item for item in db.scalars(select(StudyTask))}
    for item in backup.get("tasks") or []:
        if not item.get("title"):
            raise HTTPException(status_code=422, detail="备份中的任务缺少 title")
        due_date = item.get("due_date")
        if isinstance(due_date, str): due_date = date.fromisoformat(due_date)
        stage_id = stage_ids.get(item.get("stage_id")) if item.get("stage_id") is not None else None
        if item.get("stage_id") is not None and stage_id is None:
            skipped["tasks"] += 1
            continue
        project_id = project_ids.get(item.get("project_id")) if item.get("project_id") is not None else None
        topic_id = topic_ids.get(item.get("topic_id")) if item.get("topic_id") is not None else None
        if item.get("project_id") is not None and project_id is None:
            skipped["tasks"] += 1
            continue
        if item.get("topic_id") is not None and topic_id is None:
            skipped["tasks"] += 1
            continue
        key = (item["title"], stage_id, due_date)
        if key in existing_tasks:
            task = existing_tasks[key]
            skipped["tasks"] += 1
        else:
            task = StudyTask(title=item["title"], description=item.get("description", ""), stage_id=key[1], project_id=project_id, topic_id=topic_id, priority=item.get("priority", 3), estimated_minutes=item.get("estimated_minutes"), actual_minutes=item.get("actual_minutes"), status=item.get("status", "not_started"), acceptance_criteria=item.get("acceptance_criteria", ""), due_date=due_date, source="restore", week_key=item.get("week_key"), task_type=item.get("task_type", "practice"), expected_outcome=item.get("expected_outcome", ""), agent_feedback=item.get("agent_feedback", ""), completed_at=_parse_datetime(item.get("completed_at")), last_verified_at=_parse_datetime(item.get("last_verified_at")), next_review_date=date.fromisoformat(item["next_review_date"]) if item.get("next_review_date") else None)
            db.add(task); db.flush(); existing_tasks[key] = task; restored["tasks"] += 1; created_ids["tasks"].append(task.id)
        if item.get("id") is not None:
            task_ids[item["id"]] = task.id

    existing_verifications = {(item.task_id, item.verified_at, item.evidence): item for item in db.scalars(select(TaskVerification))}
    for item in backup.get("task_verifications") or []:
        task_id = task_ids.get(item.get("task_id")) if item.get("task_id") is not None else None
        if not task_id or not item.get("evidence"):
            skipped["task_verifications"] += 1
            continue
        verified_at = _parse_datetime(item.get("verified_at")) or utcnow()
        key = (task_id, verified_at, item.get("evidence", ""))
        if key in existing_verifications:
            skipped["task_verifications"] += 1
            continue
        verification = TaskVerification(task_id=task_id, target_status=item.get("target_status", "completed"), evidence=item.get("evidence", ""), note=item.get("note", ""), actual_minutes=item.get("actual_minutes"), verified_at=verified_at, created_at=_parse_datetime(item.get("created_at")) or verified_at)
        db.add(verification); db.flush(); existing_verifications[key] = verification; restored["task_verifications"] += 1; created_ids["task_verifications"].append(verification.id)

    existing_time_entries = {(item.task_id, item.started_at, item.duration_seconds, item.status): item for item in db.scalars(select(TaskTimeEntry))}
    for item in backup.get("task_time_entries") or []:
        task_id = task_ids.get(item.get("task_id")) if item.get("task_id") is not None else None
        started_at = _parse_datetime(item.get("started_at"))
        if not task_id or not started_at:
            skipped["task_time_entries"] += 1
            continue
        key = (task_id, started_at, int(item.get("duration_seconds") or 0), str(item.get("status") or "stopped"))
        if key in existing_time_entries:
            skipped["task_time_entries"] += 1
            continue
        entry = TaskTimeEntry(
            task_id=task_id,
            started_at=started_at,
            paused_at=_parse_datetime(item.get("paused_at")),
            ended_at=_parse_datetime(item.get("ended_at")),
            duration_seconds=max(0, int(item.get("duration_seconds") or 0)),
            status=str(item.get("status") or "stopped"),
            created_at=_parse_datetime(item.get("created_at")) or started_at,
            updated_at=_parse_datetime(item.get("updated_at")) or started_at,
        )
        # A backup must never create two active timers for one task.
        if entry.status == "running" and db.scalar(select(TaskTimeEntry).where(TaskTimeEntry.task_id == task_id, TaskTimeEntry.status == "running")):
            entry.status = "stopped"
            entry.ended_at = entry.ended_at or entry.updated_at
        db.add(entry)
        db.flush()
        existing_time_entries[key] = entry
        restored["task_time_entries"] += 1
        created_ids["task_time_entries"].append(entry.id)

    # Associations stored as JSON arrays are resolved after all referenced entities exist.
    for item in backup.get("notes") or []:
        key = (item.get("title"), item.get("content", ""))
        note = existing_notes.get(key)
        if note is None:
            continue
        note.linked_topic_ids = [mapped for value in item.get("linked_topic_ids") or [] if (mapped := topic_ids.get(value)) is not None]
        note.linked_task_ids = [mapped for value in item.get("linked_task_ids") or [] if (mapped := task_ids.get(value)) is not None]
        note.linked_project_ids = [mapped for value in item.get("linked_project_ids") or [] if (mapped := project_ids.get(value)) is not None]

    existing_relations = {(item.source_topic_id, item.target_topic_id, item.relation_type) for item in db.scalars(select(KnowledgeTopicRelation))}
    for item in backup.get("knowledge_relations") or []:
        source_id, target_id = topic_ids.get(item.get("source_topic_id")), topic_ids.get(item.get("target_topic_id"))
        relation_type = item.get("relation_type", "related")
        if not source_id or not target_id or source_id == target_id or (source_id, target_id, relation_type) in existing_relations:
            skipped["knowledge_relations"] += 1; continue
        relation = KnowledgeTopicRelation(source_topic_id=source_id, target_topic_id=target_id, relation_type=relation_type); db.add(relation); db.flush(); existing_relations.add((source_id, target_id, relation_type)); restored["knowledge_relations"] += 1; created_ids["knowledge_relations"].append(relation.id)

    existing_logs = {(item.log_date, item.raw_text): item for item in db.scalars(select(DailyLog))}
    for item in backup.get("daily_logs") or []:
        project_id = project_ids.get(item.get("project_id")) if item.get("project_id") is not None else None
        topic_ids_mapped = [mapped for value in item.get("topic_ids") or [] if (mapped := topic_ids.get(value)) is not None]
        note_ids_mapped = [mapped for value in item.get("note_ids") or [] if (mapped := note_ids.get(value)) is not None]
        if item.get("project_id") is not None and project_id is None:
            skipped["daily_logs"] += 1
            continue
        log_date = item.get("log_date") or date.today()
        if isinstance(log_date, str): log_date = date.fromisoformat(log_date)
        if not item.get("raw_text"): raise HTTPException(status_code=422, detail="备份中的学习日志缺少 raw_text")
        key = (log_date, item["raw_text"])
        log = existing_logs.get(key)
        if log is None:
            log = DailyLog(log_date=log_date, raw_text=key[1], extracted_topics=item.get("extracted_topics", []), extracted_duration=item.get("extracted_duration"), extracted_outputs=item.get("extracted_outputs", []), understood_content=item.get("understood_content", []), unresolved_questions=item.get("unresolved_questions", []), self_assessment=item.get("self_assessment"), structured_status=item.get("structured_status", "pending_review"), project_id=project_id, topic_ids=topic_ids_mapped, note_ids=note_ids_mapped); db.add(log); db.flush(); existing_logs[key] = log; restored["daily_logs"] += 1; created_ids["daily_logs"].append(log.id)
        else: skipped["daily_logs"] += 1
        if item.get("id") is not None: log_ids[item["id"]] = log.id

    existing_reviews = {(item.daily_log_id, item.review_date, item.note, item.topic_id): item for item in db.scalars(select(DailyLogReview))}
    for item in backup.get("reviews") or []:
        daily_log_id = log_ids.get(item.get("daily_log_id"))
        if not daily_log_id or not item.get("review_date"): skipped["reviews"] += 1; continue
        review_date = item["review_date"]
        if isinstance(review_date, str): review_date = date.fromisoformat(review_date)
        topic_id = topic_ids.get(item.get("topic_id")) if item.get("topic_id") is not None else None
        if item.get("topic_id") is not None and topic_id is None:
            skipped["reviews"] += 1
            continue
        key = (daily_log_id, review_date, item.get("note", ""), topic_id)
        if key in existing_reviews: skipped["reviews"] += 1; continue
        review = DailyLogReview(daily_log_id=daily_log_id, review_date=review_date, note=key[2], topic_id=key[3], status=item.get("status", "pending"), quality=item.get("quality"), interval_days=item.get("interval_days", 1), ease_factor=item.get("ease_factor", 2.5), repetitions=item.get("repetitions", 0), created_at=_parse_datetime(item.get("created_at")) or utcnow()); db.add(review); db.flush(); restored["reviews"] += 1; created_ids["reviews"].append(review.id)

    existing_weekly_plans = {item.week_key: item for item in db.scalars(select(WeeklyPlan))}
    for item in backup.get("weekly_plans") or []:
        week_key = str(item.get("week_key", "")).strip()
        if not week_key:
            skipped["weekly_plans"] += 1
            continue
        goal_id = goal_ids.get(item.get("goal_id")) if item.get("goal_id") is not None else None
        project_id = project_ids.get(item.get("project_id")) if item.get("project_id") is not None else None
        if item.get("goal_id") is not None and goal_id is None:
            skipped["weekly_plans"] += 1
            continue
        if item.get("project_id") is not None and project_id is None:
            skipped["weekly_plans"] += 1
            continue
        plan = existing_weekly_plans.get(week_key)
        if plan is None:
            plan = WeeklyPlan(week_key=week_key, goal_id=goal_id, project_id=project_id, objective=item.get("objective", ""), expected_outputs=item.get("expected_outputs", []), reflection=item.get("reflection", ""), blockers=item.get("blockers", ""), status=item.get("status", "draft"))
            db.add(plan); db.flush(); existing_weekly_plans[week_key] = plan; restored["weekly_plans"] += 1; created_ids["weekly_plans"].append(plan.id)
        else:
            skipped["weekly_plans"] += 1

    existing_cards = {(item.front, item.back, item.source_note_id, item.topic_id): item for item in db.scalars(select(ReviewCard))}
    for item in backup.get("review_cards") or []:
        topic_id = topic_ids.get(item.get("topic_id")) if item.get("topic_id") is not None else None
        source_note_id = note_ids.get(item.get("source_note_id")) if item.get("source_note_id") is not None else None
        if item.get("topic_id") is not None and topic_id is None:
            skipped["review_cards"] += 1
            continue
        if item.get("source_note_id") is not None and source_note_id is None:
            skipped["review_cards"] += 1
            continue
        key = (str(item.get("front", "")), str(item.get("back", "")), source_note_id, topic_id)
        if not key[0]:
            skipped["review_cards"] += 1
            continue
        card = existing_cards.get(key)
        if card is None:
            due_date = item.get("due_date")
            if isinstance(due_date, str): due_date = date.fromisoformat(due_date)
            card = ReviewCard(front=key[0], back=key[1], hint=item.get("hint", ""), source_note_id=key[2], topic_id=key[3], status=item.get("status", "active"), due_date=due_date or date.today(), interval_days=item.get("interval_days", 1), ease_factor=item.get("ease_factor", 2.5), repetitions=item.get("repetitions", 0), last_quality=item.get("last_quality"))
            db.add(card); db.flush(); existing_cards[key] = card; restored["review_cards"] += 1; created_ids["review_cards"].append(card.id)
        else:
            skipped["review_cards"] += 1
        if item.get("id") is not None: review_card_ids[item["id"]] = card.id

    existing_history = {(item.card_id, item.reviewed_at, item.quality, item.due_after): item for item in db.scalars(select(ReviewHistory))}
    for item in backup.get("review_history") or []:
        card_id = review_card_ids.get(item.get("card_id")) if item.get("card_id") is not None else None
        reviewed_at = _parse_datetime(item.get("reviewed_at"))
        due_before = item.get("due_before")
        due_after = item.get("due_after")
        if isinstance(due_before, str):
            due_before = date.fromisoformat(due_before)
        if isinstance(due_after, str):
            due_after = date.fromisoformat(due_after)
        if not card_id or not reviewed_at or due_before is None or due_after is None:
            skipped["review_history"] += 1
            continue
        key = (card_id, reviewed_at, item.get("quality", 0), due_after)
        if key in existing_history:
            skipped["review_history"] += 1
            continue
        history = ReviewHistory(card_id=card_id, quality=item.get("quality", 0), interval_before=item.get("interval_before", 1), interval_after=item.get("interval_after", 1), ease_before=item.get("ease_before", 2.5), ease_after=item.get("ease_after", 2.5), repetitions_before=item.get("repetitions_before", 0), repetitions_after=item.get("repetitions_after", 0), due_before=due_before, due_after=due_after, reviewed_at=reviewed_at)
        db.add(history)
        db.flush()
        existing_history[key] = history
        restored["review_history"] += 1
        created_ids["review_history"].append(history.id)

    existing_teaching_sessions = {(item.title, item.topic_id, item.task_id, item.stage_id): item for item in db.scalars(select(TeachingSession))}
    for item in backup.get("teaching_sessions") or []:
        topic_id = topic_ids.get(item.get("topic_id")) if item.get("topic_id") is not None else None
        task_id = task_ids.get(item.get("task_id")) if item.get("task_id") is not None else None
        stage_id = stage_ids.get(item.get("stage_id")) if item.get("stage_id") is not None else None
        if item.get("topic_id") is not None and topic_id is None:
            skipped["teaching_sessions"] += 1
            continue
        if item.get("task_id") is not None and task_id is None:
            skipped["teaching_sessions"] += 1
            continue
        if item.get("stage_id") is not None and stage_id is None:
            skipped["teaching_sessions"] += 1
            continue
        key = (str(item.get("title", "")), topic_id, task_id, stage_id)
        if not key[0]:
            skipped["teaching_sessions"] += 1
            continue
        session = existing_teaching_sessions.get(key)
        if session is None:
            session = TeachingSession(title=key[0], topic_id=key[1], task_id=key[2], stage_id=key[3], status=item.get("status", "active"), explanation=item.get("explanation", ""))
            db.add(session); db.flush(); existing_teaching_sessions[key] = session; restored["teaching_sessions"] += 1; created_ids["teaching_sessions"].append(session.id)
        else:
            skipped["teaching_sessions"] += 1
        if item.get("id") is not None: teaching_session_ids[item["id"]] = session.id

    existing_teaching_attempts = {(item.session_id, item.prompt, item.created_at): item for item in db.scalars(select(TeachingAttempt))}
    for item in backup.get("teaching_attempts") or []:
        session_id = teaching_session_ids.get(item.get("session_id")) if item.get("session_id") is not None else None
        topic_id = topic_ids.get(item.get("topic_id")) if item.get("topic_id") is not None else None
        task_id = task_ids.get(item.get("task_id")) if item.get("task_id") is not None else None
        stage_id = stage_ids.get(item.get("stage_id")) if item.get("stage_id") is not None else None
        review_card_id = review_card_ids.get(item.get("review_card_id")) if item.get("review_card_id") is not None else None
        if item.get("topic_id") is not None and topic_id is None:
            skipped["teaching_attempts"] += 1
            continue
        if item.get("task_id") is not None and task_id is None:
            skipped["teaching_attempts"] += 1
            continue
        if item.get("stage_id") is not None and stage_id is None:
            skipped["teaching_attempts"] += 1
            continue
        if item.get("review_card_id") is not None and review_card_id is None:
            skipped["teaching_attempts"] += 1
            continue
        if not session_id or not item.get("prompt"):
            skipped["teaching_attempts"] += 1
            continue
        created_at = item.get("created_at")
        if isinstance(created_at, str):
            try: created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            except ValueError: created_at = None
        key = (session_id, item["prompt"], created_at)
        if key in existing_teaching_attempts:
            skipped["teaching_attempts"] += 1
            continue
        attempt = TeachingAttempt(session_id=session_id, topic_id=topic_id, task_id=task_id, stage_id=stage_id, phase=item.get("phase", "practice"), prompt=item["prompt"], expected_answer=item.get("expected_answer", ""), rubric=item.get("rubric", []), user_answer=item.get("user_answer", ""), score=item.get("score"), error_type=item.get("error_type"), feedback=item.get("feedback", ""), recommendation=item.get("recommendation", ""), evaluation_source=item.get("evaluation_source", "local_deterministic"), evaluation_confidence=item.get("evaluation_confidence"), evaluation_details=item.get("evaluation_details", {}), review_card_id=review_card_id, created_at=created_at or utcnow(), answered_at=_parse_datetime(item.get("answered_at")), evaluated_at=_parse_datetime(item.get("evaluated_at")))
        db.add(attempt); db.flush(); existing_teaching_attempts[key] = attempt; restored["teaching_attempts"] += 1; created_ids["teaching_attempts"].append(attempt.id)

    existing_capabilities = {item.name: item for item in db.scalars(select(CapabilityProfile))}
    for item in backup.get("capabilities") or []:
        if not item.get("name"):
            skipped["capabilities"] += 1; continue
        if item["name"] in existing_capabilities:
            skipped["capabilities"] += 1; continue
        capability = CapabilityProfile(name=item["name"], description=item.get("description", ""), level=item.get("level", 0), confidence=item.get("confidence", 0), evidence_count=item.get("evidence_count", 0), evidence=item.get("evidence", [])); db.add(capability); db.flush()
        restored["capabilities"] += 1; created_ids["capabilities"].append(capability.id)
        if item.get("id") is not None: capability_ids[item["id"]] = capability.id
    for item in backup.get("capabilities") or []:
        existing = existing_capabilities.get(item.get("name"))
        if existing is not None and item.get("id") is not None:
            capability_ids[item["id"]] = existing.id

    existing_assessments = {(item.capability_id, item.created_at, item.new_level): item for item in db.scalars(select(CapabilityAssessment))}
    for item in backup.get("capability_assessments") or []:
        capability_id = capability_ids.get(item.get("capability_id"))
        created_at = _parse_datetime(item.get("created_at")) or utcnow()
        if not capability_id:
            skipped["capability_assessments"] += 1
            continue
        key = (capability_id, created_at, item.get("new_level", 0))
        if key in existing_assessments:
            skipped["capability_assessments"] += 1
            continue
        assessment = CapabilityAssessment(capability_id=capability_id, previous_level=item.get("previous_level", 0), new_level=item.get("new_level", 0), evidence_count=item.get("evidence_count", 0), evidence_snapshot=item.get("evidence_snapshot", []), trigger=item.get("trigger", "manual"), created_at=created_at)
        db.add(assessment); db.flush(); existing_assessments[key] = assessment; restored["capability_assessments"] += 1; created_ids["capability_assessments"].append(assessment.id)

    existing_exercises = {(item.title, item.exercise_type): item for item in db.scalars(select(PracticeExercise))}
    for item in backup.get("practice_exercises") or []:
        topic_id = topic_ids.get(item.get("topic_id")) if item.get("topic_id") is not None else None
        if not item.get("title") or item.get("exercise_type") not in {"algorithm", "sql"} or (item.get("topic_id") is not None and topic_id is None):
            skipped["practice_exercises"] += 1
            continue
        key = (str(item["title"]), str(item["exercise_type"]))
        exercise = existing_exercises.get(key)
        if exercise is None:
            exercise = PracticeExercise(title=key[0], exercise_type=key[1], prompt=item.get("prompt", ""), difficulty=item.get("difficulty", "medium"), topic_id=topic_id, validation_spec=item.get("validation_spec", {}), hints=item.get("hints", []), status=item.get("status", "active"), created_at=_parse_datetime(item.get("created_at")) or utcnow(), updated_at=_parse_datetime(item.get("updated_at")) or utcnow())
            db.add(exercise); db.flush(); existing_exercises[key] = exercise; restored["practice_exercises"] += 1; created_ids["practice_exercises"].append(exercise.id)
        else:
            skipped["practice_exercises"] += 1
        if item.get("id") is not None: exercise_ids[item["id"]] = exercise.id

    existing_attempts = {(item.exercise_id, item.created_at, item.code, item.query): item for item in db.scalars(select(PracticeAttempt))}
    for item in backup.get("practice_attempts") or []:
        exercise_id = exercise_ids.get(item.get("exercise_id"))
        created_at = _parse_datetime(item.get("created_at")) or utcnow()
        if not exercise_id:
            skipped["practice_attempts"] += 1
            continue
        key = (exercise_id, created_at, item.get("code", ""), item.get("query", ""))
        if key in existing_attempts:
            skipped["practice_attempts"] += 1
            continue
        attempt = PracticeAttempt(exercise_id=exercise_id, code=item.get("code", ""), query=item.get("query", ""), answer=item.get("answer", ""), status=item.get("status", "failed"), passed=bool(item.get("passed", False)), score=item.get("score"), feedback=item.get("feedback", ""), stdout=item.get("stdout", ""), stderr=item.get("stderr", ""), duration_ms=item.get("duration_ms", 0), created_at=created_at)
        db.add(attempt); db.flush(); existing_attempts[key] = attempt; restored["practice_attempts"] += 1; created_ids["practice_attempts"].append(attempt.id)

    existing_runs = {(item.code, item.stdin, item.created_at): item for item in db.scalars(select(CodeRun))}
    for item in backup.get("code_runs") or []:
        exercise_id = exercise_ids.get(item.get("exercise_id")) if item.get("exercise_id") is not None else None
        created_at = _parse_datetime(item.get("created_at")) or utcnow()
        key = (str(item.get("code", "")), str(item.get("stdin", "")), created_at)
        if not key[0] or key in existing_runs:
            skipped["code_runs"] += 1
            continue
        run = CodeRun(exercise_id=exercise_id, code=key[0], stdin=key[1], status=item.get("status", "failed"), stdout=item.get("stdout", ""), stderr=item.get("stderr", ""), exit_code=item.get("exit_code"), duration_ms=item.get("duration_ms", 0), policy=item.get("policy", {}), created_at=created_at)
        db.add(run); db.flush(); existing_runs[key] = run; restored["code_runs"] += 1; created_ids["code_runs"].append(run.id)

    existing_directories = {item.path: item for item in db.scalars(select(AuthorizedDirectory))}
    for item in backup.get("authorized_directories") or []:
        path = item.get("path")
        if not path: skipped["authorized_directories"] += 1; continue
        if path in existing_directories:
            if item.get("id") is not None:
                directory_ids[item["id"]] = existing_directories[path].id
            skipped["authorized_directories"] += 1
            continue
        directory = AuthorizedDirectory(path=path, label=item.get("label", ""), active=item.get("active", True), local_analysis=item.get("local_analysis", True), cloud_transfer=item.get("cloud_transfer", False), write_access=item.get("write_access", False), excluded_extensions=item.get("excluded_extensions", [])); db.add(directory); db.flush(); existing_directories[path] = directory; restored["authorized_directories"] += 1; created_ids["authorized_directories"].append(directory.id)
        if item.get("id") is not None:
            directory_ids[item["id"]] = directory.id

    existing_imports = {(item.directory_id, json.dumps(item.files or [], ensure_ascii=False, sort_keys=True, separators=(",", ":"))): item for item in db.scalars(select(FileImport))}
    import_ids: dict[int, int] = {}
    for item in backup.get("file_imports") or []:
        directory_id = directory_ids.get(item.get("directory_id")) if item.get("directory_id") is not None else None
        files = item.get("files") or []
        if not directory_id:
            skipped["file_imports"] += 1
            continue
        key = (directory_id, json.dumps(files, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        record = existing_imports.get(key)
        if record is None:
            record = FileImport(directory_id=directory_id, files=files, excluded=item.get("excluded", {}), files_scanned=item.get("files_scanned", len(files)))
            db.add(record); db.flush(); existing_imports[key] = record; restored["file_imports"] += 1; created_ids["file_imports"].append(record.id)
        else:
            skipped["file_imports"] += 1
        if item.get("id") is not None:
            import_ids[item["id"]] = record.id

    existing_files = {(item.import_id, item.relative_path, item.sha256): item for item in db.scalars(select(ImportedFile))}
    imported_file_ids: dict[int, int] = {}
    for item in backup.get("imported_files") or []:
        import_id = import_ids.get(item.get("import_id")) if item.get("import_id") is not None else None
        if not import_id or not item.get("relative_path") or not item.get("sha256"):
            skipped["imported_files"] += 1
            continue
        key = (import_id, item["relative_path"], item["sha256"])
        row = existing_files.get(key)
        if row is None:
            row = ImportedFile(import_id=import_id, relative_path=item["relative_path"], original_path="", sha256=item["sha256"], size=item.get("size", 0), mime_type=item.get("mime_type"), content_status=item.get("content_status", "metadata_only"), raw_file_path=item.get("raw_file_path"), content_file_path=item.get("content_file_path"), index_file_path=item.get("index_file_path"), content_sha256=item.get("content_sha256"), index_sha256=item.get("index_sha256"), index_status=item.get("index_status", "missing"), last_verified_at=item.get("last_verified_at"))
            db.add(row); db.flush(); existing_files[key] = row; restored["imported_files"] += 1; created_ids["imported_files"].append(row.id)
        else:
            skipped["imported_files"] += 1
        if item.get("id") is not None:
            imported_file_ids[item["id"]] = row.id

    existing_analyses = {(item.imported_file_id, item.analysis_version, json.dumps(item.result or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))): item for item in db.scalars(select(FileAnalysis))}
    for item in backup.get("file_analyses") or []:
        imported_file_id = imported_file_ids.get(item.get("imported_file_id")) if item.get("imported_file_id") is not None else None
        if not imported_file_id:
            skipped["file_analyses"] += 1
            continue
        key = (imported_file_id, item.get("analysis_version", "v1"), json.dumps(item.get("result") or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        row = existing_analyses.get(key)
        if row is None:
            row = FileAnalysis(imported_file_id=imported_file_id, provider=item.get("provider", "local_index"), model_name=item.get("model_name", "none"), analysis_version=item.get("analysis_version", "v1"), status=item.get("status", "pending_confirmation"), result={}, result_file_path=item.get("result_file_path"), result_sha256=item.get("result_sha256"), confirmed=item.get("confirmed", False), confirmed_at=item.get("confirmed_at"))
            db.add(row); db.flush(); existing_analyses[key] = row; restored["file_analyses"] += 1; created_ids["file_analyses"].append(row.id)
        else:
            skipped["file_analyses"] += 1

    existing_chats = {(item.session_id, item.role, item.content): item for item in db.scalars(select(ChatMessage))}
    for item in backup.get("chat_messages") or []:
        key = (str(item.get("session_id", "")), str(item.get("role", "")), str(item.get("content", "")))
        if not key[0] or not key[1]:
            skipped["chat_messages"] += 1
            continue
        if key in existing_chats:
            skipped["chat_messages"] += 1
            continue
        row = ChatMessage(session_id=key[0], role=key[1], content=key[2]); db.add(row); db.flush(); existing_chats[key] = row; restored["chat_messages"] += 1; created_ids["chat_messages"].append(row.id)

    existing_calls = {(item.task_type, item.provider, item.model_name, item.created_at, item.input_length, item.output_length): item for item in db.scalars(select(ModelCallLog))}
    for item in backup.get("model_calls") or []:
        created_at = item.get("created_at")
        if isinstance(created_at, str):
            try:
                created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            except ValueError:
                created_at = None
        key = (str(item.get("task_type", "")), str(item.get("provider", "")), str(item.get("model_name", "")), created_at, item.get("input_length"), item.get("output_length"))
        if not key[0] or key in existing_calls:
            skipped["model_calls"] += 1
            continue
        row = ModelCallLog(task_type=key[0], risk_level=item.get("risk_level", "low"), provider=key[1], model_name=key[2], upgraded=item.get("upgraded", False), input_length=item.get("input_length"), output_length=item.get("output_length"), input_tokens=item.get("input_tokens"), output_tokens=item.get("output_tokens"), total_tokens=item.get("total_tokens"), token_source=item.get("token_source"), duration_ms=item.get("duration_ms"), estimated_cost=item.get("estimated_cost"), success=item.get("success", False), confidence=item.get("confidence"), route_reason=item.get("route_reason"), created_at=created_at or utcnow()); db.add(row); db.flush(); existing_calls[key] = row; restored["model_calls"] += 1; created_ids["model_calls"].append(row.id)

    existing_web_resources = {(item.url, item.sha256): item for item in db.scalars(select(WebResource))}
    for item in backup.get("web_resources") or []:
        url = str(item.get("url", "")).strip()
        sha256 = str(item.get("sha256", "")).strip()
        if not url or not sha256:
            skipped["web_resources"] += 1
            continue
        key = (url, sha256)
        resource = existing_web_resources.get(key)
        if resource is None:
            resource = WebResource(url=url, final_url=item.get("final_url", url), title=item.get("title", ""), sha256=sha256, size=item.get("size", 0), mime_type=item.get("mime_type"), content_status=item.get("content_status", "metadata_only"), parse_error=item.get("parse_error"), raw_file_path=item.get("raw_file_path"), content_file_path=item.get("content_file_path"), index_file_path=item.get("index_file_path"), content_sha256=item.get("content_sha256"), index_sha256=item.get("index_sha256"), index_status=item.get("index_status", "missing"), fetched_at=_parse_datetime(item.get("fetched_at")) or utcnow(), confirmed_at=_parse_datetime(item.get("confirmed_at")), created_at=_parse_datetime(item.get("created_at")) or utcnow())
            db.add(resource); db.flush(); existing_web_resources[key] = resource; restored["web_resources"] += 1; created_ids["web_resources"].append(resource.id)
        else:
            skipped["web_resources"] += 1


    created_snapshots: dict[str, list[dict[str, Any]]] = {key: [] for key in BACKUP_KEYS}
    model_map = {"goals": LearningGoal, "stages": LearningStage, "tasks": StudyTask, "task_time_entries": TaskTimeEntry, "task_verifications": TaskVerification, "daily_logs": DailyLog, "notes": Note, "blog_drafts": BlogDraft, "knowledge_topics": KnowledgeTopic, "knowledge_relations": KnowledgeTopicRelation, "projects": LearningProject, "project_milestones": ProjectMilestone, "reviews": DailyLogReview, "weekly_plans": WeeklyPlan, "review_cards": ReviewCard, "review_history": ReviewHistory, "teaching_sessions": TeachingSession, "teaching_attempts": TeachingAttempt, "authorized_directories": AuthorizedDirectory, "capabilities": CapabilityProfile, "capability_assessments": CapabilityAssessment, "practice_exercises": PracticeExercise, "practice_attempts": PracticeAttempt, "code_runs": CodeRun, "file_imports": FileImport, "imported_files": ImportedFile, "file_analyses": FileAnalysis, "web_resources": WebResource, "github_repositories": GitHubRepository, "github_commits": GitHubCommit, "job_analyses": JobAnalysis, "chat_messages": ChatMessage, "model_calls": ModelCallLog}
    for key, ids in created_ids.items():
        model = model_map.get(key)
        if model is None:
            continue
        for row_id in ids:
            row = db.get(model, row_id)
            if row is not None:
                created_snapshots[key].append({"id": row_id, "snapshot": _restore_row_snapshot(row)})
    return {"restored": restored, "skipped": skipped, "created_ids": created_ids, "created_snapshots": created_snapshots}


@app.post("/api/backup/restore")
def restore_backup(payload: BackupRestoreRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    backup = payload.backup
    keys = BACKUP_KEYS
    invalid = [key for key, value in backup.items() if key in keys and not isinstance(value, list)]
    if invalid:
        raise HTTPException(status_code=422, detail=f"备份字段必须是数组: {', '.join(invalid)}")
    counts = _backup_summary(backup)
    if not payload.confirmed:
        return {"restored": False, "preview": counts, "strategy": "append", "idempotent": True, "reversible": True, "warning": "确认后仅追加不存在的记录，重复记录会跳过；可在恢复记录中撤销本批次新增内容"}
    digest = _backup_hash(backup)
    snapshot = db.scalar(select(BackupSnapshot).where(BackupSnapshot.sha256 == digest))
    if snapshot is None:
        snapshot = BackupSnapshot(label="恢复来源快照", source="restore", sha256=digest, payload=backup, summary=counts)
        db.add(snapshot); db.flush()
    try:
        result = _restore_items(backup, db)
        batch = RestoreBatch(snapshot_id=snapshot.id, requested_counts=counts, restored_counts=result["restored"], skipped_counts=result["skipped"], created_ids={"ids": result["created_ids"], "snapshots": result["created_snapshots"]})
        db.add(batch); db.commit(); db.refresh(batch)
    except Exception:
        db.rollback()
        raise
    _audit(db, "backup", batch.id, "restore", None, {"requested": counts, **result})
    return {"restored": True, "restore_batch_id": batch.id, "restored_counts": result["restored"], "skipped_counts": result["skipped"], "created_ids": result["created_ids"], **counts}


@app.post("/api/backup/merge")
def merge_backup_records(payload: BackupRestoreRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Field-level conflict merge: preview or apply field patches to existing records.

    Only fields explicitly present in the payload are applied. Fields that exist
    in the backup but differ from the current database are listed as conflicts.
    """
    backup = payload.backup
    keys = BACKUP_KEYS
    invalid = [key for key, value in backup.items() if key in keys and not isinstance(value, list)]
    if invalid:
        raise HTTPException(status_code=422, detail=f"备份字段必须是数组: {', '.join(invalid)}")
    model_map = {
        "goals": LearningGoal, "stages": LearningStage, "tasks": StudyTask,
        "task_time_entries": TaskTimeEntry, "task_verifications": TaskVerification,
        "daily_logs": DailyLog, "notes": Note, "blog_drafts": BlogDraft, "knowledge_topics": KnowledgeTopic,
        "knowledge_relations": KnowledgeTopicRelation, "projects": LearningProject, "project_milestones": ProjectMilestone,
        "reviews": DailyLogReview, "weekly_plans": WeeklyPlan, "review_cards": ReviewCard,
        "review_history": ReviewHistory, "teaching_sessions": TeachingSession,
        "teaching_attempts": TeachingAttempt, "authorized_directories": AuthorizedDirectory,
        "capabilities": CapabilityProfile, "capability_assessments": CapabilityAssessment,
        "practice_exercises": PracticeExercise, "practice_attempts": PracticeAttempt,
        "code_runs": CodeRun, "web_resources": WebResource, "github_repositories": GitHubRepository, "github_commits": GitHubCommit, "job_analyses": JobAnalysis, "model_calls": ModelCallLog,
    }
    id_lookup: dict[str, dict[str, Any]] = {
        "knowledge_topics": {item.name: {"id": item.id, "row": item} for item in db.scalars(select(KnowledgeTopic))},
        "authorized_directories": {item.path: {"id": item.id, "row": item} for item in db.scalars(select(AuthorizedDirectory))},
        "capabilities": {item.name: {"id": item.id, "row": item} for item in db.scalars(select(CapabilityProfile))},
        "practice_exercises": {item.title: {"id": item.id, "row": item} for item in db.scalars(select(PracticeExercise))},
        "web_resources": {_entity_match_key("web_resources", {"url": item.url, "sha256": item.sha256}): {"id": item.id, "row": item} for item in db.scalars(select(WebResource))},
        "github_repositories": {item.full_name: {"id": item.id, "row": item} for item in db.scalars(select(GitHubRepository))},
        "github_commits": {item.id: {"id": item.id, "row": item} for item in db.scalars(select(GitHubCommit))},
    }
    for key in ("goals", "stages", "tasks", "task_time_entries", "task_verifications", "daily_logs", "notes", "blog_drafts", "knowledge_relations", "projects", "project_milestones", "reviews", "weekly_plans", "review_cards", "review_history", "teaching_sessions", "teaching_attempts", "capability_assessments", "practice_attempts", "code_runs", "web_resources", "github_repositories", "github_commits", "job_analyses", "model_calls"):
        model = model_map[key]
        id_lookup[key] = {item.id: {"id": item.id, "row": item} for item in db.scalars(select(model))}

    patches: list[dict[str, Any]] = []
    for key in keys:
        for item in backup.get(key) or []:
            if key == "knowledge_topics":
                match_key = str(item.get("name", ""))
            elif key == "authorized_directories":
                match_key = str(item.get("path", ""))
            elif key == "capabilities":
                match_key = str(item.get("name", ""))
            elif key == "practice_exercises":
                match_key = str(item.get("title", ""))
            elif key == "web_resources":
                match_key = _entity_match_key(key, item)
            elif key == "github_repositories":
                match_key = str(item.get("full_name", ""))
            else:
                match_key = item.get("id")
            current = id_lookup[key].get(match_key)
            if current is None:
                continue
            row = current["row"]
            skipped_fields = {"id"}
            if key == "goals":
                skipped_fields |= {"stages"}
            if key == "stages":
                skipped_fields |= {"goal_id", "tasks"}
            if key == "tasks":
                skipped_fields |= {"stage_id", "project_id", "topic_id"}
            if key in {"task_time_entries", "task_verifications"}:
                skipped_fields |= {"task_id"}
            if key == "daily_logs":
                skipped_fields |= {"topic_ids", "note_ids", "project_id", "reviews"}
            if key == "notes":
                skipped_fields |= {"linked_topic_ids", "linked_task_ids", "linked_project_ids"}
            if key == "knowledge_relations":
                skipped_fields |= {"source_topic_id", "target_topic_id"}
            if key == "reviews":
                skipped_fields |= {"daily_log_id", "topic_id"}
            if key == "review_history":
                skipped_fields |= {"card_id"}
            if key == "teaching_attempts":
                skipped_fields |= {"session_id", "topic_id", "task_id", "stage_id", "review_card_id"}
            if key == "project_milestones":
                skipped_fields |= {"project_id"}
            if key == "capability_assessments":
                skipped_fields |= {"capability_id"}
            if key == "practice_attempts":
                skipped_fields |= {"exercise_id"}
            if key == "code_runs":
                skipped_fields |= {"exercise_id"}
            if key == "authorized_directories":
                skipped_fields |= {"active"}
            if key == "capabilities":
                skipped_fields |= {"evidence"}
            if key == "github_repositories":
                skipped_fields |= {"project_id"}
            if key == "github_commits":
                skipped_fields |= {"repository_id"}
            if key in {"goals", "projects", "notes", "daily_logs", "knowledge_topics", "project_milestones", "practice_exercises", "job_analyses"}:
                skipped_fields |= {"created_at", "updated_at"}
            if key in {"capability_assessments", "practice_attempts", "code_runs"}:
                skipped_fields |= {"created_at"}
            conflicts = []
            applicable = {}
            for field, value in item.items():
                if field in skipped_fields:
                    continue
                current_value = getattr(row, field, None)
                normalized_value = value
                if isinstance(current_value, datetime):
                    normalized_value = _parse_datetime(value) or value
                elif isinstance(current_value, date) and not isinstance(current_value, datetime) and isinstance(value, str):
                    try: normalized_value = date.fromisoformat(value)
                    except ValueError: normalized_value = value
                if current_value != normalized_value:
                    conflicts.append({"field": field, "current": current_value, "backup": value})
                    applicable[field] = normalized_value
            if applicable:
                patches.append({"entity_type": key, "match_key": match_key, "label": item.get("title") or item.get("name") or str(match_key), "fields": applicable, "conflicts": conflicts})

    selection_map = {(item.entity_type, str(item.match_key)): set(item.fields) for item in payload.selections}
    if payload.selections:
        for patch in patches:
            selected = selection_map.get((patch["entity_type"], str(patch["match_key"])), set())
            patch["fields"] = {field: value for field, value in patch["fields"].items() if field in selected}
            patch["conflicts"] = [item for item in patch["conflicts"] if item["field"] in selected]
        patches = [patch for patch in patches if patch["fields"]]

    if not payload.confirmed:
        return {"applied": False, "requires_confirmation": True, "preview": {"affected_records": len(patches), "patches": patches}, "warning": "确认后仅把备份中的字段补到已存在记录上；可在选择字段后只覆盖选中的冲突，外键和 id 字段始终跳过"}

    applied_count = 0
    audit_rows: list[dict[str, Any]] = []
    for patch in patches:
        current = id_lookup[patch["entity_type"]].get(patch["match_key"])
        if current is None:
            continue
        row = current["row"]
        if patch["entity_type"] == "tasks" and "status" in patch["fields"]:
            _ensure_task_transition(row.status, patch["fields"]["status"])
        before_data = {field: getattr(row, field, None) for field in patch["fields"]}
        for field, value in patch["fields"].items():
            if patch["entity_type"] == "tasks" and field == "status":
                _apply_task_status(row, value)
            elif field in {"completed_at", "last_verified_at", "verified_at", "created_at"}:
                parsed = _parse_datetime(value)
                if parsed is not None:
                    value = parsed
                setattr(row, field, value)
            elif field == "next_review_date" and isinstance(value, str):
                setattr(row, field, date.fromisoformat(value))
            else:
                setattr(row, field, value)
        applied_count += 1
        audit_rows.append({"entity_type": patch["entity_type"], "entity_id": row.id, "before": json.loads(json.dumps(before_data, ensure_ascii=False, default=str)), "after": json.loads(json.dumps(patch["fields"], ensure_ascii=False, default=str))})
    merge_batch = BackupMergeBatch(status="completed", patches=json.loads(json.dumps(audit_rows, ensure_ascii=False, default=str)))
    db.add(merge_batch)
    db.commit()
    for row in audit_rows:
        _audit(db, row["entity_type"], row["entity_id"], "backup_merge", row["before"], row["after"])
    return {"applied": True, "merge_batch_id": merge_batch.id, "affected_records": applied_count, "patches": patches, "skipped_records": sum(len(backup.get(key) or []) for key in keys) - applied_count}


@app.get("/api/backup/restore-batches")
def list_restore_batches(limit: int = 30, db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    rows = list(db.scalars(select(RestoreBatch).order_by(RestoreBatch.created_at.desc(), RestoreBatch.id.desc()).limit(max(1, min(limit, 100)))))
    return [{"id": row.id, "snapshot_id": row.snapshot_id, "status": row.status, "requested_counts": row.requested_counts or {}, "restored_counts": row.restored_counts or {}, "skipped_counts": row.skipped_counts or {}, "created_ids": row.created_ids or {}, "created_at": row.created_at, "reverted_at": row.reverted_at} for row in rows]


@app.get("/api/backup/merge-batches")
def list_backup_merge_batches(limit: int = 30, db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    rows = list(db.scalars(select(BackupMergeBatch).order_by(BackupMergeBatch.created_at.desc(), BackupMergeBatch.id.desc()).limit(max(1, min(limit, 100)))))
    return [{"id": row.id, "status": row.status, "patch_count": len(row.patches or []), "created_at": row.created_at, "reverted_at": row.reverted_at} for row in rows]


@app.post("/api/backup/merge-batches/{batch_id}/revert")
def revert_backup_merge_batch(batch_id: int, payload: dict[str, Any], db: Session = Depends(get_db)) -> dict[str, Any]:
    batch = db.get(BackupMergeBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="合并批次不存在")
    if not payload.get("confirmed"):
        return {"reverted": False, "requires_confirmation": True, "preview": {"patch_count": len(batch.patches or []), "status": batch.status}, "warning": "撤销只会恢复仍保持合并后状态的字段；已被后续修改的字段会跳过"}
    if batch.status == "reverted":
        return {"reverted": True, "already_reverted": True, "merge_batch_id": batch.id}
    model_map = {"goals": LearningGoal, "stages": LearningStage, "tasks": StudyTask, "task_time_entries": TaskTimeEntry, "task_verifications": TaskVerification, "daily_logs": DailyLog, "notes": Note, "knowledge_topics": KnowledgeTopic, "projects": LearningProject, "project_milestones": ProjectMilestone, "reviews": DailyLogReview, "weekly_plans": WeeklyPlan, "review_cards": ReviewCard, "review_history": ReviewHistory, "teaching_sessions": TeachingSession, "teaching_attempts": TeachingAttempt, "capabilities": CapabilityProfile, "capability_assessments": CapabilityAssessment, "practice_exercises": PracticeExercise, "practice_attempts": PracticeAttempt, "code_runs": CodeRun, "github_repositories": GitHubRepository, "github_commits": GitHubCommit, "job_analyses": JobAnalysis, "model_calls": ModelCallLog}
    reverted = 0
    conflicts: list[dict[str, Any]] = []
    for patch in batch.patches or []:
        model = model_map.get(patch.get("entity_type"))
        row = db.get(model, patch.get("entity_id")) if model else None
        if row is None:
            conflicts.append({"entity_type": patch.get("entity_type"), "entity_id": patch.get("entity_id"), "reason": "记录不存在"})
            continue
        for field, after_value in (patch.get("after") or {}).items():
            current_value = getattr(row, field, None)
            comparable_after = after_value
            if isinstance(current_value, datetime):
                comparable_after = _parse_datetime(after_value) or after_value
            elif isinstance(current_value, date) and not isinstance(current_value, datetime) and isinstance(after_value, str):
                try: comparable_after = date.fromisoformat(after_value)
                except ValueError: comparable_after = after_value
            if current_value != comparable_after:
                conflicts.append({"entity_type": patch.get("entity_type"), "entity_id": patch.get("entity_id"), "field": field, "reason": "字段已被后续修改"})
                continue
            before_value = (patch.get("before") or {}).get(field)
            if isinstance(current_value, datetime):
                before_value = _parse_datetime(before_value) or before_value
            elif isinstance(current_value, date) and not isinstance(current_value, datetime) and isinstance(before_value, str):
                try: before_value = date.fromisoformat(before_value)
                except ValueError: pass
            setattr(row, field, before_value)
            reverted += 1
    batch.status = "reverted" if not conflicts else ("partially_reverted" if reverted else "revert_conflict")
    batch.reverted_at = datetime.now(timezone.utc)
    db.commit()
    _audit(db, "backup_merge", batch.id, "revert", {"patch_count": len(batch.patches or [])}, {"reverted_fields": reverted, "conflicts": conflicts})
    return {"reverted": reverted > 0 and not conflicts, "partially_reverted": reverted > 0 and bool(conflicts), "merge_batch_id": batch.id, "reverted_fields": reverted, "conflicts": conflicts}


@app.post("/api/backup/restore-batches/{batch_id}/revert")
def revert_restore_batch(batch_id: int, payload: dict[str, Any], db: Session = Depends(get_db)) -> dict[str, Any]:
    batch = db.get(RestoreBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="恢复批次不存在")
    stored_created = batch.created_ids or {}
    created_ids = stored_created.get("ids", stored_created)
    created_snapshots = stored_created.get("snapshots", {})
    preview = {key: len(value or []) for key, value in created_ids.items()}
    if not bool(payload.get("confirmed")):
        return {"reverted": False, "requires_confirmation": True, "preview": preview, "warning": "撤销只会删除本恢复批次实际新增且仍保持恢复后快照的记录；已被后续修改的记录会跳过并报告冲突"}
    if batch.status == "reverted":
        return {"reverted": True, "already_reverted": True, "restore_batch_id": batch.id, "preview": preview}
    model_map = {"goals": LearningGoal, "stages": LearningStage, "tasks": StudyTask, "task_time_entries": TaskTimeEntry, "task_verifications": TaskVerification, "daily_logs": DailyLog, "notes": Note, "knowledge_topics": KnowledgeTopic, "knowledge_relations": KnowledgeTopicRelation, "projects": LearningProject, "project_milestones": ProjectMilestone, "reviews": DailyLogReview, "weekly_plans": WeeklyPlan, "review_cards": ReviewCard, "review_history": ReviewHistory, "teaching_sessions": TeachingSession, "teaching_attempts": TeachingAttempt, "authorized_directories": AuthorizedDirectory, "capabilities": CapabilityProfile, "capability_assessments": CapabilityAssessment, "practice_exercises": PracticeExercise, "practice_attempts": PracticeAttempt, "code_runs": CodeRun, "file_imports": FileImport, "imported_files": ImportedFile, "file_analyses": FileAnalysis, "web_resources": WebResource, "github_repositories": GitHubRepository, "github_commits": GitHubCommit, "chat_messages": ChatMessage, "model_calls": ModelCallLog}
    delete_order = ("practice_attempts", "code_runs", "practice_exercises", "capability_assessments", "teaching_attempts", "review_history", "task_time_entries", "task_verifications", "reviews", "file_analyses", "imported_files", "github_commits", "github_repositories", "job_analyses", "web_resources", "teaching_sessions", "review_cards", "weekly_plans", "daily_logs", "notes", "tasks", "stages", "knowledge_relations", "project_milestones", "projects", "knowledge_topics", "file_imports", "authorized_directories", "goals", "capabilities", "chat_messages", "model_calls")
    try:
        deleted: dict[str, int] = {}
        conflicts: list[dict[str, Any]] = []
        for key in delete_order:
            ids = created_ids.get(key, [])
            model = model_map.get(key)
            if model is None:
                continue
            expected_by_id = {item.get("id"): item.get("snapshot") for item in created_snapshots.get(key, [])}
            rows = list(db.scalars(select(model).where(model.id.in_(ids)))) if ids else []
            deleted[key] = 0
            for row in rows:
                expected = expected_by_id.get(row.id)
                if expected is not None and not _restore_snapshot_matches(row, expected):
                    conflicts.append({"entity_type": key, "entity_id": row.id, "reason": "恢复后记录已被修改"})
                    continue
                db.delete(row)
                deleted[key] += 1
        batch.status = "reverted" if not conflicts else ("partially_reverted" if any(deleted.values()) else "revert_conflict"); batch.reverted_at = datetime.now(timezone.utc)
        db.commit()
    except Exception:
        db.rollback()
        raise
    _audit(db, "backup", batch.id, "revert", {"created_ids": batch.created_ids or {}}, {"deleted": deleted, "conflicts": conflicts})
    return {"reverted": not conflicts, "partially_reverted": any(deleted.values()) and bool(conflicts), "restore_batch_id": batch.id, "deleted_counts": deleted, "conflicts": conflicts}


@app.get("/api/backup/restore-status")
def restore_status() -> dict[str, Any]:
    return {"supported": True, "requires_confirmation": True, "strategy": "append", "idempotent": True, "warning": "恢复操作会追加不存在的记录，不会删除现有数据；重复记录会跳过，失败会整体回滚"}


def _analytics_day_key(value: date | datetime | None) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    return value.isoformat() if value else date.today().isoformat()


@app.get("/api/analytics/summary")
def analytics_summary(days: int = 30, db: Session = Depends(get_db)) -> dict[str, Any]:
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    window_start = today - timedelta(days=max(1, min(days, 365)) - 1)
    logs = list(db.scalars(select(DailyLog)))
    tasks = list(db.scalars(select(StudyTask)))
    time_entries = list(db.scalars(select(TaskTimeEntry)))
    task_timer_seconds: dict[int, int] = {}
    for entry in time_entries:
        task_timer_seconds[entry.task_id] = task_timer_seconds.get(entry.task_id, 0) + _entry_elapsed(entry)
    task_by_id = {task.id: task for task in tasks}
    reviews = list(db.scalars(select(ReviewHistory)))
    attempts = list(db.scalars(select(TeachingAttempt)))
    practice_exercises = list(db.scalars(select(PracticeExercise)))
    practice_attempts = list(db.scalars(select(PracticeAttempt)))
    code_runs = list(db.scalars(select(CodeRun)))
    projects = list(db.scalars(select(LearningProject)))
    milestones = list(db.scalars(select(ProjectMilestone)))
    review_cards = list(db.scalars(select(ReviewCard)))
    topics = {topic.id: topic for topic in db.scalars(select(KnowledgeTopic))}
    daily: dict[str, dict[str, Any]] = {}
    for offset in range((today - window_start).days + 1):
        key = (window_start + timedelta(days=offset)).isoformat()
        daily[key] = {"date": key, "minutes": 0, "outputs": 0, "logs": 0, "completed_tasks": 0, "reviews": 0, "review_quality": None, "teaching_attempts": 0, "teaching_score": None}
    for log in logs:
        key = _analytics_day_key(log.log_date)
        if key in daily:
            daily[key]["minutes"] += log.extracted_duration or 0
            daily[key]["outputs"] += len(log.extracted_outputs or [])
            daily[key]["logs"] += 1
    for task in tasks:
        key = _analytics_day_key(task.updated_at)
        if key in daily and task.status in {"completed", "mastered"}:
            daily[key]["completed_tasks"] += 1
        timer_minutes = task_timer_seconds.get(task.id, 0) // 60
        if key in daily:
            daily[key]["minutes"] += timer_minutes
    review_scores: dict[str, list[int]] = {}
    for history in reviews:
        key = _analytics_day_key(history.reviewed_at)
        if key in daily:
            daily[key]["reviews"] += 1
            review_scores.setdefault(key, []).append(history.quality)
    for key, values in review_scores.items(): daily[key]["review_quality"] = round(sum(values) / len(values), 2)
    teaching_scores: dict[str, list[int]] = {}
    for attempt in attempts:
        key = _analytics_day_key(attempt.evaluated_at or attempt.created_at)
        if key in daily:
            daily[key]["teaching_attempts"] += 1
            if attempt.score is not None: teaching_scores.setdefault(key, []).append(attempt.score)
    for key, values in teaching_scores.items(): daily[key]["teaching_score"] = round(sum(values) / len(values), 2)
    topic_stats: dict[str, dict[str, Any]] = {}
    for task in tasks:
        if task.topic_id and task.topic_id in topics:
            item = topic_stats.setdefault(str(task.topic_id), {"topic_id": task.topic_id, "name": topics[task.topic_id].name, "domain": topics[task.topic_id].domain, "task_count": 0, "completed_tasks": 0, "minutes": 0, "review_count": 0, "average_quality": None, "teaching_attempts": 0, "average_score": None})
            item["task_count"] += 1; item["completed_tasks"] += task.status in {"completed", "mastered"}; item["minutes"] += task_timer_seconds.get(task.id, 0) // 60 or (task.actual_minutes or 0)
    for history in reviews:
        card = db.get(ReviewCard, history.card_id)
        topic_id = card.topic_id if card else None
        if topic_id and topic_id in topics:
            item = topic_stats.setdefault(str(topic_id), {"topic_id": topic_id, "name": topics[topic_id].name, "domain": topics[topic_id].domain, "task_count": 0, "completed_tasks": 0, "minutes": 0, "review_count": 0, "average_quality": None, "teaching_attempts": 0, "average_score": None})
            item.setdefault("_qualities", []).append(history.quality); item["review_count"] += 1
    for attempt in attempts:
        if attempt.topic_id and attempt.topic_id in topics:
            item = topic_stats.setdefault(str(attempt.topic_id), {"topic_id": attempt.topic_id, "name": topics[attempt.topic_id].name, "domain": topics[attempt.topic_id].domain, "task_count": 0, "completed_tasks": 0, "minutes": 0, "review_count": 0, "average_quality": None, "teaching_attempts": 0, "average_score": None})
            item.setdefault("_scores", []).append(attempt.score); item["teaching_attempts"] += 1
    for item in topic_stats.values():
        qualities = item.pop("_qualities", []); scores = [score for score in item.pop("_scores", []) if score is not None]
        item["average_quality"] = round(sum(qualities) / len(qualities), 2) if qualities else None
        item["average_score"] = round(sum(scores) / len(scores), 2) if scores else None
    profiles = list(db.scalars(select(CapabilityProfile).order_by(CapabilityProfile.name)))
    task_status_counts = {status_name: sum(task.status == status_name for task in tasks) for status_name in TASK_STATUSES}
    due_tasks = [task for task in tasks if task.due_date is not None and task.due_date <= today]
    overdue_tasks = [task for task in due_tasks if task.status not in {"completed", "mastered"} and task.due_date < today]
    theory_count = sum(task.task_type in {"reading", "theory", "lecture", "review"} for task in tasks)
    practice_count = sum(task.task_type not in {"reading", "theory", "lecture", "review"} for task in tasks)
    passed_practice = sum(bool(item.passed) for item in practice_attempts)
    project_milestone_count = len(milestones)
    completed_milestones = sum(item.status in {"completed", "done", "已完成"} for item in milestones)
    repeated_errors = [card for card in review_cards if card.error_count > 1 or card.error_type]
    error_trend: dict[str, int] = {}
    for card in repeated_errors:
        key = _analytics_day_key(card.updated_at)
        if key in daily:
            error_trend[key] = error_trend.get(key, 0) + max(1, card.error_count)
    capability_growth: dict[str, list[dict[str, Any]]] = {}
    for profile in profiles:
        running = 0.0
        rows = list(db.scalars(select(CapabilityEvidence).where(CapabilityEvidence.capability_id == profile.id).order_by(CapabilityEvidence.created_at, CapabilityEvidence.id)))
        points: list[dict[str, Any]] = []
        for row in rows:
            running = min(8.0, round(running + max(0.0, row.score), 2))
            points.append({"date": _analytics_day_key(row.created_at), "level": running, "source_type": row.source_type, "source_id": row.source_id})
        capability_growth[profile.name] = points
    return {
        "today_minutes": sum(log.extracted_duration or 0 for log in logs if log.log_date == today) + sum(seconds // 60 for task_id, seconds in task_timer_seconds.items() if task_by_id.get(task_id) and _analytics_day_key(task_by_id[task_id].updated_at) == today.isoformat()),
        "week_minutes": sum(log.extracted_duration or 0 for log in logs if log.log_date >= week_start) + sum(seconds // 60 for task_id, seconds in task_timer_seconds.items() if task_by_id.get(task_id) and _aware(task_by_id[task_id].updated_at).date() >= week_start),
        "total_logs": len(logs), "total_tasks": len(tasks), "completed_tasks": sum(task.status in {"completed", "mastered"} for task in tasks),
        "task_status_counts": task_status_counts,
        "outputs": sum(len(log.extracted_outputs or []) for log in logs if log.log_date >= week_start),
        "daily": list(daily.values()), "topics": list(topic_stats.values()),
        "capabilities": [{"id": profile.id, "name": profile.name, "level": profile.level, "confidence": profile.confidence, "evidence_count": profile.evidence_count, "last_assessed_at": profile.last_assessed_at, "growth": capability_growth.get(profile.name, [])} for profile in profiles],
        "model_calls": {"total": db.scalar(select(func.count(ModelCallLog.id))) or 0, "actual_tokens": db.scalar(select(func.coalesce(func.sum(ModelCallLog.total_tokens), 0)).where(ModelCallLog.token_source == "actual")) or 0, "estimated_tokens": db.scalar(select(func.coalesce(func.sum(ModelCallLog.total_tokens), 0)).where(ModelCallLog.token_source != "actual")) or 0, "estimated_cost": float(db.scalar(select(func.coalesce(func.sum(ModelCallLog.estimated_cost), 0.0))) or 0.0)},
        "metrics": {
            "overdue_task_rate": round(len(overdue_tasks) / len(due_tasks), 3) if due_tasks else 0.0,
            "overdue_tasks": len(overdue_tasks),
            "due_tasks": len(due_tasks),
            "theory_tasks": theory_count,
            "practice_tasks": practice_count,
            "theory_practice_ratio": round(theory_count / practice_count, 3) if practice_count else None,
            "input_items": len(logs),
            "output_items": sum(len(log.extracted_outputs or []) for log in logs),
            "input_output_ratio": round(len(logs) / sum(len(log.extracted_outputs or []) for log in logs), 3) if sum(len(log.extracted_outputs or []) for log in logs) else None,
            "practice_exercises": len(practice_exercises),
            "practice_attempts": len(practice_attempts),
            "practice_pass_rate": round(passed_practice / len(practice_attempts), 3) if practice_attempts else None,
            "code_runs": len(code_runs),
            "project_count": len(projects),
            "project_milestones": project_milestone_count,
            "completed_milestones": completed_milestones,
            "project_progress_rate": round(completed_milestones / project_milestone_count, 3) if project_milestone_count else None,
            "repeated_error_cards": len(repeated_errors),
            "repeated_error_trend": [{"date": key, "count": error_trend.get(key, 0)} for key in daily if key in error_trend],
        },
    }


@app.get("/api/capabilities/{capability_id}/history", response_model=list[CapabilityAssessmentRead])
def capability_assessment_history(capability_id: int, db: Session = Depends(get_db)) -> list[CapabilityAssessment]:
    if not db.get(CapabilityProfile, capability_id):
        raise HTTPException(status_code=404, detail="能力画像不存在")
    return list(db.scalars(select(CapabilityAssessment).where(CapabilityAssessment.capability_id == capability_id).order_by(CapabilityAssessment.created_at.desc(), CapabilityAssessment.id.desc())))


@app.get("/api/capabilities/{capability_id}/evidence")
def capability_evidence(capability_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    profile = db.get(CapabilityProfile, capability_id)
    if not profile:
        raise HTTPException(status_code=404, detail="能力画像不存在")

    needle = profile.name.casefold().strip()
    topics = list(db.scalars(select(KnowledgeTopic).order_by(KnowledgeTopic.name, KnowledgeTopic.id)))
    matched_topics = [
        topic
        for topic in topics
        if needle == str(topic.domain or "").casefold().strip()
        or needle in topic.name.casefold()
    ]
    topic_ids = {topic.id for topic in matched_topics}
    topic_payload = [
        {
            "id": topic.id,
            "name": topic.name,
            "domain": topic.domain,
            "match_reason": "能力名称匹配主题领域" if needle == str(topic.domain or "").casefold().strip() else "能力名称匹配主题名称",
        }
        for topic in matched_topics
    ]

    exercises = list(db.scalars(select(PracticeExercise).order_by(PracticeExercise.created_at, PracticeExercise.id)))
    matched_exercises = [
        exercise
        for exercise in exercises
        if exercise.topic_id in topic_ids
        or needle in f"{exercise.title} {exercise.prompt}".casefold()
    ]
    exercise_ids = {exercise.id for exercise in matched_exercises}
    attempts = list(
        db.scalars(
            select(PracticeAttempt)
            .where(PracticeAttempt.exercise_id.in_(exercise_ids))
            .order_by(PracticeAttempt.created_at, PracticeAttempt.id)
        )
    ) if exercise_ids else []
    attempts_by_exercise: dict[int, list[PracticeAttempt]] = {}
    for attempt in attempts:
        attempts_by_exercise.setdefault(attempt.exercise_id, []).append(attempt)
    practice_exercises = [
        {
            "id": exercise.id,
            "title": exercise.title,
            "exercise_type": exercise.exercise_type,
            "prompt": exercise.prompt,
            "difficulty": exercise.difficulty,
            "topic_id": exercise.topic_id,
            "match_reason": "关联知识主题" if exercise.topic_id in topic_ids else "能力名称匹配题目",
            "attempts": [
                {
                    "id": attempt.id,
                    "status": attempt.status,
                    "passed": attempt.passed,
                    "score": attempt.score,
                    "feedback": attempt.feedback,
                    "created_at": attempt.created_at,
                }
                for attempt in attempts_by_exercise.get(exercise.id, [])
            ],
        }
        for exercise in matched_exercises
    ]
    passed_attempt_count = sum(bool(attempt.passed) for attempt in attempts)

    review_cards = list(
        db.scalars(
            select(ReviewCard)
            .where(ReviewCard.topic_id.in_(topic_ids))
            .order_by(ReviewCard.updated_at, ReviewCard.id)
        )
    ) if topic_ids else []
    card_ids = {card.id for card in review_cards}
    histories = list(
        db.scalars(
            select(ReviewHistory)
            .where(ReviewHistory.card_id.in_(card_ids), ReviewHistory.quality < 3)
            .order_by(ReviewHistory.reviewed_at, ReviewHistory.id)
        )
    ) if card_ids else []
    histories_by_card: dict[int, list[ReviewHistory]] = {}
    for history in histories:
        histories_by_card.setdefault(history.card_id, []).append(history)
    error_cards = [card for card in review_cards if card.error_count > 0 or card.id in histories_by_card]
    by_error_type: dict[str, int] = {}
    for history in histories:
        error_type = history.error_type or "回忆失败"
        by_error_type[error_type] = by_error_type.get(error_type, 0) + 1
    review_payload = [
        {
            "id": card.id,
            "front": card.front,
            "topic_id": card.topic_id,
            "error_type": card.error_type,
            "error_count": card.error_count,
            "last_error_note": card.last_error_note,
            "error_events": [
                {
                    "id": history.id,
                    "quality": history.quality,
                    "error_type": history.error_type,
                    "error_note": history.error_note,
                    "reviewed_at": history.reviewed_at,
                }
                for history in histories_by_card.get(card.id, [])
            ],
        }
        for card in error_cards
    ]

    saved_evidence = list(
        db.scalars(
            select(CapabilityEvidence)
            .where(CapabilityEvidence.capability_id == profile.id)
            .order_by(CapabilityEvidence.created_at, CapabilityEvidence.id)
        )
    )
    return {
        "capability": {
            "id": profile.id,
            "name": profile.name,
            "description": profile.description,
            "level": profile.level,
            "confidence": profile.confidence,
            "evidence_count": profile.evidence_count,
            "last_assessed_at": profile.last_assessed_at,
        },
        "topics": topic_payload,
        "practice": {
            "exercise_count": len(matched_exercises),
            "attempt_count": len(attempts),
            "passed_attempt_count": passed_attempt_count,
            "pass_rate": round(passed_attempt_count / len(attempts), 3) if attempts else None,
            "exercises": practice_exercises,
        },
        "review": {
            "card_count": len(error_cards),
            "error_event_count": len(histories),
            "by_error_type": by_error_type,
            "cards": review_payload,
        },
        "saved_evidence": [
            {
                "id": item.id,
                "source_type": item.source_type,
                "source_id": item.source_id,
                "score": item.score,
                "note": item.note,
                "created_at": item.created_at,
            }
            for item in saved_evidence
        ],
    }


@app.post("/api/capabilities/{capability_id}/plan", response_model=AgentPlanProposalResponse)
def propose_capability_plan(capability_id: int, db: Session = Depends(get_db)) -> AgentPlanProposalResponse:
    profile = db.get(CapabilityProfile, capability_id)
    if not profile:
        raise HTTPException(status_code=404, detail="能力画像不存在")
    tasks = list(db.scalars(select(StudyTask).order_by(StudyTask.priority, StudyTask.due_date, StudyTask.id)))
    changes: list[dict[str, Any]] = []
    for task in tasks:
        if task.status in {"completed", "mastered"}:
            continue
        searchable = f"{task.title} {task.description} {task.expected_outcome}".casefold()
        if profile.name.casefold() not in searchable:
            continue
        before = TaskRead.model_validate(task).model_dump(mode="json")
        after = dict(before)
        after["priority"] = max(1, task.priority - 1)
        if task.due_date is None:
            after["due_date"] = (date.today() + timedelta(days=7)).isoformat()
        changes.append({"task_id": task.id, "before": {"due_date": before.get("due_date"), "priority": before.get("priority")}, "after": {"due_date": after.get("due_date"), "priority": after.get("priority")}, "reason": f"补强能力：{profile.name}"})
        if len(changes) >= 12:
            break
    proposal = AgentPlanProposal(status="pending", reason=f"基于能力 {profile.name} 的最新证据安排下一步实践", signal_summary={"capability_id": profile.id, "capability_name": profile.name, "level": profile.level, "confidence": profile.confidence, "evidence_count": profile.evidence_count}, changes=changes, impact={"affected_tasks": len(changes), "capability_id": profile.id, "requires_confirmation": True})
    db.add(proposal); db.commit(); db.refresh(proposal)
    return _plan_proposal_response(proposal)
