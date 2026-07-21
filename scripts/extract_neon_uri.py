#!/usr/bin/env python3
"""Read copied Neon connection text and print only its PostgreSQL URI."""

from __future__ import annotations

import re
import subprocess
import sys
from urllib.parse import urlsplit

URI_PATTERN = re.compile(r"postgres(?:ql)?://[^\s'\"`]+", re.IGNORECASE)


def extract_postgres_uri(text: str) -> str:
    match = URI_PATTERN.search(text)
    if not match:
        raise ValueError("No PostgreSQL URI found in input")

    uri = match.group(0).rstrip(";,)")
    parsed = urlsplit(uri)
    if parsed.scheme.lower() not in {"postgres", "postgresql"}:
        raise ValueError("Unsupported database URI scheme")
    if not parsed.hostname or not parsed.path.lstrip("/"):
        raise ValueError("PostgreSQL URI must include a host and database")
    return uri


def main() -> int:
    source = sys.stdin.read()
    if not source and sys.platform == "darwin":
        source = subprocess.run(["pbpaste"], check=True, capture_output=True, text=True).stdout
    try:
        print(extract_postgres_uri(source))
    except ValueError as exc:
        print(f"extract_neon_uri: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
