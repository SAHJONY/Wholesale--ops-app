from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from .auth import Principal, get_principal

router = APIRouter(prefix="/public-data", tags=["public property data providers"])

PUBLIC_DATA_PROVIDERS: tuple[dict[str, Any], ...] = (
    {
        "id": "county_recorder",
        "name": "County Recorder APIs and Official Feeds",
        "category": "public_record_verification",
        "tier": "authoritative_public",
        "access": "free_or_jurisdiction_specific",
        "feature_flag": "ENABLE_COUNTY_RECORDER",
        "endpoint_env": "COUNTY_RECORDER_BASE_URL",
        "capabilities": ["deeds", "mortgages", "liens", "releases", "assignments", "ownership_transfers"],
        "confidence": "very_high",
        "retention": "jurisdiction_terms",
        "license_required": False,
    },
    {
        "id": "county_assessor",
        "name": "County Tax Assessor APIs and GIS Services",
        "category": "public_record_verification",
        "tier": "authoritative_public",
        "access": "free_or_jurisdiction_specific",
        "feature_flag": "ENABLE_COUNTY_ASSESSOR",
        "endpoint_env": "COUNTY_ASSESSOR_BASE_URL",
        "capabilities": ["owner", "parcel", "assessed_value", "property_characteristics", "taxing_district"],
        "confidence": "very_high",
        "retention": "jurisdiction_terms",
        "license_required": False,
    },
    {
        "id": "tax_delinquent",
        "name": "County Tax Delinquent Lists",
        "category": "distress",
        "tier": "authoritative_public",
        "access": "free_where_published",
        "feature_flag": "ENABLE_TAX_DELINQUENT",
        "endpoint_env": "TAX_DELINQUENT_FEED_URL",
        "capabilities": ["delinquency_status", "amount_due", "sale_date", "redemption_period"],
        "confidence": "very_high",
        "retention": "jurisdiction_terms",
        "license_required": False,
    },
    {
        "id": "code_violations",
        "name": "Municipal Code Violations and Unsafe Structure Feeds",
        "category": "distress",
        "tier": "authoritative_public",
        "access": "free_where_published",
        "feature_flag": "ENABLE_CODE_VIOLATIONS",
        "endpoint_env": "CODE_VIOLATIONS_FEED_URL",
        "capabilities": ["code_case", "unsafe_structure", "nuisance", "demolition_notice", "vacant_building"],
        "confidence": "high",
        "retention": "jurisdiction_terms",
        "license_required": False,
    },
    {
        "id": "probate",
        "name": "Public Probate Court Feeds",
        "category": "court_records",
        "tier": "authoritative_public",
        "access": "free_where_public_and_reusable",
        "feature_flag": "ENABLE_PROBATE_FEEDS",
        "endpoint_env": "PROBATE_FEED_URL",
        "capabilities": ["estate_case", "personal_representative", "filing_status", "property_reference"],
        "confidence": "high",
        "retention": "court_terms_and_privacy_policy",
        "license_required": False,
    },
    {
        "id": "foreclosure_public",
        "name": "Public Foreclosure, Lis Pendens, and Sheriff Sale Feeds",
        "category": "court_records",
        "tier": "authoritative_public",
        "access": "free_where_published",
        "feature_flag": "ENABLE_PUBLIC_FORECLOSURE",
        "endpoint_env": "PUBLIC_FORECLOSURE_FEED_URL",
        "capabilities": ["foreclosure_filing", "lis_pendens", "sheriff_sale", "auction_date"],
        "confidence": "high",
        "retention": "jurisdiction_terms",
        "license_required": False,
    },
    {
        "id": "building_permits",
        "name": "Building Permit and Demolition Permit Feeds",
        "category": "property_condition",
        "tier": "authoritative_public",
        "access": "free_where_published",
        "feature_flag": "ENABLE_BUILDING_PERMITS",
        "endpoint_env": "BUILDING_PERMITS_FEED_URL",
        "capabilities": ["permit", "permit_value", "contractor", "inspection", "demolition"],
        "confidence": "high",
        "retention": "jurisdiction_terms",
        "license_required": False,
    },
    {
        "id": "municipal_open_data",
        "name": "Municipal and State Open Data Portals",
        "category": "open_data",
        "tier": "public_enrichment",
        "access": "free",
        "feature_flag": "ENABLE_OPEN_DATA",
        "endpoint_env": "OPEN_DATA_CATALOG_URL",
        "capabilities": ["vacant_registry", "land_bank", "zoning", "nuisance", "utility_public_release"],
        "confidence": "high",
        "retention": "dataset_license",
        "license_required": False,
    },
    {
        "id": "fema_national",
        "name": "FEMA National Flood Hazard Layer",
        "category": "risk",
        "tier": "authoritative_public",
        "access": "free",
        "feature_flag": "ENABLE_FEMA_PUBLIC",
        "endpoint_env": "FEMA_NFHL_URL",
        "capabilities": ["flood_zone", "map_panel", "special_flood_hazard_area", "risk_layer"],
        "confidence": "very_high",
        "retention": "federal_open_data_terms",
        "license_required": False,
    },
    {
        "id": "usgs_3dep",
        "name": "USGS 3D Elevation Program",
        "category": "terrain_context",
        "tier": "authoritative_public",
        "access": "free",
        "feature_flag": "ENABLE_USGS_3DEP",
        "endpoint_env": "USGS_ELEVATION_URL",
        "capabilities": ["ground_elevation", "terrain_context", "source_resolution"],
        "confidence": "high_for_interpolated_terrain",
        "retention": "federal_open_data_terms",
        "license_required": False,
        "default_enabled": True,
    },
    {
        "id": "census",
        "name": "US Census and TIGER/Line",
        "category": "market_enrichment",
        "tier": "public_enrichment",
        "access": "free",
        "feature_flag": "ENABLE_CENSUS_PUBLIC",
        "endpoint_env": "CENSUS_API_BASE_URL",
        "capabilities": ["demographics", "geography", "tract", "block_group", "housing_statistics"],
        "confidence": "high",
        "retention": "federal_open_data_terms",
        "license_required": False,
        "default_enabled": True,
    },
    {
        "id": "epa",
        "name": "EPA Environmental Public Data",
        "category": "risk",
        "tier": "public_enrichment",
        "access": "free",
        "feature_flag": "ENABLE_EPA_PUBLIC",
        "endpoint_env": "EPA_DATA_BASE_URL",
        "capabilities": ["environmental_sites", "hazardous_facilities", "brownfields", "air_and_water_context"],
        "confidence": "high",
        "retention": "federal_open_data_terms",
        "license_required": False,
    },
    {
        "id": "openaddresses",
        "name": "OpenAddresses",
        "category": "geospatial",
        "tier": "public_enrichment",
        "access": "free_open_data",
        "feature_flag": "ENABLE_OPENADDRESSES",
        "endpoint_env": "OPENADDRESSES_FEED_URL",
        "capabilities": ["address_normalization", "coordinates", "jurisdiction_coverage"],
        "confidence": "variable",
        "retention": "dataset_license",
        "license_required": False,
    },
    {
        "id": "usps_vacancy",
        "name": "USPS Vacancy Indicators",
        "category": "vacancy",
        "tier": "licensed_or_restricted",
        "access": "where_legally_available",
        "feature_flag": "ENABLE_USPS_VACANCY",
        "endpoint_env": "USPS_VACANCY_FEED_URL",
        "capabilities": ["vacancy_indicator", "vacancy_duration", "delivery_status"],
        "confidence": "variable",
        "retention": "provider_license",
        "license_required": True,
    },
    {
        "id": "mls_idx",
        "name": "MLS/IDX Licensed Feed",
        "category": "listings_and_comps",
        "tier": "licensed",
        "access": "licensed_only",
        "feature_flag": "ENABLE_MLS_IDX",
        "endpoint_env": "MLS_IDX_BASE_URL",
        "capabilities": ["active_listings", "sold_comps", "days_on_market", "price_reductions", "listing_history"],
        "confidence": "high",
        "retention": "mls_license",
        "license_required": True,
    },
)


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def provider_status(provider: dict[str, Any]) -> dict[str, Any]:
    configured_flag = os.getenv(provider["feature_flag"])
    enabled = _truthy(configured_flag) if configured_flag is not None else bool(provider.get("default_enabled", False))
    endpoint_configured = bool(os.getenv(provider["endpoint_env"]))
    if provider["access"] in {"free", "free_open_data"} and enabled and not endpoint_configured:
        state = "enabled_default_endpoint"
    elif enabled and endpoint_configured:
        state = "configured"
    elif enabled:
        state = "enabled_missing_endpoint"
    else:
        state = "disabled"
    return {
        **provider,
        "enabled": enabled,
        "endpoint_configured": endpoint_configured,
        "state": state,
        "outbound_capable": False,
        "dry_run_safe": True,
    }


