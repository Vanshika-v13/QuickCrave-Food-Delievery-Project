#!/usr/bin/env python3
"""
Offline resilience checks (no live MongoDB required).
Verifies global handlers and mongo_client failure modes.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def test_mongo_uri_required() -> bool:
    from repositories import mongo_client

    mongo_client._client = None
    mongo_client._db = None
    with patch.dict(os.environ, {"MONGODB_URI": ""}, clear=False):
        try:
            mongo_client.get_client()
            return False
        except RuntimeError as e:
            return "MONGODB_URI is required" in str(e)
    return False


async def test_health_without_mongo() -> bool:
    from mongodb_helper import check_mongodb_health

    with patch.dict(os.environ, {"MONGODB_URI": ""}, clear=False):
        status = await check_mongodb_health()
    return status.get("configured") is False and status.get("healthy") is None


async def test_warmup_middleware() -> bool:
    from httpx import ASGITransport, AsyncClient

    import main

    main.app_state["ready"] = False
    transport = ASGITransport(app=main.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/menu")
        h = await client.get("/api/health")
    # /api/menu is allowed during warmup (degraded menu path)
    return r.status_code == 200 and h.status_code == 200


async def test_global_exception_handler() -> bool:
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    import main

    probe = FastAPI()

    @probe.get("/boom")
    async def boom():
        raise ValueError("probe")

    probe.add_exception_handler(Exception, main.global_exception_handler)
    transport = ASGITransport(app=probe, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/boom")
    body = r.json()
    return r.status_code == 500 and body.get("success") is False


def test_no_db_helper_module() -> bool:
    try:
        import db_helper  # noqa: F401
        return False
    except ModuleNotFoundError:
        return True


def main() -> int:
    results = {
        "mongo_uri_required": test_mongo_uri_required(),
        "health_without_mongo": asyncio.run(test_health_without_mongo()),
        "warmup_503": asyncio.run(test_warmup_middleware()),
        "global_500_handler": asyncio.run(test_global_exception_handler()),
        "db_helper_absent": test_no_db_helper_module(),
    }
    print(results)
    ok = all(results.values())
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
