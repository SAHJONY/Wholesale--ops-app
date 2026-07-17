import os
from datetime import datetime

from fastapi import APIRouter, Depends

from .auth import Principal, get_principal

router = APIRouter(prefix="/integrations", tags=["production data integrations"])

# SAHJONY-first provider policy. A provider is never treated as authoritative merely
# because it returned data: every normalized record retains source, observed_at,
# confidence, and verification requirements.
PROVIDERS = [
    {
        "id": "attom",
        "name": "ATTOM Property Data API",
        "category": "property_intelligence",
        "tier": "primary",
        "env": ["ATTOM_API_KEY"],
        "capabilities": ["property", "owner", "mortgage", "deeds", "sales", "avm", "foreclosure", "equity"],
        "authority": "county_public_records_plus_proprietary_models",
        "verification": "county_record_for_contract_critical_facts",
    },
    {
        "id": "batchdata",
        "name": "BatchData API",
        "category": "contact_and_monitoring",
        "tier": "primary",
        "env": ["BATCHDATA_API_KEY"],
        "capabilities": ["skip_trace", "phones", "emails", "property_search", "liens", "permits", "monitoring"],
        "authority": "aggregated_property_and_contact_data",
        "verification": "multi_source_contact_confidence_and_opt_out_screening",
    },
    {
        "id": "county_records",
        "name": "County Assessor and Recorder Sources",
        "category": "public_record_verification",
        "tier": "authoritative_verification",
        "env": [],
        "capabilities": ["assessor", "recorder", "tax", "deed", "legal_owner", "parcel"],
        "authority": "government_source",
        "verification": "authoritative_when_current_and_jurisdiction_matches",
    },
    {
        "id": "google_maps",
        "name": "Google Maps and Street View",
        "category": "geospatial_and_visual",
        "tier": "primary",
        "env": ["GOOGLE_MAPS_API_KEY"],
        "capabilities": ["geocoding", "street_view", "maps", "distance", "visual_condition_support"],
        "authority": "geospatial_imagery",
        "verification": "imagery_date_must_be_displayed; no condition claim without human_review",
    },
    {
        "id": "fema",
        "name": "FEMA National Flood Hazard Layer",
        "category": "risk",
        "tier": "authoritative_public",
        "env": [],
        "capabilities": ["flood_zone", "map_panel", "special_flood_hazard_area"],
        "authority": "federal_public_source",
        "verification": "insurance_or_survey_confirmation_for_closing",
    },
    {
        "id": "bland",
        "name": "Bland AI",
        "category": "voice",
        "tier": "primary",
        "env": ["BLAND_AI_API_KEY", "BLAND_AI_WEBHOOK_SECRET"],
        "capabilities": ["inbound_calls", "outbound_calls", "transcripts", "call_outcomes"],
        "authority": "communications",
        "verification": "dnc_consent_quiet_hours_and_owner_approval",
    },
    {
        "id": "twilio",
        "name": "Twilio",
        "category": "sms_and_phone",
        "tier": "primary",
        "env": ["TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN"],
        "capabilities": ["sms", "phone_numbers", "delivery_status", "opt_out_events"],
        "authority": "communications",
        "verification": "a2p_registration_consent_and_opt_out_enforcement",
    },
    {
        "id": "docusign",
        "name": "DocuSign eSignature",
        "category": "contracts",
        "tier": "primary",
        "env": ["DOCUSIGN_INTEGRATION_KEY", "DOCUSIGN_USER_ID", "DOCUSIGN_ACCOUNT_ID"],
        "capabilities": ["envelopes", "esignature", "audit_certificate", "webhooks"],
        "authority": "agreement_execution",
        "verification": "approved_templates_and_legal_review",
    },
    {
        "id": "object_storage",
        "name": "S3-Compatible Secure Document Storage",
        "category": "documents",
        "tier": "required",
        "env": ["S3_BUCKET", "S3_ACCESS_KEY_ID", "S3_SECRET_ACCESS_KEY"],
        "capabilities": ["contracts", "photos", "proof_of_funds", "closing_documents", "versioned_files"],
        "authority": "system_of_record",
        "verification": "encryption_private_access_retention_and_audit",
    },
]


def _provider_status(provider: dict) -> dict:
    required = provider["env"]
    configured = [name for name in required if bool(os.getenv(name))]
    missing = [name for name in required if not os.getenv(name)]
    if not required:
        state = "available_public_or_manual"
    elif not missing:
        state = "configured"
    elif configured:
        state = "partial"
    else:
        state = "not_configured"
    return {**provider, "state": state, "configured_variables": configured, "missing_variables": missing}


@router.get("/catalog")
def integration_catalog(principal: Principal = Depends(get_principal)):
    return {
        "organization_id": principal.organization_id,
        "generated_at": datetime.utcnow().isoformat(),
        "strategy": {
            "property_system_of_record": "ATTOM normalized data with county-record verification",
            "contact_enrichment": "BatchData with confidence scoring and compliance screening",
            "visual_inspection": "Google Street View with imagery date and human confirmation",
            "flood_risk": "FEMA NFHL with closing-stage confirmation",
            "outbound_policy": "No call or SMS before consent/DNC/quiet-hour checks",
            "texas_policy": "Excluded from acquisition and outreach workflows",
        },
        "providers": [_provider_status(provider) for provider in PROVIDERS],
    }


@router.get("/readiness")
def integration_readiness(principal: Principal = Depends(get_principal)):
    providers = [_provider_status(provider) for provider in PROVIDERS]
    configured = [p for p in providers if p["state"] in {"configured", "available_public_or_manual"}]
    blocking = [p for p in providers if p["tier"] in {"primary", "required"} and p["state"] not in {"configured", "available_public_or_manual"}]
    return {
        "organization_id": principal.organization_id,
        "ready_for_live_acquisition": all(p["id"] not in {"attom", "batchdata"} for p in blocking),
        "ready_for_outbound": all(p["id"] not in {"bland", "twilio"} for p in blocking),
        "ready_for_contracts": all(p["id"] not in {"docusign", "object_storage"} for p in blocking),
        "configured_count": len(configured),
        "provider_count": len(providers),
        "blocking_integrations": [{"id": p["id"], "name": p["name"], "missing_variables": p["missing_variables"]} for p in blocking],
        "next_required": [p["id"] for p in blocking],
    }
