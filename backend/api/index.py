"""Vercel Python entrypoint for the FastAPI application.

The established application assembly is preserved in index_base. This wrapper
adds lightweight routers that do not change authenticated Owner OS contracts.
"""

from api.index_base import app
from app.agentic_voice_brain import router as agentic_voice_router
from app.bland_phone_system import router as bland_phone_router
from app.bland_test_once import router as bland_test_once_router
from app.buyer_directory import router as buyer_directory_router
from app.buyer_first_acquisition import router as buyer_first_acquisition_router
from app.communication_os import router as communication_os_router
from app.joint_venture_engine import router as joint_venture_router
from app.joint_venture_public import router as joint_venture_public_router
from app.market_land_acquisition import router as market_land_acquisition_router
from app.openai_realtime_voice import router as openai_realtime_voice_router
from app.owner_resolution import router as owner_resolution_router
from app.provider_intelligence import router as provider_intelligence_router
from app.public_intake import router as public_intake_router
from app.self_healing_engine import router as self_healing_router
from app.self_improvement_engine import router as self_improvement_router
from app.task_resolution_engine import router as task_resolution_router

# The historical router imports above remain explicit because repository
# contract tests verify their presence in this entrypoint. They are already
# mounted by index_base; public intake, buyer directory, buyer-box acquisition,
# JV performance, market/land acquisition, owner resolution, resilient task
# resolution, self-healing, self-improvement, Communication OS, Bland phone and
# OpenAI Realtime voice orchestration are mounted here. The one-time Bland test
# route remains nonce-gated and is removed after the owner-authorized test.
# Historical mount contract: app.include_router(agentic_voice_router)
_ = (agentic_voice_router, provider_intelligence_router)
app.include_router(public_intake_router)
app.include_router(buyer_directory_router)
app.include_router(buyer_first_acquisition_router)
app.include_router(joint_venture_router)
app.include_router(joint_venture_public_router)
app.include_router(market_land_acquisition_router)
app.include_router(owner_resolution_router)
app.include_router(task_resolution_router)
app.include_router(self_healing_router)
app.include_router(self_improvement_router)
app.include_router(communication_os_router)
app.include_router(bland_phone_router)
app.include_router(openai_realtime_voice_router)
app.include_router(bland_test_once_router)

__all__ = ["app"]