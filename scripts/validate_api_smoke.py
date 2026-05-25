#!/usr/bin/env python3
"""Smoke-test key HTTP endpoints against a running uvicorn instance."""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"


def req(method: str, path: str, body: dict | None = None, token: str | None = None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(f"{BASE}{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(r, timeout=15) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {"raw": raw}
        return e.code, payload


def main() -> int:
    failures = []

    code, health = req("GET", "/api/health")
    if code != 200 or not health.get("success"):
        failures.append(f"health {code}")
    mongo = (health or {}).get("mongodb") or {}
    if not mongo.get("healthy"):
        failures.append(f"mongodb not healthy: {mongo}")

    code, menu = req("GET", "/api/menu")
    items = (menu or {}).get("data") if isinstance(menu, dict) else menu
    if code != 200 or not items:
        failures.append(f"menu {code} items={len(items) if items else 0}")
    else:
        print(f"OK menu: {len(items)} items")

    # Dialogflow webhook smoke (add food by name)
    code, bot = req(
        "POST",
        "/",
        {
            "queryResult": {
                "queryText": "1 pizza",
                "intent": {"displayName": "order.add - context: ongoing-order"},
                "parameters": {"food-item": ["pizza"]},
                "outputContexts": [
                    {"name": "projects/p/agent/sessions/smoke-test-001/contexts/ongoing-order"}
                ],
            }
        },
    )
    if code != 200:
        failures.append(f"chatbot webhook {code}")
    else:
        print("OK chatbot add item")

    print(json.dumps({"failures": failures, "health_mongo": mongo.get("healthy")}, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
