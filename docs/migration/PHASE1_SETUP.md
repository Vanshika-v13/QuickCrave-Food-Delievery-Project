# Phase 1 — Safe MongoDB setup (completed)

## What changed

| File | Change |
|------|--------|
| `mongodb_helper.py` | New Motor-based async connection manager, health ping, graceful close |
| `main.py` | Startup/shutdown hooks initialize MongoDB alongside MySQL; health endpoints report MongoDB status |
| `requirements.txt` | Added `motor` and `pymongo` (MySQL deps unchanged) |
| `.env.example` | Documented `MONGODB_URI` and `MONGODB_DATABASE` |
| `db_helper.py` | **Untouched** — MySQL remains source of truth |

## Why it is safe

- MongoDB is **optional**: if `MONGODB_URI` is unset, the app behaves exactly as before (MySQL only).
- Connection failures **do not block** `app_state["ready"]` — same pattern as Redis degraded mode.
- No API routes, request bodies, or WebSocket events were modified.
- `db_helper.init_db()` still runs on import; all existing endpoints still use MySQL.

## What could break

| Risk | Mitigation |
|------|------------|
| Missing `motor` on Render | Add `requirements.txt` to build; `pip install -r requirements.txt` |
| Invalid Atlas URI | Logged warning only; MySQL continues |
| Slightly slower startup | 5s max server selection timeout; ping once at startup |

## Rollback

1. Remove `MONGODB_URI` from Render environment → instant MySQL-only mode.
2. Revert git commits for `mongodb_helper.py` and `main.py` startup/health changes.
3. No data migration occurred; no Atlas data required for rollback.

## How to verify

### Local (MySQL only — regression)

```bash
# Ensure MONGODB_URI is NOT set in .env
uvicorn main:app --reload
curl http://localhost:8000/api/health
# Expect: success true, mongodb.configured false
```

### Local (dual connection)

```bash
# Set in .env:
# MONGODB_URI=mongodb+srv://...
# MONGODB_DATABASE=food_delivery
pip install motor pymongo
uvicorn main:app --reload
curl http://localhost:8000/api/health
# Expect: mongodb.configured true, mongodb.healthy true
```

### Render

1. Add env vars: `MONGODB_URI`, `MONGODB_DATABASE`.
2. Deploy; check logs for `[MONGODB] Connected` or `[MONGODB] Not configured`.
3. Hit `https://<your-api>/api/health`.

### Frontend smoke (unchanged)

- Login, menu, cart, checkout, track order, rider/admin dashboards — all should work with or without MongoDB configured.

## Render environment variables

```
MONGODB_URI=<Atlas SRV connection string>
MONGODB_DATABASE=food_delivery
```

Keep all existing `DB_*` variables until Phase 9 cutover.
