from app import human_auth


class _Response:
    status_code = 200


def test_resend_password_reset_uses_verified_business_sender(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "test-key")
    monkeypatch.delenv("AUTH_FROM_EMAIL", raising=False)
    captured = {}

    def fake_post(url, *, headers, json, timeout):
        captured.update(json)
        return _Response()

    monkeypatch.setattr(human_auth.httpx, "post", fake_post)

    assert human_auth._send_with_resend("owner@example.com", "123456") is True
    assert captured["from"] == "SAHJONY Security <support@sahjony.com>"
    assert captured["to"] == ["owner@example.com"]
