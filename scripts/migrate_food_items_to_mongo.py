#!/usr/bin/env python3
"""Migrate food_items only — delegates to full migration script."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

if __name__ == "__main__":
    from scripts.migrate_mysql_to_mongodb import main

    raise SystemExit(main())
