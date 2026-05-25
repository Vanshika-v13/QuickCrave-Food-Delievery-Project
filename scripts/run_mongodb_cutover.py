#!/usr/bin/env python3
"""
Run full MongoDB cutover: connect → migrate → validate.

Prerequisites:
  - .env has real MONGODB_URI (no <placeholders>)
  - MySQL DB_* vars set for migration source
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(cmd: list[str]) -> int:
    print(f"\n>>> {' '.join(cmd)}")
    return subprocess.call(cmd, cwd=ROOT)


def main() -> int:
    steps = [
        [sys.executable, "scripts/check_mongodb_connection.py"],
        [sys.executable, "scripts/migrate_mysql_to_mongodb.py"],
        [sys.executable, "scripts/validate_mongodb_consistency.py"],
    ]
    for cmd in steps:
        code = run(cmd)
        if code != 0:
            print(f"\n[CUTOVER] Stopped — exit code {code}")
            return code
    print("\n[CUTOVER] Migration and consistency checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
