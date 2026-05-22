import axios from 'axios';
import { API_BASE_URL } from '../config/constants';

const apiClient = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
    'Pragma': 'no-cache',
    'Cache-Control': 'no-cache, no-store, must-revalidate',
    'Expires': '0'
  },
});

const decodeToken = (token) => {
  try {
    if (!token || typeof token !== 'string' || token === 'undefined' || token === 'null') return null;
    const base64Url = token.split('.')[1];
    if (!base64Url) return null;
    const base64 = base64Url.replace(/-/g, '+').replace(/_/g, '/');
    const jsonPayload = decodeURIComponent(atob(base64).split('').map(function (c) {
      return '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2);
    }).join(''));
    return JSON.parse(jsonPayload);
  } catch (e) {
    return null;
  }
};

// 1. Interceptor Management (Singleton Protection)
if (apiClient.requestInterceptorId !== undefined) {
  apiClient.interceptors.request.eject(apiClient.requestInterceptorId);
  if (process.env.NODE_ENV === 'development') console.log("[API][INTERCEPTOR][EJECTED] Request");
}
if (apiClient.responseInterceptorId !== undefined) {
  apiClient.interceptors.response.eject(apiClient.responseInterceptorId);
  if (process.env.NODE_ENV === 'development') console.log("[API][INTERCEPTOR][EJECTED] Response");
}

// 2. Public Endpoints Whitelist (Bypasses mandatory authentication)
const PUBLIC_ENDPOINTS = [
  '/api/menu',
  '/api/restaurants/nearby',
  '/api/admin/login',
  '/api/rider/login',
  '/api/customer/login',
  '/api/customer/register',
  '/api/login',
  '/api/register',
  '/api/signup',
  '/api/refresh-token',
];

// 3. Request Interceptor: Strict Auth & Role Validation
apiClient.requestInterceptorId = apiClient.interceptors.request.use(
  (config) => {
    const url = config.url || "";
    const isPublicRoute = PUBLIC_ENDPOINTS.some(endpoint => url.startsWith(endpoint));

    let tokenKey = 'customerToken';
    let roleLabel = "CUSTOMER";

    // Strict Prefix Detection
    if (url.startsWith('/api/admin/')) {
      tokenKey = 'adminToken';
      roleLabel = "ADMIN";
    } else if (url.startsWith('/api/rider/')) {
      tokenKey = 'riderToken';
      roleLabel = "RIDER";
    }

    const isHydrated = localStorage.getItem("auth_hydrated") === "true";
    let token = localStorage.getItem(tokenKey);

    // Clean corrupted tokens
    if (token && (token === "undefined" || token === "null" || token.trim().length === 0)) {
      localStorage.removeItem(tokenKey);
      token = null;
    }

    if (token) {
      const decoded = decodeToken(token);
      const now = Math.floor(Date.now() / 1000);

      // Proactive Expiry Check
      if (decoded && decoded.exp < now) {
        if (isHydrated) {
          console.warn(`[AUTH][${roleLabel}] Session expired. Clearing ${tokenKey}...`);
          localStorage.removeItem(tokenKey);
          localStorage.removeItem(tokenKey.replace('Token', 'User'));

          if (!isPublicRoute && roleLabel !== "CUSTOMER") {
            let loginPath = '/login';
            if (roleLabel === "ADMIN") loginPath = '/admin/login';
            else if (roleLabel === "RIDER") loginPath = '/rider/login';
            window.location.href = loginPath;
          }
        }

        if (!isPublicRoute) {
          return Promise.reject({ silent: true, detail: 'Session expired' });
        }
        // For public routes, just continue without token if expired
        token = null;
      }

      if (token) {
        config.headers.Authorization = `Bearer ${token}`;

        // Role Permission Guard (Only for non-public routes)
        if (!isPublicRoute && decoded) {
          const roles = decoded.roles || [];
          if (roleLabel === "ADMIN" && !roles.includes('admin')) {
            return Promise.reject({ silent: true, detail: 'Access denied: Admin role required' });
          }
          if (roleLabel === "RIDER" && !roles.includes('rider')) {
            return Promise.reject({ silent: true, detail: 'Access denied: Rider role required' });
          }
        }
      }
    }

    // FINAL BLOCKING LOGIC
    if (!token && !isPublicRoute) {
      // Always block Admin/Rider portals if token missing
      if (roleLabel !== "CUSTOMER") {
        console.debug(`[AUTH][${roleLabel}] Blocked request: Missing ${tokenKey}`);
        return Promise.reject({
          silent: false,
          authRequired: true,
          portal: roleLabel.toLowerCase(),
          detail: `Authentication required: ${roleLabel} portal`
        });
      }

      // For customer routes, if NOT in PUBLIC_ENDPOINTS, we could block, 
      // but to follow "Public/customer routes should NEVER fail if token is missing",
      // we allow it to proceed and let the backend return 401 if actually protected.
      if (process.env.NODE_ENV === 'development') {
        console.debug(`[AUTH][CUSTOMER] Proceeding without token for possibly protected route: ${url}`);
      }
    }

    return config;
  },
  (error) => Promise.reject(error)
);

