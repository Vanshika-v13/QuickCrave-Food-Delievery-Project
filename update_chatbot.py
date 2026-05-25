import sys

def replace_block(lines, start_str, end_str, replacement):
    start_idx = -1
    end_idx = -1
    for i, line in enumerate(lines):
        if line.startswith(start_str):
            start_idx = i
            break
            
    if start_idx != -1:
        for i in range(start_idx, len(lines)):
            if end_str in lines[i]:
                end_idx = i
                break
                
    if start_idx != -1 and end_idx != -1:
        return lines[:start_idx] + [replacement + "\n"] + lines[end_idx+1:]
    else:
        print(f"Could not find block {start_str}")
        return lines

with open("main.py", "r", encoding="utf-8") as f:
    lines = f.readlines()

# 1. Replace webhook
webhook_start = '@app.post("/webhook")'
webhook_end = 'return _chatbot_finalize_webhook_response(result)'
webhook_repl = """@app.post("/webhook")
async def webhook(request: Request):
    logger.info("[WEBHOOK] request received")
    payload = await request.json()

    query_result = payload.get("queryResult", {})
    intent = query_result.get("intent", {}).get("displayName", "")
    parameters = query_result.get("parameters", {}) or {}
    query_text = query_result.get("queryText", "").lower().strip()

    session_full = payload.get("session", "")
    session_id = session_full.split("/")[-1] if session_full else ""
    if not session_id:
        session_id = "default-session"

    session_id = _normalize_chatbot_session_id(session_id)
    _consolidate_chatbot_session_state(session_id)
    resolved_user, auth_source = _resolve_chatbot_auth_user(session_id, request, payload)

    parameters["_query_text"] = query_text
    parameters["_chatbot_user_id"] = resolved_user

    INTENT_HANDLER_MAP = {
        "Default Welcome Intent": greeting_handler,
        "Default Fallback Intent": fallback_handler,
        "new.order": new_order_handler,
        "order.add - context: ongoing-order": add_to_order,
        "order.remove - context: ongoing-order": remove_from_order,
        "order.complete - context: ongoing-order": complete_order,
        "track.order": track_order,
    }

    handler = INTENT_HANDLER_MAP.get(intent)
    if handler is None:
        handler = fallback_handler

    try:
        import inspect
        if inspect.iscoroutinefunction(handler):
            result = await handler(parameters, session_id)
        else:
            result = handler(parameters, session_id)
    except Exception:
        logger.exception("[CHATBOT][WEBHOOK_FATAL]")
        raise
        
    return result"""

lines = replace_block(lines, webhook_start, webhook_end, webhook_repl)

# 2. Delete _chatbot_finalize_webhook_response
fin_start = 'def _chatbot_finalize_webhook_response(result)'
fin_end = 'return _chatbot_fulfillment_response(clean)'
lines = replace_block(lines, fin_start, fin_end, "")

def replace_handler(lines, fn_name, new_content):
    start_idx = -1
    for i, line in enumerate(lines):
        if line.startswith(f"def {fn_name}(") or line.startswith(f"async def {fn_name}("):
            start_idx = i
            break
    if start_idx == -1: return lines
    
    end_idx = start_idx + 1
    while end_idx < len(lines):
        if lines[end_idx].startswith("def ") or lines[end_idx].startswith("async def ") or lines[end_idx].startswith("if __name__") or lines[end_idx].startswith("_CHATBOT"):
            break
        end_idx += 1
        
    return lines[:start_idx] + [new_content + "\n\n"] + lines[end_idx:]

new_order_repl = """def new_order_handler(parameters, session_id):
    sid = _chatbot_session_key(session_id)
    _delete_cart(sid)
    text = "Great 👍 Let’s start your order. You can say like 1 pizza, 2 vada pav, 3 mango lassi or even multiple items together."
    return JSONResponse(content={
        "fulfillmentText": text,
        "outputContexts": [
            {
                "name": f"{session_id}/contexts/ongoing-order",
                "lifespanCount": 10
            }
        ]
    })"""
lines = replace_handler(lines, "new_order_handler", new_order_repl)

