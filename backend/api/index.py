"""Vercel Python entrypoint for the FastAPI application."""

from app import background_jobs as background_jobs_module
from app.acquisition_intake import router as acquisition_intake_router
from app.acquisition_worker_safe import router as acquisition_worker_router
from app.activation import router as activation_router
from app.agentic_voice_brain import router as agentic_voice_router
from app.audit_center import router as audit_router
from app.auth import router as auth_router
from app.authorized_acquisition import router as authorized_acquisition_router
from app.bland_messaging import router as bland_messaging_router
from app.buyer_intake import router as buyer_intake_router
from app.cash_buyer_discovery import router as cash_buyer_router
from app.business_os import router as business_os_router
from app.closing_command import router as closing_command_router
from app.compliance import router as compliance_router
from app.contact_enrichment import router as contact_enrichment_router
from app.continuity import router as continuity_router
from app.continuous_ops import router as continuous_ops_router
from app.county_queue import router as county_queue_router
from app.county_verification import router as county_verification_router
from app.crm import router as crm_router
from app.data_intake import router as data_intake_router
from app.database import Base, engine
from app.deal_execution import router as deal_execution_router
from app.deal_intelligence import router as deal_intelligence_router
from app.deal_rehearsal import router as test_deal_router
from app.deployment_diagnostics import router as deployment_diagnostics_router
from app.disposition import router as disposition_router
from app.distress_discovery import router as distress_discovery_router
from app.distress_ingest import router as distress_ingest_router
from app.distress_providers import router as distress_providers_router
from app.docuseal_events import router as docuseal_events_router
from app.event_core import router as event_core_router
from app.executive_ops import router as executive_ops_router
from app.foreclosure_procedure import router as foreclosure_procedure_router
from app.getting_started import router as getting_started_router
from app.go_live import router as go_live_router
from app.google_calendar_sms import router as google_calendar_sms_router
from app.human_auth import router as human_auth_router
from app.integration_hub import router as integration_hub_router
from app.integration_reliability import router as integration_reliability_router
from app.integrations import router as integrations_router
from app.intelligence_platform import router as intelligence_platform_router
from app.launch_validation import router as launch_validation_router
from app.lead_stacking import router as lead_stacking_router
from app.lead_verification import router as lead_verification_router
from app.live_public_enrichment import router as live_public_enrichment_router
from app.main import app
from app.market_selection import router as market_selection_router
from app.national_intelligence_safe import router as national_intelligence_router
from app.nationwide_public_data import router as nationwide_public_data_router
from app.observability_api import router as observability_router
from app.observability_middleware import install_observability
from app.openai_wholesale_copilot import router as openai_wholesale_copilot_router
from app.outbound_gateway import router as outbound_gateway_router
from app.owner_insights import router as owner_insights_router
from app.phone_os import router as phone_os_router
from app.phone_os_automation import router as phone_os_automation_router
from app.property_enrichment import router as property_enrichment_router
from app.property_workspace import router as property_workspace_router
from app.provider_activation import router as provider_activation_router
from app.provider_intelligence import router as provider_intelligence_router
from app.public_data_providers import router as public_data_router
from app.real_deal_candidates import router as real_deal_candidates_router
from app.real_deals import router as real_deals_router
from app.real_estate_intelligence import router as real_estate_intelligence_router
from app.realtime_voice_orchestrator import router as realtime_voice_orchestrator_router
from app.schema_policy import configure_schema
from app.security_diagnostics import router as security_router
from app.security_middleware import SecurityMiddleware
from app.smarty_addresses import router as smarty_router
from app.sms_agentic import router as sms_agentic_router
from app.sms_attribution import router as sms_attribution_router
from app.sms_campaign_dispatch import router as sms_campaign_dispatch_router
from app.sms_campaign_execution import router as sms_campaign_execution_router
from app.sms_campaigns import router as sms_campaigns_router
from app.sms_engine import router as sms_router
from app.sms_scheduling import router as sms_scheduling_router
from app.session_control import router as session_router
from app.session_time_compat import install_session_time_compatibility
from app.tenant_ops import router as tenant_ops_router
from app.verified_ingest import router as verified_ingest_router
from app.voice_engine import router as voice_router
from app.voice_intelligence import router as voice_intelligence_router
from app.wholesale_skill_engine import router as wholesale_skill_engine_router

background_jobs_module.SCHEDULE = "30 13 * * *"
background_jobs_router = background_jobs_module.router

install_session_time_compatibility()
configure_schema(Base, engine)
install_observability(app)
app.add_middleware(SecurityMiddleware)

app.include_router(auth_router)
app.include_router(human_auth_router)
app.include_router(session_router)
app.include_router(audit_router)
app.include_router(background_jobs_router)
app.include_router(go_live_router)
app.include_router(launch_validation_router)
app.include_router(provider_activation_router)
app.include_router(provider_intelligence_router)
app.include_router(public_data_router)
app.include_router(live_public_enrichment_router)
app.include_router(nationwide_public_data_router)
app.include_router(verified_ingest_router)
app.include_router(distress_providers_router)
app.include_router(foreclosure_procedure_router)
app.include_router(distress_ingest_router)
app.include_router(distress_discovery_router)
app.include_router(lead_verification_router)
app.include_router(lead_stacking_router)
app.include_router(market_selection_router)
app.include_router(getting_started_router)
app.include_router(data_intake_router)
app.include_router(buyer_intake_router)
app.include_router(cash_buyer_router)
app.include_router(business_os_router)
app.include_router(test_deal_router)
app.include_router(real_estate_intelligence_router)
app.include_router(real_deals_router)
app.include_router(real_deal_candidates_router)
app.include_router(wholesale_skill_engine_router)
app.include_router(openai_wholesale_copilot_router)
app.include_router(property_workspace_router)
app.include_router(crm_router)
app.include_router(tenant_ops_router)
app.include_router(executive_ops_router)
app.include_router(activation_router)
app.include_router(continuous_ops_router)
app.include_router(owner_insights_router)
app.include_router(integrations_router)
app.include_router(integration_hub_router)
app.include_router(integration_reliability_router)
app.include_router(acquisition_intake_router)
app.include_router(acquisition_worker_router)
app.include_router(authorized_acquisition_router)
app.include_router(property_enrichment_router)
app.include_router(contact_enrichment_router)
app.include_router(smarty_router)
app.include_router(county_verification_router)
app.include_router(county_queue_router)
app.include_router(compliance_router)
app.include_router(outbound_gateway_router)
app.include_router(sms_router)
app.include_router(sms_agentic_router)
app.include_router(sms_attribution_router)
app.include_router(sms_campaigns_router)
app.include_router(sms_campaign_execution_router)
app.include_router(sms_campaign_dispatch_router)
app.include_router(sms_scheduling_router)
app.include_router(google_calendar_sms_router)
app.include_router(bland_messaging_router)
app.include_router(voice_router)
app.include_router(phone_os_router)
app.include_router(phone_os_automation_router)
app.include_router(agentic_voice_router)
app.include_router(voice_intelligence_router)
app.include_router(realtime_voice_orchestrator_router)
app.include_router(deal_execution_router)
app.include_router(closing_command_router)
app.include_router(disposition_router)
app.include_router(event_core_router)
app.include_router(intelligence_platform_router)
app.include_router(deal_intelligence_router)
app.include_router(national_intelligence_router)
app.include_router(docuseal_events_router)
app.include_router(deployment_diagnostics_router)
app.include_router(observability_router)
app.include_router(security_router)
app.include_router(continuity_router)

__all__ = ["app"]
