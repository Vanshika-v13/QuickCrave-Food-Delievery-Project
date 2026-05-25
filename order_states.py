# Centralized order state groupings (canonical statuses)

ACTIVE_STATES = {
    "ASSIGNED",  # accepted delivery (accepted_at set)
    "PICKED_UP",
    "ON_WAY",
    "ARRIVING",
}

HISTORY_STATES = {
    "DELIVERED",
}

RESTAURANT_STATES = {
    "PLACED",
    "CONFIRMED",
    "READY",
}
