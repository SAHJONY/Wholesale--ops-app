"""The guard audit must be able to fail.

This tool reports "defended" when a mutated suite fails. Anything that makes
the suite fail for its own reasons therefore reports every guard as defended,
which is how it behaved through two rewrites: a plugin that crashed pytest
returned non-zero, and the audit read the crash as tests doing their job.

So the audit is itself audited. If these two stop discriminating, the tool has
gone back to always saying yes.
"""

import os
import sys
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_wholesale_ops.db")
os.environ.setdefault("SMS_BUSINESS_NAME", "SAHJONY Capital")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import pytest  # noqa: E402

import audit_guard_coverage as aud  # noqa: E402


@pytest.mark.slow
def test_the_audit_reports_an_untested_constant_as_undefended():
    # DNC_MAX_AGE_DAYS is asserted nowhere in the SMS suite, so breaking it
    # must go unnoticed and the audit must say so.
    guard = aud.Guard(
        "app.compliance", "DNC_MAX_AGE_DAYS", "999999",
        "tests/test_sms_engine.py", "control",
    )
    state, _ = aud.audit(guard)
    assert state == "undefended"


@pytest.mark.slow
def test_the_audit_reports_a_tested_constant_as_defended():
    guard = aud.Guard(
        "app.compliance", "QUIET_HOURS_CHANNELS",
        'frozenset({"live_call","automated_call"})',
        "tests/test_sms_engine.py", "control",
    )
    state, _ = aud.audit(guard)
    assert state == "defended"


def test_a_renamed_guard_is_reported_rather_than_skipped():
    # A stale registry entry must be a finding, not a silent pass.
    guard = aud.Guard("app.compliance", "NO_SUCH_CONSTANT", "0", "tests/test_sms_engine.py", "x")
    state, detail = aud.audit(guard)
    assert state == "error"
    assert "NO_SUCH_CONSTANT" in detail


def test_every_registered_guard_still_exists():
    import importlib

    for guard in aud.GUARDS:
        module = importlib.import_module(guard.module)
        assert hasattr(module, guard.symbol), f"{guard.module}.{guard.symbol} was renamed or removed"
