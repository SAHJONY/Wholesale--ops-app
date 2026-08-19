import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from .auth import Principal, get_principal
from .public_data_providers import PUBLIC_DATA_PROVIDERS, provider_status as public_provider_status

router = APIRouter(prefix="/integrations", tags=["production data integrations"])

PROVIDERS = [
    {
        "id": "attom", "name": "ATTOM Property Data API", "category": "property_intelligence", "tier": "primary",
        "env": ["ATTOM_API_KEY"],
        "capabilities": ["property", "owner", "mortgage", "deeds", "sales", "avm", "foreclosure", "equity"],
        "authority": "county_public_records_plus_proprietary_models",
        "verification": "county_record_for_contract_critical_facts",
    },
    {
        "id": "smarty", "name": "Smarty US Property Data", "category": "property_intelligence", "tier": "optional",
        "env": ["SMARTY_AUTH_ID", "SMARTY_AUTH_TOKEN"], "optional_env": ["SMARTY_LICENSE", "SMARTY_ENRICHMENT_BASE_URL"],
        "capabilities": ["property", "owner", "deeds", "sales", "assessment", "tax", "parcel", "geocode"],
        "authority": "assessor_and_recorder_aggregation",
        "verification": "county_record_for_contract_critical_facts",
    },
    {
        "id": "batchdata", "name": "BatchData Contact Enrichment API", "category": "contact_and_monitoring", "tier": "primary",
        "env": ["BATCHDATA_API_KEY"],
        "optional_env": ["BATCHDATA_SKIPTRACE_URL", "BATCHDATA_AUTH_HEADER", "BATCHDATA_AUTH_SCHEME"],
        "capabilities": ["skip_trace", "phones", "emails", "property_search", "liens", "permits", "monitoring"],
        "authority": "aggregated_property_and_contact_data",
        "verification": "right_party_confirmation_plus_fresh_dnc_opt_out_and_quiet_hour_screening",
    },
    {
        "id": "county_records", "name": "County Assessor and Recorder Sources", "category": "public_record_verification",
        "tier": "authoritative_verification", "env": [],
        "capabilities": ["assessor", "recorder", "tax", "deed", "legal_owner", "parcel"],
        "authority": "government_source", "verification": "authoritative_when_current_and_jurisdiction_matches",
    },
    {
        "id": "google_maps", "name": "Google Maps and Street View", "category": "geospatial_and_visual", "tier": "optional",
        "env": ["GOOGLE_MAPS_API_KEY"],
        "capabilities": ["geocoding", "street_view", "maps", "distance", "visual_condition_support"],
        "authority": "geospatial_imagery",
        "verification": "optional_visual_support_only; imagery_date_must_be_displayed; no_condition_claim_without_human_review",
    },
    {
        "id": "google_calendar", "name": "Google Calendar", "category": "seller_scheduling", "tier": "optional",
        "env": ["GOOGLE_CALENDAR_CLIENT_ID", "GOOGLE_CALENDAR_CLIENT_SECRET", "GOOGLE_CALENDAR_REFRESH_TOKEN"],
        "optional_env": ["GOOGLE_CALENDAR_ID"],
        "capabilities": ["freebusy", "seller_appointment_create", "seller_appointment_cancel", "calendar_conflict_detection"],
        "authority": "scheduling",
        "verification": "explicit_seller_time_owner_booking_action_and_live_freebusy_check",
    },
    {
        "id": "fema", "name": "FEMA National Flood Hazard Layer", "category": "risk", "tier": "authoritative_public",
        "env": [], "capabilities": ["flood_zone", "map_panel", "special_flood_hazard_area"],
        "authority": "federal_public_source", "verification": "insurance_or_survey_confirmation_for_closing",
    },
    {
        "id": "bland", "name": "Bland AI Phone", "category": "voice_communications", "tier": "primary",
        "env": ["BLAND_AI_API_KEY", "BLAND_AI_WEBHOOK_SECRET"],
        "any_of_env": ["BLAND_DEFAULT_FROM_NUMBER", "BLAND_INBOUND_NUMBER"],
        "optional_env": ["BLAND_PHONE_WEBHOOK_URL", "BLAND_AI_WEBHOOK_SIGNATURE_HEADER", "BLAND_INBOUND_ORGANIZATION_ID", "BLAND_INBOUND_AGENT_ID", "BLAND_SELLER_OUTBOUND_AGENT_ID", "BLAND_BUYER_DISPO_AGENT_ID"],
        "capabilities": ["inbound_calls", "outbound_calls", "pathways", "personas", "transcripts", "call_outcomes", "conversation_webhooks"],
        "authority": "communications",
        "verification": "voice_only_dnc_consent_opt_out_quiet_hours_owner_policy_and_fresh_dispatch_compliance",
    },
    {
        "id": "docuseal", "name": "DocuSeal eSignature", "category": "contracts", "tier": "primary",
        "env": ["DOCUSEAL_URL", "DOCUSEAL_API_KEY"],
        "any_of_env": ["DOCUSEAL_TEMPLATE_PURCHASE_AGREEMENT", "DOCUSEAL_TEMPLATE_PURCHASE_AGREEMENT_FL", "DOCUSEAL_TEMPLATE_PURCHASE_AGREEMENT_GA", "DOCUSEAL_TEMPLATE_PURCHASE_AGREEMENT_TX"],
        "optional_env": ["DOCUSEAL_TEMPLATE_ASSIGNMENT_AGREEMENT", "DOCUSEAL_SELLER_ROLE_NAME", "DOCUSEAL_COMPLETED_REDIRECT_URL", "DOCUSEAL_REPLY_TO", "DOCUSEAL_BCC_COMPLETED"],
        "capabilities": ["submissions", "esignature", "prefill", "webhooks", "signed_documents", "self_hosting"],
        "authority": "agreement_execution", "verification": "attorney_approved_state_template_and_owner_approval",
    },
    {
        "id": "docusign", "name": "DocuSign eSignature (fallback)", "category": "contracts", "tier": "optional",
        "env": ["DOCUSIGN_ACCOUNT_ID", "DOCUSIGN_ACCESS_TOKEN"],
        "any_of_env": ["DOCUSIGN_TEMPLATE_PURCHASE_AGREEMENT", "DOCUSIGN_TEMPLATE_PURCHASE_AGREEMENT_FL", "DOCUSIGN_TEMPLATE_PURCHASE_AGREEMENT_GA", "DOCUSIGN_TEMPLATE_PURCHASE_AGREEMENT_TX"],
        "optional_env": ["DOCUSIGN_BASE_PATH", "DOCUSIGN_TEMPLATE_ASSIGNMENT_AGREEMENT", "DOCUSIGN_SELLER_ROLE_NAME"],
        "capabilities": ["envelopes", "esignature", "audit_certificate", "webhooks"],
        "authority": "agreement_execution", "verification": "fallback_only_when_selected",
    },
    {
        "id": "object_storage", "name": "S3-Compatible Secure Document Storage", "category": "documents", "tier": "required",
        "env": ["S3_BUCKET", "S3_ACCESS_KEY_ID", "S3_SECRET_ACCESS_KEY"],
        "capabilities": ["contracts", "photos", "proof_of_funds", "closing_documents", "versioned_files"],
        "authority": "system_of_record", "verification": "encryption_private_access_retention_and_audit",
    },
]


