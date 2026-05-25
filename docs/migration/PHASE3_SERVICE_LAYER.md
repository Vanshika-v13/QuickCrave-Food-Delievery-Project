# Phase 3 — Service layer abstraction

## What changed

- Added `services/` package with domain modules delegating to `db_helper` (MySQL).
- `main.py` route handlers and WebSocket helpers call services instead of `db_helper` directly (except startup `get_db_connection()`).
- Order status transition helpers moved to `services/order_lifecycle.py` (same logic as before).
- Chatbot `save_to_db` logic moved to `services/chatbot_service.place_order_from_session_cart`.
- Root `order_service.py` re-exports `OrderService` for backward compatibility.

## Why it is safe

- Every service method is a thin delegate or copied orchestration with identical rules.
- No MongoDB reads/writes in services (except existing health in `mongodb_helper`).
- API paths, JSON shapes, JWT, WebSocket events, and Dialogflow webhook unchanged.

## What could break

- Import/circular dependency errors at startup.
- Subtle copy-paste drift in moved orchestration (admin/rider status updates).

## Rollback

Revert `services/` and `main.py` service imports; restore direct `db_helper` calls. Keep `db_helper.py` untouched.

## Verification

1. `python -c "import main"` — no import errors.
2. Customer: signup, login, menu, cart, place order, track, delete placed order.
3. Rider: login, available orders, accept, location update, status updates.
4. Admin: stats, orders, assign rider, status updates.
5. Chatbot: add item, complete order, track order.
6. WebSocket: `/ws/track/{id}`, `/ws/rider`, `/ws/admin`.
7. Compare `/api/health` and a sample order JSON before/after (should match).
