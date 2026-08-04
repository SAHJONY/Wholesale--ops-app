import pytest

from app import decision_intelligence as di

UNDERWRITING = {
    "underwriting": {
        "decision_quality": {
            "verdict": "marginal",
            "probability_of_target": 0.55,
            "valuation_confidence": 48,
        },
        "valuation": {"arv": 260_000, "warnings": ["Comparable set is thin"]},
        "simulation": {"downside_spread": -2_000},
        "repairs": {"line_items": {"roof_damage": 12_000}},
        "recommended_max_offer": 65_000,
    }
}


class TestSchemas:
    def test_every_schema_is_valid_for_structured_outputs(self):
        # Structured outputs reject any object that omits additionalProperties
        # or leaves a property out of `required`, so this is a contract check
        # against the API, not a style preference.
        def check(node):
            if not isinstance(node, dict):
                return
            if node.get("type") == "object":
                assert node.get("additionalProperties") is False
                assert set(node.get("required", [])) == set(node.get("properties", {}))
                for child in node.get("properties", {}).values():
                    check(child)
            if node.get("type") == "array":
                check(node.get("items"))

        for schema in di.ANALYSIS_SCHEMAS.values():
            check(schema)

    def test_unknown_analysis_kind_is_rejected(self):
        with pytest.raises(ValueError):
            di.analyze("not_a_real_kind", {})


class TestSafetyBoundary:
    def test_system_prompt_encodes_the_approval_gates(self):
        prompt = di.SYSTEM_PROMPT.lower()
        for phrase in ("human approval", "never", "funds", "legally binding"):
            assert phrase in prompt

    def test_briefs_warn_against_unverified_claims(self):
        result = di.analyze("seller_brief", {"lead": {}, "property": {"address": "12 Oak"}})
        joined = " ".join(result["do_not_say"]).lower()
        assert "funds" in joined
        assert "title" in joined


class TestDeterministicFallback:
    def test_without_an_api_key_the_source_is_labelled(self, monkeypatch):
        monkeypatch.setattr(di.settings, "anthropic_api_key", None)
        result = di.analyze("deal_review", UNDERWRITING)
        assert result["source"] == "deterministic"
        assert result["fallback_reason"] == "no_api_key"

    def test_fallback_still_produces_every_schema_field(self, monkeypatch):
        monkeypatch.setattr(di.settings, "anthropic_api_key", None)
        for kind, schema in di.ANALYSIS_SCHEMAS.items():
            payload = UNDERWRITING if kind == "deal_review" else {}
            result = di.analyze(kind, payload)
            for field in schema["required"]:
                assert field in result, f"{kind} fallback is missing {field}"

    def test_marginal_underwriting_recommends_renegotiation(self, monkeypatch):
        monkeypatch.setattr(di.settings, "anthropic_api_key", None)
        assert di.analyze("deal_review", UNDERWRITING)["recommendation"] == "renegotiate"

    def test_valuation_warnings_surface_as_risks(self, monkeypatch):
        monkeypatch.setattr(di.settings, "anthropic_api_key", None)
        risks = di.analyze("deal_review", UNDERWRITING)["key_risks"]
        assert "Comparable set is thin" in risks

    def test_negative_downside_is_called_out(self, monkeypatch):
        monkeypatch.setattr(di.settings, "anthropic_api_key", None)
        risks = " ".join(di.analyze("deal_review", UNDERWRITING)["key_risks"])
        assert "loses" in risks

    def test_portfolio_priorities_lead_with_pending_approvals(self, monkeypatch):
        monkeypatch.setattr(di.settings, "anthropic_api_key", None)
        result = di.analyze(
            "portfolio_priorities",
            {"pending_approvals": 3, "hot_leads": 2, "active_deals": 4, "stalled_deals": 1},
        )
        assert "approval" in result["priorities"][0]["action"].lower()
        assert result["priorities"][0]["urgency"] == "today"

    def test_an_empty_pipeline_still_gets_a_recommendation(self, monkeypatch):
        monkeypatch.setattr(di.settings, "anthropic_api_key", None)
        result = di.analyze("portfolio_priorities", {})
        assert result["priorities"]


class TestModelFailureHandling:
    def test_a_transport_failure_degrades_instead_of_raising(self, monkeypatch):
        monkeypatch.setattr(di.settings, "anthropic_api_key", "test-key")
        monkeypatch.setattr(di, "_invoke", lambda *_: (_ for _ in ()).throw(RuntimeError("boom")))
        result = di.analyze("deal_review", UNDERWRITING)
        assert result["source"] == "deterministic"
        assert result["fallback_reason"] == "RuntimeError"

    def test_a_refusal_degrades_and_is_labelled_as_such(self, monkeypatch):
        monkeypatch.setattr(di.settings, "anthropic_api_key", "test-key")

        def refuse(*_):
            raise di.DecisionRefused("declined")

        monkeypatch.setattr(di, "_invoke", refuse)
        result = di.analyze("deal_review", UNDERWRITING)
        assert result["fallback_reason"] == "model_refusal"

    def test_a_successful_call_is_labelled_as_claude(self, monkeypatch):
        monkeypatch.setattr(di.settings, "anthropic_api_key", "test-key")
        monkeypatch.setattr(
            di, "_invoke", lambda kind, payload: {"recommendation": "pursue", "source": "claude"}
        )
        assert di.analyze("deal_review", UNDERWRITING)["source"] == "claude"


class TestConfiguration:
    def test_reports_whether_a_live_model_is_available(self, monkeypatch):
        monkeypatch.setattr(di.settings, "anthropic_api_key", None)
        assert di.is_configured() is False
        monkeypatch.setattr(di.settings, "anthropic_api_key", "test-key")
        assert di.is_configured() is True

    def test_targets_a_current_model(self):
        from app.config import Settings

        assert Settings(_env_file=None).claude_model == "claude-opus-5"
