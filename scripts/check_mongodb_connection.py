#!/usr/bin/env python3
"""Verify MONGODB_URI is set, has no placeholders, and Atlas ping succeeds."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

uri = (os.getenv("MONGODB_URI") or "").strip()
db_name = (os.getenv("MONGODB_DATABASE") or "food_delivery").strip()

if not uri:
    print("FAIL: MONGODB_URI is not set")
    sys.exit(1)
if "<" in uri or ">" in uri:
    print("FAIL: MONGODB_URI still contains <placeholders> — update .env after Atlas password rotation")
    sys.exit(1)

from repositories.mongo_client import get_client, get_database, MONGODB_DATABASE

try:
    get_client()
    db = get_database()
    names = sorted(db.list_collection_names())
    print(f"OK: connected to database={MONGODB_DATABASE} collections={len(names)}")
    sys.exit(0)
except Exception as e:
    print(f"FAIL: {type(e).__name__}: {e}")
    sys.exit(1)
