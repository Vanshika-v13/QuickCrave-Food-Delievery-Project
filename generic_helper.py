

import re

def get_str_from_food_dict(food_dict: dict):
    result = ", ".join([f"{int(value)} {key}" for key, value in food_dict.items()])
    return result


def extract_session_id(session_str: str):
    match = re.search(r"/sessions/(.*?)/contexts/", session_str)
    if match:
        extracted_string = match.group(1)
        return extracted_string

    return ""

if __name__ == "__main__":
    # print(extract_session_id("projects/chow-chatbot-for-food-del-jjiq/agent/sessions/f53632e4-8fa3-b080-460e-de94d2d5baf7/contexts/ongoing-order"))
    print(get_str_from_food_dict({"pizza": 2, "burger": 3}))