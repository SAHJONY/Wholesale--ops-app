from app.county_source_registry import DISTRESS_COLLECTORS, coverage_summary


def test_free_public_fsbo_collector_is_registered():
    collectors = {item["id"]: item for item in DISTRESS_COLLECTORS}
    fsbo = collectors["fsbo_public"]
    assert "fsbo_public" in fsbo["preferred_source_kinds"]
    assert "for_sale_by_owner" in fsbo["signals"]
    assert "private-group" in fsbo["query_focus"]


def test_public_facebook_groups_fsbo_collector_is_registered_and_restricted():
    collectors = {item["id"]: item for item in DISTRESS_COLLECTORS}
    facebook = collectors["facebook_groups_fsbo"]
    assert "facebook_group_fsbo" in facebook["signals"]
    assert "fsbo_public" in facebook["preferred_source_kinds"]
    assert "publicly accessible Facebook" in facebook["query_focus"]
    assert "never automate login" in facebook["query_focus"]
    assert "private/login-gated" in facebook["query_focus"]


def test_fsbo_is_counted_as_public_web_coverage_not_owner_verification():
    records = [
        {
            "state": "TX",
            "source_kind": "fsbo_public",
            "distress_signals": ["fsbo", "owner_listed"],
            "source_urls": ["https://public.example/fsbo/123"],
            "provider_evidence": {"collector_id": "fsbo_public"},
        },
        {
            "state": "TX",
            "source_kind": "fsbo_public",
            "distress_signals": ["fsbo", "facebook_group_fsbo"],
            "source_urls": ["https://www.facebook.com/groups/public-example/posts/123"],
            "provider_evidence": {"collector_id": "facebook_groups_fsbo"},
        },
    ]
    coverage = coverage_summary(
        records,
        [{"state": "TX", "city": "Houston", "county": ""}],
        [
            {"collector_id": "fsbo_public", "success": True, "records": 1},
            {"collector_id": "facebook_groups_fsbo", "success": True, "records": 1},
        ],
    )
    assert coverage["records_by_collector"]["fsbo_public"] == 1
    assert coverage["records_by_collector"]["facebook_groups_fsbo"] == 1
    assert coverage["source_kinds"]["fsbo_public"] == 2
    assert coverage["source_authority"]["public_web"] == 2
    assert "county_assessor" in coverage["verification_source_kinds"]
    assert "recorder_deed" in coverage["verification_source_kinds"]
