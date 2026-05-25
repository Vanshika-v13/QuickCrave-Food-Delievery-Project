# Phase 4 — food_items → MongoDB Atlas

## What changed

| File | Purpose |
|------|---------|
| `repositories/food_repository.py` | MongoDB-only food_items access (sync PyMongo) |
| `services/food_service.py` | MongoDB primary + MySQL fallback |
| `scripts/migrate_food_items_to_mongo.py` | Idempotent MySQL → MongoDB data copy |
| `.env.example` | `MONGODB_FOOD_ENABLED` rollback flag |

## Rollback (instant)

```env
MONGODB_FOOD_ENABLED=false
```

Or unset `MONGODB_URI` — service falls back to MySQL automatically.

## Migrate data (one-time, safe re-run)

```bash
python scripts/migrate_food_items_to_mongo.py
```

## Verify

1. `uvicorn main:app --reload`
2. `GET /api/menu` — same JSON shape
3. Chatbot: order by food name
4. Cart add — still uses MySQL `item_id` FK until cart phase
5. Fallback test: `MONGODB_FOOD_ENABLED=false` → menu still loads

## Logs

- `[MONGO_FOOD] Loaded from MongoDB (N items)`
- `[MONGO_FOOD] Falling back to MySQL (...)` 
- `[MONGO_FOOD] Migrated N items` (migration script)
