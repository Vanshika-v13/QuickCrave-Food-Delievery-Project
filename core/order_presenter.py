"""
Order response normalization — preserves exact API JSON shapes (no DB driver).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from core.eta import TOTAL_DELIVERY_MINUTES, calculate_remaining_delivery_time
from core.media import normalize_image_path
from repositories import address_repository, food_repository, order_repository, user_repository
from repositories import rider_repository
logger = logging.getLogger(__name__)


def _iso(val) -> Optional[str]:
    if val is None:
        return None
    if hasattr(val, "isoformat"):
        return val.isoformat()
    return str(val)


def _build_delivery_location(order_info, address_info=None):
    lat = order_info.get("user_lat")
    lng = order_info.get("user_lng")
    if address_info:
        if lat is None and address_info.get("latitude") is not None:
            lat = address_info.get("latitude")
        if lng is None and address_info.get("longitude") is not None:
            lng = address_info.get("longitude")
    out = {
        "latitude": None,
        "longitude": None,
        "address_line": (address_info or {}).get("address_line"),
        "city": (address_info or {}).get("city"),
        "pincode": (address_info or {}).get("pincode"),
    }
    try:
        if lat is not None and lng is not None:
            out["latitude"] = float(lat)
            out["longitude"] = float(lng)
    except (TypeError, ValueError):
        pass
    return out


def _build_rider_location(rider_dict):
    if not rider_dict:
        return None
    lat, lng = rider_dict.get("lat"), rider_dict.get("lng")
    if lat is None or lng is None:
        return None
    try:
        return {"latitude": float(lat), "longitude": float(lng)}
    except (TypeError, ValueError):
        return None


def resolve_order_status(order_id: int) -> Optional[Dict[str, Any]]:
    return order_repository.build_status_object(order_id)


def normalize_order_data(
    order_info: Dict[str, Any],
    items_rows: List[Dict[str, Any]],
    address_info=None,
    is_admin_view: bool = False,
):
    status_obj = resolve_order_status(order_info["order_id"])
    if status_obj is None:
        status_obj = {
            "current_status": "UNKNOWN",
            "last_updated": None,
            "status_history": [],
            "lat": None,
            "lng": None,
        }
    try:
        eta_data = calculate_remaining_delivery_time(order_info)
    except Exception as eta_exc:
        logger.warning(f"[ETA] normalize_order_data fallback order {order_info.get('order_id')}: {eta_exc}")
        from core.eta import FALLBACK_ETA

        eta_data = dict(FALLBACK_ETA)

    delivery_location = _build_delivery_location(order_info, address_info)
    rider_location = _build_rider_location(order_info.get("rider"))

    items_normalized = []
    calculated_subtotal = 0.0
    for item in items_rows:
        unit_price = float(item.get("unit_price") or item.get("price") or 0)
        qty = int(item.get("quantity") or 0)
        line_total = round(unit_price * qty, 2)
        calculated_subtotal += line_total
        raw_image = item.get("food_image")
        items_normalized.append(
            {
                "item_id": item.get("item_id"),
                "name": item.get("name", "Unknown Item"),
                "quantity": qty,
                "unit_price": unit_price,
                "total_price": line_total,
                "image": normalize_image_path(raw_image),
            }
        )

    delivery_fee = 40.0
    total_amount = calculated_subtotal + delivery_fee

    customer_name = (
        order_info.get("customer_name")
        or (address_info.get("name") if address_info else None)
        or "Unknown"
    )
    customer_phone = (
        order_info.get("customer_phone")
        or (address_info.get("phone") if address_info else None)
        or "Unknown"
    )

    accepted_at = _iso(order_info.get("accepted_at"))
    rider_accepted = order_info.get("accepted_at") is not None

    if is_admin_view:
        return {
            "order_id": order_info["order_id"],
            "status": status_obj,
            "accepted_at": accepted_at,
            "rider_accepted": rider_accepted,
            "customer": {
                "name": customer_name,
                "phone": customer_phone,
                "address": {
                    "address_line": address_info["address_line"] if address_info else "Unknown",
                    "city": address_info["city"] if address_info else "Unknown",
                    "pincode": address_info["pincode"] if address_info else "Unknown",
                },
            },
            "items": items_normalized,
            "rider": order_info.get("rider"),
            "payment_method": order_info.get("payment_method", "COD"),
            "total_amount": round(total_amount, 2),
            "created_at": _iso(order_info.get("created_at")),
            "assigned_at": _iso(order_info.get("assigned_at")),
            "version": order_info.get("version", 1),
            "estimated_total_minutes": TOTAL_DELIVERY_MINUTES,
            "remaining_minutes": eta_data["remaining_minutes"],
            "remaining_seconds": eta_data["remaining_seconds"],
            "eta_text": eta_data["eta_text"],
            "delivery_location": delivery_location,
            "rider_location": rider_location,
        }

    return {
        "order_id": order_info["order_id"],
        "id": order_info["order_id"],
        "status": status_obj,
        "payment_method": order_info.get("payment_method", "COD"),
        "customer_name": customer_name,
        "customer_phone": customer_phone,
        "customer": {
            "name": customer_name,
            "phone": customer_phone,
            "address": {
                "address_line": address_info["address_line"] if address_info else "Unknown",
                "city": address_info["city"] if address_info else "Unknown",
                "pincode": address_info["pincode"] if address_info else "Unknown",
            },
        },
        "items": items_normalized,
        "pricing": {
            "subtotal": round(calculated_subtotal, 2),
            "delivery_fee": round(delivery_fee, 2),
            "total": round(total_amount, 2),
        },
        "total_amount": round(total_amount, 2),
        "address": {
            "name": address_info["name"] if address_info else "Unknown",
            "phone": address_info["phone"] if address_info else "Unknown",
            "address_line": address_info["address_line"] if address_info else "Unknown",
            "city": address_info["city"] if address_info else "Unknown",
            "pincode": address_info["pincode"] if address_info else "Unknown",
        },
        "address_line": address_info["address_line"] if address_info else "Unknown",
        "city": address_info["city"] if address_info else "Unknown",
        "pincode": address_info["pincode"] if address_info else "Unknown",
        "delivery_location": delivery_location,
        "rider_location": rider_location,
        "locations": {
            "restaurant": {
                "lat": float(order_info["restaurant_lat"]) if order_info.get("restaurant_lat") else None,
                "lng": float(order_info["restaurant_lng"]) if order_info.get("restaurant_lng") else None,
            },
            "user": {
                "lat": float(order_info["user_lat"]) if order_info.get("user_lat") else None,
                "lng": float(order_info["user_lng"]) if order_info.get("user_lng") else None,
            },
            "driver": {
                "lat": float(status_obj["lat"]) if status_obj and status_obj.get("lat") is not None else None,
                "lng": float(status_obj["lng"]) if status_obj and status_obj.get("lng") is not None else None,
            },
        },
        "created_at": _iso(order_info.get("created_at")),
        "assigned_at": _iso(order_info.get("assigned_at")),
        "version": order_info.get("version", 1),
        "rider_id": order_info.get("rider_id"),
        "rider": order_info.get("rider"),
        "accepted_at": accepted_at,
        "rider_accepted": rider_accepted,
        "order_created_at": _iso(order_info.get("created_at")),
        "estimated_total_minutes": TOTAL_DELIVERY_MINUTES,
        "remaining_minutes": eta_data["remaining_minutes"],
        "remaining_seconds": eta_data["remaining_seconds"],
        "eta_text": eta_data["eta_text"],
    }


def get_order_summary(order_id: int, is_admin_view: bool = False) -> Optional[Dict[str, Any]]:
    order_doc = order_repository.find_by_order_id(order_id)
    if not order_doc:
        return None

    order_info = order_repository.order_doc_to_row(order_doc)
    order_info["accepted_at"] = order_doc.get("accepted_at")
    customer = user_repository.find_by_user_id(order_info["user_id"])
    if customer:
        order_info["customer_name"] = customer.get("name")
        order_info["customer_phone"] = customer.get("phone")

    items = order_repository.build_items_with_food_images(order_doc)
    address_info = None
    if order_info.get("address_id"):
        address_info = address_repository.find_by_address_id(
            order_info["address_id"], order_info["user_id"]
        )

    if order_info.get("rider_id"):
        order_info["rider"] = rider_repository.build_rider_payload_for_order(
            order_info["rider_id"]
        )
    else:
        order_info["rider"] = None

    return normalize_order_data(order_info, items, address_info, is_admin_view=is_admin_view)