add_to_order_repl = """def add_to_order(parameters, session_id):
    try:
        sid = _chatbot_session_key(session_id)
        cart = _get_cart(sid)
        if cart is None:
            cart = {}
            
        query_text = parameters.get("_query_text", "")

        foods = _chatbot_detect_all_foods_in_text(query_text)
        if not foods:
            foods = _chatbot_extract_food_names(parameters)
        if not foods:
            detected = _chatbot_detect_food_in_text(query_text)
            if detected:
                foods = [detected]

        if not foods:
            return fallback_handler(parameters, session_id)

        added_msgs = []
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
            
            if qty is None:
                return JSONResponse(content={"fulfillmentText": f"Please specify quantity for {canonical}. Example: 1 {canonical} or 2 {canonical}."})
            
            qty = max(1, int(qty))
            iid_str = str(iid)
            
            if iid_str in cart:
                cart[iid_str]["quantity"] += qty
            else:
                cart[iid_str] = {"item_id": iid, "name": canonical, "quantity": qty, "price": price}

            added_msgs.append(f"{canonical} ×{qty}")

        if not added_msgs:
            return fallback_handler(parameters, session_id)

        _set_cart(sid, cart)
        
        if len(added_msgs) == 1:
            single_str = added_msgs[0]
            if " ×" in single_str:
                parts = single_str.split(" ×")
                single_str = f"{parts[1]} {parts[0]}"
            return JSONResponse(content={"fulfillmentText": f"So far you have added {single_str}. Anything else?"})
        else:
            added_text = ", ".join(added_msgs)
            return JSONResponse(content={"fulfillmentText": f"Got it 👍 Your order includes:\\n{added_text}\\nAnything else?"})
    except Exception as e:
        logger.exception("[CHATBOT] add_to_order")
        return JSONResponse(content={"fulfillmentText": "Something went wrong updating your order."})"""
lines = replace_handler(lines, "add_to_order", add_to_order_repl)

remove_from_order_repl = """def remove_from_order(parameters, session_id):
    try:
        sid = _chatbot_session_key(session_id)
        cart = _get_cart(sid)
        if not cart:
            return JSONResponse(content={"fulfillmentText": "That item is not in your order."})

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

        removed_msgs = []
        for food in foods:
            row = chatbot_service.get_food_item_by_name(food)
            canonical = row["name"] if row else food.strip()
            
            existing_key = next((k for k, v in cart.items() if v["name"].lower() == canonical.lower()), None)
            if not existing_key:
                return JSONResponse(content={"fulfillmentText": "That item is not in your order."})
                
            qty_remove = _chatbot_explicit_remove_qty_for_food(query_text, canonical)
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
            return JSONResponse(content={"fulfillmentText": f"{removed_text}\\nRemaining order: Your cart is empty."})
        else:
            summary_lines = [f"{item['name']} ×{item['quantity']}" for item in cart.values()]
            summary = ", ".join(summary_lines)
            return JSONResponse(content={"fulfillmentText": f"{removed_text}\\nRemaining order: {summary}"})
            
    except Exception:
        logger.exception("[CHATBOT] remove_from_order")
        return JSONResponse(content={"fulfillmentText": "Something went wrong updating your order."})"""
lines = replace_handler(lines, "remove_from_order", remove_from_order_repl)

complete_order_repl = """async def complete_order(parameters, session_id):
    try:
        query_text = parameters.get("_query_text", "").lower()
        
        # Explicit rejection keywords
        reject_phrases = ["no", "nope", "ok", "done"]
        if query_text in reject_phrases or "no" in query_text.split() or "nope" in query_text.split():
            return JSONResponse(content={
                "fulfillmentText": "Do you want anything else?"
            })
            
        explicit_checkout_phrases = ["checkout", "finish order", "confirm order", "that's it", "place order"]
        explicit_checkout_confirmation = any(phrase in query_text for phrase in explicit_checkout_phrases)

        if not explicit_checkout_confirmation:
            return JSONResponse(content={
                "fulfillmentText": "Do you want anything else?"
            })
            
        sid = _chatbot_session_key(session_id)
        cart = _get_cart(sid)
        
        if not cart:
            return JSONResponse(content={"fulfillmentText": "Your cart is currently empty. You can add items by saying like '1 pizza'."})

        user_id, login_err = _chatbot_user_from_context(parameters.get("_chatbot_user_id"), session_id, parameters)
        if login_err:
            user_id = 1  # Fallback to test user if strictly needed by save_to_db

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
            "Your order is:\\n"
            f"{items_str}\\n"
            f"Total Amount: ₹{int(total)}\\n"
            f"Order ID: #{order_id}\\n"
            "Status: PACKING\\n"
            "You can track your order using this ID."
        )

        return JSONResponse(content={
            "fulfillmentText": text,
            "fulfillmentMessages": [
                {
                    "text": {
                        "text": [text]
                    }
                }
            ],
            "orderId": f"#{order_id}",
            "total": int(total),
            "success": True
        })

    except Exception as e:
        logger.exception("[CHATBOT] complete_order")
        return JSONResponse(content={"fulfillmentText": "Something went wrong completing your order."})"""
lines = replace_handler(lines, "complete_order", complete_order_repl)

fallback_repl = """def fallback_handler(parameters, session_id):
    return JSONResponse(
        content={
            "fulfillmentText": "If you're adding items, say like '2 pizza' or '1 vada pav'."
        }
    )"""
lines = replace_handler(lines, "fallback_handler", fallback_repl)

with open("main.py", "w", encoding="utf-8") as f:
    f.writelines(lines)
print("Updated successfully")
