import re
import os

with open("c:\\Food Chatbot\\main.py", "r", encoding="utf-8") as f:
    content = f.read()

# 1. Update routing inside webhook
webhook_routing = """    # =====================================================================
    # PIPELINE STEP 4: Route to ONE handler — cart logic lives ONLY inside
    # each handler function below. Nothing after this point runs.
    # =====================================================================
    logger.info(f"[CHATBOT][INTENT] intent={intent}")
    
    print("INTENT:", intent)
    print("SESSION:", session_id)
    print("PAYLOAD:", payload)
    
    if intent == "order.add":
        handler = add_to_order
    elif intent == "order.remove":
        handler = remove_from_order
    elif intent == "order.complete":
        handler = complete_order
    else:
        INTENT_HANDLER_MAP = {
            'Default Welcome Intent': greeting_handler,
            'Default Fallback Intent': fallback_handler,
            'order.start': new_order_handler,
            'new.order': new_order_handler,
            'order.add - context: ongoing-order': add_to_order,
            'order.remove - context: ongoing-order': remove_from_order,
            'order.complete - context: ongoing-order': complete_order,
            'track-order - context: ongoing-tracking': track_order,
            'track.order': track_order,
            'order.cancel': cancel_order_handler,
        }
        handler = INTENT_HANDLER_MAP.get(intent)
        if handler is None:
            return fallback_handler(parameters, session_id)
"""

content = re.sub(
    r"    logger\.info\(f\"\[CHATBOT\]\[INTENT\] intent=\{intent\}\"\).*?INTENT_HANDLER_MAP\.get\(intent\)\n        if handler is None:.*?(?=    logger\.info\(f\"\[CHATBOT\]\[PIPELINE\])",
    webhook_routing,
    content,
    flags=re.DOTALL
)

# 2. Redis cart helpers
redis_helpers = """
import json
from services.redis_service import get_cache, set_cache, delete_cache

def _get_cart(session_id):
    data = get_cache(f"cart:{session_id}")
    if data:
        try:
            return json.loads(data)
        except:
            pass
    return {"items": []}

def _set_cart(session_id, cart):
    set_cache(f"cart:{session_id}", json.dumps(cart), ttl=86400)
    print("CART:", cart)

def _delete_cart(session_id):
    delete_cache(f"cart:{session_id}")

"""

if "def _get_cart" not in content:
    content = content.replace("# --- Dialogflow Handlers ---", redis_helpers + "\n# --- Dialogflow Handlers ---")

# 3. Add to order
add_to_order_new = """def add_to_order(parameters, session_id):
    try:
        sid = _chatbot_session_key(session_id)
        cart = _get_cart(sid)
        query_text = parameters.get("_query_text", "")

        foods = _chatbot_detect_all_foods_in_text(query_text)
        if not foods:
            foods = _chatbot_extract_food_names(parameters)
        if not foods:
            detected = _chatbot_detect_food_in_text(query_text)
            if detected:
                foods = [detected]

        if not foods:
            return JSONResponse(content={"fulfillmentText": "Please specify a food item."})

        added_items = []
        for food in foods:
            row = chatbot_service.get_food_item_by_name(food)
            if not row:
                continue
            canonical = row["name"]
            iid = row["item_id"]
            price = float(row["price"])
            
            qty = _chatbot_find_remove_qty_in_text(query_text, _food_name_regex_pattern(canonical))
            if qty is None:
                qty = _chatbot_find_remove_qty_in_text(query_text, _food_name_regex_pattern(food))
            if qty is None and _has_explicit_quantity(parameters, query_text):
                qty = _chatbot_extract_quantity(parameters)
            
            qty = max(1, int(qty)) if qty is not None else 1
            
            existing = next((item for item in cart["items"] if item["item"] == canonical), None)
            if existing:
                existing["qty"] += qty
            else:
                cart["items"].append({"item": canonical, "qty": qty, "item_id": iid, "price": price})

        _set_cart(sid, cart)

        summary_lines = [f"- {item['qty']} {item['item']}" for item in cart["items"]]
        summary = "\\n".join(summary_lines)
        return JSONResponse(content={"fulfillmentText": f"So far you have:\\n{summary}\\nAnything else?"})
    except Exception as e:
        logger.exception("[CHATBOT] add_to_order")
        return JSONResponse(content={"fulfillmentText": "Something went wrong updating your order."})
"""

