import React, { useState, useEffect } from 'react';
import { Routes, Route, Navigate, Link, Outlet, useNavigate, useLocation } from 'react-router-dom';
import { Toaster } from 'react-hot-toast';
import Navbar from './components/Navbar';
import Hero from './components/Hero';
import MenuPage from './components/MenuPage';
import Menu from './components/Menu';
import Tracking from './components/Tracking';
import CartDrawer from './components/CartDrawer';
import CheckoutPage from './components/Checkout/CheckoutPage';
import AddAddressPage from './components/Checkout/AddAddressPage';
import OrdersPage from './components/OrdersPage';
import TrackOrderPage from './components/TrackOrderPage';
import OrderSuccessPage from './components/Checkout/OrderSuccessPage';
import Login from './components/Auth/Login';
import Signup from './components/Auth/Signup';
import AdminLogin from './components/Auth/AdminLogin';
import RiderLogin from './components/Auth/RiderLogin';
import AdminDashboard from './components/AdminDashboard';
import AdminOrders from './components/AdminOrders';
import AdminRiders from './components/AdminRiders';
import RiderDashboard from './components/RiderDashboard';
import NearbyRestaurants from './components/NearbyRestaurants';
import ErrorBoundary from './components/ErrorBoundary';
import { CartProvider } from './context/CartContext';
import { AuthProvider } from './context/AuthContext';
import { useAuth } from './hooks/useAuth';
import { useCart } from './hooks/useCart';
import WhyChooseUs from './components/WhyChooseUs';
import { Mail, Phone, MapPin } from 'lucide-react';
import { ENABLE_NEARBY_FEATURE } from './config/featureFlags';

import MainLayout from './layouts/MainLayout';
import AdminLayout from './layouts/AdminLayout';
import RiderLayout from './layouts/RiderLayout';
import { AdminRoute } from './components/Auth/AdminRoute';
import { RiderRoute } from './components/Auth/RiderRoute';
import { CustomerRoute } from './routes/CustomerRoute';
import ProfilePage from './components/ProfilePage';

import RiderHistory from './components/RiderHistory';
import RiderEarnings from './components/RiderEarnings';

// Redirect logged-in customers away from the public landing page to /home
const LandingPageGuard = ({ children }) => {
  const { isCustomer } = useAuth();
  if (isCustomer()) return <Navigate to="/home" replace />;
  return children;
};

// Redirect already-authenticated users away from login pages
const AuthRouteGuard = ({ children, to = "/home" }) => {
  const { isCustomer, isAdmin, isRider } = useAuth();
  const location = useLocation();

  if (location.pathname === '/login' && isCustomer()) return <Navigate to={to} replace />;
  if (location.pathname === '/admin/login' && isAdmin()) return <Navigate to="/admin/dashboard" replace />;
  if (location.pathname === '/rider/login' && isRider()) return <Navigate to="/rider/dashboard" replace />;

  return children;
};

function AppContent() {
  const [isOnline, setIsOnline] = useState(navigator.onLine);

  useEffect(() => {
    const handleOnline = () => setIsOnline(true);
    const handleOffline = () => setIsOnline(false);

    window.addEventListener('online', handleOnline);
    window.addEventListener('offline', handleOffline);

    return () => {
      window.removeEventListener('online', handleOnline);
      window.removeEventListener('offline', handleOffline);
    };
  }, []);

  return (
    <div className="min-h-screen font-sans selection:bg-orange-100 selection:text-[#ff6b00]">
      <Toaster position="bottom-right" reverseOrder={false} />
      
      {!isOnline && (
        <div className="fixed top-0 left-0 right-0 z-[60] bg-gray-900 text-white py-2 px-4 flex items-center justify-center gap-3 animate-in slide-in-from-top duration-300">
          <div className="w-2 h-2 bg-red-500 rounded-full animate-pulse"></div>
          <span className="text-[10px] font-black uppercase tracking-[0.2em]">You are offline • Reconnecting...</span>
        </div>
      )}
      
      <Routes>
        {/* Customer Panel */}
        <Route element={<MainLayout />}>
          <Route path="/" element={
            <LandingPageGuard>
              <div className="flex flex-col gap-0">
                <Hero />
                <WhyChooseUs />
                <Menu previewOnly={true} />
              </div>
            </LandingPageGuard>
          } />
          
          {/* Public Auth Routes - Redirect if already logged in */}
          <Route 
            path="/login" 
            element={<AuthRouteGuard><Login /></AuthRouteGuard>} 
          />
          <Route 
            path="/signup" 
            element={<AuthRouteGuard><Signup /></AuthRouteGuard>} 
          />
          
          {/* Protected Customer Routes */}
          <Route element={<CustomerRoute><Outlet /></CustomerRoute>}>
            <Route path="/home" element={
              <div className="flex flex-col gap-0">
                <Hero />
                <WhyChooseUs />
                <Menu previewOnly={true} />
              </div>
            } />
            <Route path="/menu" element={<MenuPage />} />
            <Route path="/nearby" element={ENABLE_NEARBY_FEATURE ? <NearbyRestaurants /> : <Navigate to="/" />} />
            <Route path="/checkout" element={<CheckoutPage />} />
            <Route path="/add-address" element={<AddAddressPage />} />
            <Route path="/profile" element={<ProfilePage />} />
            <Route path="/orders" element={<ErrorBoundary><OrdersPage /></ErrorBoundary>} />
            <Route path="/track-order" element={<TrackOrderPage />} />
            <Route path="/track-order/:orderId" element={<TrackOrderPage />} />
            <Route path="/order-success" element={<OrderSuccessPage />} />
          </Route>
        </Route>

        {/* Admin Panel */}
        <Route path="/admin/login" element={<AuthRouteGuard><AdminLogin /></AuthRouteGuard>} />
        <Route path="/admin" element={<AdminRoute><AdminLayout /></AdminRoute>}>
          <Route index element={<Navigate to="/admin/dashboard" replace />} />
          <Route path="dashboard" element={<ErrorBoundary><AdminDashboard /></ErrorBoundary>} />
          <Route path="riders" element={<ErrorBoundary><AdminRiders /></ErrorBoundary>} />
          <Route path="orders" element={<ErrorBoundary><AdminOrders /></ErrorBoundary>} />
        </Route>

        {/* Rider Panel */}
        <Route path="/rider/login" element={<AuthRouteGuard><RiderLogin /></AuthRouteGuard>} />
        <Route path="/rider" element={<RiderRoute><RiderLayout /></RiderRoute>}>
          <Route index element={<Navigate to="/rider/dashboard" replace />} />
          <Route path="dashboard" element={<ErrorBoundary><RiderDashboard /></ErrorBoundary>} />
          <Route path="history" element={<ErrorBoundary><RiderHistory /></ErrorBoundary>} />
          <Route path="earnings" element={<ErrorBoundary><RiderEarnings /></ErrorBoundary>} />
        </Route>

        <Route path="*" element={<Navigate to="/" />} />
      </Routes>
    </div>
  );
}

function App() {
  return <AppContent />;
}

export default App;
