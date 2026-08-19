from __future__ import annotations

import os
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import Integer, JSON, String, Text, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from .auth import Principal, get_principal, require_role
from .auth_models import AppUser, CrmActivity, Membership, Organization, WorkspaceEntity
from .database import Base, UtcDateTime, get_db
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
    available_at: Mapped[datetime] = mapped_column(UtcDateTime, default=lambda: datetime.now(timezone.utc), index=True)
    locked_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    failed_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=lambda: datetime.now(timezone.utc), index=True)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))


router = APIRouter(prefix="/jobs", tags=["durable background jobs"])
SUPPORTED_JOB_TYPES = {
    "process_events",
    "acquisition_lead",
    "autonomous_property_acquisition",
    "autonomous_cash_buyer_intelligence",
    "sms_due_followups",
}
STALE_LOCK_MINUTES = 20
SCHEDULE = "*/15 * * * *"
_TRUE_VALUES = {"1", "true", "yes", "on"}


def _buyer_first_mode() -> bool:
    # Buyer-first is the current owner-directed operating phase. It defaults
    # ON so a missing env cannot silently restart nationwide property mining.
    return str(os.getenv("BUYER_FIRST_MODE", "true")).strip().lower() in _TRUE_VALUES


def _authorized_cron(authorization: str | None) -> None:
    configured = os.getenv("CRON_SECRET")
    if not configured:
        raise HTTPException(503, "CRON_SECRET is not configured")
    expected = f"Bearer {configured}"
    if not authorization or not secrets.compare_digest(authorization, expected):
        raise HTTPException(401, "Invalid cron authorization")


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
    return timedelta(minutes=min(60, 2 ** max(0, attempts - 1)))


def _owner_principal(db: Session, organization: Organization) -> Principal | None:
    membership = db.scalar(select(Membership).where(
        Membership.organization_id == organization.id,
        Membership.role == "owner",
    ))
    user = db.get(AppUser, membership.user_id) if membership else None
    if not membership or not user or not user.is_active:
        return None
    return Principal(
        organization_id=organization.id,
        organization_name=organization.name,
        user_id=user.id,
        email=user.email,
        name=user.name,
        role=membership.role,
    )


def _recover_stale_jobs(db: Session, organization_id: int, now: datetime) -> int:
    stale_before = now - timedelta(minutes=STALE_LOCK_MINUTES)
    rows = db.scalars(select(BackgroundJob).where(
        BackgroundJob.organization_id == organization_id,
        BackgroundJob.status == "running",
        BackgroundJob.locked_at.is_not(None),
        BackgroundJob.locked_at < stale_before,
    )).all()
    for job in rows:
        job.last_error = "Recovered after worker lease expired"
        job.locked_at = None
        if job.attempts >= job.max_attempts:
            job.status = "dead_letter"
            job.failed_at = now
        else:
            job.status = "retry"
            job.available_at = now
    if rows:
        db.commit()
    return len(rows)


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
    if job.job_type == "autonomous_property_acquisition":
        if _buyer_first_mode():
            raise RuntimeError("Autonomous property acquisition is paused while BUYER_FIRST_MODE is active")
        from .autonomous_property_acquisition import run_autonomous_property_acquisition
        return await run_autonomous_property_acquisition(db, principal)
    if job.job_type == "autonomous_cash_buyer_intelligence":
        from .autonomous_cash_buyer_intelligence import run_autonomous_cash_buyer_intelligence
        max_sources = max(1, min(10, int(job.payload_json.get("max_sources") or 3)))
        max_rows = max(1, min(5000, int(job.payload_json.get("max_rows") or 1000)))
        return await run_autonomous_cash_buyer_intelligence(
            db,
            principal,
            max_sources=max_sources,
            max_rows=max_rows,
        )
    if job.job_type == "sms_due_followups":
        from .sms_scheduling import prepare_due_followups
        limit = max(1, min(25, int(job.payload_json.get("limit") or 25)))
        result = prepare_due_followups({"limit": limit}, principal, db)
        return {
            **result,
            "execution_boundary": "approval_only_no_sms_dispatch",
            "automated_by": "durable_background_job",
        }
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
        "locked_at": job.locked_at,
        "started_at": job.started_at,
        "completed_at": job.completed_at,
        "failed_at": job.failed_at,
        "last_error": job.last_error,
        "payload": job.payload_json,
        "result": job.result_json,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
    }


