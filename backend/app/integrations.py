import os
from datetime import datetime

from fastapi import APIRouter, Depends

from .auth import Principal, get_principal

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
        "id": "batchdata", "name": "BatchData Contact Enrichment API", "category": "contact_and_monitoring", "tier": "primary",
        "env": ["BATCHDATA_API_KEY", "BATCHDATA_SKIPTRACE_URL"],
        "optional_env": ["BATCHDATA_AUTH_HEADER", "BATCHDATA_AUTH_SCHEME"],
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
        "id": "google_maps", "name": "Google Maps and Street View", "category": "geospatial_and_visual", "tier": "primary",
        "env": ["GOOGLE_MAPS_API_KEY"],
        "capabilities": ["geocoding", "street_view", "maps", "distance", "visual_condition_support"],
        "authority": "geospatial_imagery",
        "verification": "imagery_date_must_be_displayed; no condition claim without human_review",
    },
    {
        "id": "fema", "name": "FEMA National Flood Hazard Layer", "category": "risk", "tier": "authoritative_public",
        "env": [], "capabilities": ["flood_zone", "map_panel", "special_flood_hazard_area"],
        "authority": "federal_public_source", "verification": "insurance_or_survey_confirmation_for_closing",
    },
    {
        "id": "bland", "name": "Bland AI", "category": "voice", "tier": "primary",
        "env": ["BLAND_AI_API_KEY", "BLAND_AI_WEBHOOK_SECRET"],
        "capabilities": ["inbound_calls", "outbound_calls", "transcripts", "call_outcomes"],
        "authority": "communications", "verification": "dnc_consent_quiet_hours_and_owner_approval",
    },
    {
        "id": "twilio", "name": "Twilio", "category": "sms_and_phone", "tier": "primary",
        "env": ["TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN"],
        "any_of_env": ["TWILIO_MESSAGING_SERVICE_SID", "TWILIO_FROM_NUMBER", "BLAND_DEFAULT_FROM_NUMBER"],
        "optional_env": ["TWILIO_STATUS_CALLBACK_URL"],
        "capabilities": ["sms", "phone_numbers", "delivery_status", "opt_out_events"],
        "authority": "communications", "verification": "a2p_registration_consent_and_opt_out_enforcement",
    },
    {
        "id": "docusign", "name": "DocuSign eSignature", "category": "contracts", "tier": "primary",
        "env": ["DOCUSIGN_INTEGRATION_KEY", "DOCUSIGN_USER_ID", "DOCUSIGN_ACCOUNT_ID", "DOCUSIGN_ACCESS_TOKEN"],
        "any_of_env": ["DOCUSIGN_TEMPLATE_PURCHASE_AGREEMENT", "DOCUSIGN_TEMPLATE_PURCHASE_AGREEMENT_FL", "DOCUSIGN_TEMPLATE_PURCHASE_AGREEMENT_GA"],
        "optional_env": ["DOCUSIGN_BASE_PATH", "DOCUSIGN_TEMPLATE_ASSIGNMENT_AGREEMENT", "DOCUSIGN_SELLER_ROLE_NAME"],
        "capabilities": ["envelopes", "esignature", "audit_certificate", "webhooks"],
        "authority": "agreement_execution", "verification": "attorney_approved_state_template_and_owner_approval",
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


@router.get("/catalog")
def integration_catalog(principal: Principal = Depends(get_principal)):
    return {
        "organization_id": principal.organization_id,
        "generated_at": datetime.utcnow().isoformat(),
        "strategy": {
            "property_system_of_record": "ATTOM normalized data with county-record verification",
            "contact_enrichment": "BatchData preview/apply with right-party and compliance screening",
            "visual_inspection": "Google Street View with imagery date and human confirmation",
            "flood_risk": "FEMA NFHL with closing-stage confirmation",
            "outbound_policy": "No call or SMS before fresh DNC, consent, opt-out, quiet-hour, and owner-approval checks",
            "contract_policy": "No envelope before attorney-approved state template and owner approval",
            "texas_policy": "Excluded from acquisition and outreach workflows",
        },
        "providers": [_provider_status(provider) for provider in PROVIDERS],
    }


@router.get("/readiness")
def integration_readiness(principal: Principal = Depends(get_principal)):
    providers = [_provider_status(provider) for provider in PROVIDERS]
    ready_states = {"configured", "available_public_or_manual"}
    configured = [provider for provider in providers if provider["state"] in ready_states]
    blocking = [provider for provider in providers if provider["tier"] in {"primary", "required"} and provider["state"] not in ready_states]
    return {
        "organization_id": principal.organization_id,
        "ready_for_live_acquisition": all(provider["id"] not in {"attom", "batchdata"} for provider in blocking),
        "ready_for_outbound": all(provider["id"] not in {"bland", "twilio"} for provider in blocking),
        "ready_for_contracts": all(provider["id"] not in {"docusign", "object_storage"} for provider in blocking),
        "configured_count": len(configured),
        "provider_count": len(providers),
        "blocking_integrations": [
            {"id": provider["id"], "name": provider["name"], "missing_variables": provider["missing_variables"]}
            for provider in blocking
        ],
        "next_required": [provider["id"] for provider in blocking],
    }