def _provider_status(provider: dict) -> dict:
    required = provider.get("env", [])
    optional = provider.get("optional_env", [])
    any_of = provider.get("any_of_env", [])
    configured = [name for name in required if bool(os.getenv(name))]
    missing = [name for name in required if not os.getenv(name)]
    optional_configured = [name for name in optional if bool(os.getenv(name))]
    any_of_configured = [name for name in any_of if bool(os.getenv(name))]
    any_of_missing = list(any_of) if any_of and not any_of_configured else []
    all_missing = missing + (["one_of:" + "|".join(any_of)] if any_of_missing else [])
    if not required and not any_of:
        state = "available_public_or_manual"
    elif not all_missing:
        state = "configured"
    elif configured or any_of_configured:
        state = "partial"
    else:
        state = "not_configured"
    return {
        **provider,
        "state": state,
        "configured_variables": configured,
        "missing_variables": all_missing,
        "optional_configured_variables": optional_configured,
        "alternative_configured_variables": any_of_configured,
    }


def _contracts_ready(providers: list[dict]) -> bool:
    selected = str(os.getenv("E_SIGNATURE_PROVIDER") or "docuseal").lower()
    provider_id = "docusign" if selected == "docusign" else "docuseal"
    signature = next((item for item in providers if item["id"] == provider_id), None)
    storage = next((item for item in providers if item["id"] == "object_storage"), None)
    ready_states = {"configured", "available_public_or_manual"}
    return bool(signature and storage and signature["state"] in ready_states and storage["state"] in ready_states)


