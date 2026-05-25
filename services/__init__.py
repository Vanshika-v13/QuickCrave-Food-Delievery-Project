"""
Service layer — business orchestration over MongoDB repositories.

Routes → services → repositories → MongoDB Atlas
"""

from services import (
    admin_service,
    address_service,
    auth_service,
    cart_service,
    chatbot_service,
    food_service,
    order_service,
    rider_service,
    user_service,
)

__all__ = [
    "admin_service",
    "address_service",
    "auth_service",
    "cart_service",
    "chatbot_service",
    "food_service",
    "order_service",
    "rider_service",
    "user_service",
]
