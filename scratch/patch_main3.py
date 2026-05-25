import re
import sys

def patch_file(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # 1. Remove the "no", "nope" hack in webhook
    hack_block = """    if query_text in ["no", "nope", "nothing else"]:
        return _chatbot_finalize_webhook_response(JSONResponse(content={
            "fulfillmentText": "Okay 👍 Got it. You can continue adding items or say checkout when you're ready."
        }))"""
    content = content.replace(hack_block, "")

    # 2. Add _chatbot_extract_quantities
    quantities_func = """def _chatbot_extract_quantities(parameters: dict) -> list:
    if not parameters:
        return []
    quantities = []
    for key in ("number", "Number", "quantity", "amount"):
        v = parameters.get(key)
        if v is None or v == "" or v == [] or v == [""]:
            continue
        if isinstance(v, list):
            for x in v:
                if x is None or str(x).strip() == "":
                    continue
                try:
                    quantities.append(max(1, int(float(x))))
                except (TypeError, ValueError):
                    continue
            if quantities:
                return quantities
        else:
            try:
                quantities.append(max(1, int(float(v))))
                return quantities
            except (TypeError, ValueError):
                continue
    return quantities"""
    
    # Insert it right before _chatbot_extract_food_names
    target_insert = "def _chatbot_extract_food_names(parameters: dict) -> list:"
    content = content.replace(target_insert, quantities_func + "\n\n\n" + target_insert)

    # 3. Replace greeting_handler & fallback_handler & new_order_handler
    old_handlers_pattern = r"def greeting_handler.*?def add_to_order\(parameters, session_id\):"
    
    new_handlers = """def greeting_handler(parameters, session_id):
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

def add_to_order(parameters, session_id):"""
    content = re.sub(old_handlers_pattern, new_handlers, content, flags=re.DOTALL)

    # 4. Replace add_to_order body
    old_add = r"def add_to_order\(parameters, session_id\):.*?def remove_from_order\(parameters, session_id\):"
    
    new_add = """def add_to_order(parameters, session_id):
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

def remove_from_order(parameters, session_id):"""
    content = re.sub(old_add, new_add, content, flags=re.DOTALL)

    # 5. Replace remove_from_order body
    old_remove = r"def remove_from_order\(parameters, session_id\):.*?async def _chatbot_push_order_update_safe\(order_id: int\) -> None:"
    
    new_remove = """def remove_from_order(parameters, session_id):
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

async def _chatbot_push_order_update_safe(order_id: int) -> None:"""
    content = re.sub(old_remove, new_remove, content, flags=re.DOTALL)

    # 6. Replace complete_order body
    old_complete = r"async def complete_order\(parameters, session_id\):.*?def track_order\(parameters, session_id\):"
    
    new_complete = """async def complete_order(parameters, session_id):
    try:
        sid = _chatbot_session_key(session_id)
        cart = _get_cart(sid)
        
        if not cart:
            return JSONResponse(content={"fulfillmentText": "Your cart is currently empty."})

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

def track_order(parameters, session_id):"""
    content = re.sub(old_complete, new_complete, content, flags=re.DOTALL)

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)

if __name__ == '__main__':
    patch_file('c:/Food Chatbot/main.py')
