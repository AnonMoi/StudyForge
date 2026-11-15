from datetime import date, datetime, timedelta, timezone
import ast
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import tempfile
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import get_db
from .models import (
    AuditLog,
    CodeRun,
    LearningProject,
    PracticeAttempt,
    PracticeExercise,
    ProjectMilestone,
    ReviewCard,
    ReviewHistory,
    StudyTask,
    utcnow,
)
from .notes_models import KnowledgeTopic
from .schemas import (
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


router = APIRouter()


def _audit(
    db: Session,
    entity_type: str,
    entity_id: int | None,
    action: str,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
) -> None:
    safe_before = json.loads(json.dumps(before, ensure_ascii=False, default=str)) if before is not None else None
    safe_after = json.loads(json.dumps(after, ensure_ascii=False, default=str)) if after is not None else None
    db.add(AuditLog(entity_type=entity_type, entity_id=entity_id, action=action, before_data=safe_before, after_data=safe_after))
    db.commit()


def _code_policy_error(code: str) -> str | None:
    allowed_imports = {"bisect", "collections", "functools", "heapq", "itertools", "json", "math", "re", "statistics"}
    blocked_calls = {"__import__", "breakpoint", "compile", "eval", "exec", "open"}
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return f"代码语法错误：{exc.msg}"
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".", 1)[0] not in allowed_imports:
                    return f"禁止导入模块：{alias.name}"
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".", 1)[0] not in allowed_imports:
                return f"禁止导入模块：{node.module or ''}"
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in blocked_calls:
                return f"禁止调用：{node.func.id}"
            if isinstance(node.func, ast.Attribute) and node.func.attr in blocked_calls:
                return f"禁止调用：{node.func.attr}"
        elif isinstance(node, ast.Name) and node.id.startswith("__"):
            return "禁止使用双下划线运行时对象"
    return None


def _run_restricted_code(code: str, stdin: str, timeout_seconds: int) -> dict[str, Any]:
    policy = {"runtime": "python", "timeout_seconds": timeout_seconds, "network": "blocked_by_policy", "filesystem": "blocked_by_static_policy", "max_output_bytes": 12000}
    policy_error = _code_policy_error(code)
    if policy_error:
        return {"status": "blocked", "stdout": "", "stderr": policy_error, "exit_code": None, "duration_ms": 0, "policy": policy}
    started = time.perf_counter()
    try:
        with tempfile.TemporaryDirectory(prefix="learning-code-run-") as workspace:
            script = Path(workspace) / "main.py"
            script.write_text(code, encoding="utf-8")
            env = {"PATH": os.environ.get("PATH", ""), "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"}
            result = subprocess.run([sys.executable, "-I", "-S", str(script)], input=stdin, capture_output=True, text=True, cwd=workspace, env=env, timeout=timeout_seconds)
        stdout = result.stdout[:12000]
        stderr = result.stderr[:12000]
        return {"status": "passed" if result.returncode == 0 else "failed", "stdout": stdout, "stderr": stderr, "exit_code": result.returncode, "duration_ms": int((time.perf_counter() - started) * 1000), "policy": policy}
    except subprocess.TimeoutExpired as exc:
        return {"status": "timeout", "stdout": str(exc.stdout or "")[:12000], "stderr": "代码运行超过时间限制", "exit_code": None, "duration_ms": int((time.perf_counter() - started) * 1000), "policy": policy}


@router.post("/code-runs", response_model=None)
def create_code_run(payload: CodeRunCreate, db: Session = Depends(get_db)) -> CodeRun | dict[str, Any]:
    if not payload.confirmed:
        return {"executed": False, "requires_confirmation": True, "policy": {"runtime": "python", "timeout_seconds": payload.timeout_seconds, "network": "blocked_by_policy", "filesystem": "blocked_by_static_policy", "max_output_bytes": 12000}, "warning": "代码将在本机受限环境中执行；请确认代码来源和运行结果可能影响学习判断。"}
    result = _run_restricted_code(payload.code, payload.stdin, payload.timeout_seconds)
    if result["status"] == "blocked":
        raise HTTPException(status_code=422, detail=result["stderr"])
    row = CodeRun(code=payload.code, stdin=payload.stdin, status=result["status"], stdout=result["stdout"], stderr=result["stderr"], exit_code=result["exit_code"], duration_ms=result["duration_ms"], policy=result["policy"])
    db.add(row); db.commit(); db.refresh(row)
    _audit(db, "code_run", row.id, "execute", None, CodeRunRead.model_validate(row).model_dump(mode="json"))
    return JSONResponse(status_code=status.HTTP_201_CREATED, content=CodeRunRead.model_validate(row).model_dump(mode="json"))


