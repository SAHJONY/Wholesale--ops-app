from __future__ import annotations

import os
import time
from collections import Counter
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from .auth import Principal, get_principal
from .database import get_db
from .observability_store import SLOW_REQUEST_MS, STARTED_AT, get_events

router = APIRouter(prefix="/observability", tags=["system observability"])


@router.get("/snapshot")
def snapshot(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    events = get_events()
    errors = [item for item in events if int(item.get("status_code") or 0) >= 500]
    slow = [item for item in events if item.get("slow")]
    durations = [float(item.get("duration_ms") or 0) for item in events]
    route_counts = Counter(str(item.get("path")) for item in events)
    status_counts = Counter(str(item.get("status_code")) for item in events)

    started = time.perf_counter()
    database = {"status": "unknown", "latency_ms": None}
    try:
        db.execute(text("select 1"))
        database = {
            "status": "reachable",
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
        }
    except Exception as exc:
        database = {
            "status": "unreachable",
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            "error_type": type(exc).__name__,
        }

    return {
        "organization_id": principal.organization_id,
        "generated_at": datetime.now(timezone.utc),
        "instance": {
            "started_at": STARTED_AT,
            "uptime_seconds": int((datetime.now(timezone.utc) - STARTED_AT).total_seconds()),
            "deployment": os.getenv("VERCEL_GIT_COMMIT_SHA") or "unknown",
            "environment": os.getenv("VERCEL_ENV") or "unknown",
            "serverless_notice": "Metrics reset when the active serverless instance is replaced.",
        },
        "database": database,
        "requests": {
            "sample_size": len(events),
            "error_count": len(errors),
            "slow_count": len(slow),
            "average_duration_ms": round(sum(durations) / len(durations), 2) if durations else 0,
            "slow_threshold_ms": SLOW_REQUEST_MS,
            "status_counts": dict(status_counts),
            "top_routes": [{"path": path, "count": count} for path, count in route_counts.most_common(10)],
        },
        "recent_errors": list(reversed(errors[-20:])),
        "recent_slow_requests": list(reversed(slow[-20:])),
    }
