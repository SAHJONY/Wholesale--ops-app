from app.deal_dossier import _json_object


def test_json_object_preserves_object_payloads():
    payload = {"auction_date": "2026-09-01"}
    assert _json_object(payload) is payload


def test_json_object_wraps_legacy_signal_arrays():
    payload = ["pre_foreclosure", "vacant"]
    assert _json_object(payload) == {"signals": payload}


def test_json_object_fails_closed_for_scalar_or_null_payloads():
    assert _json_object(None) == {}
    assert _json_object("legacy") == {}
