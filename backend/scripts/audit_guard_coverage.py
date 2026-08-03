#!/usr/bin/env python3
"""Ask whether each safety guard has a test that would notice it disappearing.

Four defects in this codebase shared one shape: a check that was present,
looked right, and did nothing.

* Quiet hours were enforced for calls but not texts, because SMS was missing
  from the channel set. Every text skipped the 8pm-8am restriction.
* The nationwide state filter matched two-letter codes as substrings, so "IN"
  matched "Building" and the filter excluded almost nothing.
* The SMS frequency cap counted rows from a log that nothing wrote to, so the
  count was permanently zero and the cap never fired.
* /health reported a hardcoded version string, so a month-stale deployment was
  indistinguishable from a current one.

Each had tests. The tests asserted the guard's *configuration* -- that the
constant existed and held a sensible value -- rather than its *effect*. A test
that only shows the allow-path passing cannot tell a working guard from a
missing one.

So this does not read the guard. It breaks it, runs the tests, and reports any
guard the suite failed to notice being broken. A guard whose mutation leaves
the suite green is a guard nobody is testing, whatever its coverage says.

    python scripts/audit_guard_coverage.py            # audit every guard
    python scripts/audit_guard_coverage.py --list     # show what is covered

Exit codes: 0 every guard is defended, 1 at least one is not.
"""

from __future__ import annotations

import argparse
import importlib
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

GREEN, RED, DIM, RESET = "\033[32m", "\033[31m", "\033[2m", "\033[0m"


@dataclass
class Guard:
    """One safety constant, and how to sabotage it."""

    module: str
    symbol: str
    # A Python expression, not a value: each mutation runs in its own
    # interpreter, so the replacement has to survive being written to a file.
    broken_expr: str
    tests: str
    why: str
    # Set when the suite fails to notice.
    undefended: bool = field(default=False, init=False)


GUARDS: tuple[Guard, ...] = (
    Guard(
        "app.compliance", "QUIET_HOURS_CHANNELS",
        'frozenset({"live_call", "automated_call"})',
        "tests/test_sms_engine.py",
        "Dropping SMS is the exact bug that let texts send at 3am.",
    ),
    Guard(
        "app.sms_engine", "OPT_OUT_KEYWORDS",
        'frozenset({"unsubscribe"})',
        "tests/test_sms_engine.py",
        "Losing STOP means opt-outs are ignored.",
    ),
    Guard(
        "app.sms_engine", "MAX_MESSAGES_PER_WINDOW",
        "999999",
        "tests/test_sms_engine.py",
        "A cap this high is no cap.",
    ),
    Guard(
        "app.cash_buyer_discovery", "MIN_CONFIDENCE_TO_PROMOTE",
        "0.0",
        "tests/test_cash_buyer_discovery.py",
        "Zero lets one recorded purchase become an 'active cash buyer'.",
    ),
    Guard(
        "app.distress_providers", "EXCLUDED_STATES",
        "frozenset()",
        "tests/test_distress_ingest.py tests/test_foreclosure_procedure.py",
        "Emptying this readmits Texas, which the workflow excludes.",
    ),
    Guard(
        # A function rather than a constant: the default lives inside it, and
        # what matters is the behaviour, not where the value is spelled.
        "app.lead_verification", "enforcement_enabled",
        "lambda: False",
        "tests/test_lead_verification.py",
        "Enforcement off would let unverified leads be actioned.",
    ),
    Guard(
        "app.voice_engine", "ALL_PARTY_CONSENT_STATES",
        "frozenset()",
        "tests/test_voice_engine.py",
        "Emptying this permits recording a Florida call nobody consented to, "
        "which is a criminal statute rather than a compliance ticket.",
    ),
    Guard(
        # Broadened rather than emptied. A pattern matching everything is the
        # realistic failure -- someone loosens the regex to stop a script being
        # rejected -- and it silently passes calls that disclose nothing.
        "app.voice_engine", "AI_DISCLOSURE_PATTERNS",
        r'(r".",)',
        "tests/test_voice_engine.py",
        "If every script counts as disclosed, no script is.",
    ),
    Guard(
        "app.voice_engine", "RECORDING_DISCLOSURE_PATTERNS",
        r'(r".",)',
        "tests/test_voice_engine.py",
        "The all-party recording gate is only as good as this pattern.",
    ),
    Guard(
        "app.voice_engine", "VERBAL_OPT_OUT_PATTERNS",
        "()",
        "tests/test_voice_engine.py",
        "A spoken 'take me off your list' would stop being heard.",
    ),
    Guard(
        # The webhook is the one endpoint here with no authentication in front
        # of it. If verification ever returns True unconditionally, anyone on
        # the internet can write calls and opt-outs into the workspace.
        "app.voice_engine", "verify_webhook_signature",
        'lambda headers, body: (True, "bypassed")',
        "tests/test_voice_engine.py",
        "An accept-everything verifier makes this a public write endpoint.",
    ),
    Guard(
        # Collapsing the refusal class into its parent makes a refusal
        # indistinguishable from an outage, so the chain would retry a
        # declined analysis on the second engine -- refusal shopping.
        "app.decision_intelligence", "DecisionRefused",
        "app.decision_intelligence.DecisionUnavailable",
        "tests/test_decision_intelligence.py",
        "A refusal must not be retried on a different provider.",
    ),
    Guard(
        # The channels the dispatcher actually runs the script gate for.
        # Emptying it leaves validate_call_script defined, imported and never
        # consulted -- which is the precise shape of every defect this tool
        # exists to catch.
        "app.outbound_gateway", "VOICE_CHANNELS",
        "frozenset()",
        "tests/test_outbound_gateway.py",
        "An empty set means undisclosed AI calls dial real phones.",
    ),
)