def canonical_preview(provider_id: str, record: dict[str, Any]) -> dict[str, Any]:
    provider = next((item for item in PUBLIC_DATA_PROVIDERS if item["id"] == provider_id), None)
    if not provider:
        raise HTTPException(404, "Unknown public data provider")
    state = str(record.get("state") or record.get("property_state") or "").upper().strip()
    if state == "TX":
        raise HTTPException(409, "Texas properties are excluded from SAHJONY wholesale workflows")
    observed_at = str(record.get("observed_at") or datetime.now(timezone.utc).isoformat())
    return {
        "provider_id": provider_id,
        "provider_record_id": record.get("provider_record_id") or record.get("id"),
        "address": record.get("address") or record.get("property_address"),
        "city": record.get("city"),
        "state": state,
        "zip_code": record.get("zip_code") or record.get("zip"),
        "parcel_id": record.get("parcel_id") or record.get("apn"),
        "owner_name": record.get("owner_name") or record.get("owner"),
        "assessed_value": record.get("assessed_value"),
        "distress_indicators": record.get("distress_indicators") or [],
        "source": {
            "provider": provider["name"],
            "provider_id": provider_id,
            "observed_at": observed_at,
            "confidence": provider["confidence"],
            "authority_tier": provider["tier"],
            "raw_payload_retention": provider["retention"],
        },
        "workflow": {
            "dry_run": True,
            "external_actions_allowed": False,
            "owner_review_required": True,
        },
    }


