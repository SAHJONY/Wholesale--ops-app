"""Vercel Python entrypoint for the FastAPI application."""

from app.activation import router as activation_router
from app.auth import router as auth_router
from app.compliance import router as compliance_router
from app.contact_enrichment import router as contact_enrichment_router
from app.continuous_ops import router as continuous_ops_router
from app.crm import router as crm_router
from app.database import Base, engine
from app.deal_execution import router as deal_execution_router
from app.executive_ops import router as executive_ops_router
from app.human_auth import router as human_auth_router
from app.integrations import router as integrations_router
from app.main import app
from app.outbound_gateway import router as outbound_gateway_router
from app.owner_insights import router as owner_insights_router
from app.property_enrichment import router as property_enrichment_router
from app.tenant_ops import router as tenant_ops_router

# Extension models are imported by the routers above. Running create_all again
# registers additive workspace, identity, CRM, password, compliance, outbound,
# deal-execution, and tenant-operation tables.
Base.metadata.create_all(bind=engine)

app.include_router(auth_router)
app.include_router(human_auth_router)
app.include_router(crm_router)
app.include_router(tenant_ops_router)
app.include_router(executive_ops_router)
app.include_router(activation_router)
app.include_router(continuous_ops_router)
app.include_router(owner_insights_router)
app.include_router(integrations_router)
app.include_router(property_enrichment_router)
app.include_router(contact_enrichment_router)
app.include_router(compliance_router)
app.include_router(outbound_gateway_router)
app.include_router(deal_execution_router)

__all__ = ["app"]
