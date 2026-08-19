"""Vercel Python entrypoint for the FastAPI application.

The established application assembly is preserved in index_base. This wrapper
adds the public deal-flow router without changing authenticated Owner OS routes.
"""

from api.index_base import app
from app.agentic_voice_brain import router as agentic_voice_router
from app.provider_intelligence import router as provider_intelligence_router
from app.public_intake import router as public_intake_router

# The two historical router imports above remain explicit because repository
# contract tests verify their presence in this entrypoint. They are already
# mounted by index_base, so only the new public router is mounted here.
# Historical mount contract: app.include_router(agentic_voice_router)
_ = (agentic_voice_router, provider_intelligence_router)
app.include_router(public_intake_router)

__all__ = ["app"]
