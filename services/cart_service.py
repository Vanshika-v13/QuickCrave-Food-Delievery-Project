"""Cart — MongoDB only."""

from __future__ import annotations

from repositories import cart_repository


def get_cart_items(user_id: int):
    return cart_repository.get_cart_items(user_id)


def add_to_cart(user_id: int, item_id: int, quantity: int = 1):
    cart_repository.add_to_cart(user_id, item_id, quantity)
    return get_cart_items(user_id)


def update_cart_quantity(user_id: int, item_id: int, quantity: int):
    cart_repository.update_cart_quantity(user_id, item_id, quantity)
    return get_cart_items(user_id)


def remove_from_cart(user_id: int, item_id: int):
    cart_repository.remove_from_cart(user_id, item_id)
    return get_cart_items(user_id)


def clear_cart(user_id: int):
    cart_repository.clear_cart(user_id)