@router.get("/exercises", response_model=list[PracticeExerciseRead])
def list_exercises(exercise_type: str | None = None, db: Session = Depends(get_db)) -> list[PracticeExercise]:
    query = select(PracticeExercise).where(PracticeExercise.status == "active").order_by(PracticeExercise.created_at.desc(), PracticeExercise.id.desc())
    if exercise_type:
        if exercise_type not in {"algorithm", "sql"}:
            raise HTTPException(status_code=422, detail="练习类型不支持")
        query = query.where(PracticeExercise.exercise_type == exercise_type)
    return list(db.scalars(query))


@router.post("/exercises", response_model=PracticeExerciseRead, status_code=status.HTTP_201_CREATED)
def create_exercise(payload: PracticeExerciseCreate, db: Session = Depends(get_db)) -> PracticeExercise:
    if payload.exercise_type == "algorithm" and not isinstance(payload.validation_spec.get("cases"), list):
        raise HTTPException(status_code=422, detail="算法练习必须提供 cases 校验用例")
    if payload.exercise_type == "sql" and not all(isinstance(payload.validation_spec.get(key), str) for key in ("schema_sql", "seed_sql")):
        raise HTTPException(status_code=422, detail="SQL 练习必须提供 schema_sql 和 seed_sql")
    row = PracticeExercise(**payload.model_dump())
    db.add(row); db.commit(); db.refresh(row)
    _audit(db, "practice_exercise", row.id, "create", None, PracticeExerciseRead.model_validate(row).model_dump(mode="json"))
    return row


@router.get("/exercises/{exercise_id}", response_model=PracticeExerciseRead)
def get_exercise(exercise_id: int, db: Session = Depends(get_db)) -> PracticeExercise:
    row = db.get(PracticeExercise, exercise_id)
    if not row:
        raise HTTPException(status_code=404, detail="练习不存在")
    return row


def _normalized_rows(rows: list[tuple[Any, ...]]) -> list[list[Any]]:
    return [[value.isoformat() if isinstance(value, (date, datetime)) else value for value in row] for row in rows]


def _run_sql_validation(exercise: PracticeExercise, query: str) -> dict[str, Any]:
    if not re.match(r"^\s*(SELECT|WITH)\b", query, re.IGNORECASE) or ";" in query.rstrip(";"):
        return {"passed": False, "status": "blocked", "feedback": "SQL 练习只允许单条 SELECT/WITH 查询", "stdout": "", "stderr": "", "duration_ms": 0}
    spec = exercise.validation_spec or {}
    started = time.perf_counter()
    try:
        connection = sqlite3.connect(":memory:")
        connection.executescript(str(spec.get("schema_sql", "")))
        connection.executescript(str(spec.get("seed_sql", "")))
        cursor = connection.execute(query)
        rows = _normalized_rows(cursor.fetchmany(1000))
        expected = spec.get("expected_rows", [])
        passed = rows == expected
        feedback = "查询结果与标准答案一致" if passed else f"结果不匹配：实际 {rows[:10]}，预期 {expected[:10]}"
        return {"passed": passed, "status": "passed" if passed else "failed", "feedback": feedback, "stdout": json.dumps(rows, ensure_ascii=False), "stderr": "", "duration_ms": int((time.perf_counter() - started) * 1000)}
    except sqlite3.Error as exc:
        return {"passed": False, "status": "failed", "feedback": f"SQL 执行失败：{exc}", "stdout": "", "stderr": str(exc), "duration_ms": int((time.perf_counter() - started) * 1000)}
    finally:
        try:
            connection.close()
        except UnboundLocalError:
            pass


