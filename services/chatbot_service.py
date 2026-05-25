"""
Dialogflow chatbot data access — MongoDB via services (Phase 3+).

Session cart state (inprogress_orders) remains in main.py until Phase 7 migration.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

from services import address_service, food_service, order_service

logger = logging.getLogger(__name__)


def get_food_item_by_name(name: str):
    return food_service.get_food_item_by_name(name)


def get_chatbot_delivery_address(user_id: int):
    return address_service.get_chatbot_delivery_address(user_id)


def get_order_status_for_user(order_id: int, user_id: int):
    return order_service.get_order_status_for_user(order_id, user_id)


def place_order_from_session_cart(
    user_id: int,
    session_cart: Dict[str, Any],
    restaurant_lat: float,
    restaurant_lng: float,
) -> Tuple[Optional[int], Optional[str]]:
    """
    Create a production order from chatbot in-memory cart.
    Returns (order_id, error_message). error_message is None on success.
    """
    try:
        if not session_cart:
            return None, "Your order is empty. Add some items before completing."

        addr = get_chatbot_delivery_address(user_id)
        if not addr or not addr.get("id"):
            return None, "Please add a delivery address before placing an order."

        items_payload = [
            {"item_id": it["item_id"], "quantity": it["quantity"]}
            for it in session_cart.values()
        ]
        if not items_payload:
            return None, "Your order is empty."

        order_id = order_service.place_order_in_db(
            user_id,
            addr["id"],
            items=items_payload,
            payment_method="COD",
            restaurant_lat=restaurant_lat,
            restaurant_lng=restaurant_lng,
            clear_cart=False,
        )
        if not order_id:
            return None, "We could not save your order. Please try again."

        order_service.insert_order_tracking(order_id, "ORDER_PLACED")
        return order_id, None

    except Exception as e:
        logger.exception("[CHATBOT] place_order_from_session_cart failed")
        msg = str(e)
        if "DELIVERY_COORDS_INVALID" in msg:
            return (
                None,
                "Your saved delivery address needs valid map coordinates before we can place an order. Please update it on the website.",
            )
        if "not found" in msg.lower() and "address" in msg.lower():
            return None, "Please add a delivery address before placing an order."
        return None, "Something went wrong while saving your order. Please try again later."
