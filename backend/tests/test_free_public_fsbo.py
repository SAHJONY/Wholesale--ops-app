from app.county_source_registry import DISTRESS_COLLECTORS, coverage_summary


def test_free_public_fsbo_collector_is_registered():
    collectors = {item["id"]: item for item in DISTRESS_COLLECTORS}
    fsbo = collectors["fsbo_public"]
    assert "fsbo_public" in fsbo["preferred_source_kinds"]
    assert "for_sale_by_owner" in fsbo["signals"]
    assert "private-group" in fsbo["query_focus"]


def test_fsbo_is_counted_as_public_web_coverage_not_owner_verification():
    records = [
        {
            "state": "TX",
            "source_kind": "fsbo_public",
            "distress_signals": ["fsbo", "owner_listed"],
            "source_urls": ["https://public.example/fsbo/123"],
            "provider_evidence": {"collector_id": "fsbo_public"},
        }
    ]
    coverage = coverage_summary(
        records,
        [{"state": "TX", "city": "Houston", "county": ""}],
        [{"collector_id": "fsbo_public", "success": True, "records": 1}],
    )
    assert coverage["records_by_collector"]["fsbo_public"] == 1
    assert coverage["source_kinds"]["fsbo_public"] == 1
    assert coverage["source_authority"]["public_web"] == 1
    assert "county_assessor" in coverage["verification_source_kinds"]
    assert "recorder_deed" in coverage["verification_source_kinds"]
