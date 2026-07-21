from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.background_jobs import BackgroundJob, _recover_stale_jobs, _retry_delay
from app.database import Base


def test_retry_delay_uses_bounded_exponential_backoff():
    assert _retry_delay(1) == timedelta(minutes=1)
    assert _retry_delay(2) == timedelta(minutes=2)
    assert _retry_delay(3) == timedelta(minutes=4)
    assert _retry_delay(10) == timedelta(minutes=60)


def test_stale_running_job_returns_to_retry_queue():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    now = datetime.now(timezone.utc)
    with Session(engine) as db:
        job = BackgroundJob(
            organization_id=1,
            job_type="process_events",
            status="running",
            attempts=1,
            max_attempts=5,
            locked_at=now - timedelta(minutes=30),
            available_at=now,
        )
        db.add(job)
        db.commit()
        recovered = _recover_stale_jobs(db, 1, now)
        db.refresh(job)
        assert recovered == 1
        assert job.status == "retry"
        assert job.locked_at is None
        assert job.last_error == "Recovered after worker lease expired"


def test_stale_exhausted_job_moves_to_dead_letter():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    now = datetime.now(timezone.utc)
    with Session(engine) as db:
        job = BackgroundJob(
            organization_id=1,
            job_type="process_events",
            status="running",
            attempts=5,
            max_attempts=5,
            locked_at=now - timedelta(minutes=30),
            available_at=now,
        )
        db.add(job)
        db.commit()
        _recover_stale_jobs(db, 1, now)
        db.refresh(job)
        assert job.status == "dead_letter"
        assert job.failed_at is not None