@router.post("/exercises/{exercise_id}/attempts", response_model=PracticeAttemptRead, status_code=status.HTTP_201_CREATED)
def submit_exercise_attempt(exercise_id: int, payload: PracticeAttemptCreate, db: Session = Depends(get_db)) -> PracticeAttempt:
    exercise = db.get(PracticeExercise, exercise_id)
    if not exercise or exercise.status != "active":
        raise HTTPException(status_code=404, detail="练习不存在")
    if exercise.exercise_type == "algorithm":
        cases = exercise.validation_spec.get("cases", [])
        results = [_run_restricted_code(payload.code, str(case.get("stdin", "")), 3) for case in cases]
        blocked = next((result for result in results if result["status"] == "blocked"), None)
        passed = bool(results) and all(result["status"] == "passed" and result["stdout"].strip() == str(case.get("expected_stdout", "")).strip() for result, case in zip(results, cases))
        result = blocked or {"status": "passed" if passed else "failed", "stdout": "\n".join(item["stdout"] for item in results), "stderr": "\n".join(item["stderr"] for item in results), "duration_ms": sum(item["duration_ms"] for item in results), "feedback": "全部测试用例通过" if passed else "至少一个测试用例未通过"}
    else:
        result = _run_sql_validation(exercise, payload.query)
        passed = bool(result["passed"])
    row = PracticeAttempt(exercise_id=exercise.id, code=payload.code, query=payload.query, answer=payload.answer, status=result["status"], passed=passed, score=1.0 if passed else 0.0, feedback=result.get("feedback", ""), stdout=result.get("stdout", ""), stderr=result.get("stderr", ""), duration_ms=result.get("duration_ms", 0))
    db.add(row); db.commit(); db.refresh(row)
    _audit(db, "practice_attempt", row.id, "submit", None, PracticeAttemptRead.model_validate(row).model_dump(mode="json"))
    return row


def _ensure_project_milestones(project: LearningProject, db: Session) -> list[ProjectMilestone]:
    rows = list(db.scalars(select(ProjectMilestone).where(ProjectMilestone.project_id == project.id).order_by(ProjectMilestone.order_index, ProjectMilestone.id)))
    if rows or not project.milestones:
        return rows
    for index, item in enumerate(project.milestones):
        if not isinstance(item, dict) or not str(item.get("title", "")).strip():
            continue
        status_name = str(item.get("status", "pending"))
        if status_name not in {"pending", "in_progress", "completed", "blocked"}:
            status_name = "pending"
        db.add(ProjectMilestone(project_id=project.id, title=str(item["title"]).strip(), description=str(item.get("description", "")), status=status_name, due_date=date.fromisoformat(item["due_date"]) if item.get("due_date") else None, order_index=index, evidence=str(item.get("evidence", "")), completed_at=utcnow() if status_name == "completed" else None))
    db.commit()
    return list(db.scalars(select(ProjectMilestone).where(ProjectMilestone.project_id == project.id).order_by(ProjectMilestone.order_index, ProjectMilestone.id)))


