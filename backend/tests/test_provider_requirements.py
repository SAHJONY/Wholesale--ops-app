"""One answer to "is this provider configured", wherever it is asked.

Go-live and launch validation each kept their own copy of these rules and the
copies drifted apart. Two live disagreements, both of which sent the owner the
wrong way:

* Go-live took any one of TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN or
  BLAND_AI_API_KEY as working communications. An account SID with no auth token
  reported ready and could send nothing.
* Go-live knew only the SMTP pair for email, so a workspace running on
  RESEND_API_KEY was told to configure email that was already working.
"""

import os

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_wholesale_ops.db")

import pytest

from app import provider_requirements as pr

ALL_NAMES = sorted({
    name
    for requirement in pr.REQUIREMENTS
    for group in requirement.alternatives
    for name in group
})


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Start every test from nothing configured, so a real environment
    variable in the shell cannot make a failing case pass."""
    for name in ALL_NAMES:
        monkeypatch.delenv(name, raising=False)


def test_nothing_configured_means_nothing_ready():
    assert not any(item["ready"] for item in pr.evaluate_all())


# ------------------------------------------------- the two real divergences --

def test_half_a_twilio_account_is_not_working_communications(monkeypatch):
    # The go-live bug. An account SID alone authenticates no request.
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "AC123")
    assert pr.ready("communications") is False
    assert "TWILIO_AUTH_TOKEN" in pr.evaluate(pr.BY_ID["communications"])["missing"]

    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "secret")
    assert pr.ready("communications") is True


def test_bland_alone_is_a_complete_alternative(monkeypatch):
    monkeypatch.setenv("BLAND_AI_API_KEY", "key")
    assert pr.ready("communications") is True


def test_resend_alone_satisfies_email(monkeypatch):
    # The other go-live bug: a live Resend setup reported as missing email.
    monkeypatch.setenv("RESEND_API_KEY", "re_live")
    assert pr.ready("email") is True


def test_half_an_smtp_pair_does_not_satisfy_email(monkeypatch):
    monkeypatch.setenv("SMTP_USER", "ops@example.com")
    assert pr.ready("email") is False


# ------------------------------------------------------------- reporting --

def test_missing_names_come_from_the_closest_alternative(monkeypatch):
    # Half-way through Twilio, the advice should be "add the auth token",
    # not "or set up Bland instead".
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "AC123")
    assert pr.evaluate(pr.BY_ID["communications"])["missing"] == ["TWILIO_AUTH_TOKEN"]


def test_an_untouched_requirement_names_a_whole_group(monkeypatch):
    missing = pr.evaluate(pr.BY_ID["contact_enrichment"])["missing"]
    assert set(missing) == {"BATCHDATA_API_KEY", "BATCHDATA_SKIPTRACE_URL"}


def test_a_satisfied_requirement_says_which_group_satisfied_it(monkeypatch):
    monkeypatch.setenv("BLAND_AI_API_KEY", "key")
    assert pr.evaluate(pr.BY_ID["communications"])["satisfied_by"] == ["BLAND_AI_API_KEY"]


def test_whitespace_is_not_a_credential(monkeypatch):
    # A variable set to an empty string or spaces is the usual result of a
    # half-finished dashboard entry, and it must not read as configured.
    monkeypatch.setenv("BLAND_AI_API_KEY", "   ")
    assert pr.ready("communications") is False


# --------------------------------------------------------- registry shape --

def test_every_requirement_has_at_least_one_alternative():
    for requirement in pr.REQUIREMENTS:
        assert requirement.alternatives, requirement.id
        for group in requirement.alternatives:
            assert group, f"{requirement.id} has an empty alternative"


def test_severities_are_ones_the_readiness_screens_weight():
    # go_live and launch_validation both weight by these exact strings; an
    # unrecognised severity raises a KeyError when scoring.
    for requirement in pr.REQUIREMENTS:
        assert requirement.severity in {"critical", "high", "medium", "low"}, requirement.id


def _code_lines(module) -> str:
    """Module source with comments and docstrings stripped.

    Scanning raw source would fail on the comments explaining this very fix,
    which name the variables as prose. That mistake has been made in this
    repository before: a test asserted a variable name was absent from a
    function and broke on the comment written to explain why it was absent.
    """
    import ast
    import inspect

    source = inspect.getsource(module)
    tree = ast.parse(source)
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            doc = ast.get_docstring(node, clean=False)
            if doc:
                docstrings.add(doc)
    kept = [line for line in source.splitlines() if not line.lstrip().startswith("#")]
    text = "\n".join(kept)
    for doc in docstrings:
        text = text.replace(doc, "")
    return text


def test_both_readiness_screens_read_this_registry():
    """The point of the module. Neither may reintroduce a private copy."""
    from app import go_live, launch_validation

    for module in (go_live, launch_validation):
        code = _code_lines(module)
        assert "provider_requirements" in code, module.__name__
        # Neither may go back to branching on raw provider variable names.
        for name in ("TWILIO_ACCOUNT_SID", "RESEND_API_KEY", "DOCUSEAL_API_KEY"):
            assert name not in code, (
                f"{module.__name__} still names {name} in code; that is how the "
                "two screens drifted apart the first time"
            )
