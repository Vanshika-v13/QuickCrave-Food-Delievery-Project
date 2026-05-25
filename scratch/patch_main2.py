import re

with open(r'c:\Food Chatbot\main.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Update _get_cart
get_cart_pattern = r'''def _get_cart\(session_id\):
    data = get_cache\(f"cart:\{session_id\}"\)
    if data:
        try:
            return json\.loads\(data\)
        except json\.JSONDecodeError as e:
            logger\.error\(f"\[CART\]\[REDIS_DECODE_ERROR\] \{e\}"\)
    return \{\}'''

get_cart_replacement = '''def _get_cart(session_id):
    data = get_cache(f"cart:{session_id}")
    if data:
        try:
            parsed = json.loads(data)
            if "items" in parsed:
                logger.error("[CART][SCHEMA_ERROR] Found list-based cart! Failing fast.")
                return {}
            return parsed
        except json.JSONDecodeError as e:
            logger.error(f"[CART][REDIS_DECODE_ERROR] {e}")
    return {}'''

content = re.sub(get_cart_pattern, get_cart_replacement, content)

# 2. Update new_order_handler
new_order_handler_pattern = r'''def new_order_handler\(parameters, session_id\):
    sid = _chatbot_session_key\(session_id\)
    _delete_cart\(sid\)
    logger\.info\("Cart system unified to dict-based structure with Redis as single source of truth"\)
    text = \(
        "Starting new order\. Specify food items and quantities\.\\n"
        "For example: 'I would like to order 2 pizzas and 1 mango lassi'\.\\n"
        "Menu: Pav Bhaji, Chole Bhature, Pizza, Mango Lassi, Masala Dosa, Biryani, Vada Pav, Rava Dosa, Samosa\."
    \)
    return JSONResponse\(content=\{"fulfillmentText": text\}\)'''

new_order_handler_replacement = '''def new_order_handler(parameters, session_id):
    sid = _chatbot_session_key(session_id)
    _delete_cart(sid)
    logger.info("Cart system unified to dict-based structure with Redis as single source of truth")
    text = (
        "Starting new order. Specify food items and quantities.\\n"
        "For example: 'I would like to order 2 pizzas and 1 mango lassi'.\\n"
        "Menu: Pav Bhaji, Chole Bhature, Pizza, Mango Lassi, Masala Dosa, Biryani, Vada Pav, Rava Dosa, Samosa."
    )
    return JSONResponse(content={
        "fulfillmentText": text,
        "outputContexts": [
            {
                "name": f"{session_id}/contexts/ongoing-order",
                "lifespanCount": 10
            }
        ]
    })'''

content = re.sub(new_order_handler_pattern, new_order_handler_replacement, content)

# 3. Add startup log
startup_pattern = r'''@app\.on_event\("startup"\)
async def startup_event\(\):
    """Safe Startup Wrapper\."""
    init_redis\(\)'''

startup_replacement = '''@app.on_event("startup")
async def startup_event():
    """Safe Startup Wrapper."""
    logger.info("CART_MODE=DICT_ONLY")
    init_redis()'''

content = re.sub(startup_pattern, startup_replacement, content)


with open(r'c:\Food Chatbot\main.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("Patch 2 applied.")
