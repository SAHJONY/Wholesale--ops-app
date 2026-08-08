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
        # An alternative to ATTOM, not an addition to it. The tier is optional so
        # a deployment that runs on Smarty is not reported as missing a required
        # provider; whether property data is satisfied at all is decided by
        # property_data.property_data_configured(), which accepts either.
        "id": "smarty", "name": "Smarty US Property Data", "category": "property_intelligence", "tier": "optional",
        "env": ["SMARTY_AUTH_ID", "SMARTY_AUTH_TOKEN"], "optional_env": ["SMARTY_LICENSE", "SMARTY_ENRICHMENT_BASE_URL"],
        "capabilities": ["property", "owner", "deeds", "sales", "assessment", "tax", "parcel", "geocode"],
        "authority": "assessor_and_recorder_aggregation",
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
        "verification": "imagery_date_must_be_displayed; no condition claim_without_human_review",
    },
    {
        "id": "fema", "name": "FEMA National Flood Hazard Layer", "category": "risk", "tier": "authoritative_public",
        "env": [], "capabilities": ["flood_zone", "map_panel", "special_flood_hazard_area"],
        "authority": "federal_public_source", "verification": "insurance_or_survey_confirmation_for_closing",
    },
    {
        "id": "bland", "name": "Bland AI Messaging + Voice", "category": "omnichannel_communications", "tier": "primary",
        "env": ["BLAND_AI_API_KEY", "BLAND_WEBHOOK_SIGNING_SECRET"],
        "any_of_env": ["BLAND_SMS_AGENT_NUMBER", "BLAND_MESSAGING_NUMBER"],
        "optional_env": ["BLAND_SMS_WEBHOOK_URL", "BLAND_DEFAULT_FROM_NUMBER", "BLAND_DEFAULT_CALLER_ID"],
        "capabilities": [
            "inbound_sms", "outbound_sms", "inbound_calls", "outbound_calls",
            "pathways", "personas", "transcripts", "call_outcomes", "conversation_webhooks",
        ],
        "authority": "communications",
        "verification": "a2p_registration_dnc_consent_opt_out_quiet_hours_owner_approval_and_fresh_dispatch_compliance",
    },
    {
        "id": "docuseal", "name": "DocuSeal eSignature", "category": "contracts", "tier": "primary",
        "env": ["DOCUSEAL_URL", "DOCUSEAL_API_KEY"],
        "any_of_env": ["DOCUSEAL_TEMPLATE_PURCHASE_AGREEMENT", "DOCUSEAL_TEMPLATE_PURCHASE_AGREEMENT_FL", "DOCUSEAL_TEMPLATE_PURCHASE_AGREEMENT_GA"],
        "optional_env": ["DOCUSEAL_TEMPLATE_ASSIGNMENT_AGREEMENT", "DOCUSEAL_SELLER_ROLE_NAME", "DOCUSEAL_COMPLETED_REDIRECT_URL", "DOCUSEAL_REPLY_TO", "DOCUSEAL_BCC_COMPLETED"],
        "capabilities": ["submissions", "esignature", "prefill", "webhooks", "signed_documents", "self_hosting"],
        "authority": "agreement_execution", "verification": "attorney_approved_state_template_and_owner_approval",
    },
    {
        "id": "docusign", "name": "DocuSign eSignature (fallback)", "category": "contracts", "tier": "optional",
        "env": ["DOCUSIGN_ACCOUNT_ID", "DOCUSIGN_ACCESS_TOKEN"],
        "any_of_env": ["DOCUSIGN_TEMPLATE_PURCHASE_AGREEMENT", "DOCUSIGN_TEMPLATE_PURCHASE_AGREEMENT_FL", "DOCUSIGN_TEMPLATE_PURCHASE_AGREEMENT_GA"],
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
            "contact_enrichment": "BatchData preview/apply with right-party and compliance screening",
            "public_data": "Official government and open-data feeds with provenance, licensing, retention, and confidence metadata",
            "visual_inspection": "Google Street View with imagery date and human confirmation",
            "flood_risk": "FEMA NFHL with closing-stage confirmation",
            "outbound_policy": "Bland-only SMS and voice; no outreach before fresh DNC, consent, opt-out, quiet-hour, and owner-approval checks",
            "contract_policy": "DocuSeal-first provider-neutral signing; no submission before attorney-approved state template and owner approval",
            "texas_policy": "Excluded from acquisition and outreach workflows",
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
    return {
        "organization_id": principal.organization_id,
        "selected_signature_provider": str(os.getenv("E_SIGNATURE_PROVIDER") or "docuseal").lower(),
        "ready_for_live_acquisition": all(provider["id"] not in {"attom", "batchdata"} for provider in blocking) and not public_blocked,
        "ready_for_outbound": bool(bland and bland["state"] in ready_states),
        "outbound_provider": "bland",
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
