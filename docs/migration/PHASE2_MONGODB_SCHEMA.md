# Phase 2 — MongoDB collection architecture (design only)

**Status:** Design document. No runtime behavior changes until Phase 4 module migration.

**Goal:** Mirror current MySQL semantics while keeping API JSON shapes identical for the React frontend.

---

## SQL → MongoDB mapping

| MySQL table | MongoDB collection | Notes |
|-------------|-------------------|--------|
| `users` | `users` | Riders/admins/customers in one collection; `roles` array preserved |
| `food_items` | `food_items` | Use `item_id` as business key (`_id` can equal `item_id` or store both) |
| `cart` | `carts` | **One doc per user** with embedded `items[]` (recommended) OR mirror row-per-line |
| `orders` | `orders` | Header doc; embed or reference line items |
| `order_items` | `order_items` OR embedded in `orders.items` | Prefer **embedded items** on order doc for atomic reads; keep separate collection if admin reporting needs it |
| `user_addresses` | `user_addresses` | `user_id` indexed; one-default constraint via partial unique index |
| `users` (role=rider) | `riders` | **Optional** denormalized rider profile; can stay in `users` until rider module migrates |
| `orders.rider_id` + assignment flow | `rider_assignments` | Audit trail: `{ order_id, rider_id, assigned_at, actor, status }` |
| (in-memory / Redis today) | `chatbot_sessions` | Persist Dialogflow `session_id`, cart snapshot, linked `user_id`, TTL |
| (future / optional) | `notifications` | Push/in-app notifications if added later |
| (Redis + WS rooms today) | `websocket_sessions` | Optional persistence for cross-worker room state on Render |

**Not in MySQL today:** `chatbot_sessions`, `notifications`, `websocket_sessions` are logical collections for migration completeness; implement when those modules move off Redis/memory.

---

## Document shapes (API-compatible fields)

### `users`

```json
{
  "_id": 1,
  "legacy_mysql_id": 1,
  "name": "string",
  "email": "string",
  "password": "hashed|null",
  "google_id": "string|null",
  "profile_pic": "string|null",
  "roles": ["customer"],
  "role": "customer",
  "is_active": 1,
  "phone": "string|null",
  "vehicle_type": "string|null",
  "license_number": "string|null",
  "rider_status": "offline|available|busy",
  "created_at": "ISODate",
  "updated_at": "ISODate"
}
```

**Indexes:** `email` (unique), `roles`, compound `(role, rider_status, is_active)` for rider queries.

### `food_items`

```json
{
  "_id": 101,
  "item_id": 101,
  "name": "string",
  "price": "Decimal128",
  "description": "string",
  "image_url": "string",
  "rating": 4.5,
  "tag": "string"
}
```

**Indexes:** `item_id` (unique), `name` (for chatbot name lookup).

### `carts` (recommended: one document per user)

```json
{
  "_id": "user:42",
  "user_id": 42,
  "items": [
    { "item_id": 101, "quantity": 2, "updated_at": "ISODate" }
  ],
  "updated_at": "ISODate"
}
```

**Indexes:** `user_id` (unique).

### `orders`

```json
{
  "_id": 5001,
  "order_id": 5001,
  "user_id": 42,
  "address_id": 7,
  "subtotal": "Decimal128",
  "delivery_fee": "Decimal128",
  "total_amount": "Decimal128",
  "address": "snapshot text",
  "payment_method": "COD",
  "payment_status": "PENDING",
  "status": "ORDER_PLACED",
  "rider_id": null,
  "restaurant_lat": 0.0,
  "restaurant_lng": 0.0,
  "user_lat": 0.0,
  "user_lng": 0.0,
  "version": 1,
  "items": [
    { "item_id": 101, "quantity": 2, "price": "Decimal128", "total_price": "Decimal128" }
  ],
  "tracking": [
    { "status": "ORDER_PLACED", "actor": "SYSTEM", "lat": null, "lng": null, "created_at": "ISODate" }
  ],
  "created_at": "ISODate",
  "updated_at": "ISODate",
  "assigned_at": null,
  "accepted_at": null,
  "picked_up_at": null,
  "delivered_at": null,
  "estimated_delivery_time": null
}
```

**Indexes:** `order_id` (unique), `user_id`, `rider_id`, `status`, `created_at`.

**Concurrency:** Use `find_one_and_update` with `version` field for optimistic locking (matches existing `orders.version` column).

### `user_addresses`

```json
{
  "_id": 7,
  "address_id": 7,
  "user_id": 42,
  "name": "string",
  "phone": "string",
  "address_line": "string",
  "city": "string",
  "state": "string",
  "pincode": "string",
  "is_default": false,
  "latitude": null,
  "longitude": null,
  "created_at": "ISODate"
}
```

**Indexes:** `user_id`, partial unique index for one `is_default: true` per `user_id`.

### `rider_locations` → embed or `rider_locations` collection

```json
{
  "_id": 99,
  "rider_id": 99,
  "lat": 28.6,
  "lng": 77.2,
  "heading": 0,
  "speed": 0,
  "updated_at": "ISODate"
}
```

### `admin_audit_log` → `admin_audit_logs`

Preserve admin action history for compliance.

---

## ID strategy (Phase 5 data migration)

1. Preserve numeric `user_id`, `order_id`, `item_id`, `address_id` in documents for frontend URLs and JWT payloads.
2. Use the same integer as MongoDB `_id` where possible to minimize mapping layers.
3. Maintain `legacy_mysql_id` only if `_id` must be ObjectId for new records after cutover.

---

## Query patterns

| Operation | Pattern |
|-----------|---------|
| Login | `users.find_one({ email })` |
| Menu | `food_items.find({}).sort("item_id")` |
| Cart | `carts.find_one_and_update({ user_id }, ...)` |
| Place order | **Transaction** (multi-doc) or single embedded order doc |
| Track order | `orders.find_one({ order_id })` + ETA from `order_states` / `db_helper.calculate_remaining_delivery_time` |
| Rider pool | `users.find({ roles: "rider", rider_status: "available", is_active: 1 })` |
| WS broadcast | No change to event names; service layer reads from MongoDB then broadcasts |

---

## Rollback (Phase 2 design only)

No production impact. If implementation of indexes/collections is wrong, delete empty Atlas collections and re-run Phase 5 scripts — MySQL remains untouched until cutover.

---

## Next step (Phase 3)

Introduce `services/` package; route handlers call services; services delegate to `db_helper` (MySQL) first, then swap internals per module in Phase 4.
