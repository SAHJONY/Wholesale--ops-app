"""Safe public readiness probe for SAHJONY departmental email.

Exposes only booleans and non-secret routing metadata so production operators
can verify that a new Vercel deployment received the expected environment
configuration without revealing credential values.
"""

import os

from fastapi import APIRouter

router = APIRouter(prefix="/business-email", tags=["business email"])


@router.get("/public-readiness")
def public_email_readiness():
    checks = {
        "resend_api_key_configured": bool(os.getenv("RESEND_API_KEY")),
        "webhook_secret_configured": bool(os.getenv("RESEND_WEBHOOK_SECRET")),
        "default_organization_configured": bool(os.getenv("EMAIL_DEFAULT_ORGANIZATION_ID")),
        "domain_verified": str(os.getenv("EMAIL_DOMAIN_VERIFIED") or "").lower() == "true",
        "inbound_verified": str(os.getenv("EMAIL_INBOUND_VERIFIED") or "").lower() == "true",
    }
    return {
        "provider": "resend",
        "domain": "sahjony.com",
        "default_sender": "acquisitions@sahjony.com",
        "checks": checks,
        "sending_live": checks["resend_api_key_configured"] and checks["domain_verified"],
        "responding_live": all(checks.values()),
        "fail_closed": True,
        "secrets_exposed": False,
    }
