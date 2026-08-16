from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any
from urllib.parse import urlparse

DISTRESS_COLLECTORS: tuple[dict[str, Any], ...] = (
    {
        "id": "tax_distress",
        "label": "Tax delinquency / tax sale",
        "signals": ["tax_delinquent", "tax_sale", "tax_lien"],
        "preferred_source_kinds": ["county_tax", "tax_sale", "government_open_data"],
        "query_focus": "official delinquent property tax lists, tax sale lists, tax lien lists, treasurer/tax collector records",
    },
    {
        "id": "code_vacancy",
        "label": "Code / vacancy / unsafe property",
        "signals": ["code_violation", "vacant", "unsafe", "nuisance"],
        "preferred_source_kinds": ["code_enforcement", "government_open_data"],
        "query_focus": "official code enforcement, vacant building, nuisance, unsafe structure, demolition or abatement records",
    },
    {
        "id": "foreclosure_public_sale",
        "label": "Foreclosure / sheriff / public sale",
        "signals": ["foreclosure", "pre_foreclosure", "sheriff_sale", "public_sale"],
        "preferred_source_kinds": ["foreclosure_notice", "government_open_data"],
        "query_focus": "official foreclosure, sheriff sale, trustee sale, court sale, notice of default or public sale records",
    },
    {
        "id": "probate_estate",
        "label": "Probate / estate indicators",
        "signals": ["probate", "estate"],
        "preferred_source_kinds": ["other_public", "recorder_deed"],
        "query_focus": "official probate, estate administration, executor, personal representative, decedent estate or court docket records that identify a property address",
    },
    {
        "id": "fsbo_public",
        "label": "Free public FSBO / owner-listed",
        "signals": ["fsbo", "owner_listed", "for_sale_by_owner"],
        "preferred_source_kinds": ["fsbo_public", "other_public"],
        "query_focus": "free publicly accessible for-sale-by-owner, owner-listed, owner selling directly, no-agent property listing pages and public classifieds; exclude login-gated, paid, private-group, broker-only and skip-trace sources",
    },
)

VERIFICATION_SOURCE_KINDS: tuple[str, ...] = (
    "county_assessor",
    "recorder_deed",
    "county_tax",
    "government_open_data",
)

OFFICIAL_HOST_HINTS = (
    ".gov",
    ".us",
    "arcgis.com",
    "govqa.us",
    "tylertech.com",
    "qpublic.net",
    "schneidercorp.com",
)


def source_host(url: str) -> str:
    try:
        return (urlparse(str(url or "")).hostname or "").lower()
    except ValueError:
        return ""


def source_authority(url: str) -> str:
    host = source_host(url)
    if not host:
        return "unknown"
    if host.endswith(".gov") or ".gov." in host:
        return "official_government"
    if host.endswith(".us") or any(hint in host for hint in OFFICIAL_HOST_HINTS[2:]):
        return "government_platform"
    return "public_web"


def coverage_summary(records: list[dict[str, Any]], targets: list[dict[str, str]], collector_runs: list[dict[str, Any]]) -> dict[str, Any]:
    source_kinds = Counter()
    authorities = Counter()
    hosts = Counter()
    signals = Counter()
    records_by_state = Counter()
    records_by_collector = Counter()
    official_records = 0

    for record in records:
        source_kinds[str(record.get("source_kind") or "other_public")] += 1
        records_by_state[str(record.get("state") or "")] += 1
        for signal in record.get("distress_signals") or []:
            signals[str(signal)] += 1
        collector_id = str((record.get("provider_evidence") or {}).get("collector_id") or "unknown")
        records_by_collector[collector_id] += 1
        urls = record.get("source_urls") or []
        record_official = False
        for url in urls:
            host = source_host(str(url))
            authority = source_authority(str(url))
            if host:
                hosts[host] += 1
            authorities[authority] += 1
            if authority in {"official_government", "government_platform"}:
                record_official = True
        if record_official:
            official_records += 1

    target_keys = []
    for target in targets:
        label = target.get("state", "")
        if target.get("county"):
            label = f"{target['county']} County, {label}"
        elif target.get("city"):
            label = f"{target['city']}, {label}"
        target_keys.append(label)

    run_status = defaultdict(lambda: {"attempted": 0, "successful": 0, "records": 0})
    for run in collector_runs:
        cid = str(run.get("collector_id") or "unknown")
        run_status[cid]["attempted"] += 1
        if run.get("success"):
            run_status[cid]["successful"] += 1
        run_status[cid]["records"] += int(run.get("records") or 0)

    total = len(records)
    official_ratio = round(official_records / total, 3) if total else 0.0
    collector_coverage = sum(1 for cid in (c["id"] for c in DISTRESS_COLLECTORS) if records_by_collector[cid] > 0)
    score = 0
    if total:
        score += min(35, total * 3)
        score += round(35 * official_ratio)
        score += round(20 * collector_coverage / len(DISTRESS_COLLECTORS))
        score += min(10, len(hosts) * 2)

    return {
        "coverage_score": min(100, int(score)),
        "targets": target_keys,
        "candidate_records": total,
        "official_source_ratio": official_ratio,
        "unique_source_hosts": len(hosts),
        "top_source_hosts": hosts.most_common(15),
        "source_kinds": dict(source_kinds),
        "source_authority": dict(authorities),
        "distress_signals": dict(signals),
        "records_by_state": dict(records_by_state),
        "records_by_collector": dict(records_by_collector),
        "collector_run_health": dict(run_status),
        "collector_catalog": [
            {"id": c["id"], "label": c["label"], "signals": c["signals"], "preferred_source_kinds": c["preferred_source_kinds"]}
            for c in DISTRESS_COLLECTORS
        ],
        "verification_source_kinds": list(VERIFICATION_SOURCE_KINDS),
        "boundary": "Coverage measures searched public-source depth, including free public FSBO discovery, not completeness of all distressed or owner-listed properties in a jurisdiction.",
    }
