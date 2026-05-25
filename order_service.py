"""
Backward-compatible re-export — prefer `from services.order_service import OrderService`.
"""

from services.order_service import OrderService

__all__ = ["OrderService"]
