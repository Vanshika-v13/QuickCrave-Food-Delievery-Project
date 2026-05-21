import React, { useEffect } from 'react';
import { useLocation, useNavigate, Link } from 'react-router-dom';
import { CheckCircle, Home, Package, ArrowRight, ShoppingBag } from 'lucide-react';
import { motion } from 'framer-motion';

const OrderSuccessPage = () => {
  const location = useLocation();
  const navigate = useNavigate();
  const orderId = location.state?.orderId;

  useEffect(() => {
    // If no orderId in state, redirect to home
    if (!orderId) {
      navigate('/');
    }
    // Scroll to top on mount
    window.scrollTo(0, 0);
  }, [orderId, navigate]);

  if (!orderId) return null;

  return (
    <div className="min-h-screen bg-white flex flex-col items-center justify-center px-4 py-12">
      <motion.div 
        initial={{ scale: 0.8, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        transition={{ duration: 0.5, ease: "easeOut" }}
        className="max-w-md w-full text-center"
      >
        {/* Success Icon */}
        <div className="mb-8 flex justify-center">
          <div className="w-24 h-24 bg-green-50 rounded-full flex items-center justify-center relative">
            <motion.div
              initial={{ scale: 0 }}
              animate={{ scale: 1 }}
              transition={{ delay: 0.3, type: "spring", stiffness: 200 }}
            >
              <CheckCircle className="w-16 h-16 text-green-500" />
            </motion.div>
            
            {/* Animated Rings */}
            <motion.div 
              animate={{ scale: [1, 1.2, 1], opacity: [0.5, 0.2, 0.5] }}
              transition={{ repeat: Infinity, duration: 2 }}
              className="absolute inset-0 border-4 border-green-200 rounded-full"
            />
          </div>
        </div>

        {/* Success Message */}
        <h1 className="text-3xl font-bold text-gray-900 mb-2">Order Placed Successfully!</h1>
        <p className="text-gray-500 mb-8 font-medium">
          Hang tight! Your delicious food is on its way.
        </p>

        {/* Order Info Card */}
        <div className="bg-gray-50 border border-gray-100 rounded-2xl p-6 mb-10 text-left">
          <div className="flex items-center justify-between mb-4 pb-4 border-b border-gray-200/60">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 bg-white rounded-xl flex items-center justify-center shadow-sm border border-gray-100">
                <Package className="w-5 h-5 text-orange-500" />
              </div>
              <div>
                <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest">Order ID</p>
                <p className="text-sm font-bold text-gray-800">#{orderId}</p>
              </div>
            </div>
            <div className="text-right">
              <span className="px-3 py-1 bg-green-100 text-green-700 text-[10px] font-bold rounded-full uppercase tracking-wider">
                Confirmed
              </span>
            </div>
          </div>
          
          <div className="flex items-start gap-3">
            <div className="w-10 h-10 bg-white rounded-xl flex items-center justify-center shadow-sm border border-gray-100 shrink-0">
              <ShoppingBag className="w-5 h-5 text-orange-500" />
            </div>
            <div>
              <p className="text-sm font-semibold text-gray-800 mb-1">Estimated Delivery</p>
              <p className="text-xs text-gray-500 font-medium">Your order will be delivered within 30-45 mins</p>
            </div>
          </div>
        </div>

        {/* Action Buttons */}
        <div className="flex flex-col gap-3">
          <Link 
            to={`/track/${orderId}`}
            className="w-full py-4 bg-orange-500 text-white rounded-xl font-bold text-sm hover:bg-orange-600 transition-all shadow-lg shadow-orange-200 flex items-center justify-center gap-2 group"
          >
            Track My Order
            <ArrowRight className="w-4 h-4 group-hover:translate-x-1 transition-transform" />
          </Link>
          
          <Link 
            to="/"
            className="w-full py-4 bg-white text-gray-700 border border-gray-200 rounded-xl font-bold text-sm hover:bg-gray-50 transition-all flex items-center justify-center gap-2"
          >
            <Home className="w-4 h-4" />
            Back to Home
          </Link>
        </div>

        {/* Support Link */}
        <p className="mt-10 text-xs text-gray-400 font-medium">
          Need help with your order? <span className="text-orange-500 cursor-pointer hover:underline">Contact Support</span>
        </p>
      </motion.div>
    </div>
  );
};

export default OrderSuccessPage;
