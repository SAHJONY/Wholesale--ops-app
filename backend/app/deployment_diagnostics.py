from __future__ import annotations

import os
from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from .auth import Principal, get_principal
from .database import get_db

router = APIRouter(prefix="/deployment", tags=["deployment diagnostics"])

CRITICAL_ROUTES = [
    "/health",
    "/human-auth/login",
    "/sessions/snapshot",
    "/workspace/dashboard",
    "/acquisition-intake/snapshot",
    "/acquisition-worker/snapshot",
    "/county-queue/snapshot",
    "/event-core/snapshot",
    "/intelligence-platform/snapshot",
    "/national-intelligence/snapshot",
    "/integration-hub/snapshot",
    "/integration-reliability/snapshot",
    "/observability/snapshot",
    "/security/snapshot",
    "/continuity/snapshot",
    "/deal-execution/snapshot",
    "/closing-command/snapshot",
    "/disposition/snapshot",
]


def registered_route_paths(app) -> set[str]:
    return {getattr(route, "path", "") for route in app.routes}


@router.get("/status")
def deployment_status(principal: Principal = Depends(get_principal), db: Session = Depends(get_db)):
    from api.index import app

    paths = registered_route_paths(app)
    missing = [path for path in CRITICAL_ROUTES if path not in paths]
    database_ok = False
    database_error = None
    try:
        db.execute(text("SELECT 1"))
        database_ok = True
    except Exception as exc:  # pragma: no cover - environment-specific
        database_error = f"{type(exc).__name__}: {exc}"

    return {
        "status": "healthy" if not missing and database_ok else "degraded",
        "generated_at": datetime.utcnow(),
        "organization_id": principal.organization_id,
        "release": os.getenv("VERCEL_GIT_COMMIT_SHA") or os.getenv("RAILWAY_GIT_COMMIT_SHA") or "unknown",
        "environment": os.getenv("VERCEL_ENV") or os.getenv("RAILWAY_ENVIRONMENT_NAME") or "unknown",
        "database": {"ok": database_ok, "error": database_error},
        "route_contract": {
            "required": len(CRITICAL_ROUTES),
            "registered": len(CRITICAL_ROUTES) - len(missing),
            "missing": missing,
        },
    }
