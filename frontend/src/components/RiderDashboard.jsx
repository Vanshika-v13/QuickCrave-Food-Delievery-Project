import React, { useState, useEffect, useRef } from 'react';
import { 
  Bike, Package, MapPin, CheckCircle2, Navigation, 
  Power, Clock, IndianRupee, Bell, AlertCircle,
  Phone, ChevronRight, User, Play, Square, Loader2
} from 'lucide-react';
import { Routes, Route, Navigate, Link, Outlet, useNavigate, useLocation } from 'react-router-dom';
import { getStatusUI, normalizeStatus, getStatusLabel, compareStatus, getEtaCountdownText } from '../services/statusService';
import apiClient from '../services/apiClient';
import { WS_BASE_URL, ROLES } from '../config/constants';
import { useAuth } from '../hooks/useAuth';
import { toast } from 'react-hot-toast';

const RiderDashboard = () => {
  const { logoutRider: logout, riderToken, riderUser } = useAuth();
  const navigate = useNavigate();

  // PHASE 3 HARDENING: RECONNECT & SYNC (PRODUCTION)
  const [isOnline, setIsOnline] = useState(false);
  const [gpsPermissionMessage, setGpsPermissionMessage] = useState('');
  const [dashboardState, setDashboardState] = useState({
    availableOrders: [],
    activeOrders: [],
    activeOrder: null,
    riderStatus: 'offline'
  });
  const [loading, setLoading] = useState(true);
  const [isUpdating, setIsUpdating] = useState(false);
  const [isWsConnecting, setIsWsConnecting] = useState(false);
  const [stats, setStats] = useState({ completed_today: 0, earnings_today: 0, active_count: 0 });
  const { availableOrders, activeOrders, activeOrder, riderStatus } = dashboardState;
  const safeAvailableOrders = Array.isArray(availableOrders) ? availableOrders : [];
  const riderId = riderUser?.id;
  const AVAILABLE_STATUSES = new Set(['ASSIGNED']);
  const ACTIVE_STATUSES = new Set(['ACCEPTED', 'ORDER_PICKED_UP', 'OUT_FOR_DELIVERY']);
  const HISTORY_STATUSES = new Set(['DELIVERED']);

  const getOrderStatusValue = (order) => normalizeStatus(order?.status?.current_status || order?.status);
  const isOrderForCurrentRider = (order) => {
    const orderRiderId = order?.rider_id ?? order?.rider?.id ?? order?.rider?.riderId;
    return Number(orderRiderId) === Number(riderId);
  };
  const isAvailableOrder = (order) => isOrderForCurrentRider(order) && AVAILABLE_STATUSES.has(getOrderStatusValue(order));
  const isActiveOrder = (order) => isOrderForCurrentRider(order) && ACTIVE_STATUSES.has(getOrderStatusValue(order));
  const isHistoryOrder = (order) => isOrderForCurrentRider(order) && HISTORY_STATUSES.has(getOrderStatusValue(order));

  const formatAddress = (addr) => {
    if (!addr || typeof addr !== 'object') return '';
    return `${addr.name ?? ''}, ${addr.address_line ?? ''}, ${addr.city ?? ''} - ${addr.pincode ?? ''}`.replace(/^,\s*|,\s*-\s*$/g, '').trim();
  };

  const safeText = (value, fallback = '') => {
    if (value == null) return fallback;
    if (typeof value === 'object') return formatAddress(value) || fallback;
    return String(value);
  };

  const getOrderTotalAmount = (order) => Number(order?.total_amount ?? order?.total ?? 0);
  
  // Persistence Refs
  const gpsTriggeredRef = useRef(false);
  const gpsRetryRef = useRef(0);
  const lastBroadcastPosRef = useRef(null); 
  const lastUpdateRef = useRef(0);
  const isPollingRef = useRef(false); 
  const pendingStatusUpdateRef = useRef(false); 

  // Hardening Refs (Phase 3)
  const reconnectCountRef = useRef(0);
  const maxReconnects = 5;
  const socketRef = useRef(null);
  const reconnectTimeoutRef = useRef(null);
  const pollingIntervalRef = useRef(null);
  const gpsWatchIdRef = useRef(null);
  const lastPayloadRef = useRef(""); // For WS dedup
  const isLoggedOutRef = useRef(false);
  const cleanupActiveRef = useRef(false);
  const prevRiderTokenRef = useRef(null);
  const lastOrderIdRef = useRef(null);
  const hasInitialWsSyncRef = useRef(false);
  const geoBlockedRef = useRef(false);
  const syncLockRef = useRef(false);
  const activeOrderRef = useRef(null);
  const wsConnectInFlightRef = useRef(false);
  const fullResyncRequestedRef = useRef(false);
  const wsProcessingRef = useRef(false);
  const activeOrderIdRef = useRef(null);
  const executionLockRef = useRef(false);
  const wsLockRef = useRef(false);
  const cleanupLockRef = useRef(false);
  const fetchInProgressRef = useRef(false);
  const goingOnlineRef = useRef(false);
  const permissionWatchIdRef = useRef(null);

  const normalizeRiderStatusForFlow = (status) => normalizeStatus(status);

  const orderListSignature = (orders = []) =>
    (Array.isArray(orders) ? orders : [])
      .map((order) => `${order?.order_id ?? 'na'}:${normalizeStatus(order?.status)}:${order?.version ?? 0}`)
      .join('|');

  const clearDashboardState = () => {
    applyRiderEvent({ type: 'CLEAR_DASHBOARD' });
  };

  const applyRiderEvent = (event) => {
    if (!event || typeof event !== 'object') return;
    setDashboardState((prev) => {
      const next = { ...prev };
      const currentOrderId = prev.activeOrder?.order_id ?? null;

      switch (event.type) {
        case 'CLEAR_DASHBOARD': {
          return {
            ...prev,
            activeOrders: [],
            availableOrders: [],
            activeOrder: null
          };
        }
        case 'ORDER_UPDATE': {
          const incomingOrder = event.data || event.order;
          if (!incomingOrder || typeof incomingOrder !== 'object' || !incomingOrder.order_id) return prev;
          const incomingOrderId = incomingOrder.order_id;
          const incomingStatus = incomingOrder.status?.current_status || incomingOrder.status;
          const incomingTimestamp = incomingOrder.status?.last_updated
            ? new Date(incomingOrder.status.last_updated).getTime()
            : Date.now();
          const incomingVersion = incomingOrder.version || 1;
          const currentStatus = prev.activeOrder?.status;
          const currentVersion = prev.activeOrder?.version || 1;

          if (incomingVersion < currentVersion) return prev;

          const isNewer = incomingTimestamp > lastUpdateRef.current;
          const isHigherPriority = compareStatus(incomingStatus, currentStatus) > 0;
          const isBackwardRegression = compareStatus(incomingStatus, currentStatus) < 0;

          if (isBackwardRegression && !isNewer && incomingVersion <= currentVersion) return prev;
          if (!(isNewer || isHigherPriority || incomingVersion > currentVersion || !prev.activeOrder)) return prev;

          lastUpdateRef.current = incomingTimestamp;
          const normalizedOrder = {
            ...incomingOrder,
            status: normalizeStatus(incomingStatus)
          };

          // Reset flow refs only when order switches.
          if (currentOrderId && incomingOrderId !== currentOrderId) {
            lastOrderIdRef.current = incomingOrderId;
            activeOrderIdRef.current = incomingOrderId;
            gpsTriggeredRef.current = false;
            gpsRetryRef.current = 0;
            lastBroadcastPosRef.current = null;
          } else if (!currentOrderId) {
            activeOrderIdRef.current = incomingOrderId;
          }

          if (prev.activeOrder && orderListSignature([prev.activeOrder]) === orderListSignature([normalizedOrder])) {
            return prev;
          }
          const activeWithoutIncoming = prev.activeOrders.filter((o) => o.order_id !== incomingOrderId);
          const availableWithoutIncoming = prev.availableOrders.filter((o) => o.order_id !== incomingOrderId);

          let nextActiveOrders = activeWithoutIncoming;
          let nextAvailableOrders = availableWithoutIncoming;
          let nextActiveOrder = prev.activeOrder?.order_id === incomingOrderId ? null : prev.activeOrder;

          if (isActiveOrder(normalizedOrder)) {
            nextActiveOrders = [normalizedOrder, ...activeWithoutIncoming];
            nextActiveOrder = normalizedOrder;
          } else if (isAvailableOrder(normalizedOrder)) {
            nextAvailableOrders = [normalizedOrder, ...availableWithoutIncoming];
          } else if (isHistoryOrder(normalizedOrder)) {
            nextActiveOrder = null;
          }

          next.activeOrders = nextActiveOrders;
          next.availableOrders = nextAvailableOrders;
          next.activeOrder = nextActiveOrder;
          return next;
        }
        case 'RIDER_STATUS_UPDATE': {
          const nextStatus = typeof event.rider_status === 'string'
            ? event.rider_status
            : typeof event.data === 'string'
              ? event.data
              : 'offline';
          if (prev.riderStatus === nextStatus) return prev;
          next.riderStatus = nextStatus;
          return next;
        }
        case 'ORDER_REMOVED': {
          const oid = event.order_id;
          if (oid == null) return prev;
          next.availableOrders = prev.availableOrders.filter((o) => o.order_id !== oid);
          next.activeOrders = prev.activeOrders.filter((o) => o.order_id !== oid);
          if (prev.activeOrder?.order_id === oid) {
            next.activeOrder = null;
            lastOrderIdRef.current = null;
            activeOrderIdRef.current = null;
          }
          return next;
        }
        case 'FETCH_SNAPSHOT':
        case 'FETCH_RESPONSE': {
          const data = event.data || {};
          const backendActiveOrdersRaw = Array.isArray(data.active_orders) ? data.active_orders : [];
          const backendAvailableOrdersRaw = Array.isArray(data.available_orders) ? data.available_orders : [];
          const backendActiveOrders = backendActiveOrdersRaw.filter(isActiveOrder);
          const backendAvailableOrders = backendAvailableOrdersRaw.filter(isAvailableOrder);
          const backendRiderStatus = data?.rider?.rider_status || 'offline';
          const backendActiveOrder = data.active_order && typeof data.active_order === 'object' ? data.active_order : null;

          const nextActiveOrders = orderListSignature(prev.activeOrders) === orderListSignature(backendActiveOrders)
            ? prev.activeOrders
            : backendActiveOrders;
          const nextAvailableOrders = orderListSignature(prev.availableOrders) === orderListSignature(backendAvailableOrders)
            ? prev.availableOrders
            : backendAvailableOrders;

          let nextActiveOrder = prev.activeOrder;
          if (backendActiveOrder?.order_id && isActiveOrder(backendActiveOrder)) {
            const normalizedStatus = backendActiveOrder.status?.current_status || backendActiveOrder.status;
            const normalizedOrder = {
              ...backendActiveOrder,
              status: normalizeStatus(normalizedStatus)
            };
            if (!prev.activeOrder || orderListSignature([prev.activeOrder]) !== orderListSignature([normalizedOrder])) {
              nextActiveOrder = normalizedOrder;
            }
          } else if (prev.activeOrder) {
            nextActiveOrder = null;
            lastOrderIdRef.current = null;
            activeOrderIdRef.current = null;
          }

          if (
            nextActiveOrders === prev.activeOrders &&
            nextAvailableOrders === prev.availableOrders &&
            nextActiveOrder === prev.activeOrder &&
            backendRiderStatus === prev.riderStatus
          ) {
            return prev;
          }

          return {
            ...prev,
            activeOrders: nextActiveOrders,
            availableOrders: nextAvailableOrders,
            activeOrder: nextActiveOrder,
            riderStatus: backendRiderStatus
          };
        }
        case 'STATUS_CHANGE_RESPONSE': {
          if (!event.data || !event.data.order_id) return prev;
          return prev.activeOrder?.order_id === event.data.order_id
            ? { ...prev, activeOrder: { ...prev.activeOrder, ...event.data } }
            : prev;
        }
        default:
          return prev;
      }
    });
  };

  const canTransitionTo = () => true;

  const hardCleanup = () => {
    if (cleanupLockRef.current) return;
    if (!isLoggedOutRef.current && riderToken) return;
    cleanupLockRef.current = true;
    executionLockRef.current = true;
    cleanupActiveRef.current = true;
    isPollingRef.current = false;
    pendingStatusUpdateRef.current = false;
    clearDashboardState();
    lastOrderIdRef.current = null;
    hasInitialWsSyncRef.current = false;
    applyRiderEvent({ type: 'RIDER_STATUS_UPDATE', rider_status: 'offline' });
    if (pollingIntervalRef.current) {
      clearInterval(pollingIntervalRef.current);
      pollingIntervalRef.current = null;
    }
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }
    if (gpsWatchIdRef.current && typeof navigator !== 'undefined' && navigator.geolocation) {
      navigator.geolocation.clearWatch(gpsWatchIdRef.current);
      gpsWatchIdRef.current = null;
    }
    if (socketRef.current) {
      socketRef.current.onopen = null;
      socketRef.current.onmessage = null;
      socketRef.current.onclose = null;
      socketRef.current.onerror = null;
      socketRef.current.close();
      socketRef.current = null;
    }
    wsProcessingRef.current = false;
    activeOrderIdRef.current = null;
    wsConnectInFlightRef.current = false;
    wsLockRef.current = false;
    fetchInProgressRef.current = false;
    setIsWsConnecting(false);
    executionLockRef.current = false;
    cleanupLockRef.current = false;
  };

  useEffect(() => {
    if (!riderToken) {
      isLoggedOutRef.current = true;
      hardCleanup();
      setLoading(false);
      return;
    }
    isLoggedOutRef.current = false;
    cleanupActiveRef.current = false;
  }, [riderToken]);

  // Haversine Distance Formula (Production Grade)
  const calculateDistance = (lat1, lon1, lat2, lon2) => {
    const R = 6371000; 
    const dLat = (lat2 - lat1) * Math.PI / 180;
    const dLon = (lon2 - lon1) * Math.PI / 180;
    const a = 
      Math.sin(dLat/2) * Math.sin(dLat/2) +
      Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) * 
      Math.sin(dLon/2) * Math.sin(dLon/2);
    const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
    return R * c; 
  };

  const forceOfflineFromGps = (msg) => {
    geoBlockedRef.current = true;
    setIsOnline(false);
    setGpsPermissionMessage(msg || '');
    lastBroadcastPosRef.current = null;
    if (gpsWatchIdRef.current && typeof navigator !== 'undefined' && navigator.geolocation) {
      try {
        navigator.geolocation.clearWatch(gpsWatchIdRef.current);
      } catch (_) {}
      gpsWatchIdRef.current = null;
    }
    if (permissionWatchIdRef.current && typeof navigator !== 'undefined' && navigator.geolocation) {
      try {
        navigator.geolocation.clearWatch(permissionWatchIdRef.current);
      } catch (_) {}
      permissionWatchIdRef.current = null;
    }
  };

  const requestGoOffline = () => {
    geoBlockedRef.current = false;
    setIsOnline(false);
    setGpsPermissionMessage('');
    lastBroadcastPosRef.current = null;
    if (gpsWatchIdRef.current && typeof navigator !== 'undefined' && navigator.geolocation) {
      try {
        navigator.geolocation.clearWatch(gpsWatchIdRef.current);
      } catch (_) {}
      gpsWatchIdRef.current = null;
    }
    if (permissionWatchIdRef.current && typeof navigator !== 'undefined' && navigator.geolocation) {
      try {
        navigator.geolocation.clearWatch(permissionWatchIdRef.current);
      } catch (_) {}
      permissionWatchIdRef.current = null;
    }
  };

  const requestGoOnline = async () => {
    if (goingOnlineRef.current) return;
    goingOnlineRef.current = true;
    setGpsPermissionMessage('');
    try {
      if (typeof navigator === 'undefined' || !navigator.geolocation) {
        const msg = 'Geolocation is not supported in this browser.';
        setGpsPermissionMessage(msg);
        toast.error(msg);
        return;
      }
      await new Promise((resolve, reject) => {
        navigator.geolocation.getCurrentPosition(
          () => resolve(),
          (err) => reject(err),
          { enableHighAccuracy: true, timeout: 25000, maximumAge: 0 }
        );
      });
      geoBlockedRef.current = false;
      lastBroadcastPosRef.current = null;
      setIsOnline(true);
    } catch (err) {
      const code = err?.code;
      const msg =
        code === 1
          ? 'Location permission is required to go online.'
          : 'Could not read GPS. Enable location services and try again.';
      forceOfflineFromGps(msg);
      toast.error(msg);
    } finally {
      goingOnlineRef.current = false;
    }
  };

  const toggleOnline = () => {
    if (isOnline) requestGoOffline();
    else requestGoOnline();
  };

  /** Detect permission revoked / GPS blocked while rider thought they were online. */
  useEffect(() => {
    if (!isOnline || typeof navigator === 'undefined' || !navigator.geolocation) {
      if (permissionWatchIdRef.current) {
        try {
          navigator.geolocation.clearWatch(permissionWatchIdRef.current);
        } catch (_) {}
        permissionWatchIdRef.current = null;
      }
      return undefined;
    }
    permissionWatchIdRef.current = navigator.geolocation.watchPosition(
      () => {},
      (err) => {
        if (err?.code === 1 || err?.code === 2 || err?.code === 3) {
          const msg =
            err.code === 1
              ? 'Location permission is required to go online.'
              : 'GPS unavailable.';
          forceOfflineFromGps(msg);
          toast.error(msg);
        }
      },
      { enableHighAccuracy: false, maximumAge: 60000, timeout: 60000 }
    );
    return () => {
      if (permissionWatchIdRef.current && navigator.geolocation) {
        try {
          navigator.geolocation.clearWatch(permissionWatchIdRef.current);
        } catch (_) {}
        permissionWatchIdRef.current = null;
      }
    };
  }, [isOnline]);

  useEffect(() => {
    activeOrderRef.current = activeOrder || null;
    activeOrderIdRef.current = activeOrder?.order_id ?? null;
  }, [activeOrder]);

  const fetchRiderData = async () => {
    if (!riderToken || isLoggedOutRef.current || cleanupActiveRef.current || isPollingRef.current || pendingStatusUpdateRef.current || syncLockRef.current || wsProcessingRef.current || fetchInProgressRef.current) return;
    if (executionLockRef.current) return;
    
    // 1. Hydration Guard
    if (localStorage.getItem("auth_hydrated") !== "true") return;

    // Tab Visibility Optimization
    if (document.visibilityState === 'hidden' && activeOrder?.status !== 'OUT_FOR_DELIVERY') {
      return; 
    }

    executionLockRef.current = true;
    isPollingRef.current = true;
    fetchInProgressRef.current = true;
    syncLockRef.current = true;
    try {
      const assignedRes = await apiClient.get('/api/rider/orders');
      if (isLoggedOutRef.current || cleanupActiveRef.current) return;
      const assignedData = assignedRes?.data || {};
      const backendActiveOrders = Array.isArray(assignedData.active_orders) ? assignedData.active_orders : [];
      const backendAvailableOrders = Array.isArray(assignedData.available_orders) ? assignedData.available_orders : [];
      const backendActiveOrder = assignedData.active_order && typeof assignedData.active_order === 'object'
        ? assignedData.active_order
        : null;
      const backendRiderStatus = assignedData?.rider?.rider_status || "offline";

      applyRiderEvent({
        type: "FETCH_SNAPSHOT",
        data: {
          active_orders: backendActiveOrders,
          available_orders: backendAvailableOrders,
            active_order: backendActiveOrder && isActiveOrder(backendActiveOrder) ? backendActiveOrder : null,
          rider: { rider_status: backendRiderStatus }
        }
      });
      
      const statsRes = await apiClient.get('/api/rider/stats');
      if (isLoggedOutRef.current || cleanupActiveRef.current) return;
      if (statsRes?.success) setStats(statsRes.data || { completed_today: 0, earnings_today: 0, active_count: 0 });
      
    } catch (err) {
      console.error("[SYNC] Polling failure:", err);
      if (err?.silent || err?.authRequired || err?.status === 403 || err?.status === 401) {
        isLoggedOutRef.current = true;
        toast.error("Session expired.");
        logout();
        window.location.href = '/rider/login';
      }
    } finally {
      fullResyncRequestedRef.current = false;
      syncLockRef.current = false;
      isPollingRef.current = false;
      fetchInProgressRef.current = false;
      executionLockRef.current = false;
      setLoading(false);
    }
  };

  useEffect(() => {
    const hadToken = !!prevRiderTokenRef.current;
    const hasToken = !!riderToken;
    const restoredToken = !hadToken && hasToken;

    if (restoredToken) {
      // Rehydration recovery: explicitly clear idle gates and force immediate sync.
      cleanupActiveRef.current = false;
      isLoggedOutRef.current = false;
      isPollingRef.current = false;
      setLoading(true);
      if (navigator.onLine) {
        fetchRiderData();
      }
    }

    prevRiderTokenRef.current = riderToken || null;
  }, [riderToken]);

  // Visibility Change Handling
  useEffect(() => {
    if (!riderToken || isLoggedOutRef.current) return;
    const handleVisibility = () => {
      if (document.visibilityState === 'visible' && isOnline && riderToken && !isLoggedOutRef.current && !cleanupActiveRef.current) {
        console.log("[SYSTEM] Tab visible, instant resync...");
        fetchRiderData();
      }
    };
    document.addEventListener("visibilitychange", handleVisibility);
    return () => document.removeEventListener("visibilitychange", handleVisibility);
  }, [isOnline]);

  // Polling Lifecycle (Hardened)
  useEffect(() => {
    if (!riderToken || isLoggedOutRef.current) {
      setLoading(false);
      return;
    }
    if (isOnline) {
      fetchRiderData();
      pollingIntervalRef.current = setInterval(fetchRiderData, 18000); 
    } else {
      setLoading(false);
      clearDashboardState();
    }
    return () => {
      if (pollingIntervalRef.current) clearInterval(pollingIntervalRef.current);
    };
  }, [isOnline, riderToken]);

  // GPS Tracking (Production watchPosition Hardening)
  useEffect(() => {
    const startGps = () => {
      if (!riderToken || isLoggedOutRef.current || cleanupActiveRef.current || !isOnline || !activeOrder || activeOrder.status === 'DELIVERED') return;
      if (gpsWatchIdRef.current) return;

      // Tab visibility check: only pause GPS if not delivering
      if (document.visibilityState === 'hidden' && activeOrder.status !== 'OUT_FOR_DELIVERY') {
         return;
      }

      if (geoBlockedRef.current) return;
      if (typeof navigator !== 'undefined' && "geolocation" in navigator) {
        gpsWatchIdRef.current = navigator.geolocation.watchPosition(async (position) => {
          const { latitude, longitude, heading, speed } = position.coords;
          
          if (lastBroadcastPosRef.current) {
            const moveDist = calculateDistance(
              latitude, longitude, 
              lastBroadcastPosRef.current.lat, lastBroadcastPosRef.current.lng
            );
            if (moveDist < 10) return; 
          }

          const isInDelivery = normalizeStatus(activeOrder.status) === 'OUT_FOR_DELIVERY';
          if (isInDelivery) {
            try {
              await apiClient.post('/api/rider/location', { 
                lat: latitude, 
                lng: longitude,
                heading: heading || 0,
                speed: speed || 0
              });
              lastBroadcastPosRef.current = { lat: latitude, lng: longitude };
            } catch (err) {
              console.error("[GPS] Broadcast failed:", err);
            }
          }
        }, (err) => {
          if (err?.code === 1 || err?.code === 2 || err?.code === 3) {
            const msg =
              err.code === 1
                ? 'Location permission is required to go online.'
                : 'GPS unavailable.';
            forceOfflineFromGps(msg);
            toast.error(msg);
          }
        }, { enableHighAccuracy: true, timeout: 10000, maximumAge: 5000 });
      }
    };

    const stopGps = () => {
      if (gpsWatchIdRef.current && typeof navigator !== 'undefined' && navigator.geolocation) {
        navigator.geolocation.clearWatch(gpsWatchIdRef.current);
        gpsWatchIdRef.current = null;
      }
    };

    const handleVisibility = () => {
      if (document.visibilityState === 'visible') startGps();
      else if (activeOrder?.status !== 'OUT_FOR_DELIVERY') stopGps();
    };

    startGps();
    document.addEventListener("visibilitychange", handleVisibility);

    return () => {
      stopGps();
      document.removeEventListener("visibilitychange", handleVisibility);
    };
  }, [isOnline, activeOrder?.order_id, activeOrder?.status, riderToken]);

  const handleUpdateStatus = async (nextStatus, lat = null, lng = null) => {
    if (pendingStatusUpdateRef.current) return;
    if (!activeOrder?.order_id) return;
    
    const previousStatus = activeOrder.status;
    // Frontend does not enforce workflow rules; backend is authoritative.
    const previousTime = lastUpdateRef.current;
    
    pendingStatusUpdateRef.current = true;
    setIsUpdating(true);

    try {
      const res = await apiClient.put(`/api/rider/orders/${activeOrder.order_id}/status`, { 
        status: nextStatus,
        lat,
        lng
      });
      
      if (!res?.success) {
        toast.error(res?.message || "Status update failed");
        return;
      }
      applyRiderEvent({
        type: 'STATUS_CHANGE_RESPONSE',
        data: {
          order_id: activeOrder.order_id,
          status: nextStatus
        }
      });

      if (nextStatus === 'DELIVERED') {
        await fetchRiderData();
        toast.success("Order Delivered!");
      }
    } catch (err) {
      console.error("[MANUAL] Update failed:", err);
      const errorMsg = err?.detail || err?.message || "Conflict or network error";
      const errorLower = String(errorMsg).toLowerCase();
      if (err?.status === 400 || errorLower.includes('invalid transition')) {
        toast.error(`Status update blocked: ${errorMsg}`);
      } else {
        toast.error(errorMsg);
      }
      
      if (err.status === 409) fetchRiderData();
    } finally {
      pendingStatusUpdateRef.current = false;
      setIsUpdating(false);
    }
  };

  const handleAcceptOrder = async (orderId) => {
    try {
      setIsUpdating(true);
      console.log("[UI][STATE_UPDATE] Accepting order:", orderId);
      
      const res = await apiClient.post('/api/rider/accept_order', { order_id: orderId });
      
      if (res.success) {
        toast.success("Order Accepted! Drive safe.");
        // Authoritative resync
        await fetchRiderData();
      } else {
        throw new Error(res.message || "Acceptance failed");
      }
    } catch (err) {
      console.error("[RIDER] Accept failed:", err);
      toast.error(err.message || "Could not accept order");
      await fetchRiderData();
    } finally {
      setIsUpdating(false);
    }
  };

  // WebSocket Hardening (Enterprise Reconnect & Visibility Optimization)
  useEffect(() => {
    const intentionalCloseRef = { current: false };

    const connectWs = () => {
      if (!riderToken || isLoggedOutRef.current || cleanupActiveRef.current || !isOnline || intentionalCloseRef.current) return;
      if (fetchInProgressRef.current || executionLockRef.current) return;
      
      // 1. Hydration Guard
      if (localStorage.getItem("auth_hydrated") !== "true") return;

      if (!navigator.onLine) {
        setIsWsConnecting(false);
        return;
      }
      
      // 2. Strict Socket Dedup
      if (wsLockRef.current) return;
      if (wsConnectInFlightRef.current) return;
      if (socketRef.current && (socketRef.current.readyState === WebSocket.OPEN || socketRef.current.readyState === WebSocket.CONNECTING)) {
        return;
      }

      if (socketRef.current) {
        socketRef.current.close();
      }

      const wsUrl = `${WS_BASE_URL}/ws/rider?token=${riderToken}`;
      
      wsLockRef.current = true;
      wsConnectInFlightRef.current = true;
      setIsWsConnecting(true);
      const socket = new WebSocket(wsUrl);
      socketRef.current = socket;

      socket.onopen = () => {
        if (intentionalCloseRef.current || isLoggedOutRef.current || cleanupActiveRef.current) { socket.close(); return; }
        console.log("[WS] Connected.");
        wsConnectInFlightRef.current = false;
        setIsWsConnecting(false);
        reconnectCountRef.current = 0;
        if (!hasInitialWsSyncRef.current || fullResyncRequestedRef.current) {
          hasInitialWsSyncRef.current = true;
          fetchRiderData();
        }
      };

      socket.onmessage = (event) => {
        try {
          if (fetchInProgressRef.current || executionLockRef.current) return;
          executionLockRef.current = true;
          wsProcessingRef.current = true;
          const data = JSON.parse(event.data);
          if (isLoggedOutRef.current || cleanupActiveRef.current) return;
          if (syncLockRef.current) return;
          if (!data || typeof data !== 'object') return;

          if (data.event === 'ORDER_UPDATE' || data.type === 'ORDER_UPDATE' || data.type === 'tracking_update') {
            const payloadOrder = data.order && typeof data.order === 'object' ? data.order : data.data;
            if (payloadOrder && typeof payloadOrder === 'object' && payloadOrder.order_id) {
              const incomingStatus = payloadOrder.status?.current_status || payloadOrder.status;
              const incomingTimestamp = payloadOrder.status?.last_updated ? new Date(payloadOrder.status.last_updated).getTime() : Date.now();
              const payloadKey = JSON.stringify({ s: incomingStatus, t: incomingTimestamp, loc: payloadOrder.locations?.driver });
              if (lastPayloadRef.current === payloadKey) return;
              lastPayloadRef.current = payloadKey;
              applyRiderEvent({ type: 'ORDER_UPDATE', order: payloadOrder });
            }
          } else if (data.event === 'RIDER_STATUS_UPDATE' || data.type === 'RIDER_STATUS_UPDATE') {
            applyRiderEvent({
              type: 'RIDER_STATUS_UPDATE',
              rider_status: typeof data.rider_status === 'string' ? data.rider_status : 'offline'
            });
          } else if (data.event === 'ORDER_REMOVED' && data.order_id != null) {
            applyRiderEvent({ type: 'ORDER_REMOVED', order_id: data.order_id });
          }
        } catch (e) { console.error("[WS] Parse error:", e); }
        finally {
          wsProcessingRef.current = false;
          executionLockRef.current = false;
        }
      };

      socket.onclose = (event) => {
        if (intentionalCloseRef.current) return;
        wsConnectInFlightRef.current = false;
        setIsWsConnecting(true);
        socketRef.current = null;

        // STOP RECONNECT ON AUTH ERRORS
        const stopCodes = [4001, 4003, 1008, 4401];
        if (stopCodes.includes(event.code)) {
          console.error(`[WS] Fatal error ${event.code}. Stopping reconnect.`);
          isLoggedOutRef.current = true;
          toast.error("Session expired. Please login again.");
          logout();
          navigate('/rider/login');
          return;
        }
        
        if (reconnectCountRef.current < maxReconnects) {
          const backoff = Math.min(Math.pow(2, reconnectCountRef.current) * 1000, 15000);
          console.log(`[WS] Offline. Reconnecting in ${backoff}ms...`);
          reconnectTimeoutRef.current = setTimeout(() => {
            reconnectCountRef.current += 1;
            connectWs();
          }, backoff);
        } else {
          console.error("[WS] Max reconnect attempts reached.");
          setIsWsConnecting(false);
        }
      };

      socket.onerror = () => {
        wsConnectInFlightRef.current = false;
        socket.close();
      };
    };

    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible' && isOnline) {
        console.log("[WS] Tab visible. Reconnecting...");
        connectWs();
      }
    };

    const handleOnline = () => {
      console.log("[WS] Online. Reconnecting...");
      connectWs();
    };

    const handleOffline = () => {
      setIsWsConnecting(false);
      if (socketRef.current) socketRef.current.close();
    };

    window.addEventListener('online', handleOnline);
    window.addEventListener('offline', handleOffline);
    document.addEventListener('visibilitychange', handleVisibilityChange);

    connectWs();

    return () => {
      intentionalCloseRef.current = true;
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
        reconnectTimeoutRef.current = null;
      }
      wsConnectInFlightRef.current = false;
      setIsWsConnecting(false);
      if (socketRef.current) {
        socketRef.current.onopen = null;
        socketRef.current.onmessage = null;
        socketRef.current.onclose = null;
        socketRef.current.onerror = null;
        socketRef.current.close();
        socketRef.current = null;
      }
      
      window.removeEventListener('online', handleOnline);
      window.removeEventListener('offline', handleOffline);
      document.removeEventListener('visibilitychange', handleVisibilityChange);
    };
  }, [isOnline, riderToken]);

  if (!riderToken || isLoggedOutRef.current) {
    return null;
  }

  return (
    <div className="max-w-5xl mx-auto pb-12 font-sans">
      {/* Header Section */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-6 mb-8">
        <div>
          <h1 className="text-2xl font-black text-gray-900 uppercase tracking-tight">
            Welcome, <span className="text-[#f97316]">{safeText(riderUser?.name, 'Rider')}</span>
          </h1>
          <p className="text-gray-500 font-bold text-[10px] uppercase tracking-widest mt-1">QuickCrave Logistics Fleet • ID: {safeText(riderUser?.id, '---')}</p>
          {gpsPermissionMessage ? (
            <p className="text-red-600 text-xs font-bold mt-2 max-w-md">{gpsPermissionMessage}</p>
          ) : null}
        </div>
        
        <div className="flex items-center gap-3">
          {isWsConnecting && isOnline && (
            <div className="flex items-center gap-2 px-3 py-2 bg-orange-50 border border-orange-100 rounded-lg text-[#f97316] text-[10px] font-black uppercase tracking-widest animate-pulse">
              <Loader2 className="w-3 h-3 animate-spin" />
              Syncing...
            </div>
          )}
          <button 
            type="button"
            onClick={toggleOnline}
            className={`flex items-center gap-2 px-6 py-3 rounded-lg font-black transition-all uppercase tracking-widest text-xs ${
              isOnline 
              ? 'bg-[#f97316] text-white shadow-lg shadow-orange-500/20' 
              : 'bg-gray-200 text-gray-500'
            }`}
          >
            <Power className="w-4 h-4" />
            {isOnline ? `Online (${safeText(riderStatus, 'offline')})` : 'Offline'}
          </button>
        </div>
      </div>

      {!isOnline ? (
        <div className="bg-white border border-gray-100 rounded-lg p-12 text-center shadow-sm">
          <div className="w-20 h-20 bg-gray-50 rounded-full flex items-center justify-center mx-auto mb-6">
            <Power className="w-10 h-10 text-gray-300" />
          </div>
          <h2 className="text-xl font-black text-gray-900 uppercase tracking-tight mb-2">You are currently offline</h2>
          <p className="text-gray-500 font-medium mb-8">Go online to start receiving and managing deliveries.</p>
          <button 
            type="button"
            onClick={requestGoOnline}
            className="px-8 py-4 bg-[#f97316] text-white rounded-lg font-black uppercase tracking-widest text-sm hover:opacity-90 transition-all shadow-lg shadow-orange-500/20"
          >
            Go Online Now
          </button>
        </div>
      ) : (
        <div className="space-y-8">
          {/* Today Stats Section */}
          <section>
            <div className="flex items-center gap-3 mb-6">
              <div className="w-2 h-6 bg-[#f97316] rounded-full"></div>
              <h2 className="text-lg font-black text-gray-900 uppercase tracking-widest">Today Stats</h2>
            </div>
            
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
              <div className="bg-white border border-gray-100 p-6 rounded-lg shadow-sm">
                <div className="flex items-center justify-between mb-4">
                  <div className="p-2 bg-orange-50 rounded-lg">
                    <CheckCircle2 className="w-5 h-5 text-[#f97316]" />
                  </div>
                </div>
                <p className="text-[10px] font-black text-gray-400 uppercase tracking-widest mb-1">Completed</p>
                <h3 className="text-2xl font-black text-gray-900">{Number(stats?.completed_today ?? 0)}</h3>
              </div>
              
              <div className="bg-white border border-gray-100 p-6 rounded-lg shadow-sm">
                <div className="flex items-center justify-between mb-4">
                  <div className="p-2 bg-green-50 rounded-lg">
                    <IndianRupee className="w-5 h-5 text-green-600" />
                  </div>
                </div>
                <p className="text-[10px] font-black text-gray-400 uppercase tracking-widest mb-1">Today's Earnings</p>
                <h3 className="text-2xl font-black text-gray-900">₹{Number(stats?.earnings_today ?? 0).toFixed(2)}</h3>
              </div>

              <div className="bg-white border border-gray-100 p-6 rounded-lg shadow-sm">
                <div className="flex items-center justify-between mb-4">
                  <div className="p-2 bg-blue-50 rounded-lg">
                    <Clock className="w-5 h-5 text-blue-600" />
                  </div>
                </div>
                <p className="text-[10px] font-black text-gray-400 uppercase tracking-widest mb-1">Active Now</p>
                <h3 className="text-2xl font-black text-gray-900">{Number(stats?.active_count ?? 0)}</h3>
              </div>
            </div>
          </section>

          {/* Active Order Section */}
          <section>
            <div className="flex items-center gap-3 mb-6">
              <div className="w-2 h-6 bg-[#f97316] rounded-full"></div>
              <h2 className="text-lg font-black text-gray-900 uppercase tracking-widest">Active Delivery</h2>
            </div>
            
            {activeOrder ? (
              <div className="bg-white border border-gray-100 rounded-lg shadow-sm overflow-hidden">
                <div className="p-6 md:p-8">
                  <div className="flex flex-col md:flex-row justify-between gap-6 mb-8">
                    <div className="flex-1">
                      <div className="flex items-center gap-3 mb-4">
                        <span className="px-3 py-1 bg-orange-50 text-[#f97316] text-[10px] font-black rounded uppercase tracking-widest border border-orange-100">
                          Order #{activeOrder.order_id}
                        </span>
                        {activeOrder.status === 'NEAR_CUSTOMER_LOCATION' && (
                          <span className="flex items-center gap-1.5 px-3 py-1 bg-green-50 text-green-600 text-[10px] font-black rounded uppercase tracking-widest border border-green-100 animate-pulse">
                            <Navigation className="w-3 h-3" />
                            Arrived
                          </span>
                        )}
                      </div>
                      <h3 className="text-2xl font-black text-gray-900 mb-1">{safeText(activeOrder.customer_name, 'Customer')}</h3>
                      <div className="flex items-center gap-2 text-gray-500 font-bold text-sm">
                        <MapPin className="w-4 h-4 text-[#f97316]" />
                        <span>{typeof activeOrder.address === 'object' ? formatAddress(activeOrder.address) || 'Address not provided' : safeText(activeOrder.address, 'Address not provided')}</span>
                      </div>
                    </div>
                    
                    <div className="flex flex-col items-end gap-2">
                      <div className="text-right">
                        <p className="text-[10px] font-black text-gray-400 uppercase tracking-widest mb-1">Delivery ETA</p>
                        <p className="text-sm font-black text-[#f97316]">{getEtaCountdownText(activeOrder)}</p>
                      </div>
                      <div className="text-right">
                        <p className="text-[10px] font-black text-gray-400 uppercase tracking-widest mb-1">Status</p>
                        <div className={`inline-flex items-center gap-2 px-4 py-2 rounded-lg font-black text-xs uppercase tracking-widest border ${getStatusUI(activeOrder.status).color}`}>
                          <span className={`w-2 h-2 rounded-full ${getStatusUI(activeOrder.status).dot}`}></span>
                          {getStatusLabel(activeOrder.status)}
                        </div>
                      </div>
                    </div>
                  </div>

                  {/* Payment Info - Read Only */}
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8 p-4 bg-gray-50 rounded-lg">
                    <div>
                      <p className="text-[10px] font-black text-gray-400 uppercase tracking-widest mb-1">Total Amount</p>
                      <p className="text-sm font-black text-gray-900">₹{getOrderTotalAmount(activeOrder)}</p>
                    </div>
                    <div>
                      <p className="text-[10px] font-black text-gray-400 uppercase tracking-widest mb-1">Method</p>
                      <p className="text-sm font-black text-gray-900 uppercase">{safeText(activeOrder.payment_method, 'COD')}</p>
                    </div>
                    <div>
                      <p className="text-[10px] font-black text-gray-400 uppercase tracking-widest mb-1">Payment Status</p>
                      <p className={`text-sm font-black uppercase ${activeOrder.payment_status === 'PAID' ? 'text-green-600' : 'text-orange-500'}`}>
                        {safeText(activeOrder.payment_status, 'Pending')}
                      </p>
                    </div>
                    <div>
                      <p className="text-[10px] font-black text-gray-400 uppercase tracking-widest mb-1">Distance</p>
                      <p className="text-sm font-black text-gray-900">1.2 KM</p>
                    </div>
                  </div>

                  {/* Actions */}
                  <div className="flex flex-wrap gap-3">
                    {/* UI GUARD: Ensure activeOrder exists before rendering action buttons */}
                    {(!activeOrder || !activeOrder.order_id) ? null : (
                      <>
                        {normalizeRiderStatusForFlow(activeOrder.status) === 'ACCEPTED' && (
                          <button 
                            onClick={() => handleUpdateStatus('ORDER_PICKED_UP')}
                            disabled={isUpdating}
                            className="flex-1 bg-[#f97316] text-white px-6 py-4 rounded-lg font-black uppercase tracking-widest text-sm hover:opacity-90 transition-all shadow-lg shadow-orange-500/20 disabled:opacity-50"
                          >
                            Confirm Pickup
                          </button>
                        )}
                        {normalizeRiderStatusForFlow(activeOrder.status) === 'ASSIGNED' && (
                          <button
                            onClick={() => handleAcceptOrder(activeOrder.order_id)}
                            disabled={isUpdating}
                            className="flex-1 bg-[#f97316] text-white px-6 py-4 rounded-lg font-black uppercase tracking-widest text-sm hover:opacity-90 transition-all shadow-lg shadow-orange-500/20 disabled:opacity-50"
                          >
                            Accept Order
                          </button>
                        )}
                        {normalizeRiderStatusForFlow(activeOrder.status) === 'FOOD_READY' && (
                          <div className="flex-1 text-center py-4 bg-orange-50 text-[#f97316] rounded-lg font-black uppercase tracking-widest text-xs border border-orange-100">
                            Waiting for rider assignment.
                          </div>
                        )}
                        {normalizeRiderStatusForFlow(activeOrder.status) === 'ORDER_PICKED_UP' && (
                          <button 
                            onClick={() => handleUpdateStatus('OUT_FOR_DELIVERY')}
                            disabled={isUpdating}
                            className="flex-1 bg-[#f97316] text-white px-6 py-4 rounded-lg font-black uppercase tracking-widest text-sm hover:opacity-90 transition-all shadow-lg shadow-orange-500/20 disabled:opacity-50"
                          >
                            On The Way
                          </button>
                        )}
                        {normalizeRiderStatusForFlow(activeOrder.status) === 'OUT_FOR_DELIVERY' && (
                          <button 
                            onClick={() => handleUpdateStatus('DELIVERED')}
                            disabled={isUpdating}
                            className="flex-1 bg-green-600 text-white px-6 py-4 rounded-lg font-black uppercase tracking-widest text-sm hover:opacity-90 transition-all shadow-lg shadow-green-500/20 disabled:opacity-50"
                          >
                            Delivered
                          </button>
                        )}
                      </>
                    )}
                    <a 
                      href={`tel:${activeOrder?.customer_phone}`}
                      className="px-6 py-4 bg-white border border-gray-200 text-gray-700 rounded-lg font-black uppercase tracking-widest text-sm hover:bg-gray-50 transition-all flex items-center justify-center gap-2"
                    >
                      <Phone className="w-4 h-4 text-gray-400" />
                      Call Customer
                    </a>
                  </div>
                </div>
              </div>
            ) : (
              <div className="bg-white border border-dashed border-gray-200 rounded-lg p-12 text-center">
                <Bike className="w-12 h-12 text-gray-200 mx-auto mb-4" />
                <p className="text-gray-400 font-bold uppercase tracking-widest text-sm">No active delivery at the moment</p>
              </div>
            )}
          </section>

          {/* New Orders (Radar) */}
          <section>
            <div className="flex items-center justify-between mb-6">
              <div className="flex items-center gap-3">
                <div className="w-2 h-6 bg-gray-300 rounded-full"></div>
                <h2 className="text-lg font-black text-gray-900 uppercase tracking-widest">Available Orders</h2>
              </div>
              <span className="px-3 py-1 bg-gray-100 text-gray-500 text-[10px] font-black rounded uppercase tracking-widest">
                {safeAvailableOrders.length} Found
              </span>
            </div>

            {safeAvailableOrders.length > 0 ? (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {safeAvailableOrders.map((order) => (
                  <div key={order.order_id} className="bg-white border border-gray-100 rounded-lg p-6 shadow-sm hover:border-orange-200 transition-all group">
                    <div className="flex justify-between items-start mb-4">
                      <div>
                        <span className="text-[10px] font-black text-[#f97316] uppercase tracking-widest">Order #{order.order_id}</span>
                        <h3 className="font-black text-gray-900 mt-1">{safeText(order.restaurant_name, 'QuickCrave Kitchen')}</h3>
                      </div>
                      <div className="text-right">
                        <p className="text-sm font-black text-gray-900">₹{getOrderTotalAmount(order)}</p>
                        <p className="text-[10px] font-bold text-gray-400 uppercase tracking-tighter">{safeText(order.payment_method, 'COD')}</p>
                      </div>
                    </div>
                    <div className="flex items-center gap-2 text-gray-500 text-xs font-bold mb-6">
                      <MapPin className="w-3.5 h-3.5 text-gray-400" />
                      <span className="truncate">{typeof order.address === 'object' ? formatAddress(order.address) || 'Standard Delivery' : safeText(order.address, 'Standard Delivery')}</span>
                    </div>
                    <div className="mb-4">
                      <p className="text-[10px] font-black text-gray-400 uppercase tracking-widest mb-1">Delivery ETA</p>
                      <p className="text-sm font-black text-[#f97316]">{getEtaCountdownText(order)}</p>
                    </div>
                    <button 
                      onClick={() => handleAcceptOrder(order.order_id)}
                      className="w-full py-3 bg-white border-2 border-gray-100 group-hover:border-[#f97316] group-hover:bg-[#f97316] group-hover:text-white text-gray-900 rounded-lg font-black uppercase tracking-widest text-xs transition-all"
                    >
                      Accept Order
                    </button>
                  </div>
                ))}
              </div>
            ) : (
              <div className="bg-gray-50 rounded-lg p-12 text-center border border-gray-100">
                <p className="text-gray-400 font-bold uppercase tracking-widest text-xs">Waiting for new orders in your area...</p>
              </div>
            )}
          </section>

          {/* Delivery History Section */}
          <section>
            <div className="flex items-center justify-between mb-6">
              <div className="flex items-center gap-3">
                <div className="w-2 h-6 bg-gray-300 rounded-full"></div>
                <h2 className="text-lg font-black text-gray-900 uppercase tracking-widest">Delivery History</h2>
              </div>
              <Link 
                to="/rider/history" 
                className="text-[#f97316] text-[10px] font-black uppercase tracking-widest hover:underline"
              >
                View All
              </Link>
            </div>
            
            <div className="bg-white border border-gray-100 rounded-lg p-6 shadow-sm flex items-center justify-between">
              <div className="flex items-center gap-4">
                <div className="p-3 bg-gray-50 rounded-full">
                  <Package className="w-6 h-6 text-gray-400" />
                </div>
                <div>
                  <h3 className="font-black text-gray-900">Past Deliveries</h3>
                  <p className="text-xs text-gray-500 font-bold">Track your performance and earnings history</p>
                </div>
              </div>
              <Link 
                to="/rider/history" 
                className="p-3 bg-gray-50 hover:bg-orange-50 text-gray-400 hover:text-[#f97316] rounded-lg transition-all"
              >
                <ChevronRight className="w-5 h-5" />
              </Link>
            </div>
          </section>
        </div>
      )}
    </div>
  );
};

export default RiderDashboard;
