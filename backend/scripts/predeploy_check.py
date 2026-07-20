from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]


def run(label: str, command: list[str], *, allow_failure: bool = False) -> bool:
    print(f"\n== {label} ==")
    result = subprocess.run(command, cwd=BACKEND_DIR, env=os.environ.copy())
    if result.returncode == 0:
        print(f"PASS: {label}")
        return True
    print(f"FAIL: {label} (exit {result.returncode})")
    if not allow_failure:
        raise SystemExit(result.returncode)
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the backend before production deployment.")
    parser.add_argument("--skip-tests", action="store_true", help="Skip the pytest suite.")
    parser.add_argument(
        "--code-only",
        action="store_true",
        help="Run code checks without requiring a reachable production database.",
    )
    args = parser.parse_args()

    run("Compile backend", [sys.executable, "-m", "compileall", "-q", "app", "api", "tests", "scripts", "migrations"])
    run("Verify one Alembic head", [sys.executable, "-m", "alembic", "heads"])

    if not args.skip_tests:
        run("Backend tests", [sys.executable, "-m", "pytest", "-q"])

    if args.code_only:
        print("\nCode-only validation completed. Database migration and release gates were skipped.")
        return 0

    if not os.getenv("DATABASE_URL"):
        print("\nFAIL: DATABASE_URL is required for production migration and release checks.")
        return 2

    run("Migration guard", [sys.executable, "scripts/migration_guard.py", "--json"])
    run("Release gate", [sys.executable, "scripts/release_gate.py"])
    print("\nPREDEPLOY READY")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
