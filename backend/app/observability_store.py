from __future__ import annotations

import os
from collections import deque
from datetime import datetime, timezone
from threading import Lock
from typing import Any

STARTED_AT = datetime.now(timezone.utc)
EVENT_LIMIT = max(50, min(int(os.getenv("OBSERVABILITY_EVENT_LIMIT", "500")), 2000))
SLOW_REQUEST_MS = max(250, int(os.getenv("SLOW_REQUEST_THRESHOLD_MS", "1500")))
_EVENTS: deque[dict[str, Any]] = deque(maxlen=EVENT_LIMIT)
_LOCK = Lock()


def add_event(event: dict[str, Any]) -> None:
    with _LOCK:
        _EVENTS.append(event)


def get_events() -> list[dict[str, Any]]:
    with _LOCK:
        return list(_EVENTS)
