import React, { useState, useEffect, useMemo, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  Package, MapPin, CheckCircle2, Clock, Loader2, IndianRupee,
  ArrowLeft, Phone, Navigation, Home, Bike, AlertCircle,
  Star, ChevronRight, User, Search, ArrowRight, ShoppingBag,
  UtensilsCrossed, PackageCheck, HandHelping, Flag
} from 'lucide-react';
import { MapContainer, TileLayer, Marker, Polyline, useMap } from "react-leaflet";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { normalizeStatus, STATUS_STEPS, STATUS_PRIORITY, compareStatus, getEtaCountdownText } from '../services/statusService';
import { useAuth } from '../hooks/useAuth';
import { getRoute } from '../services/mapService';
import apiClient from '../services/apiClient';
import { WS_BASE_URL } from '../config/constants';
import { toast } from 'react-hot-toast';

// Fix for Leaflet default marker icons in React
import iconUrl from 'leaflet/dist/images/marker-icon.png';
import iconShadow from 'leaflet/dist/images/marker-shadow.png';

let DefaultIcon = L.icon({
  iconUrl: iconUrl,
  shadowUrl: iconShadow,
  iconSize: [25, 41],
  iconAnchor: [12, 41]
});

L.Marker.prototype.options.icon = DefaultIcon;

// Rider marker (delivery partner)
const driverIcon = new L.Icon({
  iconUrl: "https://cdn-icons-png.flaticon.com/512/2972/2972185.png",
  iconSize: [50, 50],
  iconAnchor: [25, 25],
  popupAnchor: [0, -25]
});

/** Fixed orange marker at customer delivery address (from order snapshot / saved address). */
const destinationIcon = L.divIcon({
  className: 'track-order-destination-marker',
  html: '<div style="width:28px;height:28px;background:#ff6b00;border:3px solid #fff;border-radius:50%;box-shadow:0 2px 10px rgba(0,0,0,0.35);"></div>',
  iconSize: [28, 28],
  iconAnchor: [14, 14],
});

const ROUTE_FROM_RIDER_STATUSES = new Set([
  'ASSIGNED',
  'PICKED_UP',
  'ON_WAY',
  'ARRIVING',
]);

/** Read rider lat/lng — prefer order snapshot (WS/API), then live driver state. */
function readRiderCoords(order, driverLocation) {
  const rl = order?.rider_location;
  const r = order?.rider;
  const lat = parseFloat(
    rl?.latitude ?? rl?.lat ?? r?.lat ?? driverLocation?.lat
  );
  const lng = parseFloat(
    rl?.longitude ?? rl?.lng ?? r?.lng ?? driverLocation?.lng
  );
  return isValidLatLngPair(lat, lng) ? { lat, lng } : null;
}

function isValidLatLngPair(lat, lng) {
  if (lat === null || lat === undefined || lng === null || lng === undefined) return false;
  const la = Number(lat);
  const ln = Number(lng);
  if (!Number.isFinite(la) || !Number.isFinite(ln)) return false;
  return la >= -90 && la <= 90 && ln >= -180 && ln <= 180;
}

function coordRejectionReason(rawLat, rawLng, parsedLat, parsedLng) {
  if (rawLat === undefined && rawLng === undefined) return 'missing';
  if (rawLat === null || rawLng === null) return 'null';
  if (!Number.isFinite(parsedLat) || !Number.isFinite(parsedLng)) return 'nan';
  if (parsedLat < -90 || parsedLat > 90 || parsedLng < -180 || parsedLng > 180) return 'out_of_bounds';
  return 'unknown';
}

/**
 * Resolve customer destination from order payload (priority order preserved).
 * Accepts numeric strings; rejects only null/undefined/NaN/out-of-bounds.
 */
function resolveDeliveryCoords(order) {
  if (!order) return null;

  const candidates = [
    {
      source: 'delivery_location',
      lat: order?.delivery_location?.latitude,
      lng: order?.delivery_location?.longitude,
    },
    {
      source: 'delivery_location.lat',
      lat: order?.delivery_location?.lat,
      lng: order?.delivery_location?.lng,
    },
    {
      source: 'locations.user',
      lat: order?.locations?.user?.lat,
      lng: order?.locations?.user?.lng,
    },
    {
      source: 'user_lat',
      lat: order?.user_lat,
      lng: order?.user_lng,
    },
    {
      source: 'address',
      lat: order?.address?.latitude,
      lng: order?.address?.longitude,
    },
    {
      source: 'delivery_address',
      lat: order?.delivery_address?.latitude,
      lng: order?.delivery_address?.longitude,
    },
    {
      source: 'user_address',
      lat: order?.user_address?.latitude,
      lng: order?.user_address?.longitude,
    },
  ];

  const rejections = [];
  for (const { source, lat, lng } of candidates) {
    if (lat === undefined && lng === undefined) continue;
    const parsedLat = parseFloat(lat);
    const parsedLng = parseFloat(lng);
    if (isValidLatLngPair(parsedLat, parsedLng)) {
      return { lat: parsedLat, lng: parsedLng, source };
    }
    rejections.push({
      source,
      raw: { lat, lng },
      reason: coordRejectionReason(lat, lng, parsedLat, parsedLng),
    });
  }
  return { rejections };
}

/** Keep valid delivery snapshot coords when WS/API payloads omit them. */
function mergeOrderPreserveDeliveryCoords(prev, incoming) {
  if (!incoming) return incoming ?? prev;
  const readDelivery = (o) => {
    const resolved = resolveDeliveryCoords(o);
    return resolved?.lat != null ? { lat: resolved.lat, lng: resolved.lng } : null;
  };
  const inc = readDelivery(incoming);
  if (inc) return incoming;
  const kept = readDelivery(prev);
  if (!kept) return incoming;
  return {
    ...incoming,
    user_lat: kept.lat,
    user_lng: kept.lng,
    delivery_location: {
      ...(incoming.delivery_location || {}),
      latitude: kept.lat,
      longitude: kept.lng,
      lat: kept.lat,
      lng: kept.lng,
    },
    address: {
      ...(incoming.address || {}),
      latitude: kept.lat,
      longitude: kept.lng,
    },
    locations: {
      ...(incoming.locations || {}),
      user: {
        ...(incoming.locations?.user || {}),
        lat: kept.lat,
        lng: kept.lng,
      },
    },
  };
}