@router.get("/projects/{project_id}/milestones", response_model=list[ProjectMilestoneRead])
def list_project_milestones(project_id: int, db: Session = Depends(get_db)) -> list[ProjectMilestone]:
    project = db.get(LearningProject, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    return _ensure_project_milestones(project, db)


@router.post("/projects/{project_id}/milestones", response_model=ProjectMilestoneRead, status_code=status.HTTP_201_CREATED)
def create_project_milestone(project_id: int, payload: ProjectMilestoneCreate, db: Session = Depends(get_db)) -> ProjectMilestone:
    if not db.get(LearningProject, project_id):
        raise HTTPException(status_code=404, detail="项目不存在")
    if payload.status == "completed" and not payload.evidence.strip():
        raise HTTPException(status_code=422, detail="完成里程碑必须提供成果证据")
    row = ProjectMilestone(project_id=project_id, **payload.model_dump(), completed_at=utcnow() if payload.status == "completed" else None)
    db.add(row); db.commit(); db.refresh(row)
    _audit(db, "project_milestone", row.id, "create", None, ProjectMilestoneRead.model_validate(row).model_dump(mode="json"))
    return row


@router.patch("/project-milestones/{milestone_id}", response_model=ProjectMilestoneRead)
def update_project_milestone(milestone_id: int, payload: ProjectMilestoneUpdate, db: Session = Depends(get_db)) -> ProjectMilestone:
    row = db.get(ProjectMilestone, milestone_id)
    if not row:
        raise HTTPException(status_code=404, detail="里程碑不存在")
    changes = payload.model_dump(exclude_unset=True)
    target_status = changes.get("status", row.status)
    target_evidence = changes.get("evidence", row.evidence)
    if target_status == "completed" and not str(target_evidence or "").strip():
        raise HTTPException(status_code=422, detail="完成里程碑必须提供成果证据")
    before = ProjectMilestoneRead.model_validate(row).model_dump(mode="json")
    for field, value in changes.items():
        setattr(row, field, value)
    row.completed_at = utcnow() if target_status == "completed" else None
    db.commit(); db.refresh(row)
    _audit(db, "project_milestone", row.id, "update", before, ProjectMilestoneRead.model_validate(row).model_dump(mode="json"))
    return row


@router.get("/projects/{project_id}/board")
def project_board(project_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    project = db.get(LearningProject, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    rows = _ensure_project_milestones(project, db)
    columns = {status_name: [] for status_name in ("pending", "in_progress", "completed", "blocked")}
    for row in rows:
        columns.setdefault(row.status, []).append(ProjectMilestoneRead.model_validate(row).model_dump(mode="json"))
    return {"project_id": project_id, "columns": columns, "total": len(rows)}


@router.get("/projects/{project_id}/timeline")
def project_timeline(project_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    project = db.get(LearningProject, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    _ensure_project_milestones(project, db)
    milestones = list(db.scalars(select(ProjectMilestone).where(ProjectMilestone.project_id == project_id).order_by(ProjectMilestone.due_date, ProjectMilestone.order_index, ProjectMilestone.id)))
    tasks = list(db.scalars(select(StudyTask).where(StudyTask.project_id == project_id).order_by(StudyTask.due_date, StudyTask.id)))
    items = [{"type": "milestone", "id": row.id, "title": row.title, "status": row.status, "date": row.due_date, "evidence": row.evidence} for row in milestones]
    items.extend({"type": "task", "id": task.id, "title": task.title, "status": task.status, "date": task.due_date, "evidence": [verification.evidence for verification in task.verifications]} for task in tasks)
    items.sort(key=lambda item: (item["date"] or date.max, item["type"], item["id"]))
    return {"project_id": project_id, "items": items, "evidence_count": sum(bool(item.get("evidence")) for item in items)}


def _analytics_day_key(value: date | datetime | None) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    return value.isoformat() if value else date.today().isoformat()


@router.get("/review-cards/errors/analysis")
def review_error_analysis(days: int = 30, db: Session = Depends(get_db)) -> dict[str, Any]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, min(days, 365)))
    histories = list(db.scalars(select(ReviewHistory).where(ReviewHistory.quality < 3, ReviewHistory.reviewed_at >= cutoff).order_by(ReviewHistory.reviewed_at)))
    cards = {card.id: card for card in db.scalars(select(ReviewCard))}
    topics = {topic.id: topic.name for topic in db.scalars(select(KnowledgeTopic))}
    by_error: dict[str, int] = {}
    by_topic: dict[str, int] = {}
    by_day: dict[str, int] = {}
    for history in histories:
        card = cards.get(history.card_id)
        error_type = history.error_type or (card.error_type if card else None) or "回忆失败"
        by_error[error_type] = by_error.get(error_type, 0) + 1
        topic_name = topics.get(card.topic_id, "未关联主题") if card else "未关联主题"
        by_topic[topic_name] = by_topic.get(topic_name, 0) + 1
        day = _analytics_day_key(history.reviewed_at)
        by_day[day] = by_day.get(day, 0) + 1
    recommendations = []
    for error_type, count in sorted(by_error.items(), key=lambda item: (-item[1], item[0]))[:5]:
        recommendations.append({"error_type": error_type, "count": count, "action": "重新解释概念并完成一道迁移练习" if "概念" in error_type else "在 1 天内重新复习并提交带证据的回答"})
    return {"days": days, "total_errors": len(histories), "by_error_type": by_error, "by_topic": by_topic, "trend": [{"date": key, "count": value} for key, value in sorted(by_day.items())], "recommendations": recommendations}