content = re.sub(r"def add_to_order\(parameters, session_id\):.*?(?=def remove_from_order)", add_to_order_new + "\n", content, flags=re.DOTALL)

# 4. Remove from order
remove_from_order_new = """def remove_from_order(parameters, session_id):
    try:
        sid = _chatbot_session_key(session_id)
        cart = _get_cart(sid)
        if not cart["items"]:
            return JSONResponse(content={"fulfillmentText": "Your order is empty."})

        query_text = parameters.get("_query_text", "")
        foods = _chatbot_detect_all_foods_in_text(query_text)
        if not foods:
            foods = _chatbot_extract_food_names(parameters)
        if not foods:
            detected = _chatbot_detect_food_in_text(query_text)
            if detected:
                foods = [detected]

        if not foods:
            return JSONResponse(content={"fulfillmentText": "I did not catch which dish to remove."})

        removed_any = False
        for food in foods:
            row = chatbot_service.get_food_item_by_name(food)
            canonical = row["name"] if row else food.strip()
            
            existing = next((item for item in cart["items"] if item["item"] == canonical), None)
            if not existing:
                return JSONResponse(content={"fulfillmentText": f"Item not in cart"})
                
            qty_remove = _chatbot_explicit_remove_qty_for_food(query_text, canonical)
            if qty_remove is None:
                cart["items"] = [item for item in cart["items"] if item["item"] != canonical]
            else:
                existing["qty"] -= qty_remove
                if existing["qty"] <= 0:
                    cart["items"] = [item for item in cart["items"] if item["item"] != canonical]

        _set_cart(sid, cart)

        summary_lines = [f"- {item['qty']} {item['item']}" for item in cart["items"]]
        if summary_lines:
            summary = "\\n".join(summary_lines)
            return JSONResponse(content={"fulfillmentText": f"Updated cart:\\n{summary}"})
        else:
            return JSONResponse(content={"fulfillmentText": "Your cart is now empty."})
            
    except Exception:
        logger.exception("[CHATBOT] remove_from_order")
        return JSONResponse(content={"fulfillmentText": "Something went wrong updating your order."})
"""

content = re.sub(r"def remove_from_order\(parameters, session_id\):.*?(?=async def _chatbot_push_order_update_safe)", remove_from_order_new + "\n", content, flags=re.DOTALL)

# 5. Complete order
complete_order_new = """async def complete_order(parameters, session_id):
    try:
        sid = _chatbot_session_key(session_id)
        cart = _get_cart(sid)
        
        if not cart["items"]:
            return JSONResponse(content={"fulfillmentText": "Your order is empty"})

        user_id, login_err = _chatbot_user_from_context(parameters.get("_chatbot_user_id"), session_id, parameters)
        if login_err:
            user_id = 1  # Fallback to test user if strictly needed by save_to_db

        session_cart_format = {}
        total = 0
        for item in cart["items"]:
            iid = item["item_id"]
            session_cart_format[iid] = {
                "item_id": iid,
                "name": item["item"],
                "quantity": item["qty"],
                "price": float(item["price"])
            }
            total += item["qty"] * item["price"]

        order_id, err = save_to_db(session_cart_format, user_id)
        if err or not order_id:
            return JSONResponse(content={"fulfillmentText": "Sorry, I couldn't place your order right now."})

        _delete_cart(sid)

        text = f"Order placed successfully. Your Order ID is ORD{order_id}. Total amount is ₹{int(total)}."

        return JSONResponse(content={
            "fulfillmentText": text,
            "fulfillmentMessages": [
                {
                    "text": {
                        "text": [text]
                    }
                }
            ],
            "orderId": f"ORD{order_id}",
            "total": int(total),
            "success": True
        })

    except Exception as e:
        logger.exception("[CHATBOT] complete_order")
        return JSONResponse(content={"fulfillmentText": "Something went wrong completing your order."})
"""

content = re.sub(r"async def complete_order\(parameters, session_id\):.*?(?=def track_order)", complete_order_new + "\n", content, flags=re.DOTALL)

with open("c:\\Food Chatbot\\main.py", "w", encoding="utf-8") as f:
    f.write(content)

print("Update completed.")
