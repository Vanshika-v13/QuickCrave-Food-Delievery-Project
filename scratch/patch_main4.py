import re
import sys

def patch_file(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # Define the exact new webhook and handlers block
    new_handlers_code = """
# --- Dialogflow Handlers ---

def greeting_handler(parameters, session_id):
    return JSONResponse(
        content={"fulfillmentText": "Hi! You can say 'New Order' or 'Track Order'."}
    )

def fallback_handler(parameters, session_id):
    return JSONResponse(
        content={
            "fulfillmentText": "If you're adding items, say like '2 pizza' or '1 vada pav'."
        }
    )

def new_order_handler(parameters, session_id):
    sid = _chatbot_session_key(session_id)
    _delete_cart(sid)
    text = (
        "Great 👍 Let’s start your order.\\n"
        "You can say like 1 pizza, 2 vada pav, 3 mango lassi, or multiple items together."
    )
    return JSONResponse(content={
        "fulfillmentText": text,
        "outputContexts": [
            {
                "name": f"{session_id}/contexts/ongoing-order",
                "lifespanCount": 10
            }
        ]
    })

def add_to_order(parameters, session_id):
    try:
        sid = _chatbot_session_key(session_id)
        cart = _get_cart(sid)
        
        foods = _chatbot_extract_food_names(parameters)
        if not foods:
            return JSONResponse(content={"fulfillmentText": "Please specify a food item."})
            
        quantities = _chatbot_extract_quantities(parameters)
        
        if len(quantities) < len(foods):
            canonical_names = []
            for food in foods:
                row = chatbot_service.get_food_item_by_name(food)
                canonical = row["name"] if row else food
                canonical_names.append(canonical)
            
            return JSONResponse(content={"fulfillmentText": f"Please specify quantity for {canonical_names[0]}.\\nExample: 1 {canonical_names[0]} or 2 {canonical_names[0]}."})
            
        added_msgs = []
        for food, qty in zip(foods, quantities):
            row = chatbot_service.get_food_item_by_name(food)
            if not row:
                continue
            canonical = row["name"]
            iid = row["item_id"]
            price = float(row["price"])
            
            qty = max(1, int(qty))
            iid_str = str(iid)
            
            if iid_str in cart:
                cart[iid_str]["quantity"] += qty
            else:
                cart[iid_str] = {"item_id": iid, "name": canonical, "quantity": qty, "price": price}
                
            added_msgs.append(f"{canonical} ×{qty}")
            
        if not added_msgs:
            return JSONResponse(content={"fulfillmentText": "I couldn't find that item on the menu."})
            
        _set_cart(sid, cart)
        
        if len(added_msgs) == 1:
            added_text = added_msgs[0]
            return JSONResponse(content={"fulfillmentText": f"So far you have added {added_text.replace(' ×', ' ')}. Anything else?"})
        else:
            added_text = ", ".join(added_msgs)
            return JSONResponse(content={"fulfillmentText": f"Got it 👍 Your order includes:\\n{added_text}\\nAnything else?"})
            
    except Exception as e:
        logger.exception("[CHATBOT] add_to_order")
        return JSONResponse(content={"fulfillmentText": "Something went wrong updating your order."})

def remove_from_order(parameters, session_id):
    try:
        sid = _chatbot_session_key(session_id)
        cart = _get_cart(sid)
        if not cart:
            return JSONResponse(content={"fulfillmentText": "Your cart is currently empty."})
            
        foods = _chatbot_extract_food_names(parameters)
        if not foods:
            return JSONResponse(content={"fulfillmentText": "I did not catch which dish to remove."})
            
        quantities = _chatbot_extract_quantities(parameters)
        
        removed_msgs = []
        for i, food in enumerate(foods):
            row = chatbot_service.get_food_item_by_name(food)
            canonical = row["name"] if row else food.strip()
            
            existing_key = next((k for k, v in cart.items() if v["name"] == canonical), None)
            if not existing_key:
                return JSONResponse(content={"fulfillmentText": "That item is not in your order."})
                
            qty_remove = quantities[i] if i < len(quantities) else None
            
            if qty_remove is None:
                del cart[existing_key]
                removed_msgs.append(f"{canonical} removed completely")
            else:
                cart[existing_key]["quantity"] -= qty_remove
                if cart[existing_key]["quantity"] <= 0:
                    del cart[existing_key]
                    removed_msgs.append(f"{canonical} removed completely")
                else:
                    removed_msgs.append(f"Removed {qty_remove} {canonical}")
                    
        _set_cart(sid, cart)
        
        removed_text = ".\\n".join(removed_msgs) + "."
        if not cart:
            summary = "Your cart is currently empty."
        else:
            summary_lines = [f"{item['name']} ({item['quantity']})" for item in cart.values()]
            summary = ", ".join(summary_lines)
            
        return JSONResponse(content={"fulfillmentText": f"{removed_text}\\nRemaining order: {summary}"})
            
    except Exception:
        logger.exception("[CHATBOT] remove_from_order")
        return JSONResponse(content={"fulfillmentText": "Something went wrong updating your order."})

async def _chatbot_push_order_update_safe(order_id: int) -> None:
    try:
        await ecosystem_socket_manager.push_order_update(order_id)
    except Exception as ws_err:
        logger.warning(
            f"[CHATBOT] push_order_update non-critical failure for order_id={order_id}: {ws_err}"
        )

async def complete_order(parameters, session_id):
    try:
        sid = _chatbot_session_key(session_id)
        cart = _get_cart(sid)
        
        if not cart:
            return JSONResponse(content={"fulfillmentText": "Your cart is currently empty."})

        mapped_user = _read_session_mapped_user_id(sid, allow_fuzzy=True)
        user_id = mapped_user if mapped_user else 1

        total = 0
        summary_lines = []
        for item in cart.values():
            total += item["quantity"] * float(item["price"])
            summary_lines.append(f"{item['name']} ×{item['quantity']}")

        order_id, err = save_to_db(cart, user_id)
        if err or not order_id:
            return JSONResponse(content={"fulfillmentText": "Sorry, I couldn't place your order right now."})

        _delete_cart(sid)
        
        items_str = ", ".join(summary_lines)

        text = (
            "🎉 Order placed successfully!\\n"
            f"Your order is:\\n{items_str}\\n"
            f"Total Amount: ₹{int(total)}\\n"
            f"Order ID: #{order_id}\\n"
            "Status: PACKING\\n"
            "You can track your order using this ID."
        )

        return JSONResponse(content={
            "fulfillmentText": text,
            "fulfillmentMessages": [{"text": {"text": [text]}}],
            "orderId": f"#{order_id}",
            "total": int(total),
            "success": True
        })
    except Exception as e:
        logger.exception("[CHATBOT] complete_order")
        return JSONResponse(content={"fulfillmentText": "Something went wrong completing your order."})

def track_order(parameters, session_id):
    try:
        sid = _chatbot_session_key(session_id)
        mapped_user = _read_session_mapped_user_id(sid, allow_fuzzy=True)
        user_id = mapped_user if mapped_user else 1

        oid = _chatbot_extract_order_id(parameters)

        if oid is None:
            return JSONResponse(content={"fulfillmentText": "Please provide your order ID to track your order."})

        status = chatbot_service.get_order_status_for_user(oid, user_id)
        if not status:
            return JSONResponse(
                content={"fulfillmentText": "No order found with this ID for your account."}
            )

        s = (status or "").strip().upper()
        if s == "CONFIRMED":
            friendly = "Preparing"
        elif s == "DELIVERED":
            friendly = "Delivered"
        else:
            friendly = s.replace("_", " ").title()

        text = f"Order #{oid} is currently: {friendly}"
        return JSONResponse(content={"fulfillmentText": text})
    except Exception:
        logger.exception("[CHATBOT] track_order")
        return JSONResponse(
            content={
                "fulfillmentText": (
                    "Something went wrong looking up your order. Please try again in a moment."
                )
            }
        )

INTENT_HANDLER_MAP = {
    "Default Welcome Intent": greeting_handler,
    "Default Fallback Intent": fallback_handler,
    "new.order": new_order_handler,
    "order.add - context: ongoing-order": add_to_order,
    "order.remove - context: ongoing-order": remove_from_order,
    "order.complete - context: ongoing-order": complete_order,
    "track.order": track_order
}

@app.post("/webhook")
async def webhook(request: Request):
    payload = await request.json()

    intent = payload.get("queryResult", {}).get("intent", {}).get("displayName", "")
    parameters = payload.get("queryResult", {}).get("parameters", {})
    session_id = payload.get("session", "")

    handler = INTENT_HANDLER_MAP.get(intent, fallback_handler)

    return await handler(parameters, session_id) if __import__('inspect').iscoroutinefunction(handler) else handler(parameters, session_id)
"""

    # We will replace from # --- Dialogflow Webhook --- (around line 870) 
    # to the start of "class ChatbotLinkSession(BaseModel):" which is around 926
    # But wait, we also want to remove all the regex handlers at the bottom.
    
    # 1. Strip out the old webhook completely
    webhook_start = content.find("# --- Dialogflow Webhook ---")
    webhook_end = content.find("class ChatbotLinkSession(BaseModel):")
    if webhook_start != -1 and webhook_end != -1:
        content = content[:webhook_start] + content[webhook_end:]
        
    # 2. Strip out everything from def _chatbot_extract_order_id_from_text to the end, 
    # replacing it with the new handlers code
    
    pattern_to_remove = r"_ORDER_ID_TEXT_RE = re.compile.*?if __name__ == '__main__':"
    # Actually, a better approach is to find the start of the junk and the start of the end block
    junk_start = content.find("_ORDER_ID_TEXT_RE = re.compile")
    junk_end = content.find('if __name__ == "__main__":')
    
    if junk_start != -1 and junk_end != -1:
        content = content[:junk_start] + new_handlers_code + "\\n\\n" + content[junk_end:]
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)

if __name__ == '__main__':
    patch_file('c:/Food Chatbot/main.py')
