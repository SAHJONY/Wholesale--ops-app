"""One canonical scale for close probability.

Extracted from test_owner_attention.py, whose other three tests covered
owner_insights and executive_ops and went with them. This one did not: it
guards the percentage scale itself, which the deal pipeline still uses.

The bug it was written for: probability_to_close was stored as 0.10 in some
rows and 61 in others, so anything that summed weighted revenue was mixing two
scales and producing numbers that looked plausible and were wrong by 100x.
"""

from app.percentages import INITIAL_CLOSE_PROBABILITY, canonical_percentage


def test_close_probability_uses_one_canonical_zero_to_one_hundred_scale():
    assert INITIAL_CLOSE_PROBABILITY == 10
    # A legacy fractional value and its whole-number equivalent must agree.
    assert canonical_percentage(0.10) == 10
    assert canonical_percentage(61) == 61


def test_out_of_range_probabilities_are_clamped_rather_than_trusted():
    assert canonical_percentage(150) == 100
    assert canonical_percentage(-4) == 0
    assert canonical_percentage(None) == 0