def run_tests(paths: str, mutation: tuple[str, str, str] | None = None) -> bool:
    """Run tests in a fresh interpreter. True when they pass.

    A subprocess per run, deliberately. The first version called pytest.main()
    repeatedly in one process, and it was worthless: test modules bind their
    imports on first load, so a later mutation never reached the name the test
    had already captured, and pytest's own global state carried across runs.
    Every guard came back "defended" whether or not anything tested it.
    """
    env = dict(os.environ)
    args = [sys.executable, "-m", "pytest", "-q", "--no-header", "-p", "no:cacheprovider"]

    with tempfile.TemporaryDirectory() as tmp:
        if mutation:
            module, symbol, expression = mutation
            plugin = Path(tmp) / "guard_mutation_plugin.py"
            # Imported before collection, so the module is patched before any
            # test module performs a `from ... import` against it.
            # Deferred to pytest_configure(trylast) rather than done at
            # import. A plugin passed with -p loads before conftest, so
            # importing the app here binds a database engine before conftest
            # sets DATABASE_URL -- which crashed pytest with an internal error.
            # That returned non-zero, the audit read it as "the tests failed",
            # and every guard was reported defended while nothing had run.
            # trylast puts the mutation after conftest has prepared the schema
            # and before collection imports any test module.
            plugin.write_text(
                "import importlib\n"
                "import pytest\n"
                "\n"
                "@pytest.hookimpl(trylast=True)\n"
                "def pytest_configure(config):\n"
                f"    _m = importlib.import_module({module!r})\n"
                f"    setattr(_m, {symbol!r}, {expression})\n"
            )
            env["PYTHONPATH"] = f"{tmp}{os.pathsep}{env.get('PYTHONPATH', '')}"
            args += ["-p", "guard_mutation_plugin"]

        completed = subprocess.run(
            args + paths.split(), cwd=str(BACKEND), env=env,
            capture_output=True, text=True, timeout=600,
        )
    return completed.returncode == 0


def audit(guard: Guard) -> tuple[str, str]:
    """Break the guard in a fresh interpreter, run its tests, report."""
    try:
        module = importlib.import_module(guard.module)
    except Exception as exc:  # noqa: BLE001
        return "error", f"cannot import {guard.module}: {type(exc).__name__}"
    if not hasattr(module, guard.symbol):
        # A stale registry is itself a finding: the guard was renamed or
        # removed and nothing noticed.
        return "error", f"{guard.module} has no {guard.symbol}"

    if run_tests(guard.tests, (guard.module, guard.symbol, guard.broken_expr)):
        guard.undefended = True
        return "undefended", "suite still passed with this guard disabled"
    return "defended", "suite failed, as it should"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--list", action="store_true", help="List the guards and exit")
    args = parser.parse_args()

    if args.list:
        for guard in GUARDS:
            print(f"{guard.module}.{guard.symbol}\n{DIM}  {guard.why}{RESET}")
        return 0

    # Without this, a suite failing for any unrelated reason makes every guard
    # look defended, because "defended" is literally "the tests failed". The
    # audit would then report perfect coverage of a suite that never ran.
    suites = sorted({path for guard in GUARDS for path in guard.tests.split()})
    print("Checking the tests pass before breaking anything.")
    baseline = run_tests(" ".join(suites))
    if not baseline:
        print(f"{RED}The suite fails unmutated, so no guard can be audited.{RESET}")
        print(f"{DIM}Every guard would report 'defended' for the wrong reason. Fix the suite first.{RESET}")
        return 2
    print(f"{GREEN}  baseline green{RESET}\n")

    print("Breaking each safety guard to see whether its tests notice.\n")
    undefended, errors = [], []
    for guard in GUARDS:
        state, detail = audit(guard)
        label = f"{guard.module.split('.')[-1]}.{guard.symbol}"
        if state == "defended":
            print(f"{GREEN}  defended  {RESET}{label}")
        elif state == "undefended":
            undefended.append(guard)
            print(f"{RED}  UNDEFENDED{RESET}{label}")
            print(f"{DIM}             {guard.why}{RESET}")
            print(f"{DIM}             {detail}{RESET}")
        else:
            errors.append((guard, detail))
            print(f"{RED}  ERROR     {RESET}{label} {DIM}{detail}{RESET}")

    print("\n" + "=" * 70)
    if not undefended and not errors:
        print(f"{GREEN}Every guard has a test that fails when it is removed.{RESET}")
        return 0
    if undefended:
        print(f"{RED}{len(undefended)} guard(s) can be disabled without failing a test.{RESET}")
        print("A guard nobody tests is a guard that has already stopped working once")
        print("in this codebase without anyone noticing. Add a test that asserts what")
        print("each one excludes, not merely that it exists.")
    if errors:
        print(f"{RED}{len(errors)} guard(s) could not be audited; the registry is stale.{RESET}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
