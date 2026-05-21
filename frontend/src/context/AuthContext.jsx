import React, { createContext, useState, useContext, useEffect, useCallback, useMemo, useRef } from 'react';
import apiClient from '../services/apiClient';
import { ROLES } from '../config/constants';

export const AuthContext = createContext(null);

// ─── JWT decoder (no dependency) ──────────────────────────────────────────────
function decodeToken(token) {
  try {
    if (!token || token === 'undefined' || token === 'null') return null;
    const base64Url = token.split('.')[1];
    if (!base64Url) return null;
    const base64 = base64Url.replace(/-/g, '+').replace(/_/g, '/');
    const jsonPayload = decodeURIComponent(
      atob(base64).split('').map(c => '%' + ('00' + c.charCodeAt(0).toString(16)).slice(-2)).join('')
    );
    return JSON.parse(jsonPayload);
  } catch {
    return null;
  }
}


// ─── Provider ────────────────────────────────────────────────────────────────
export function AuthProvider({ children }) {
  const mountedRef = useRef(true);

  // ── Per-portal state (fully isolated) ──────────────────────────────────────
  const [customerToken, setCustomerToken] = useState(() => localStorage.getItem('customerToken'));
  const [customerUser,  setCustomerUser]  = useState(() => {
    try {
      const raw = localStorage.getItem('customerUser');
      return raw ? JSON.parse(raw) : null;
    } catch { return null; }
  });

  const [adminToken, setAdminToken] = useState(() => localStorage.getItem('adminToken'));
  const [adminUser,  setAdminUser]  = useState(() => {
    try {
      const raw = localStorage.getItem('adminUser');
      return raw ? JSON.parse(raw) : null;
    } catch { return null; }
  });

  const [riderToken, setRiderToken] = useState(() => localStorage.getItem('riderToken'));
  const [riderUser,  setRiderUser]  = useState(() => {
    try {
      const raw = localStorage.getItem('riderUser');
      return raw ? JSON.parse(raw) : null;
    } catch { return null; }
  });

  // Loading state to prevent premature redirection
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // Initial hydration is sync in useState, but we set loading false in useEffect 
    // to allow a render cycle for the app to settle.
    setLoading(false);
    localStorage.setItem('auth_hydrated', 'true');
    return () => { mountedRef.current = false; };
  }, []);

  // ── Logout Handlers ────────────────────────────────────────────────────────
  const logoutCustomer = useCallback(() => {
    localStorage.removeItem('customerToken');
    localStorage.removeItem('customerUser');
    setCustomerToken(null);
    setCustomerUser(null);
    window.dispatchEvent(new Event('storage'));
    console.log('[AUTH][CUSTOMER] Logged out');
  }, []);

  const logoutAdmin = useCallback(() => {
    localStorage.removeItem('adminToken');
    localStorage.removeItem('adminUser');
    setAdminToken(null);
    setAdminUser(null);
    window.dispatchEvent(new Event('storage'));
    console.log('[AUTH][ADMIN] Logged out');
  }, []);

  const logoutRider = useCallback(() => {
    localStorage.removeItem('riderToken');
    localStorage.removeItem('riderUser');
    setRiderToken(null);
    setRiderUser(null);
    window.dispatchEvent(new Event('storage'));
    console.log('[AUTH][RIDER] Logged out');
  }, []);

  // ── Login Handlers ─────────────────────────────────────────────────────────
  const loginPortal = async (email, password, roleKey) => {
    try {
      try {
        await apiClient.get('/health');
      } catch (healthError) {
        return { success: false, message: "server starting" };
      }

      const response = await apiClient.post(`/api/${roleKey}/login`, { email, password });
      if (!response.success) return { success: false, message: response.message || 'Login failed' };

      const { token, user } = response.data;
      const roleTokenKey = `${roleKey}Token`;
      const roleUserKey = `${roleKey}User`;
      
      const decoded = decodeToken(token);
      const userWithRoles = {
        ...(user || {}),
        id: decoded?.user_id || user?.id,
        email: decoded?.email || user?.email,
        roles: decoded?.roles || user?.roles || [roleKey],
      };

      localStorage.setItem(roleTokenKey, token);
      localStorage.setItem(roleUserKey, JSON.stringify(userWithRoles));

      if (roleKey === 'admin') {
        setAdminToken(token);
        setAdminUser(userWithRoles);
      } else if (roleKey === 'rider') {
        setRiderToken(token);
        setRiderUser(userWithRoles);
      } else {
        setCustomerToken(token);
        setCustomerUser(userWithRoles);
      }

      localStorage.setItem('auth_hydrated', 'true');
      return { success: true };
    } catch (error) {
      return { success: false, message: error?.detail || error?.message || 'Login failed' };
    }
  };

  const loginCustomer = useCallback((e, p) => loginPortal(e, p, 'customer'), []);
  const loginAdmin    = useCallback((e, p) => loginPortal(e, p, 'admin'), []);
  const loginRider    = useCallback((e, p) => loginPortal(e, p, 'rider'), []);

  const signup = useCallback(async (name, email, password) => {
    return apiClient.post('/api/customer/signup', { name, email, password });
  }, []);

  // ── Role checks (simple, synchronous) ──────────────────────────────────────
  const isAdmin = useCallback(() => {
    if (!adminToken) return false;
    if (Array.isArray(adminUser?.roles) && adminUser.roles.includes(ROLES.ADMIN)) return true;
    const decoded = decodeToken(adminToken);
    return decoded?.roles?.includes(ROLES.ADMIN) || decoded?.roles?.includes('admin');
  }, [adminToken, adminUser]);

  const isRider = useCallback(() => {
    if (!riderToken) return false;
    if (Array.isArray(riderUser?.roles) && riderUser.roles.includes(ROLES.RIDER)) return true;
    const decoded = decodeToken(riderToken);
    return decoded?.roles?.includes(ROLES.RIDER) || decoded?.roles?.includes('rider');
  }, [riderToken, riderUser]);

  const isCustomer = useCallback(() => {
    if (!customerToken) return false;
    if (Array.isArray(customerUser?.roles) && customerUser.roles.includes(ROLES.CUSTOMER)) return true;
    const decoded = decodeToken(customerToken);
    return decoded?.roles?.includes(ROLES.CUSTOMER) || decoded?.roles?.includes('customer');
  }, [customerToken, customerUser]);

  // isResolved: always true now (sync hydration). Kept for route guard compatibility.
  const isResolved = useCallback((_role) => true, []);

  // ── Cross-tab sync ──────────────────────────────────────────────────────────
  useEffect(() => {
    const onStorage = (e) => {
      if (!mountedRef.current || e.storageArea !== localStorage) return;
      const key = e.key;
      if (!key) return;

      if (key === 'adminToken') {
        const token = localStorage.getItem('adminToken');
        setAdminToken(token);
        // User hydration omitted for brevity or can be added if needed
      } else if (key === 'riderToken') {
        const token = localStorage.getItem('riderToken');
        setRiderToken(token);
      } else if (key === 'customerToken') {
        const token = localStorage.getItem('customerToken');
        setCustomerToken(token);
      }
    };
    window.addEventListener('storage', onStorage);
    return () => window.removeEventListener('storage', onStorage);
  }, []);

  // ── Context value ───────────────────────────────────────────────────────────
  const value = useMemo(() => ({
    loading,
    isAuthenticated: !!customerToken || !!adminToken || !!riderToken,
    user: customerUser || adminUser || riderUser || null,
    customerToken, customerUser,
    adminToken,    adminUser,
    riderToken,    riderUser,
    loginCustomer, loginAdmin, loginRider,
    signup,
    logoutCustomer, logoutAdmin, logoutRider,
    isAdmin,
    isRider,
    isCustomer,
    isResolved,
    isHydrated: true,
  }), [
    loading,
    customerToken, adminToken, riderToken,
    customerUser,  adminUser,  riderUser,
    loginCustomer, loginAdmin, loginRider,
    signup,
    logoutCustomer, logoutAdmin, logoutRider,
    isAdmin, isRider, isCustomer, isResolved,
  ]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

