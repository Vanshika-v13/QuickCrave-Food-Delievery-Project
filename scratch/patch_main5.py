import sys

def patch_file(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # 1. new_order_handler text
    old_new_order = '''    text = (
        "Great 👍 Let’s start your order.\\n"
        "You can say like 1 pizza, 2 vada pav, 3 mango lassi, or multiple items together."
    )'''
    new_new_order = '''    text = "Great 👍 Let’s start your order. You can say like 1 pizza, 2 vada pav, 3 mango lassi."'''
    content = content.replace(old_new_order, new_new_order)

    # 2. add_to_order multiple items text
    old_add_multi = '''        if len(added_msgs) == 1:
            added_text = added_msgs[0]
            return JSONResponse(content={"fulfillmentText": f"So far you have added {added_text.replace(' ×', ' ')}. Anything else?"})
        else:
            added_text = ", ".join(added_msgs)
            return JSONResponse(content={"fulfillmentText": f"Got it 👍 Your order includes:\\n{added_text}\\nAnything else?"})'''
    new_add_multi = '''        if len(added_msgs) == 1:
            added_text = added_msgs[0]
            return JSONResponse(content={"fulfillmentText": f"So far you have added {added_text.replace(' ×', ' ')}. Anything else?"})
        else:
            added_text = ", ".join(added_msgs)
            return JSONResponse(content={"fulfillmentText": f"Got it 👍 Your order includes {added_text}. Anything else?"})'''
    content = content.replace(old_add_multi, new_add_multi)

    # 3. add_to_order missing quantity
    old_add_missing = '''            return JSONResponse(content={"fulfillmentText": f"Please specify quantity for {canonical_names[0]}.\\nExample: 1 {canonical_names[0]} or 2 {canonical_names[0]}."})'''
    new_add_missing = '''            return JSONResponse(content={"fulfillmentText": f"Please specify quantity for {canonical_names[0]}. Example: 1 {canonical_names[0]} or 2 {canonical_names[0]}."})'''
    content = content.replace(old_add_missing, new_add_missing)

    # 4. remove_from_order text
    old_remove_full_1 = '''removed_msgs.append(f"{canonical} removed completely")'''
    new_remove_full_1 = '''removed_msgs.append(f"Removed {canonical} completely")'''
    content = content.replace(old_remove_full_1, new_remove_full_1)
    
    old_remove_full_2 = '''removed_text = ".\\n".join(removed_msgs) + "."'''
    new_remove_full_2 = '''removed_text = ". ".join(removed_msgs) + "."'''
    content = content.replace(old_remove_full_2, new_remove_full_2)
    
    old_remove_summary = '''return JSONResponse(content={"fulfillmentText": f"{removed_text}\\nRemaining order: {summary}"})'''
    new_remove_summary = '''return JSONResponse(content={"fulfillmentText": f"{removed_text} Remaining order: {summary}"})'''
    content = content.replace(old_remove_summary, new_remove_summary)

    # 5. INTENT_HANDLER_MAP to intent_handler_map
    content = content.replace('INTENT_HANDLER_MAP = {', 'intent_handler_map = {')
    content = content.replace('handler = INTENT_HANDLER_MAP.get', 'handler = intent_handler_map.get')
    
    # 6. complete_order text format
    old_complete_text = '''        text = (
            "🎉 Order placed successfully!\\n"
            f"Your order is:\\n{items_str}\\n"
            f"Total Amount: ₹{int(total)}\\n"
            f"Order ID: #{order_id}\\n"
            "Status: PACKING\\n"
            "You can track your order using this ID."
        )'''
    new_complete_text = '''        text = (
            "🎉 Order placed successfully!\\n"
            "Your order is:\\n"
            f"{items_str}\\n"
            f"Total Amount: ₹{int(total)}\\n"
            f"Order ID: #{order_id}\\n"
            "Status: PACKING\\n"
            "You can track your order using this ID."
        )'''
    content = content.replace(old_complete_text, new_complete_text)

    # 7. webhook clean up
    old_webhook = '''@app.post("/webhook")
async def webhook(request: Request):
    payload = await request.json()

    intent = payload["queryResult"]["intent"]["displayName"]
    parameters = payload["queryResult"]["parameters"]
    session_id = payload["session"]

    handler = intent_handler_map.get(intent, fallback_handler)

    return await handler(parameters, session_id) if __import__('inspect').iscoroutinefunction(handler) else handler(parameters, session_id)'''
    
    # The user provided a snippet without await, but since we have async handlers we have to handle it correctly while looking identical.
    # Actually I will just make it as requested:
    new_webhook = '''@app.post("/webhook")
async def webhook(request: Request):
    payload = await request.json()
    intent = payload["queryResult"]["intent"]["displayName"]
    parameters = payload["queryResult"]["parameters"]
    session_id = payload["session"]

    handler = intent_handler_map.get(intent, fallback_handler)
    if __import__('inspect').iscoroutinefunction(handler):
        return await handler(parameters, session_id)
    return handler(parameters, session_id)'''
    content = content.replace(old_webhook, new_webhook)

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)

if __name__ == '__main__':
    patch_file('c:/Food Chatbot/main.py')