async def _run_available(db: Session, principal: Principal, limit: int, trigger: str) -> dict:
    now = datetime.now(timezone.utc)
    recovered = _recover_stale_jobs(db, principal.organization_id, now)
    jobs = db.scalars(select(BackgroundJob).where(
        BackgroundJob.organization_id == principal.organization_id,
        BackgroundJob.status.in_(["queued", "retry"]),
        BackgroundJob.available_at <= now,
    ).order_by(BackgroundJob.priority.desc(), BackgroundJob.created_at).limit(limit)).all()
    results: list[dict] = []
    dead_lettered = 0
    for job in jobs:
        job.status = "running"
        job.locked_at = datetime.now(timezone.utc)
        job.started_at = job.started_at or datetime.now(timezone.utc)
        job.attempts += 1
        db.commit()
        try:
            result = await _execute_job(db, principal, job)
            job.status = "completed"
            job.result_json = result if isinstance(result, dict) else {"result": result}
            job.completed_at = datetime.now(timezone.utc)
            job.locked_at = None
            job.last_error = None
        except Exception as exc:
            db.rollback()
            job = db.get(BackgroundJob, job.id)
            if not job:
                continue
            job.locked_at = None
            job.last_error = f"{type(exc).__name__}: {exc}"
            if job.attempts >= job.max_attempts:
                job.status = "dead_letter"
                job.failed_at = datetime.now(timezone.utc)
                dead_lettered += 1
                db.add(CrmActivity(
                    organization_id=principal.organization_id,
                    user_id=principal.user_id,
                    activity_type="background_job_dead_letter",
                    summary=f"Background job #{job.id} moved to dead letter",
                    metadata_json={"job_id": job.id, "job_type": job.job_type, "error": job.last_error},
                ))
            else:
                job.status = "retry"
                job.available_at = datetime.now(timezone.utc) + _retry_delay(job.attempts)
        db.commit()
        results.append(_serialize(job))
    return {
        "trigger": trigger,
        "organization_id": principal.organization_id,
        "processed": len(results),
        "recovered_stale": recovered,
        "dead_lettered": dead_lettered,
        "jobs": results,
    }


