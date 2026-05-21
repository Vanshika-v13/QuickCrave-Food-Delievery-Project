/**
 * CENTRALIZED STATUS ADAPTER
 * Single source of truth for all status normalization, UI mapping, and ETA logic.
 * Matches backend STRICT 9-STAGE state machine exactly.
 */

export const STATUS_STEPS = [
  { id: 'ORDER_PLACED',           label: 'Order Placed' },
  { id: 'RESTAURANT_CONFIRMED',   label: 'Confirmed' },
  { id: 'FOOD_READY',             label: 'Food Ready' },
  { id: 'ASSIGNED',               label: 'Rider Assigned' },
  { id: 'ACCEPTED',               label: 'Accepted' },
  { id: 'ORDER_PICKED_UP',        label: 'Picked Up' },
  { id: 'OUT_FOR_DELIVERY',       label: 'On the Way' },
  { id: 'NEAR_CUSTOMER_LOCATION', label: 'Arriving' },
  { id: 'DELIVERED',              label: 'Delivered' },
  { id: 'CANCELLED',              label: 'Cancelled' }
];

// ─── STATUS PRIORITY MAP ──────────────────────────────────────────────────────
// Rule: Higher number = later stage. Prevents backward regression.
export const STATUS_PRIORITY = {
  'CANCELLED':              -1,
  'ORDER_PLACED':            0,
  'RESTAURANT_CONFIRMED':    1,
  'FOOD_READY':              2,
  'ASSIGNED':                3,
  'ACCEPTED':                4,
  'ORDER_PICKED_UP':         5,
  'OUT_FOR_DELIVERY':        6,
  'NEAR_CUSTOMER_LOCATION':  7,
  'DELIVERED':               8
};

/**
 * compareStatus — Returns:
 *   > 0 if s1 is after  s2
 *   < 0 if s1 is before s2
 *   = 0 if equal
 */
export const compareStatus = (s1, s2) => {
  const p1 = STATUS_PRIORITY[normalizeStatus(s1)] ?? 0;
  const p2 = STATUS_PRIORITY[normalizeStatus(s2)] ?? 0;
  return p1 - p2;
};

// ─── NORMALIZE STATUS ─────────────────────────────────────────────────────────
/**
 * Converts any raw status value (string or object) into a clean canonical string.
 */
export const normalizeStatus = (rawStatus) => {
  if (!rawStatus) return 'ORDER_PLACED';

  let statusStr;
  if (typeof rawStatus === 'object' && rawStatus !== null) {
    statusStr = (rawStatus.current_status || 'ORDER_PLACED').toString();
  } else {
    statusStr = rawStatus.toString();
  }

  const s = statusStr.trim().toUpperCase().replace(/\s+/g, '_');

  // Legacy aliases → canonical
  if (s === 'PLACED')                                        return 'ORDER_PLACED';
  if (s === 'CONFIRMED')                                     return 'RESTAURANT_CONFIRMED';
  if (s === 'NEAR_YOUR_LOCATION')                            return 'NEAR_CUSTOMER_LOCATION';
  if (s === 'PARTNER_ASSIGNED' || s === 'DELIVERY_PARTNER_ASSIGNED') return 'ASSIGNED';
  if (s === 'ACCEPTED')                                      return 'ACCEPTED';

  return s;
};

/** Fixed ETA labels — only change when order status changes (matches backend map). */
export const ETA_TEXT_BY_STATUS = {
  ORDER_PLACED: '45 min left',
  RESTAURANT_CONFIRMED: '35 min left',
  PREPARING_FOOD: '30 min left',
  FOOD_READY: '25 min left',
  ASSIGNED: '20 min left',
  ACCEPTED: '15 min left',
  ORDER_PICKED_UP: '10 min left',
  OUT_FOR_DELIVERY: '5 min left',
  NEAR_CUSTOMER_LOCATION: '5 min left',
  DELIVERED: 'Delivered',
  DELIVERED_SUCCESS: 'Delivered',
  CANCELLED: 'Cancelled'
};

/**
 * Status-only ETA line for tracking / rider UIs.
 * Prefer backend `eta_text` when present; otherwise map from normalized status.
 */
export const getEtaCountdownText = (order) => {
  if (order?.eta_text) return order.eta_text;
  const status = normalizeStatus(order?.status?.current_status || order?.status || order?.current_status);
  return ETA_TEXT_BY_STATUS[status] || ETA_TEXT_BY_STATUS.ORDER_PLACED;
};

/**
 * @deprecated Legacy helper — prefer getEtaCountdownText(order).
 */
export const getEtaText = (rawStatus, lastUpdated) => {
  const status = normalizeStatus(rawStatus);
  return ETA_TEXT_BY_STATUS[status] || ETA_TEXT_BY_STATUS.ORDER_PLACED;
};

// ─── STATUS UI STYLES ─────────────────────────────────────────────────────────
/**
 * Returns Tailwind class strings for badge/dot styling per status.
 */
export const getStatusUI = (rawStatus) => {
  const status = normalizeStatus(rawStatus);
  switch (status) {
    case 'ORDER_PLACED':
    case 'RESTAURANT_CONFIRMED':
      return { color: 'bg-orange-50 text-orange-600 border-orange-100', dot: 'bg-orange-500' };
    case 'FOOD_READY':
    case 'ASSIGNED':
      return { color: 'bg-blue-50 text-blue-600 border-blue-100', dot: 'bg-blue-500' };
    case 'ORDER_PICKED_UP':
    case 'OUT_FOR_DELIVERY':
      return { color: 'bg-purple-50 text-purple-600 border-purple-100', dot: 'bg-purple-500' };
    case 'NEAR_CUSTOMER_LOCATION':
      return { color: 'bg-indigo-50 text-indigo-600 border-indigo-100', dot: 'bg-indigo-500' };
    case 'DELIVERED':
      return { color: 'bg-green-50 text-green-600 border-green-100', dot: 'bg-green-500' };
    case 'CANCELLED':
      return { color: 'bg-red-50 text-red-600 border-red-100', dot: 'bg-red-500' };
    default:
      return { color: 'bg-gray-50 text-gray-600 border-gray-100', dot: 'bg-gray-500' };
  }
};

// ─── STATUS LABEL ─────────────────────────────────────────────────────────────
/**
 * Returns the human-readable label for a given status.
 */
export const getStatusLabel = (rawStatus) => {
  const status = normalizeStatus(rawStatus);
  const step = STATUS_STEPS.find(s => s.id === status);
  return step ? step.label : status;
};

