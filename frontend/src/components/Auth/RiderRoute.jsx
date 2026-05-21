import React from 'react';
import { Navigate } from 'react-router-dom';
import { useAuth } from '../../hooks/useAuth';

export function RiderRoute({ children }) {
  const { riderToken, loading } = useAuth();

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-white">
        <div className="w-10 h-10 border-4 border-orange-100 border-t-[#ff6b00] rounded-full animate-spin"></div>
      </div>
    );
  }

  // 2. Token check (Hardened: use ONLY riderToken)
  if (!riderToken) {
    return <Navigate to="/rider/login" replace />;
  }

  // 3. Authorized access
  return children;
}
