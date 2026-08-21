from app.phone_os_automation import _phone_schema_not_ready


def test_phone_schema_not_ready_detects_missing_voice_calls_table():
    exc = Exception('psycopg.errors.UndefinedTable: relation "voice_calls" does not exist')
    assert _phone_schema_not_ready(exc) is True


def test_phone_schema_not_ready_does_not_mask_unrelated_programming_errors():
    assert _phone_schema_not_ready(Exception('column foo does not exist')) is False
