"""Nationwide sweep filtering, and the two ways it silently loses counties.

Both defects here fail the same way: they return a plausible-looking result
that is wrong, rather than an obvious error. A state filter that matches
everything looks like it worked, and a category with no search terms looks like
a county that publishes nothing.
"""

import os

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_wholesale_ops.db")

from app import distress_discovery as dd
from app.distress_providers import PROVIDERS_BY_ID


def hit(title="", domain="data.example.gov", description=""):
    return {"domain": domain, "title": title, "description": description}


def test_abbreviation_no_longer_matches_inside_words():
    # Every one of these matched before: substring matching on a two-letter
    # code turns "building" into Indiana and "vacant" into California.
    assert not dd._matches_state(hit(title="Vacant Property Registry"), {"CA"})
    assert not dd._matches_state(hit(title="Chicago Building Permits"), {"CA"})
    assert not dd._matches_state(hit(title="Building Code Cases"), {"IN"})
    assert not dd._matches_state(hit(title="Property Records Index"), {"OR"})
    assert not dd._matches_state(hit(title="Home Improvement Violations"), {"ME"})
    assert not dd._matches_state(hit(title="Code Violation Cases"), {"LA"})
    assert not dd._matches_state(hit(title="Delinquent Tax Roll"), {"DE"})


def test_full_state_name_matches():
    assert dd._matches_state(hit(title="California Foreclosure Filings"), {"CA"})
    assert dd._matches_state(hit(description="Recorded in North Carolina"), {"NC"})


def test_abbreviation_matches_as_a_whole_word():
    assert dd._matches_state(hit(title="Cook County, IL sheriff sales"), {"IL"})
    assert dd._matches_state(hit(title="Travis County (TX) records"), {"TX"})


def test_abbreviation_matches_as_a_domain_label():
    # How government portals actually encode the state.
    assert dd._matches_state(hit(domain="data.ca.gov"), {"CA"})
    assert dd._matches_state(hit(domain="gis.tn.us"), {"TN"})
    # A domain that merely contains the letters must not match.
    assert not dd._matches_state(hit(domain="data.cambridgema.gov", title=""), {"CA"})


def test_no_filter_still_returns_everything():
    assert dd._matches_state(hit(title="Anything at all"), set())


def test_multiple_states_match_any():
    candidate = hit(title="Florida tax deed auctions")
    assert dd._matches_state(candidate, {"GA", "FL"})
    assert not dd._matches_state(candidate, {"GA", "OH"})


def test_state_name_table_is_complete():
    # 50 states plus the District of Columbia.
    assert len(dd.STATE_NAMES) == 51
    assert all(len(code) == 2 and code.isupper() for code in dd.STATE_NAMES)
    assert dd.STATE_NAMES["DC"] == "district of columbia"


def test_every_public_record_category_is_discoverable():
    # Adding a provider category without search terms removes it from
    # nationwide coverage silently. Splitting the foreclosure track did exactly
    # that to notice_of_default and notice_of_trustee_sale.
    assert dd.categories_without_queries() == []


def test_the_new_foreclosure_categories_have_their_own_terms():
    assert "notice of default" in dd.CATEGORY_QUERIES["notice_of_default"]
    assert "notice of trustee sale" in dd.CATEGORY_QUERIES["notice_of_trustee_sale"]
    # The judicial category must no longer claim a non-judicial artefact.
    assert "notice of default" not in dd.CATEGORY_QUERIES["lis_pendens"]


def test_sweep_defaults_cover_every_public_record_category():
    defaults = set(dd._public_record_categories())
    expected = {spec.id for spec in PROVIDERS_BY_ID.values() if spec.access == "public_record"}
    assert defaults == expected


def test_licensed_categories_are_never_swept():
    # FSBO and MLS are licensed inventory; a catalog sweep must not propose them.
    for category in dd._public_record_categories():
        assert PROVIDERS_BY_ID[category].access == "public_record"
