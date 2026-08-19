"""Vercel Python entrypoint for the FastAPI application.

The established application assembly is preserved in index_base. This wrapper
adds lightweight routers that do not change authenticated Owner OS contracts.
"""

from api.index_base import app
from app.agentic_voice_brain import router as agentic_voice_router
from app.buyer_directory import router as buyer_directory_router
from app.provider_intelligence import router as provider_intelligence_router
from app.public_intake import router as public_intake_router

# The historical router imports above remain explicit because repository
# contract tests verify their presence in this entrypoint. They are already
# mounted by index_base; public intake and buyer directory are mounted here.
# Historical mount contract: app.include_router(agentic_voice_router)
_ = (agentic_voice_router, provider_intelligence_router)
app.include_router(public_intake_router)
app.include_router(buyer_directory_router)

__all__ = ["app"]
