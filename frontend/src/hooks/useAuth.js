import { useContext } from 'react';
import { AuthContext } from '../context/AuthContext';
import { logProviderWarning } from '../utils/contextLogger';

export const useAuth = () => {
  const context = useContext(AuthContext);
  
  if (!context) {
    logProviderWarning('Auth');
    
    // Return a strict fallback object that indicates failure
    return {
      _isProviderMissing: true,
      loading: false,
      isAuthenticated: false,
      user: null,
      token: null, // Unified token source of truth
      customerToken: null,
      customerUser: null,
      adminToken: null,
      adminUser: null,
      riderToken: null,
      riderUser: null,
      loginCustomer: async () => { throw new Error('[AUTH] Provider missing'); },
      loginAdmin: async () => { throw new Error('[AUTH] Provider missing'); },
      loginRider: async () => { throw new Error('[AUTH] Provider missing'); },
      signup: async () => { throw new Error('[AUTH] Provider missing'); },
      logoutCustomer: () => { console.error('[AUTH] logout called without provider'); },
      logoutAdmin: () => { console.error('[AUTH] logout called without provider'); },
      logoutRider: () => { console.error('[AUTH] logout called without provider'); },
      isAdmin: () => false,
      isRider: () => false,
      isCustomer: () => false,
      isResolved: () => true,
      isHydrated: true,
    };
  }
  
  return context;
};