@router.get("/catalog")
def integration_catalog(principal: Principal = Depends(get_principal)):
    public_providers = [public_provider_status(provider) for provider in PUBLIC_DATA_PROVIDERS]
    return {
        "organization_id": principal.organization_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "strategy": {
            "property_system_of_record": "Canonical multi-provider facts with county recorder and assessor verification",
            "contact_enrichment": "BatchData preview/apply with right-party and compliance screening; official skip-trace endpoint is the default and can be overridden by environment",
            "public_data": "Official government and open-data feeds with provenance, licensing, retention, and confidence metadata",
            "visual_inspection": "Google Street View is optional support; dated imagery and human confirmation are required before condition claims",
            "seller_scheduling": "Google Calendar OAuth with explicit seller time, free/busy verification, and owner-triggered booking",
            "flood_risk": "FEMA NFHL with closing-stage confirmation",
            "outbound_policy": "Bland phone-only inbound and compliant outbound voice; SMS disabled until owner re-enables it by policy change",
            "contract_policy": "DocuSeal-first provider-neutral signing; no submission before attorney-approved state template and owner approval",
            "texas_policy": "Texas acquisition is permitted only through current disclosure and compliance gates; assignment/equitable-interest marketing must accurately disclose the interest being sold and must not misrepresent legal title.",
        },
        "providers": [_provider_status(provider) for provider in PROVIDERS],
        "public_data_providers": public_providers,
    }


@router.get("/readiness")
def integration_readiness(principal: Principal = Depends(get_principal)):
    providers = [_provider_status(provider) for provider in PROVIDERS]
    public_providers = [public_provider_status(provider) for provider in PUBLIC_DATA_PROVIDERS]
    ready_states = {"configured", "available_public_or_manual"}
    configured = [provider for provider in providers if provider["state"] in ready_states]
    blocking = [provider for provider in providers if provider["tier"] in {"primary", "required"} and provider["state"] not in ready_states]
    public_enabled = [provider for provider in public_providers if provider["enabled"]]
    public_blocked = [provider for provider in public_enabled if provider["state"] == "enabled_missing_endpoint"]
    bland = next((provider for provider in providers if provider["id"] == "bland"), None)
    calendar = next((provider for provider in providers if provider["id"] == "google_calendar"), None)
    property_ready = any(
        provider["id"] in {"attom", "smarty"} and provider["state"] in ready_states
        for provider in providers
    )
    live_acquisition_blockers = [
        provider for provider in blocking
        if provider["id"] not in {"attom", "docuseal", "object_storage", "bland"}
    ]
    return {
        "organization_id": principal.organization_id,
        "selected_signature_provider": str(os.getenv("E_SIGNATURE_PROVIDER") or "docuseal").lower(),
        "ready_for_live_acquisition": property_ready and not live_acquisition_blockers and not public_blocked,
        "ready_for_outbound": bool(bland and bland["state"] in ready_states),
        "outbound_provider": "bland_phone",
        "sms_enabled": False,
        "ready_for_calendar_booking": bool(calendar and calendar["state"] in ready_states),
        "calendar_provider": "google_calendar",
        "ready_for_contracts": _contracts_ready(providers),
        "configured_count": len(configured),
        "provider_count": len(providers),
        "public_data_enabled_count": len(public_enabled),
        "public_data_provider_count": len(public_providers),
        "public_data_blocked": [{"id": provider["id"], "missing": provider["endpoint_env"]} for provider in public_blocked],
        "blocking_integrations": [
            {"id": provider["id"], "name": provider["name"], "missing_variables": provider["missing_variables"]}
            for provider in blocking
        ],
        "next_required": [provider["id"] for provider in blocking] + [provider["id"] for provider in public_blocked],
    }