@router.get("/snapshot")
def snapshot(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    counts = dict(db.execute(select(BackgroundJob.status, func.count(BackgroundJob.id)).where(
        BackgroundJob.organization_id == principal.organization_id,
    ).group_by(BackgroundJob.status)).all())
    rows = db.scalars(select(BackgroundJob).where(
        BackgroundJob.organization_id == principal.organization_id,
    ).order_by(BackgroundJob.created_at.desc()).limit(100)).all()
    stale = db.scalar(select(func.count(BackgroundJob.id)).where(
        BackgroundJob.organization_id == principal.organization_id,
        BackgroundJob.status == "running",
        BackgroundJob.locked_at < datetime.now(timezone.utc) - timedelta(minutes=STALE_LOCK_MINUTES),
    )) or 0
    return {
        "generated_at": datetime.now(timezone.utc),
        "counts": counts,
        "supported_job_types": sorted(SUPPORTED_JOB_TYPES),
        "scheduler": {
            "enabled": bool(os.getenv("CRON_SECRET")),
            "schedule": SCHEDULE,
            "stale_lock_minutes": STALE_LOCK_MINUTES,
            "stale_running_jobs": stale,
            "buyer_first_mode": _buyer_first_mode(),
            "property_acquisition_paused": _buyer_first_mode(),
        },
        "jobs": [_serialize(job) for job in rows],
    }


@router.post("")
def enqueue(payload: dict, principal: Principal = Depends(require_role("manager")), db: Session = Depends(get_db)):
    job_type = str(payload.get("job_type") or "").strip()
    if job_type not in SUPPORTED_JOB_TYPES:
        raise HTTPException(422, "Unsupported job type")
    if job_type == "autonomous_property_acquisition" and _buyer_first_mode():
        raise HTTPException(409, "Property acquisition is paused while BUYER_FIRST_MODE is active")
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
    return await _run_available(db, principal, limit, "owner_manual")


@router.get("/scheduled")
async def scheduled(authorization: str | None = Header(default=None), db: Session = Depends(get_db)):
    _authorized_cron(authorization)
    organizations = db.scalars(select(Organization).where(Organization.is_active.is_(True))).all()
    results = []
    now = datetime.now(timezone.utc)
    for organization in organizations:
        principal = _owner_principal(db, organization)
        if not principal:
            results.append({"organization_id": organization.id, "status": "skipped", "reason": "active owner not found"})
            continue
        try:
            if not _buyer_first_mode():
                from .autonomous_property_acquisition import acquisition_feed_status
                feed = acquisition_feed_status()
                pending_feed_job = db.scalar(select(BackgroundJob.id).where(
                    BackgroundJob.organization_id == organization.id,
                    BackgroundJob.job_type == "autonomous_property_acquisition",
                    BackgroundJob.status.in_(["queued", "retry", "running"]),
                ))
                if feed["enabled"] and feed["configured"] and feed["secure"] and not pending_feed_job:
                    db.add(BackgroundJob(
                        organization_id=organization.id,
                        job_type="autonomous_property_acquisition",
                        status="queued",
                        priority=70,
                        payload_json={"review_only": True},
                        created_by_user_id=principal.user_id,
                    ))
                    db.commit()

            # Cash Buyer Intelligence is the primary autonomous workload in
            # BUYERS FIRST mode. It runs only from configured public deed feeds
            # and promotes only repeated buyers with explicit cash evidence.
            from .distress_ingest import load_jurisdictions
            buyer_sources = [source for source in load_jurisdictions() if source.category == "cash_purchase_deed"]
            pending_buyer_job = db.scalar(select(BackgroundJob.id).where(
                BackgroundJob.organization_id == organization.id,
                BackgroundJob.job_type == "autonomous_cash_buyer_intelligence",
                BackgroundJob.status.in_(["queued", "retry", "running"]),
            ))
            if buyer_sources and not pending_buyer_job:
                db.add(BackgroundJob(
                    organization_id=organization.id,
                    job_type="autonomous_cash_buyer_intelligence",
                    status="queued",
                    priority=95 if _buyer_first_mode() else 72,
                    payload_json={"max_sources": 10, "max_rows": 5000} if _buyer_first_mode() else {"max_sources": 3, "max_rows": 1000},
                    created_by_user_id=principal.user_id,
                ))
                db.commit()

            # Due seller follow-ups are converted only into fresh compliance
            # decisions + owner approvals. This job has no dispatch authority.
            from .sms_scheduling_models import SmsFollowUpJob
            due_followup = db.scalar(select(SmsFollowUpJob.id).where(
                SmsFollowUpJob.organization_id == organization.id,
                SmsFollowUpJob.status == "scheduled",
                SmsFollowUpJob.due_at <= now,
            ))
            pending_followup_job = db.scalar(select(BackgroundJob.id).where(
                BackgroundJob.organization_id == organization.id,
                BackgroundJob.job_type == "sms_due_followups",
                BackgroundJob.status.in_(["queued", "retry", "running"]),
            ))
            if due_followup and not pending_followup_job:
                db.add(BackgroundJob(
                    organization_id=organization.id,
                    job_type="sms_due_followups",
                    status="queued",
                    priority=85,
                    payload_json={"limit": 25, "approval_only": True},
                    created_by_user_id=principal.user_id,
                ))
                db.commit()

            results.append(await _run_available(db, principal, 20, "vercel_cron"))
        except Exception as exc:
            db.rollback()
            results.append({"organization_id": organization.id, "status": "failed", "error": f"{type(exc).__name__}: {exc}"})
    return {"generated_at": datetime.now(timezone.utc), "organizations_processed": len(results), "results": results}


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
    if job.job_type == "autonomous_property_acquisition" and _buyer_first_mode():
        raise HTTPException(409, "Property acquisition is paused while BUYER_FIRST_MODE is active")
    job.status = "retry"
    job.available_at = datetime.now(timezone.utc)
    job.failed_at = None
    job.locked_at = None
    job.last_error = None
    db.commit()
    return _serialize(job)