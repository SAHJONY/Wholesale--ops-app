import importlib.util
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[2] / "scripts/extract_neon_uri.py"
SPEC = importlib.util.spec_from_file_location("extract_neon_uri", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("psql 'postgresql://user:pass@host.neon.tech/db?sslmode=require'", "postgresql://user:pass@host.neon.tech/db?sslmode=require"),
        ("DATABASE_URL=postgresql://user:pass@host.neon.tech/db", "postgresql://user:pass@host.neon.tech/db"),
        ('export DATABASE_URL="postgresql://user:pass@host.neon.tech/db"', "postgresql://user:pass@host.neon.tech/db"),
        ("postgres://user:pass@host.neon.tech/db", "postgres://user:pass@host.neon.tech/db"),
    ],
)
def test_extract_postgres_uri(source, expected):
    assert MODULE.extract_postgres_uri(source) == expected


def test_rejects_non_uri_text():
    with pytest.raises(ValueError):
        MODULE.extract_postgres_uri("DATABASE_URL is missing")
