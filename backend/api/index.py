"""Vercel Python entrypoint for the FastAPI application."""

from app.auth import router as auth_router
from app.crm import router as crm_router
from app.database import Base, engine
from app.main import app
from app.tenant_ops import router as tenant_ops_router

# Extension models are imported by the routers above. Running create_all again
# registers additive workspace, identity, CRM, and tenant-operation tables.
Base.metadata.create_all(bind=engine)

app.include_router(auth_router)
app.include_router(crm_router)
app.include_router(tenant_ops_router)

__all__ = ["app"]
