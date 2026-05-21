import React from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { useAuth } from '../hooks/useAuth';

export const CustomerRoute = ({ children }) => {
  const { customerToken, isCustomer, loading } = useAuth();
  const location = useLocation();

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-white">
        <div className="w-10 h-10 border-4 border-orange-100 border-t-[#ff6b00] rounded-full animate-spin"></div>
      </div>
    );
  }

  // Only redirect if loading has completed and customerToken is definitively missing
  if (!loading && !customerToken) {
    console.warn('[AUTH][CUSTOMER] Missing token — redirecting to login');
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  // If we have a token but roles are missing/corrupted, stay put. 
  // This prevents "false logouts" if the backend is down and user data isn't hydrated.
  if (!isCustomer()) {
    console.debug('[AUTH][CUSTOMER] Token present but roles unresolved. Staying on route.');
  }


  return children;
};
