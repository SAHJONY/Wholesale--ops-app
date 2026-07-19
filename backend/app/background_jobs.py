from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import DateTime, Integer, JSON, String, Text, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .auth import Principal, get_principal, require_role
from .auth_models import WorkspaceEntity
from .database import Base, get_db
from .event_bus import process_events
from .models import Lead


class BackgroundJob(Base):
    __tablename__ = "background_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(Integer, index=True)
    job_type: Mapped[str] = mapped_column(String(80), index=True)
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    priority: Mapped[int] = mapped_column(Integer, default=50, index=True)
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict)
    result_json: Mapped[dict] = mapped_column(JSON, default=dict)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5)
    available_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


router = APIRouter(prefix="/jobs", tags=["durable background jobs"])
SUPPORTED_JOB_TYPES = {"process_events", "acquisition_lead"}


def _linked_lead(db: Session, organization_id: int, lead_id: int) -> Lead:
    linked = db.scalar(select(WorkspaceEntity.id).where(
        WorkspaceEntity.organization_id == organization_id,
        WorkspaceEntity.entity_type == "lead",
        WorkspaceEntity.entity_id == lead_id,
    ))
    lead = db.get(Lead, lead_id)
    if not linked or not lead:
        raise HTTPException(404, "Lead not found in this workspace")
    return lead


def _retry_delay(attempts: int) -> timedelta:
    minutes = min(60, 2 ** max(0, attempts - 1))
    return timedelta(minutes=minutes)


async def _execute_job(db: Session, principal: Principal, job: BackgroundJob) -> dict:
    if job.job_type == "process_events":
        limit = max(1, min(200, int(job.payload_json.get("limit") or 50)))
        return process_events(db, principal.organization_id, limit)

    if job.job_type == "acquisition_lead":
        lead_id = int(job.payload_json.get("lead_id") or 0)
        lead = _linked_lead(db, principal.organization_id, lead_id)
        try:
            from .acquisition_worker import _process_one
        except Exception as exc:
            raise RuntimeError(f"Acquisition worker unavailable: {type(exc).__name__}: {exc}") from exc
        return await _process_one(db, principal, lead, force=bool(job.payload_json.get("force")))

    raise RuntimeError(f"Unsupported job type: {job.job_type}")


def _serialize(job: BackgroundJob) -> dict:
    return {
        "id": job.id,
        "job_type": job.job_type,
        "status": job.status,
        "priority": job.priority,
        "attempts": job.attempts,
        "max_attempts": job.max_attempts,
        "available_at": job.available_at,
        "started_at": job.started_at,
        "completed_at": job.completed_at,
        "failed_at": job.failed_at,
        "last_error": job.last_error,
        "payload": job.payload_json,
        "result": job.result_json,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
    }


@router.get("/snapshot")
def snapshot(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    counts = dict(db.execute(select(BackgroundJob.status, func.count(BackgroundJob.id)).where(
        BackgroundJob.organization_id == principal.organization_id,
    ).group_by(BackgroundJob.status)).all())
    rows = db.scalars(select(BackgroundJob).where(
        BackgroundJob.organization_id == principal.organization_id,
    ).order_by(BackgroundJob.created_at.desc()).limit(100)).all()
    return {
        "generated_at": datetime.utcnow(),
        "counts": counts,
        "supported_job_types": sorted(SUPPORTED_JOB_TYPES),
        "jobs": [_serialize(job) for job in rows],
    }


@router.post("")
def enqueue(payload: dict, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    job_type = str(payload.get("job_type") or "").strip()
    if job_type not in SUPPORTED_JOB_TYPES:
        raise HTTPException(422, "Unsupported job type")
    job = BackgroundJob(
        organization_id=principal.organization_id,
        job_type=job_type,
        priority=max(1, min(100, int(payload.get("priority") or 50))),
        payload_json=payload.get("payload") or {},
        max_attempts=max(1, min(10, int(payload.get("max_attempts") or 5))),
        created_by_user_id=principal.user_id,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return _serialize(job)


@router.post("/run-next")
async def run_next(payload: dict | None = None, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    limit = max(1, min(25, int((payload or {}).get("limit") or 10)))
    now = datetime.utcnow()
    jobs = db.scalars(select(BackgroundJob).where(
        BackgroundJob.organization_id == principal.organization_id,
        BackgroundJob.status.in_(["queued", "retry"]),
        BackgroundJob.available_at <= now,
    ).order_by(BackgroundJob.priority.desc(), BackgroundJob.created_at).limit(limit)).all()
    results = []
    for job in jobs:
        job.status = "running"
        job.locked_at = now
        job.started_at = job.started_at or now
        job.attempts += 1
        db.commit()
        try:
            result = await _execute_job(db, principal, job)
            job.status = "completed"
            job.result_json = result if isinstance(result, dict) else {"result": result}
            job.completed_at = datetime.utcnow()
            job.last_error = None
        except Exception as exc:
            db.rollback()
            job = db.get(BackgroundJob, job.id)
            if not job:
                continue
            job.last_error = f"{type(exc).__name__}: {exc}"
            if job.attempts >= job.max_attempts:
                job.status = "dead_letter"
                job.failed_at = datetime.utcnow()
            else:
                job.status = "retry"
                job.available_at = datetime.utcnow() + _retry_delay(job.attempts)
        db.commit()
        results.append(_serialize(job))
    return {"processed": len(results), "jobs": results}


@router.post("/{job_id}/retry")
def retry(job_id: int, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    job = db.scalar(select(BackgroundJob).where(
        BackgroundJob.id == job_id,
        BackgroundJob.organization_id == principal.organization_id,
    ))
    if not job:
        raise HTTPException(404, "Job not found")
    if job.status not in {"failed", "dead_letter"}:
        raise HTTPException(409, "Only failed or dead-letter jobs can be retried")
    job.status = "retry"
    job.available_at = datetime.utcnow()
    job.failed_at = None
    job.last_error = None
    db.commit()
    return _serialize(job)
