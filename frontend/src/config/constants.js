export const ROLES = {
  CUSTOMER: "customer",
  ADMIN: "admin",
  RIDER: "rider"
};

export const ORDER_STATUS = {
  PLACED: "placed",
  CONFIRMED: "confirmed",
  ASSIGNED: "assigned",
  ACCEPTED: "accepted",
  PREPARING: "preparing",
  PICKED_UP: "picked_up",
  ON_THE_WAY: "on_the_way",
  DELIVERED: "delivered",
  CANCELLED: "cancelled"
};

// Environment-driven URLs — set VITE_API_BASE_URL in .env for LAN/production
export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";

// Auto-derive WebSocket URL from API base (http→ws, https→wss)
export const WS_BASE_URL = (() => {
  const base = import.meta.env.VITE_API_BASE_URL || "http://127.0.0.1:8000";
  return base.replace(/^http/, 'ws');
})();
