/**
 * CENTRALIZED STATUS ADAPTER
 * Canonical lifecycle (matches backend):
 * PLACED → CONFIRMED → READY → ASSIGNED → PICKED_UP → ON_WAY → ARRIVING → DELIVERED
 */

export const STATUS_STEPS = [
  { id: 'PLACED',    label: 'Order Placed' },
  { id: 'CONFIRMED', label: 'Confirmed' },
  { id: 'READY',     label: 'Ready' },
  { id: 'ASSIGNED',  label: 'Rider Assigned' },
  { id: 'PICKED_UP', label: 'Picked Up' },
  { id: 'ON_WAY',    label: 'On the Way' },
  { id: 'ARRIVING',  label: 'Arriving' },
  { id: 'DELIVERED', label: 'Delivered' },
  { id: 'CANCELLED', label: 'Cancelled' }
];

export const STATUS_PRIORITY = {
  CANCELLED: -1,
  PLACED: 0,
  CONFIRMED: 1,
  READY: 2,
  ASSIGNED: 3,
  PICKED_UP: 4,
  ON_WAY: 5,
  ARRIVING: 6,
  DELIVERED: 7
};

export const compareStatus = (s1, s2) => {
  const p1 = STATUS_PRIORITY[normalizeStatus(s1)] ?? 0;
  const p2 = STATUS_PRIORITY[normalizeStatus(s2)] ?? 0;
  return p1 - p2;
};

/**
 * Maps legacy / raw statuses to canonical lifecycle strings.
 */
export const normalizeStatus = (rawStatus) => {
  if (!rawStatus) return 'PLACED';

  let statusStr;
  if (typeof rawStatus === 'object' && rawStatus !== null) {
    statusStr = (rawStatus.current_status || 'PLACED').toString();
  } else {
    statusStr = rawStatus.toString();
  }

  const s = statusStr.trim().toUpperCase().replace(/\s+/g, '_');

  const aliases = {
    ORDER_PLACED: 'PLACED',
    PLACED: 'PLACED',
    RESTAURANT_CONFIRMED: 'CONFIRMED',
    CONFIRMED: 'CONFIRMED',
    PREPARING_FOOD: 'READY',
    FOOD_READY: 'READY',
    READY: 'READY',
    PARTNER_ASSIGNED: 'ASSIGNED',
    DELIVERY_PARTNER_ASSIGNED: 'ASSIGNED',
    RIDER_ASSIGNED: 'ASSIGNED',
    ORDER_ACCEPTED: 'ASSIGNED',
    ACCEPTED: 'ASSIGNED',
    ASSIGNED: 'ASSIGNED',
    ORDER_PICKED_UP: 'PICKED_UP',
    PICKED_UP: 'PICKED_UP',
    PICKED: 'PICKED_UP',
    OUT_FOR_DELIVERY: 'ON_WAY',
    ON_THE_WAY: 'ON_WAY',
    ON_WAY: 'ON_WAY',
    NEAR_CUSTOMER_LOCATION: 'ARRIVING',
    NEAR_YOUR_LOCATION: 'ARRIVING',
    ARRIVING: 'ARRIVING',
    DELIVERED_SUCCESS: 'DELIVERED',
    DELIVERED: 'DELIVERED',
    CANCELLED: 'CANCELLED'
  };

  return aliases[s] || (STATUS_PRIORITY[s] !== undefined ? s : s);
};

export const ETA_TEXT_BY_STATUS = {
  PLACED: '45 min left',
  CONFIRMED: '35 min left',
  READY: '25 min left',
  ASSIGNED: '20 min left',
  PICKED_UP: '10 min left',
  ON_WAY: '5 min left',
  ARRIVING: '5 min left',
  DELIVERED: 'Delivered',
  CANCELLED: 'Cancelled'
};

export const getEtaCountdownText = (order) => {
  if (order?.eta_text) return order.eta_text;
  const status = normalizeStatus(order?.status?.current_status || order?.status || order?.current_status);
  return ETA_TEXT_BY_STATUS[status] || ETA_TEXT_BY_STATUS.PLACED;
};

export const getEtaText = (rawStatus) => {
  const status = normalizeStatus(rawStatus);
  return ETA_TEXT_BY_STATUS[status] || ETA_TEXT_BY_STATUS.PLACED;
};

export const getStatusUI = (rawStatus) => {
  const status = normalizeStatus(rawStatus);
  switch (status) {
    case 'PLACED':
    case 'CONFIRMED':
      return { color: 'bg-orange-50 text-orange-600 border-orange-100', dot: 'bg-orange-500' };
    case 'READY':
    case 'ASSIGNED':
      return { color: 'bg-blue-50 text-blue-600 border-blue-100', dot: 'bg-blue-500' };
    case 'PICKED_UP':
    case 'ON_WAY':
      return { color: 'bg-purple-50 text-purple-600 border-purple-100', dot: 'bg-purple-500' };
    case 'ARRIVING':
      return { color: 'bg-indigo-50 text-indigo-600 border-indigo-100', dot: 'bg-indigo-500' };
    case 'DELIVERED':
      return { color: 'bg-green-50 text-green-600 border-green-100', dot: 'bg-green-500' };
    case 'CANCELLED':
      return { color: 'bg-red-50 text-red-600 border-red-100', dot: 'bg-red-500' };
    default:
      return { color: 'bg-gray-50 text-gray-600 border-gray-100', dot: 'bg-gray-500' };
  }
};

export const getStatusLabel = (rawStatus) => {
  const status = normalizeStatus(rawStatus);
  const step = STATUS_STEPS.find((s) => s.id === status);
  return step ? step.label : status.replace(/_/g, ' ');
};

/** Rider accepted assignment but status remains ASSIGNED until pickup. */
export const isRiderAccepted = (order) =>
  Boolean(order?.rider_accepted || order?.accepted_at);