@router.get("/catalog")
def catalog(principal: Principal = Depends(get_principal)):
    providers = [provider_status(provider) for provider in PUBLIC_DATA_PROVIDERS]
    return {
        "organization_id": principal.organization_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "providers": providers,
        "enabled_count": sum(1 for item in providers if item["enabled"]),
        "licensed_disabled_count": sum(1 for item in providers if item["license_required"] and not item["enabled"]),
        "safety": {
            "dry_run_default": True,
            "outbound_actions": False,
            "texas_excluded": True,
            "human_approval_required": True,
        },
    }


@router.get("/readiness")
def readiness(principal: Principal = Depends(get_principal)):
    providers = [provider_status(provider) for provider in PUBLIC_DATA_PROVIDERS]
    enabled = [item for item in providers if item["enabled"]]
    blocked = [item for item in enabled if item["state"] == "enabled_missing_endpoint"]
    return {
        "organization_id": principal.organization_id,
        "ready": bool(enabled) and not blocked,
        "enabled": [item["id"] for item in enabled],
        "blocked": [{"id": item["id"], "missing": item["endpoint_env"]} for item in blocked],
        "licensed_sources": [item["id"] for item in providers if item["license_required"]],
        "public_sources": [item["id"] for item in providers if not item["license_required"]],
    }


@router.post("/normalize-preview")
def normalize_preview(payload: dict[str, Any], principal: Principal = Depends(get_principal)):
    provider_id = str(payload.get("provider_id") or "").strip()
    record = payload.get("record") or {}
    if not isinstance(record, dict):
        raise HTTPException(422, "record must be an object")
    return {
        "organization_id": principal.organization_id,
        "canonical": canonical_preview(provider_id, record),
        "committed": False,
    }
