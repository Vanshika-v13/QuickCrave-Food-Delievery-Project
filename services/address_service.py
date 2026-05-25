"""Addresses — MongoDB only."""

from __future__ import annotations

from repositories import address_repository


def get_user_addresses(user_id: int):
    return address_repository.list_by_user(user_id)


def add_address(
    user_id, name, phone, address_line, city, state, pincode, is_default=False, latitude=None, longitude=None
):
    return address_repository.add_address(
        user_id, name, phone, address_line, city, state, pincode, is_default, latitude, longitude
    )


def delete_address(user_id: int, address_id: int):
    return address_repository.delete_address(user_id, address_id)


def set_default_address(address_id: int, user_id: int):
    return address_repository.set_default_address(address_id, user_id)


def add_user_address(user_id: int, data: dict):
    return address_repository.add_user_address(user_id, data)


def update_user_address(address_id: int, user_id: int, data: dict):
    return address_repository.update_user_address(address_id, user_id, data)


def delete_user_address(address_id: int, user_id: int):
    return address_repository.delete_address(address_id, user_id)


def get_default_address(user_id: int):
    return address_repository.get_default_or_first(user_id)


def get_chatbot_delivery_address(user_id: int):
    return address_repository.get_default_or_first(user_id)
