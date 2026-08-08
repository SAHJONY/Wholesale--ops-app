import os
from types import SimpleNamespace

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_wholesale_ops.db")
os.environ.setdefault("SMS_BUSINESS_NAME", "SAHJONY")

from app.sms_campaigns import _validate_merge_fields, lead_matches, render_message


def lead(**overrides):
    property_record = SimpleNamespace(
        address="123 Main St", city="Houston", state="TX", zip_code="77021",
        asking_price=95000, arv=220000, mao=116000,
    )
    base = {
        "id": 1,
        "seller_name": "Rosa Diaz",
        "phone": "+17135551212",
        "source": "foreclosure",
        "status": "new",
        "motivation_score": 82,
        "distress_score": 91,
        "timeline_days": 14,
        "property": property_record,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_campaign_template_renders_sahjony_merge_fields():
    body = "Hi {{first_name}}, this is {{company}} about {{property_address}} in {{city}}. Reply STOP to opt out."
    rendered = render_message(body, lead())
    assert rendered == "Hi Rosa, this is SAHJONY about 123 Main St in Houston. Reply STOP to opt out."


def test_money_fields_are_rendered_without_becoming_property_facts():
    rendered = render_message("Ask {{asking_price}} ARV {{arv}} MAO {{mao}}", lead())
    assert rendered == "Ask $95,000 ARV $220,000 MAO $116,000"


def test_unknown_merge_fields_are_rejected():
    assert _validate_merge_fields("Hi {{first_name}} {{secret_field}}") == ["secret_field"]


def test_smart_list_filters_distressed_short_timeline_lead():
    filters = {
        "states": ["TX"],
        "zip_codes": ["77021"],
        "statuses": ["new"],
        "sources": ["foreclosure"],
        "min_motivation": 70,
        "min_distress": 80,
        "max_timeline_days": 30,
        "has_phone": True,
    }
    assert lead_matches(lead(), filters) is True
    assert lead_matches(lead(motivation_score=40), filters) is False
    assert lead_matches(lead(timeline_days=90), filters) is False


def test_missing_phone_never_enters_sendable_audience():
    assert lead_matches(lead(phone=""), {"has_phone": True}) is False
