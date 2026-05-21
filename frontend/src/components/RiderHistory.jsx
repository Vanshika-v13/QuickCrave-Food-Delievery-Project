import React, { useState, useEffect, useRef } from 'react';
import { 
  History, 
  MapPin, 
  CheckCircle2, 
  XCircle,
  ChevronRight,
  Search,
  Filter
} from 'lucide-react';
import apiClient from '../services/apiClient';
import { getStatusUI, getStatusLabel } from '../services/statusService';

const RiderHistory = () => {
  const [orders, setOrders] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState('ALL');
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    const MAX_ATTEMPTS = 6;

    const fetchHistory = async (attempt = 0) => {
      // Hydration guard: auth_hydrated is set by AuthContext useEffect which may
      // run AFTER this component's useEffect on first mount — retry until ready.
      if (localStorage.getItem('auth_hydrated') !== 'true') {
        if (attempt < MAX_ATTEMPTS) {
          setTimeout(() => { if (mountedRef.current) fetchHistory(attempt + 1); }, 300);
        } else {
          if (mountedRef.current) setLoading(false);
        }
        return;
      }

      let willRetry = false;
      try {
        const res = await apiClient.get('/api/rider/history');
        if (!mountedRef.current) return;

        if (res?.success === true) {
          // Standard wrapped response: { success, message, data }
          setOrders(Array.isArray(res.data) ? res.data : []);
        } else if (Array.isArray(res)) {
          // Direct array fallback
          setOrders(res);
        } else {
          setOrders([]);
        }
      } catch (err) {
        if (!mountedRef.current) return;

        // Silent rejections (hydration pending, missing token) — retry
        if ((err?.hydrationPending || err?.silent || err?.authRequired) && attempt < MAX_ATTEMPTS) {
          willRetry = true;
          setTimeout(() => { if (mountedRef.current) fetchHistory(attempt + 1); }, 400);
          return;
        }

        console.error('[RIDER HISTORY] Fetch failed:', err);
      } finally {
        // Only clear loading when we are NOT about to retry
        if (mountedRef.current && !willRetry) {
          setLoading(false);
        }
      }
    };

    // Small delay so AuthContext useEffect (sets auth_hydrated) fires first
    const initTimer = setTimeout(() => fetchHistory(), 120);

    return () => {
      mountedRef.current = false;
      clearTimeout(initTimer);
    };
  }, []);

  const filteredOrders = orders.filter(order => {
    if (filter === 'ALL') return true;
    return order.status === filter;
  });

  return (
    <div className="max-w-5xl mx-auto pb-12 font-sans">
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-6 mb-8">
        <div>
          <h1 className="text-2xl font-black text-gray-900 uppercase tracking-tight">Delivery History</h1>
          <p className="text-gray-500 font-bold text-[10px] uppercase tracking-widest mt-1">Your Performance Records</p>
        </div>

        <div className="flex items-center gap-2">
          <div className="relative">
            <Filter className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
            <select 
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              className="pl-10 pr-4 py-2.5 bg-white border border-gray-100 rounded-lg text-sm font-bold text-gray-700 focus:outline-none focus:ring-1 focus:ring-[#f97316] appearance-none cursor-pointer min-w-[140px]"
            >
              <option value="ALL">All Completed</option>
              <option value="DELIVERED">Delivered</option>
              <option value="DELIVERED_SUCCESS">Delivered (Legacy)</option>
              <option value="CANCELLED">Cancelled</option>
            </select>
          </div>
        </div>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-20">
          <div className="w-10 h-10 border-4 border-orange-500 border-t-transparent rounded-full animate-spin"></div>
        </div>
      ) : filteredOrders.length === 0 ? (
        <div className="bg-white border border-gray-100 rounded-lg p-20 text-center shadow-sm">
          <div className="w-20 h-20 bg-gray-50 rounded-full flex items-center justify-center mx-auto mb-6">
            <History className="w-10 h-10 text-gray-200" />
          </div>
          <h2 className="text-xl font-black text-gray-900 uppercase tracking-tight mb-2">No history found</h2>
          <p className="text-gray-500 font-medium">You haven't completed any deliveries yet. Start riding to see your records here!</p>
        </div>
      ) : (
        <div className="space-y-4">
          {filteredOrders.map(order => (
            <div key={order.order_id} className="bg-white border border-gray-100 rounded-lg p-6 shadow-sm hover:border-orange-200 transition-all group">
              <div className="flex flex-col md:flex-row md:items-center justify-between gap-6">
                <div className="flex-1">
                  <div className="flex items-center gap-3 mb-3">
                    <span className="text-[10px] font-black text-gray-400 uppercase tracking-widest">Order #{order.order_id}</span>
                    <span className={`flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[10px] font-black uppercase tracking-widest border ${getStatusUI(order.status).color}`}>
                      <span className={`w-1.5 h-1.5 rounded-full ${getStatusUI(order.status).dot}`}></span>
                      {getStatusLabel(order.status)}
                    </span>
                    <span className="text-[10px] font-black text-gray-400 uppercase tracking-widest border border-gray-100 px-2 py-1 rounded-md">
                      {order.payment_method}
                    </span>
                  </div>
                  <h3 className="text-lg font-black text-gray-900 mb-1">{order.customer_name}</h3>
                  <div className="flex items-center gap-2 text-gray-500 text-xs font-bold">
                    <MapPin className="w-3.5 h-3.5 text-gray-400" />
                    <span className="truncate">{order.customer_address || 'Standard Delivery'}</span>
                  </div>
                </div>

                <div className="flex items-center gap-8 px-6 border-l border-gray-50">
                  <div className="text-center">
                    <p className="text-[10px] font-black text-gray-400 uppercase tracking-widest mb-1">Earning</p>
                    <p className="text-sm font-black text-green-600">₹{order.rider_earning?.toFixed(2)}</p>
                  </div>
                  <div className="text-center">
                    <p className="text-[10px] font-black text-gray-400 uppercase tracking-widest mb-1">Total</p>
                    <p className="text-sm font-black text-gray-900">₹{order.total_amount?.toFixed(2)}</p>
                  </div>
                  <div className="text-center">
                    <p className="text-[10px] font-black text-gray-400 uppercase tracking-widest mb-1">Delivered</p>
                    <p className="text-sm font-black text-gray-900">
                      {order.delivered_at && order.delivered_at !== 'None'
                        ? new Date(order.delivered_at).toLocaleDateString('en-IN', {
                            day: '2-digit', month: 'short'
                          })
                        : '—'}
                    </p>
                  </div>
                  <button className="w-10 h-10 bg-gray-50 rounded-lg flex items-center justify-center text-gray-400 group-hover:bg-orange-50 group-hover:text-[#f97316] transition-all">
                    <ChevronRight className="w-5 h-5" />
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
};

export default RiderHistory;
