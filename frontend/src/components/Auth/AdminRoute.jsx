import React from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { useAuth } from '../../hooks/useAuth';

export function AdminRoute({ children }) {
  const { adminToken, isAdmin, loading } = useAuth();
  const location = useLocation();

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-white">
        <div className="w-10 h-10 border-4 border-orange-100 border-t-[#ff6b00] rounded-full animate-spin"></div>
      </div>
    );
  }

  if (!adminToken && !isAdmin()) {
    console.warn('[AUTH][ADMIN] No token — redirecting to admin login');
    return <Navigate to="/admin/login" state={{ from: location }} replace />;
  }

  return children;
}
