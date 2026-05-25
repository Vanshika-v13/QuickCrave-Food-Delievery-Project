# MongoDB-only cutover (complete)

## Architecture

```
main.py (routes + WebSockets)
  → services/*.py
  → repositories/*.py (PyMongo)
  → MongoDB Atlas
```

## Removed

- `db_helper.py` (MySQL) — deleted
- MySQL fallback in `food_service`
- Runtime dependency on `DB_*` env vars (migration script only)

## Collections

| Collection | Purpose |
|------------|---------|
| `users` | Customers, admins, riders |
| `food_items` | Menu catalog |
| `carts` | One doc per `user_id` with embedded `items[]` |
| `orders` | Order header + embedded `items[]` + `tracking[]` |
| `order_tracking` | Append-only audit trail (mirrors transitions) |
| `rider_locations` | Live GPS per rider |
| `user_addresses` | Delivery addresses |
| `admin_audit_log` | Admin actions |
| `counters` | Numeric ID sequences |

## Before first run

1. Set `MONGODB_URI` and `MONGODB_DATABASE` in `.env` / Render.
2. Migrate data (one-time, requires MySQL still reachable):

```bash
python scripts/migrate_mysql_to_mongodb.py
```

3. Start API:

```bash
uvicorn main:app --reload
```

## Verification checklist

- [ ] `GET /api/menu`
- [ ] Cart add/update/remove
- [ ] Place order + WebSocket tracking
- [ ] Rider accept + location + status
- [ ] Admin stats / orders / assign rider
- [ ] Chatbot add + complete order
- [ ] `grep -r db_helper` → comments/docs only

## Rollback

Git revert only — not reversible without MySQL backup.
