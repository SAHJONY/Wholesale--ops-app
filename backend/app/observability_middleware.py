from __future__ import annotations

import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone

from fastapi import FastAPI, Request

from .observability_store import SLOW_REQUEST_MS, add_event

logger = logging.getLogger("sahjony.observability")


def install_observability(app: FastAPI) -> None:
    if getattr(app.state, "observability_installed", False):
        return
    app.state.observability_installed = True

    @app.middleware("http")
    async def observe_request(request: Request, call_next):
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        started = time.perf_counter()
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path[:300],
            "status_code": response.status_code,
            "duration_ms": duration_ms,
            "slow": duration_ms >= SLOW_REQUEST_MS,
            "deployment": os.getenv("VERCEL_GIT_COMMIT_SHA") or "unknown",
        }
        add_event(event)
        logger.info(json.dumps(event, separators=(",", ":")))
        response.headers["X-Request-ID"] = request_id
        response.headers["Server-Timing"] = f"app;dur={duration_ms}"
        return response
