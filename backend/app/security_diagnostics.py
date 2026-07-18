from fastapi import APIRouter, Depends

from .auth import Principal, get_principal
from .security_middleware import runtime_snapshot

router = APIRouter(prefix="/security", tags=["security hardening"])


@router.get("/snapshot")
def snapshot(principal: Principal = Depends(get_principal)):
    return {
        "status": "active",
        "organization_id": principal.organization_id,
        "controls": {
            "login_rate_limit": "10 attempts per 5 minutes per hashed source",
            "auth_block_window": "15 minutes",
            "general_rate_limit": "240 requests per minute per route and hashed source",
            "raw_ip_storage": False,
            "security_headers": True,
            "hsts_in_production": True,
        },
        "runtime": {
            **runtime_snapshot(),
            "serverless_note": "Runtime counters may reset after cold starts or instance replacement.",
        },
    }