// 4. Response Interceptor: Isolated 401 Handling
apiClient.responseInterceptorId = apiClient.interceptors.response.use(
  (response) => response.data,
  (error) => {
    // 1. Handle silent rejections from request interceptor (expiry, RBAC)
    if (error?.silent) return Promise.reject(error);

    // 2. Network/CORS/Timeout Handling (STRICT RULE)
    // If there is NO response from the server (err.response is undefined),
    // it means the backend is unreachable or there's a network error.
    // RULE: We MUST NOT clear the token or redirect in this case.
    if (!error.response) {
      console.error("[API] Backend unreachable - DO NOT LOGOUT USER");
      return Promise.reject({ error: "NETWORK_ERROR" });
    }

    const { status, data } = error.response;
    const url = error.config?.url || "";

    // 3. 401 Unauthorized / 403 Forbidden (THE ONLY TRIGGERS FOR LOGOUT)
    if (status === 401 || status === 403) {
      // Rule: Do NOT logout if the failed request was a login attempt itself
      const isAuthEndpoint = url.includes('/login') || url.includes('/signup') || url.includes('/register');

      if (!isAuthEndpoint) {
        let tokenKey = 'customerToken';
        let loginPath = '/login';

        if (url.startsWith('/api/admin/')) {
          tokenKey = 'adminToken';
          loginPath = '/admin/login';
        } else if (url.startsWith('/api/rider/')) {
          tokenKey = 'riderToken';
          loginPath = '/rider/login';
        }

        console.error(`[AUTH] Session expired or invalid (Status: ${status}). Clearing state and redirecting to ${loginPath}.`);

        // Atomic cleanup
        localStorage.removeItem(tokenKey);
        localStorage.removeItem(tokenKey.replace('Token', 'User'));

        // Force redirect to login
        if (!window.location.pathname.includes('/login')) {
          window.location.href = loginPath;
        }
      }
    }

    // 4. Pass through for other errors (400, 404, 500, etc.)
    return Promise.reject(data || error);
  }
);

if (process.env.NODE_ENV === 'development') console.log("[API][INTERCEPTOR][ATTACHED]");

// --- Retry Logic for Transient Network Failures ---
/**
 * Wraps an async API call with single-retry on network errors.
 * Usage:  const data = await requestWithRetry(() => apiClient.get('/api/menu'));
 * Only retries on network errors (no response), NOT on 4xx/5xx.
 */
export async function requestWithRetry(fn, retries = 1) {
  try {
    return await fn();
  } catch (err) {
    const isNetworkError = err?.error === "NETWORK_ERROR" || err?.networkError || !err?.response;
    if (isNetworkError && retries > 0) {
      console.warn(`[API][RETRY] Retrying request (${retries} left)...`);
      await new Promise(r => setTimeout(r, 2500)); // retry after 2-3 seconds instead of redirecting
      return requestWithRetry(fn, retries - 1);
    }
    throw err;
  }
}

export default apiClient;