// Helper: fit map when destination/rider/route context changes — not on every live rider tick.
function FitBounds({ route, points, orderId, fitKey }) {
  const map = useMap();
  const lastFitKeyRef = useRef('');

  useEffect(() => {
    lastFitKeyRef.current = '';
  }, [orderId]);

  useEffect(() => {
    const timer = setTimeout(() => {
      map.invalidateSize();
    }, 250);
    return () => clearTimeout(timer);
  }, [map, orderId]);

  useEffect(() => {
    if (!fitKey || lastFitKeyRef.current === fitKey) return;
    lastFitKeyRef.current = fitKey;

    if (route && route.length > 1) {
      map.fitBounds(L.latLngBounds(route), { padding: [50, 50], maxZoom: 16 });
    } else if (points && points.length > 1) {
      map.fitBounds(L.latLngBounds(points), { padding: [50, 50], maxZoom: 16 });
    } else if (points && points.length === 1) {
      map.setView(points[0], 15);
    }
  }, [fitKey, route, points, map]);

  return null;
}

const TrackOrderPage = () => {
  const { orderId } = useParams();
  const navigate = useNavigate();
  const { customerToken } = useAuth();
  const [order, setOrder] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const [driverLocation, setDriverLocation] = useState(null);
  const [interpolatedDriverPos, setInterpolatedDriverPos] = useState(null);
  const [status, setStatus] = useState("PLACED");
  const [lastUpdate, setLastUpdate] = useState(new Date());
  const [connectionStatus, setConnectionStatus] = useState('connecting');
  const [route, setRoute] = useState([]);
  const [eta, setEta] = useState(null);
  const [distance, setDistance] = useState(null);
  const [driverBearing, setDriverBearing] = useState(0);
  const [activeRiderId, setActiveRiderId] = useState(null);
  const [isOffline, setIsOffline] = useState(false);

  const [searchInput, setSearchInput] = useState('');
  // Refs (Phase 3 Hardening)
  const socketRef = useRef(null);
  const reconnectTimeoutRef = useRef(null);
  const pollingIntervalRef = useRef(null);
  const lastUpdateRef = useRef(0);
  const isPollingRef = useRef(false);
  const previousPosRef = useRef(null);
  const lastPayloadRef = useRef(""); // WS dedup
  const interpolationRef = useRef({
    startPos: null,
    endPos: null,
    startTime: 0,
    duration: 1500
  });
  const riderVersionRef = useRef({});

  const [reconnectDelay, setReconnectDelay] = useState(1000);
  const reconnectAttemptRef = useRef(0);
  const MAX_RECONNECT_ATTEMPTS = 10;
  const intentionalCloseRef = useRef(false);
  const orderSnapshotRef = useRef(null);
  const invalidDeliveryCoordWarnedRef = useRef(false);
  const lastDestLogKeyRef = useRef('');
  const lastRouteLogKeyRef = useRef('');

  useEffect(() => {
    orderSnapshotRef.current = order;
  }, [order]);

  // Reset state on orderId change
  useEffect(() => {
    invalidDeliveryCoordWarnedRef.current = false;
    lastDestLogKeyRef.current = '';
    lastRouteLogKeyRef.current = '';
    lastUpdateRef.current = 0;
    lastPayloadRef.current = "";
    previousPosRef.current = null;
    interpolationRef.current = { startPos: null, endPos: null, startTime: 0, duration: 1500 };
    setDriverLocation(null);
    setInterpolatedDriverPos(null);
    setEta(null);
    setDistance(null);
  }, [orderId]);

  // Animation Loop for Smooth Movement
  useEffect(() => {
    let animId;
    const animate = (time) => {
      const { startPos, endPos, startTime, duration } = interpolationRef.current;

      if (startPos && endPos && startTime > 0) {
        const elapsed = time - startTime;
        const t = Math.min(elapsed / duration, 1);

        const easeOut = (x) => 1 - Math.pow(1 - x, 3);
        const smoothT = easeOut(t);

        const currentLat = startPos.lat + (endPos.lat - startPos.lat) * smoothT;
        const currentLng = startPos.lng + (endPos.lng - startPos.lng) * smoothT;

        if (previousPosRef.current) {
          const dy = currentLat - previousPosRef.current.lat;
          const dx = currentLng - previousPosRef.current.lng;
          if (Math.abs(dx) > 0.000001 || Math.abs(dy) > 0.000001) {
            const angle = Math.atan2(dx, dy) * (180 / Math.PI);
            setDriverBearing(angle);
          }
        }
        previousPosRef.current = { lat: currentLat, lng: currentLng };

        setInterpolatedDriverPos({ lat: currentLat, lng: currentLng });

        if (t < 1) {
          animId = requestAnimationFrame(animate);
        }
      } else if (endPos) {
        setInterpolatedDriverPos(endPos);
      }
    };

    animId = requestAnimationFrame(animate);
    return () => cancelAnimationFrame(animId);
  }, []);

  /**
   * CENTRAL SYNC LOGIC (Rule: Latest Timestamp + Priority Wins)
   * TrackOrderPage MUST ONLY use backend-confirmed data.
   */
  const syncOrderState = (data, source = "POLLING") => {
    if (!data) return;

    const statusObj = data.status_full || data.status;
    const incomingStatus = statusObj?.current_status || statusObj;
    const incomingTimestamp = statusObj?.last_updated ? new Date(statusObj.last_updated).getTime() : Date.now();

    // 1. DEDUPLICATION
    const payloadKey = JSON.stringify({
      s: incomingStatus,
      t: incomingTimestamp,
      rlat: data.rider_location?.latitude ?? data.rider?.lat ?? data.driver_lat,
      rlng: data.rider_location?.longitude ?? data.rider?.lng ?? data.driver_lng,
      p: data.payment_status
    });
    if (source === "WS" && lastPayloadRef.current === payloadKey) return;
    lastPayloadRef.current = payloadKey;

    // 2. SAFETY CHECK: "Version", "Latest Timestamp", "Status Priority"
    const incomingVersion = data.version || statusObj?.version || 1;
    const currentVersion = order?.version || 1;

    if (order && incomingVersion < currentVersion) {
      console.warn(`[SYNC] Blocking stale version update: v${incomingVersion} < v${currentVersion}`);
      return;
    }

    // RULE: Only newer timestamp OR strictly higher priority status allowed.
    const isNewer = incomingTimestamp > lastUpdateRef.current;
    const isHigherPriority = compareStatus(incomingStatus, status) > 0;
    const isSamePriority = compareStatus(incomingStatus, status) === 0;

    // Rider GPS always applied when present (independent of status/version gate)
    const riderCoords = readRiderCoords(data, null);
    if (riderCoords) {
      const newPos = riderCoords;
      interpolationRef.current = {
        startPos: interpolatedDriverPos || newPos,
        endPos: newPos,
        startTime: performance.now(),
        duration: 2000
      };
      setDriverLocation(newPos);
    }

    if (!order || incomingVersion > currentVersion || isHigherPriority || (isSamePriority && isNewer)) {
      lastUpdateRef.current = incomingTimestamp;
      const normalized = normalizeStatus(statusObj);

      setStatus(normalized);

      if (data.activeRiderId || data.rider?.riderId) {
        setActiveRiderId(data.activeRiderId || data.rider.riderId);
      }
      if (data.rider?.status) {
        setIsOffline(data.rider.status === 'offline');
      }

      // Update payment status if provided
      if (data.payment_status || data.status_full?.payment_status) {
        const newPayStatus = data.payment_status || data.status_full?.payment_status;
        setOrder(prev => prev ? { ...prev, payment_status: newPayStatus } : prev);
      }

      setLastUpdate(new Date());
    } else {
      console.warn(`[SYNC] Blocking stale update or regression: ${status} (${lastUpdateRef.current}) -> ${incomingStatus} (${incomingTimestamp})`);
    }
  };

  // NOTE: visibilitychange is handled inside the WebSocket effect below.
  // Keeping a second listener here would cause double-fetches on tab-restore.
  // The WS effect's handleVisibilityChange calls connect() which also triggers fetchOrderDetails on open.

  // WebSocket Hardening (Enterprise Reconnect & Visibility Optimization)
  useEffect(() => {
    let heartbeatInterval = null;
    let cleanupCalled = false;
    intentionalCloseRef.current = false;
    reconnectAttemptRef.current = 0; // Reset attempts on new connection cycle

    const connect = () => {
      // Do NOT gate on `loading` — WS must be able to connect once orderId and token are ready
      if (!customerToken || !orderId || cleanupCalled || intentionalCloseRef.current) return;

      // 1. Hydration Guard
      if (localStorage.getItem("auth_hydrated") !== "true") return;

      if (!navigator.onLine) {
        setConnectionStatus('offline');
        return;
      }

      // 2. Strict Socket Dedup
      if (socketRef.current && (socketRef.current.readyState === WebSocket.OPEN || socketRef.current.readyState === WebSocket.CONNECTING)) {
        return;
      }

      if (socketRef.current) {
        socketRef.current.close();
        socketRef.current = null;
      }

      console.log(`[WS][CONNECTING] order=${orderId}`);
      setConnectionStatus('connecting');

      // Use localStorage directly for the most current token state
      const token = localStorage.getItem("customerToken");
      const socket = new WebSocket(`${WS_BASE_URL}/ws/track/${orderId}?token=${token}`);
      socketRef.current = socket;

      socket.onopen = () => {
        if (cleanupCalled) { socket.close(); return; }
        console.log(`[WS][CONNECTED] order=${orderId}`);
        setConnectionStatus('connected');
        reconnectAttemptRef.current = 0;
        heartbeatInterval = setInterval(() => {
          if (socket.readyState === WebSocket.OPEN) socket.send("ping");
        }, 15000);
        fetchOrderDetails();
      };

      socket.onmessage = (event) => {
        if (event.data === "pong") return;
        try {
          const data = JSON.parse(event.data);
          if (data.event === 'ORDER_REMOVED' && Number(data.order_id) === Number(orderId)) {
            toast.success('This order was removed.');
            intentionalCloseRef.current = true;
            navigate('/orders');
            return;
          }
          if (data.event === 'ORDER_UPDATE' || data.type === 'tracking_update') {
            const fullOrder = data.data && data.data.order_id ? data.data : data;
            const incomingVersion = fullOrder?.version || data.version || 0;
            const currentVersion = orderSnapshotRef.current?.version || 0;
            const prev = orderSnapshotRef.current;
            const newLat = fullOrder?.rider_location?.latitude ?? fullOrder?.rider?.lat;
            const newLng = fullOrder?.rider_location?.longitude ?? fullOrder?.rider?.lng;
            const oldLat = prev?.rider_location?.latitude ?? prev?.rider?.lat;
            const oldLng = prev?.rider_location?.longitude ?? prev?.rider?.lng;
            const riderMoved =
              newLat != null &&
              newLng != null &&
              (Number(newLat) !== Number(oldLat) || Number(newLng) !== Number(oldLng));
            if (incomingVersion <= currentVersion && !riderMoved) return;
            const mergedOrder = mergeOrderPreserveDeliveryCoords(prev, fullOrder);
            setOrder(mergedOrder);
            syncOrderState(mergedOrder, "WS");
          } else if (data.event === 'RIDER_STATUS_UPDATE') {
            const riderId = data.rider_id;
            const incomingVersion = data.version || 0;
            const currentRiderVersion = riderVersionRef.current[riderId] || 0;
            if (incomingVersion <= currentRiderVersion) return;
            riderVersionRef.current[riderId] = incomingVersion;

            setOrder(prev => {
              if (!prev?.rider || prev.rider.id !== riderId) return prev;
              const nextRiderStatus = data.rider_status ?? prev.rider.status;
              setIsOffline(nextRiderStatus === 'offline');
              const nextLat = data.lat ?? prev.rider.lat;
              const nextLng = data.lng ?? prev.rider.lng;
              const upd = {
                ...prev,
                rider: {
                  ...prev.rider,
                  status: nextRiderStatus,
                  lat: nextLat,
                  lng: nextLng,
                  heading: data.heading ?? prev.rider.heading,
                  updated_at: data.updated_at ?? prev.rider.updated_at
                },
                rider_location:
                  nextLat != null && nextLng != null
                    ? { latitude: parseFloat(nextLat), longitude: parseFloat(nextLng) }
                    : prev.rider_location
              };
              return upd;
            });

            const glat = data.lat != null ? parseFloat(data.lat) : null;
            const glng = data.lng != null ? parseFloat(data.lng) : null;
            if (
              isValidLatLngPair(glat, glng) &&
              orderSnapshotRef.current?.rider?.id === riderId
            ) {
              const newPos = { lat: glat, lng: glng };
              interpolationRef.current = {
                startPos: previousPosRef.current || newPos,
                endPos: newPos,
                startTime: performance.now(),
                duration: 2000
              };
              setDriverLocation(newPos);
            }
          }
        } catch (e) { console.error('[WS] Parse error:', e); }
      };

      socket.onclose = (event) => {
        if (cleanupCalled || intentionalCloseRef.current) return;

        console.log(`[WS][DISCONNECTED] order=${orderId} code=${event.code}`);
        clearInterval(heartbeatInterval);
        socketRef.current = null;

        // AUTH FAILURE CODES — do NOT reconnect
        const AUTH_FAILURE_CODES = [4001, 1008, 4401];
        if (AUTH_FAILURE_CODES.includes(event.code)) {
          console.warn(`[WS][AUTH_FAILED] code=${event.code} — halting reconnect loop`);
          intentionalCloseRef.current = true;
          setConnectionStatus('error');

          if (event.code === 4001) {
            setError('Session expired. Please login again.');
            // Clear expired token to prevent immediate loop on reload
            localStorage.removeItem("customerToken");
            setTimeout(() => navigate('/login'), 2500);
          }
          return;
        }

        // Hard cap
        if (reconnectAttemptRef.current >= MAX_RECONNECT_ATTEMPTS) {
          console.warn(`[WS][MAX_RECONNECT_REACHED] ${MAX_RECONNECT_ATTEMPTS} attempts exhausted.`);
          setConnectionStatus('error');
          return;
        }

        // NETWORK FAILURE — exponential backoff reconnect
        setConnectionStatus('reconnecting');
        const delay = Math.min(Math.pow(2, reconnectAttemptRef.current) * 1000, 15000);
        clearTimeout(reconnectTimeoutRef.current);
        console.log(`[WS][RECONNECT_ATTEMPT] ${reconnectAttemptRef.current + 1}/${MAX_RECONNECT_ATTEMPTS} in ${Math.round(delay / 1000)}s`);
        reconnectTimeoutRef.current = setTimeout(() => {
          reconnectAttemptRef.current++;
          connect();
        }, delay);
      };

      socket.onerror = () => socket.close();
    };

    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') {
        console.log("[WS] Tab visible. Instant resync.");
        connect();
      }
    };

    const handleOnline = () => {
      console.log("[WS] Browser online. Reconnecting...");
      connect();
    };

    const handleOffline = () => {
      setConnectionStatus('offline');
      if (socketRef.current) socketRef.current.close();
    };

    window.addEventListener('online', handleOnline);
    window.addEventListener('offline', handleOffline);
    document.addEventListener('visibilitychange', handleVisibilityChange);

    connect();

    return () => {
      cleanupCalled = true;
      intentionalCloseRef.current = true;
      if (socketRef.current) {
        socketRef.current.close();
        socketRef.current = null;
      }
      clearTimeout(reconnectTimeoutRef.current);
      clearInterval(heartbeatInterval);
      window.removeEventListener('online', handleOnline);
      window.removeEventListener('offline', handleOffline);
      document.removeEventListener('visibilitychange', handleVisibilityChange);
    };
  }, [orderId, customerToken]);

  // Fetch Order Details (Polling Hardened)
  const fetchOrderDetails = async () => {
    // IMPORTANT: Do NOT check `loading` here — this function is what clears loading.
    // Checking `loading` caused a deadlock: loading===true → bail → setLoading never called.
    if (!customerToken || !orderId || orderId === 'undefined' || isPollingRef.current) return;

    // 1. Hydration Guard — with fallback retry for first-render timing edge case
    if (localStorage.getItem("auth_hydrated") !== "true") {
      // Auth context may not have fired its useEffect yet; retry after a short delay
      setTimeout(() => {
        isPollingRef.current = false;
        fetchOrderDetails();
      }, 300);
      return;
    }

    // Tab Visibility Optimization
    if (document.visibilityState === 'hidden') return;

    isPollingRef.current = true;
    try {
      const response = await apiClient.get(`/api/order/${orderId}`);
      // Backend returns the order object directly (no success wrapper on this endpoint)
      const data = response?.success ? response.data : response;
      if (data && data.order_id) {
        const merged = mergeOrderPreserveDeliveryCoords(orderSnapshotRef.current, data);
        setOrder(merged);
        syncOrderState(merged, "POLLING");
      }
    } catch (err) {
      if (err?.silent) {
        // Silent skip — do NOT leave spinner stuck; clear loading so UI is visible
        setLoading(false);
        return;
      }

      console.error("[SYNC] Polling error:", err);
      if (err?.status === 403 || err?.detail?.includes('denied')) setError("This order does not belong to your account");
      else if (err?.status === 404) setError("Order not found");
      else setError(null); // Let the search UI show instead of blank
    } finally {
      isPollingRef.current = false;
      setLoading(false); // Always clear loading — success or failure
    }
  };

  useEffect(() => {
    if (orderId && orderId !== 'undefined') {
      // Small delay to ensure auth hydration useEffect has fired before first fetch
      const initTimer = setTimeout(() => fetchOrderDetails(), 100);
      pollingIntervalRef.current = setInterval(fetchOrderDetails, 12000);
      return () => {
        clearTimeout(initTimer);
        if (pollingIntervalRef.current) clearInterval(pollingIntervalRef.current);
      };
    } else {
      // No orderId in URL — stop spinner immediately so the search UI appears
      setLoading(false);
    }
  }, [orderId]);

  const handleSearch = (e) => {
    e.preventDefault();
    if (!searchInput.trim()) return;
    navigate(`/track-order/${searchInput.trim()}`);
  };

  /** Delivery destination — multi-source resolution with defensive parseFloat. */
  const validatedDeliveryCoords = useMemo(() => {
    const resolved = resolveDeliveryCoords(order);
    if (!resolved || resolved.rejections) {
      if (order?.order_id && !invalidDeliveryCoordWarnedRef.current) {
        const rejected = resolved?.rejections || [];
        rejected.forEach(({ source, reason }) => {
          console.warn('[TrackOrder][DEST] invalid source rejected', { source, reason });
        });
        if (!rejected.length) {
          console.warn('[TrackOrder][DEST] invalid source rejected', { source: 'none', reason: 'missing' });
        }
        invalidDeliveryCoordWarnedRef.current = true;
      }
      return null;
    }
    const { lat, lng, source } = resolved;
    const destKey = `${order?.order_id}:${lat},${lng}`;
    if (lastDestLogKeyRef.current !== destKey) {
      lastDestLogKeyRef.current = destKey;
      console.log('[TrackOrder][DEST] selected coordinates', { lat, lng, source });
    }
    return { lat, lng };
  }, [order]);

  const showRiderToCustomerRoute = useMemo(() => {
    const s = normalizeStatus(status);
    if (s === 'DELIVERED' || s === 'CANCELLED') return false;
    if (ROUTE_FROM_RIDER_STATUSES.has(s)) return true;
    const riderCoords = readRiderCoords(order, driverLocation);
    if (!riderCoords || isOffline) return false;
    return (STATUS_PRIORITY[s] ?? 0) >= STATUS_PRIORITY.ASSIGNED;
  }, [status, isOffline, order, driverLocation]);

  /** Route start: live rider position during active delivery (interpolated WS updates). */
  const riderRouteStart = useMemo(() => {
    if (!showRiderToCustomerRoute) return null;
    if (
      interpolatedDriverPos &&
      isValidLatLngPair(interpolatedDriverPos.lat, interpolatedDriverPos.lng)
    ) {
      return interpolatedDriverPos;
    }
    if (driverLocation && isValidLatLngPair(driverLocation.lat, driverLocation.lng)) {
      return driverLocation;
    }
    return readRiderCoords(order, null);
  }, [showRiderToCustomerRoute, interpolatedDriverPos, driverLocation, order?.rider, order?.rider_location]);

  /** Throttled origin for OSRM — avoids refetch on every animation frame. */
  const routeFetchOriginKey = useMemo(() => {
    if (!showRiderToCustomerRoute || !validatedDeliveryCoords) return null;
    const pos = readRiderCoords(order, driverLocation);
    if (!pos) return null;
    const snapLat = Math.round(pos.lat * 1000) / 1000;
    const snapLng = Math.round(pos.lng * 1000) / 1000;
    return `${snapLat},${snapLng}`;
  }, [showRiderToCustomerRoute, validatedDeliveryCoords, driverLocation, order?.rider, order?.rider_location]);

  /** Polyline shown on map: road route when available, straight line fallback, live rider anchor. */
  const displayRoute = useMemo(() => {
    if (!showRiderToCustomerRoute || !validatedDeliveryCoords || !riderRouteStart) return [];
    const dest = [validatedDeliveryCoords.lat, validatedDeliveryCoords.lng];
    const liveStart = [riderRouteStart.lat, riderRouteStart.lng];
    if (route.length > 1) {
      const pts = route.map(([la, ln]) => [la, ln]);
      pts[0] = liveStart;
      pts[pts.length - 1] = dest;
      return pts;
    }
    return [liveStart, dest];
  }, [route, riderRouteStart, validatedDeliveryCoords, showRiderToCustomerRoute]);

  const showRiderMarker = Boolean(
    showRiderToCustomerRoute &&
    riderRouteStart &&
    Number.isFinite(riderRouteStart.lat) &&
    Number.isFinite(riderRouteStart.lng)
  );

  const fitBoundsPoints = useMemo(() => {
    const pts = [];
    if (validatedDeliveryCoords) pts.push([validatedDeliveryCoords.lat, validatedDeliveryCoords.lng]);
    if (showRiderMarker && riderRouteStart) {
      pts.push([riderRouteStart.lat, riderRouteStart.lng]);
    }
    return pts;
  }, [validatedDeliveryCoords, showRiderMarker, riderRouteStart]);

  const mapFitKey = useMemo(() => {
    if (!validatedDeliveryCoords || !order?.order_id) return '';
    const dest = `${validatedDeliveryCoords.lat},${validatedDeliveryCoords.lng}`;
    const riderKey = showRiderMarker ? 'with-rider' : 'destination-only';
    const routeKey = displayRoute.length > 1 ? 'with-route' : 'no-route';
    return `${order.order_id}:${dest}:${riderKey}:${routeKey}`;
  }, [order?.order_id, validatedDeliveryCoords, showRiderMarker, displayRoute.length]);

  useEffect(() => {
    if (!showRiderToCustomerRoute || !validatedDeliveryCoords || !routeFetchOriginKey) return;
    const routeKey = `${order?.order_id}:${routeFetchOriginKey}:${validatedDeliveryCoords.lat},${validatedDeliveryCoords.lng}`;
    if (lastRouteLogKeyRef.current === routeKey) return;
    lastRouteLogKeyRef.current = routeKey;
    const [latStr, lngStr] = routeFetchOriginKey.split(',');
    console.log('[TrackOrder][ROUTE] rider + destination route triggered', {
      rider: { lat: parseFloat(latStr), lng: parseFloat(lngStr) },
      destination: validatedDeliveryCoords,
    });
  }, [showRiderToCustomerRoute, validatedDeliveryCoords, routeFetchOriginKey, order?.order_id]);

  useEffect(() => {
    let cancelled = false;
    const loadRoute = async () => {
      if (!validatedDeliveryCoords || !routeFetchOriginKey || !showRiderToCustomerRoute) {
        setRoute([]);
        return;
      }
      const [latStr, lngStr] = routeFetchOriginKey.split(',');
      const origin = { lat: parseFloat(latStr), lng: parseFloat(lngStr) };
      try {
        const routeData = await getRoute(origin, {
          lat: validatedDeliveryCoords.lat,
          lng: validatedDeliveryCoords.lng,
        });
        if (!cancelled) {
          setRoute(Array.isArray(routeData) ? routeData : []);
        }
      } catch (err) {
        console.error('[TrackOrder][ROUTE] loading failed:', err);
        if (!cancelled) setRoute([]);
      }
    };
    loadRoute();
    return () => {
      cancelled = true;
    };
  }, [validatedDeliveryCoords, routeFetchOriginKey, showRiderToCustomerRoute]);

  // Rule 11: Memoize derived timeline calculations to prevent unnecessary re-renders
  const statusStepsWithIcons = useMemo(() => [
    { id: 'PLACED', label: 'Placed', icon: ShoppingBag },
    { id: 'CONFIRMED', label: 'Confirmed', icon: CheckCircle2 },
    { id: 'READY', label: 'Ready', icon: PackageCheck },
    { id: 'ASSIGNED', label: 'Assigned', icon: Bike },
    { id: 'PICKED_UP', label: 'Picked Up', icon: HandHelping },
    { id: 'ON_WAY', label: 'On Way', icon: Bike },
    { id: 'ARRIVING', label: 'Arriving', icon: MapPin },
    { id: 'DELIVERED', label: 'Delivered', icon: Flag }
  ], []);

  const currentStepIndex = useMemo(() =>
    statusStepsWithIcons.findIndex(s => s.id === normalizeStatus(status)),
    [status, statusStepsWithIcons]);

  const center = useMemo(() => {
    if (validatedDeliveryCoords) return [validatedDeliveryCoords.lat, validatedDeliveryCoords.lng];
    if (riderRouteStart && isValidLatLngPair(riderRouteStart.lat, riderRouteStart.lng)) {
      return [riderRouteStart.lat, riderRouteStart.lng];
    }
    return [0, 0];
  }, [validatedDeliveryCoords, riderRouteStart]);

  const mapZoom = validatedDeliveryCoords || riderRouteStart ? 14 : 2;

  if (loading) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center bg-white">
        <Loader2 className="w-10 h-10 text-[#ff6b00] animate-spin mb-4" />
        <p className="text-gray-500 font-medium">Securing your delivery details...</p>
      </div>
    );
  }

  if (error || !order) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center bg-gray-50 px-6 text-center pt-20 pb-20">
        <div className="w-24 h-24 bg-orange-50 rounded-full flex items-center justify-center mb-8">
          <Search className="w-10 h-10 text-[#ff6b00]" />
        </div>

        <h2 className="text-3xl font-black text-gray-900 mb-2 tracking-tight">Track Your Order</h2>
        <p className="text-gray-500 mb-10 max-w-sm mx-auto font-medium">Enter your order ID below to see live updates and delivery progress.</p>

        <form onSubmit={handleSearch} className="w-full max-w-md space-y-4">
          <div className="relative group">
            <div className="absolute inset-y-0 left-0 pl-5 flex items-center pointer-events-none">
              <Package className="h-5 w-5 text-gray-400 group-focus-within:text-[#ff6b00] transition-colors" />
            </div>
            <input
              type="text"
              placeholder="Enter Order ID (e.g. 101)"
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              className="block w-full pl-12 pr-4 py-5 bg-white border-2 border-gray-100 rounded-2xl text-base font-bold placeholder-gray-400 focus:outline-none focus:border-[#ff6b00] focus:ring-4 focus:ring-orange-50 transition-all shadow-sm"
            />
          </div>

          {error && (
            <div className="flex items-center gap-2 text-red-500 text-sm font-bold bg-red-50 p-4 rounded-xl border border-red-100">
              <AlertCircle className="w-4 h-4" />
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={!searchInput.trim()}
            className="w-full py-5 bg-gray-900 text-white rounded-2xl font-black hover:bg-[#ff6b00] transition-all transform hover:scale-[1.02] active:scale-[0.98] shadow-lg shadow-gray-200 disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:bg-gray-900 flex items-center justify-center gap-3"
          >
            Track Order Now
            <ArrowRight className="w-5 h-5" />
          </button>
        </form>

        <button
          onClick={() => navigate('/menu')}
          className="mt-8 text-sm font-bold text-gray-500 hover:text-gray-900 transition-colors flex items-center gap-2"
        >
          <ArrowLeft className="w-4 h-4" />
          Back to Menu
        </button>
      </div>
    );
  }

  const items = order?.items || [];

  return (
    <div className="min-h-screen bg-[#FDFDFD] pt-24 sm:pt-32 pb-16 overflow-x-hidden">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">

        <div className="flex flex-col md:flex-row md:items-center justify-between mb-8 gap-4">
          <div className="flex items-center gap-4">
            <button
              onClick={() => navigate('/orders')}
              className="p-3 bg-white border border-gray-100 rounded-xl text-gray-500 hover:text-[#ff6b00] hover:border-orange-100 transition-all shadow-sm group"
            >
              <ArrowLeft className="w-5 h-5 group-hover:-translate-x-1 transition-transform" />
            </button>
            <div>
              <h1 className="text-2xl font-black text-gray-900 tracking-tight flex items-center gap-3">
                Track Order
                {connectionStatus === 'reconnecting' && (
                  <span className="text-[10px] bg-amber-50 text-amber-600 px-2 py-1 rounded-full animate-pulse border border-amber-100">Reconnecting...</span>
                )}
                {connectionStatus === 'error' && (
                  <span className="text-[10px] bg-red-50 text-red-600 px-2 py-1 rounded-full border border-red-100">Connection Offline</span>
                )}
              </h1>
              <p className="text-xs font-bold text-gray-400 uppercase tracking-widest mt-0.5">#{order.order_id} • Placed on {new Date(order.created_at).toLocaleDateString()}</p>
            </div>
          </div>
          <div className="flex flex-col items-end gap-1.5">
            <div className="flex items-center gap-3 bg-white px-4 py-2 rounded-xl border border-gray-100 shadow-sm">
              <div className="flex items-center gap-2">
                <div className={`w-2 h-2 rounded-full ${connectionStatus === 'connected' ? 'bg-green-500 animate-pulse' :
                  connectionStatus === 'reconnecting' ? 'bg-amber-500 animate-pulse' :
                    'bg-red-500'
                  }`} />
                <span className="text-[10px] font-black text-gray-900 uppercase tracking-widest">
                  {connectionStatus === 'connected' ? 'Live Updates' :
                    connectionStatus === 'reconnecting' ? 'Reconnecting...' :
                      'Offline'}
                </span>
              </div>
            </div>
            <p className="text-sm font-black text-[#ff6b00] text-right pr-1 tracking-wide">
              {getEtaCountdownText(order)}
            </p>
          </div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-start">
          <div className="lg:col-span-8 space-y-6 min-w-0">
            <div className="bg-white rounded-2xl shadow-xl shadow-gray-200/50 border border-gray-100 overflow-hidden relative w-full z-0" style={{ height: '450px' }}>
              {validatedDeliveryCoords ? (
                <MapContainer
                  center={center}
                  zoom={mapZoom}
                  style={{ width: '100%', height: '100%' }}
                  zoomControl={false}
                  scrollWheelZoom
                  dragging
                  touchZoom
                  doubleClickZoom
                  boxZoom
                >
                  <TileLayer
                    url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
                    attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
                  />

                  <Marker
                    position={[validatedDeliveryCoords.lat, validatedDeliveryCoords.lng]}
                    icon={destinationIcon}
                  />

                  {showRiderMarker && riderRouteStart && (
                    <Marker
                      position={[riderRouteStart.lat, riderRouteStart.lng]}
                      icon={driverIcon}
                    />
                  )}

                  {displayRoute.length > 1 && showRiderToCustomerRoute && (
                    <Polyline
                      positions={displayRoute}
                      color="#ff6b00"
                      weight={5}
                      opacity={0.8}
                      lineCap="round"
                    />
                  )}

                  <FitBounds
                    route={displayRoute.length > 1 ? displayRoute : null}
                    points={fitBoundsPoints}
                    orderId={order?.order_id}
                    fitKey={mapFitKey}
                  />
                </MapContainer>
              ) : (
                <div className="w-full h-full flex flex-col items-center justify-center bg-gray-50 px-6 text-center">
                  <AlertCircle className="w-12 h-12 text-amber-500 mb-3" />
                  <p className="text-sm font-bold text-gray-700 max-w-md">
                    Delivery map location is unavailable for this order (saved coordinates missing or invalid).
                  </p>
                  <p className="text-xs text-gray-500 mt-2 max-w-sm">
                    Orders placed before address pinning may need a new delivery address with valid coordinates.
                  </p>
                </div>
              )}
            </div>

            <div className="bg-white rounded-2xl p-5 sm:p-8 border border-gray-100 shadow-sm overflow-x-auto scrollbar-hide">
              {/* Progress connector line (desktop only) */}
              <div className="relative min-w-[600px] sm:min-w-0">
                <div className="hidden sm:block absolute top-6 left-6 right-6 h-0.5 bg-gray-100">
                  <div
                    className="h-full bg-[#ff6b00] transition-all duration-1000 shadow-[0_0_8px_rgba(255,107,0,0.4)]"
                    style={{
                      width: currentStepIndex >= 0
                        ? `${(currentStepIndex / Math.max(statusStepsWithIcons.length - 1, 1)) * 100}%`
                        : '0%'
                    }}
                  />
                </div>

                <div className="flex justify-between items-start gap-1">
                  {statusStepsWithIcons.map((step, idx) => {
                    const Icon = step.icon;
                    // Guard: if status not yet resolved, treat index 0 as current
                    const safeIndex = currentStepIndex >= 0 ? currentStepIndex : 0;
                    const isCompleted = idx < safeIndex;
                    const isCurrent = idx === safeIndex;

                    return (
                      <div key={step.id} className="relative z-10 flex flex-col items-center text-center flex-1">
                        <div className={`w-10 h-10 sm:w-12 sm:h-12 rounded-xl flex items-center justify-center transition-all duration-500 mb-2 ${isCurrent
                          ? 'bg-[#ff6b00] text-white shadow-[0_0_20px_rgba(255,107,0,0.4)] ring-4 ring-orange-100 scale-110 z-20'
                          : isCompleted
                            ? 'bg-[#ff6b00] text-white shadow-md shadow-orange-100'
                            : 'bg-gray-50 text-gray-300'
                          }`}>
                          <Icon className={`w-4 h-4 sm:w-5 sm:h-5 ${isCurrent ? 'animate-pulse' : ''}`} />
                        </div>
                        <p className={`text-[8px] sm:text-[10px] font-black uppercase leading-tight max-w-[60px] sm:max-w-none mx-auto ${isCurrent
                          ? 'text-[#ff6b00] scale-105 transition-transform duration-500'
                          : isCompleted
                            ? 'text-orange-600/80'
                            : 'text-gray-300'
                          }`}>
                          {step.label}
                        </p>
                        {isCurrent && (
                          <span className="mt-1 inline-block w-1.5 h-1.5 rounded-full bg-[#ff6b00] animate-pulse" />
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>

            <div className="space-y-4">
              <h3 className="text-sm font-black text-gray-900 uppercase tracking-widest px-1">Delivery Partner</h3>
              {/* RULE: Always show rider info if assigned */}
              {order.rider ? (
                <div className={`bg-white rounded-2xl p-6 border transition-all duration-300 ${isOffline ? 'border-red-200 bg-red-50/10' : 'border-orange-200'} shadow-md ring-1 ${isOffline ? 'ring-red-100' : 'ring-orange-100'} flex flex-col sm:flex-row items-center justify-between gap-6`}>
                  <div className="flex items-center gap-5 w-full sm:w-auto">
                    <div className={`w-16 h-16 rounded-full flex items-center justify-center border-4 shadow-inner overflow-hidden ${isOffline ? 'bg-red-50 border-red-100' : 'bg-orange-50 border-orange-100'}`}>
                      {order.rider.profile_pic ? (
                        <img src={order.rider.profile_pic} alt={order.rider.name} className="w-full h-full object-cover" />
                      ) : (
                        <User className={`w-8 h-8 ${isOffline ? 'text-red-400' : 'text-[#ff6b00]'}`} />
                      )}
                    </div>
                    <div>
                      <div className="flex items-center gap-2">
                        <h4 className="text-xl font-black text-gray-900">{order.rider.name}</h4>
                        <span className={`flex h-2 w-2 rounded-full ${isOffline ? 'bg-red-500' : 'bg-green-500 animate-pulse'}`} />
                      </div>
                      <p className={`text-xs font-bold uppercase tracking-widest ${isOffline ? 'text-red-500' : 'text-[#ff6b00]'}`}>
                        {isOffline ? 'Partner Offline' : 'Active Delivery Partner'}
                      </p>
                      <div className="flex items-center gap-1.5 mt-1.5">
                        <Star className={`w-3.5 h-3.5 ${isOffline ? 'text-red-400 fill-red-400' : 'text-[#ff6b00] fill-[#ff6b00]'}`} />
                        <span className="text-sm font-black text-gray-700">4.9</span>
                      </div>
                    </div>
                  </div>
                  <a href="tel:+919876543210" className="w-full sm:w-auto flex items-center justify-center gap-3 px-8 py-4 bg-gray-900 text-white rounded-xl font-black hover:bg-[#ff6b00] transition-all transform hover:scale-[1.02] active:scale-[0.98]">
                    <Phone className="w-4 h-4" />
                    Call Partner
                  </a>
                </div>
              ) : (
                <div className="bg-gray-50/50 rounded-2xl p-8 border border-dashed border-gray-200 text-center">
                  <div className="w-12 h-12 bg-white rounded-full flex items-center justify-center mx-auto mb-4 border border-gray-100 shadow-sm">
                    <Bike className="w-6 h-6 text-gray-300" />
                  </div>
                  <p className="text-xs font-bold text-gray-500 uppercase tracking-widest">Rider assignment in progress</p>
                  <p className="text-[10px] text-gray-400 mt-1 uppercase font-medium">Partner info appears as soon as assignment is available</p>
                </div>
              )}
            </div>
          </div>

          <div className="lg:col-span-4 space-y-6 min-w-0">
            <div className="bg-white rounded-2xl shadow-sm border border-gray-100 overflow-hidden">
              <div className="px-6 py-4 bg-gray-50/50 border-b border-gray-100">
                <h3 className="text-sm font-black text-gray-900 uppercase tracking-widest">Order Summary</h3>
              </div>
              <div className="p-6 space-y-5 max-h-[400px] overflow-y-auto">
                {items.map((item, idx) => (
                  <div key={idx} className="flex gap-4 group">
                    <div className="w-16 h-16 bg-gray-50 rounded-xl overflow-hidden shrink-0 border border-gray-100">
                      <img src={item.image || "/images/samosa.jpg"} alt={item.name} className="w-full h-full object-cover" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-black text-gray-800 truncate">{item.name}</p>
                      <div className="flex items-center justify-between mt-1">
                        <p className="text-[10px] font-black text-gray-400 uppercase">Qty: {item.quantity}</p>
                        <p className="text-sm font-black text-gray-900">₹{Math.round(item.total_price)}</p>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
              <div className="p-6 bg-gray-50/50 border-t border-gray-100 space-y-3">
                <div className="flex justify-between items-center text-[10px] font-black text-gray-400 uppercase tracking-widest">
                  <span>Subtotal</span>
                  <span className="text-gray-900 font-black">₹{Math.round(order.pricing.subtotal)}</span>
                </div>
                <div className="flex justify-between items-center text-[10px] font-black text-gray-400 uppercase tracking-widest">
                  <span>Delivery Fee</span>
                  <span className="text-gray-900 font-black">₹{Math.round(order.pricing.delivery_fee)}</span>
                </div>
                <div className="pt-3 border-t border-gray-200 flex justify-between items-end">
                  <span className="text-xs font-black text-gray-900 uppercase">Total Paid</span>
                  <span className="text-2xl font-black text-[#ff6b00] leading-none">₹{Math.round(order.pricing.total)}</span>
                </div>
              </div>
            </div>

            <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-6">
              <h3 className="text-sm font-black text-gray-900 uppercase tracking-widest mb-5 flex items-center gap-2">
                <MapPin className="w-4 h-4 text-[#ff6b00]" />
                Delivery Destination
              </h3>
              <div className="space-y-5">
                <div className="flex items-start gap-4">
                  <div className="w-10 h-10 bg-orange-50 rounded-xl flex items-center justify-center shrink-0">
                    <Home className="w-5 h-5 text-[#ff6b00]" />
                  </div>
                  <div className="min-w-0">
                    <p className="text-sm font-black text-gray-900 truncate">{order.address.name || 'Your Home'}</p>
                    <p className="text-xs font-medium text-gray-500 mt-1 leading-relaxed line-clamp-2">
                      {order.address.address_line}, {order.address.city} - {order.address.pincode}
                    </p>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default TrackOrderPage;
