
import re

from repositories.user_repository import get_rider_by_id_safe  # noqa: F401 — re-export
from services.order_lifecycle import normalize_status_internal

normalize_order_status = normalize_status_internal


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
    print(get_str_from_food_dict({"pizza": 2, "burger": 3}))
