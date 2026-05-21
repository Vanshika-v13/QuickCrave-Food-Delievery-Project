from order_states import ACTIVE_STATES, HISTORY_STATES

class OrderService:

    @staticmethod
    def classify(status: str) -> str:
        """Classifies order status as ACTIVE, HISTORY, or PENDING."""
        if status in ACTIVE_STATES:
            return "ACTIVE"
        if status in HISTORY_STATES:
            return "HISTORY"
        return "PENDING"

    @staticmethod
    def normalize(status: str) -> str:
        """Normalizes inconsistent or legacy status strings."""
        if not status:
            return "ORDER_PLACED"
            
        s = status.strip().upper().replace(" ", "_")
        
        mapping = {
            "ASSIGNED": "PARTNER_ASSIGNED",
            "RIDER_ASSIGNED": "PARTNER_ASSIGNED",
            "FOOD_ASSIGNED": "PARTNER_ASSIGNED",
            "PLACED": "ORDER_PLACED",
            "CONFIRMED": "RESTAURANT_CONFIRMED",
            "PREPARING": "PREPARING_FOOD",
            "PICKED": "ORDER_PICKED_UP",
            "PICKED_UP": "ORDER_PICKED_UP",
            "ON_THE_WAY": "OUT_FOR_DELIVERY"
        }
        return mapping.get(s, s)

    @staticmethod
    def validate_transition(old_status: str, new_status: str) -> str:
        """Validates state transitions to prevent rollbacks or illegal modifications."""
        if not old_status:
            return new_status
            
        # RULE: Cannot modify completed orders
        if old_status in HISTORY_STATES:
            raise Exception(f"Terminal State Violation: Cannot update order in state '{old_status}'")
            
        # RULE: Prevent backward regression (simple check for now, can be expanded)
        # For now, we trust the specific status updates but prevent terminal rollbacks
        return new_status

    @staticmethod
    def assert_mutual_exclusion(status: str):
        """Strictly ensures an order is not in both active and history states."""
        if status in ACTIVE_STATES and status in HISTORY_STATES:
            raise Exception(f"State Corruption: Status '{status}' detected in both ACTIVE and HISTORY sets.")
