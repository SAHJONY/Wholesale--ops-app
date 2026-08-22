from app.provider_intelligence import jurisdiction_public_record_sources


def test_registered_county_returns_exact_official_sources():
    sources = jurisdiction_public_record_sources("fl", "Escambia County")
    assert len(sources) == 2
    assert all(not source.get("discovery_only") for source in sources)
    assert all(source["state"] == "FL" for source in sources)


def test_any_county_gets_fail_closed_official_discovery():
    sources = jurisdiction_public_record_sources("OH", "Cuyahoga")
    assert {source["provider_id"] for source in sources} == {"county_assessor", "county_recorder"}
    assert all(source["discovery_only"] is True for source in sources)
    assert all("site%3A.gov" in source["url"] for source in sources)
    assert all(source["verification_status"] == "human_review_required" for source in sources)
