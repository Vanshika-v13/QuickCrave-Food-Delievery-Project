import React, { useState, useEffect, useMemo, useCallback, memo } from 'react';
import { 
  ShoppingBag, TrendingUp, Clock, 
  AlertCircle, Search, Filter, 
  ChevronRight, ArrowUpRight, Bike, MoreVertical
} from 'lucide-react';
import { getStatusUI, normalizeStatus } from '../services/statusService';
import { useAuth } from '../hooks/useAuth';
import apiClient from '../services/apiClient';

const DASHBOARD_ORDERS_LIMIT = 20;
const REFRESH_MS = 30000;

const AdminDashboard = () => {
  const { adminToken, loading: authLoading } = useAuth();
  const [stats, setStats] = useState({ active_orders: 0, today_revenue: 0, total_riders: 0 });
  const [orders, setOrders] = useState([]);
  const [loading, setLoading] = useState(true);
  const [searchTerm, setSearchTerm] = useState('');

  const fetchStats = useCallback(async () => {
    if (authLoading || !adminToken || localStorage.getItem('auth_hydrated') !== 'true') return;
    try {
      const statsRes = await apiClient.get('/api/admin/stats');
      const safeStats = (statsRes?.success ? statsRes.data : statsRes) || {};
      setStats(safeStats);
    } catch (err) {
      if (!err?.silent) console.error('Failed to fetch admin stats:', err);
    }
  }, [adminToken, authLoading]);

  const fetchOrders = useCallback(async () => {
    if (authLoading || !adminToken || localStorage.getItem('auth_hydrated') !== 'true') return;
    try {
      const ordersRes = await apiClient.get('/api/admin/orders', {
        params: { page: 1, limit: DASHBOARD_ORDERS_LIMIT },
      });
      const payload = ordersRes?.success ? ordersRes.data : ordersRes;
      const safeOrders = Array.isArray(payload?.items)
        ? payload.items
        : Array.isArray(payload)
          ? payload
          : [];
      setOrders(safeOrders);
    } catch (err) {
      if (!err?.silent) console.error('Failed to fetch admin orders:', err);
    }
  }, [adminToken, authLoading]);

  useEffect(() => {
    if (authLoading || !adminToken) return undefined;

    let cancelled = false;
    const load = async () => {
      await Promise.all([fetchStats(), fetchOrders()]);
      if (!cancelled) setLoading(false);
    };
    load();

    const interval = setInterval(() => {
      if (!document.hidden && navigator.onLine) fetchStats();
    }, REFRESH_MS);

    const handleSync = () => {
      if (!document.hidden && navigator.onLine) {
        fetchStats();
        fetchOrders();
      }
    };

    window.addEventListener('online', handleSync);
    window.addEventListener('visibilitychange', handleSync);

    return () => {
      cancelled = true;
      clearInterval(interval);
      window.removeEventListener('online', handleSync);
      window.removeEventListener('visibilitychange', handleSync);
    };
  }, [adminToken, authLoading, fetchStats, fetchOrders]);

  const filteredOrders = useMemo(() => {
    const safeOrders = Array.isArray(orders) ? orders : [];
    return safeOrders.filter((order) => {
      const orderIdText = String(order?.order_id ?? '');
      const customerName = String(order?.customer_name ?? order?.customer?.name ?? '');
      return (
        orderIdText.includes(searchTerm) ||
        customerName.toLowerCase().includes(searchTerm.toLowerCase())
      );
    });
  }, [orders, searchTerm]);

  if (loading) return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50">
      <div className="w-12 h-12 border-4 border-[#f97316] border-t-transparent rounded-full animate-spin"></div>
    </div>
  );

  return (
    <div className="min-h-screen bg-[#F8FAFC] pt-24 pb-12">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        
        <div className="flex flex-col md:flex-row md:items-center justify-between mb-8 gap-4">
          <div>
            <h1 className="text-3xl font-black text-gray-900 tracking-tight flex items-center gap-3">
              Admin Control Center
              <span className="text-xs bg-green-100 text-green-600 px-2 py-1 rounded-full font-bold uppercase">Live</span>
            </h1>
            <p className="text-gray-500 font-medium mt-1">Operational overview of QuickCrave ecosystem</p>
          </div>
          <div className="flex items-center gap-3">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
              <input 
                type="text" 
                placeholder="Search orders..." 
                className="pl-10 pr-4 py-2 bg-white border border-gray-200 rounded-xl focus:ring-2 focus:ring-[#f97316]/20 focus:border-[#f97316] outline-none transition-all w-64"
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
              />
            </div>
            <button type="button" className="p-2 bg-white border border-gray-200 rounded-xl text-gray-500 hover:text-gray-900 transition-all">
              <Filter className="w-5 h-5" />
            </button>
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
          <StatCard 
            title="Active Orders" 
            value={stats.active_orders} 
            icon={ShoppingBag} 
            color="blue" 
            trend="+12% from last hour" 
          />
          <StatCard 
            title="Today's Revenue" 
            value={`₹${stats.today_revenue}`} 
            icon={TrendingUp} 
            color="green" 
            trend="+8% from yesterday" 
          />
          <StatCard 
            title="Active Riders" 
            value={stats.total_riders} 
            icon={Bike} 
            color="purple" 
            trend="92% utilization" 
          />
          <StatCard 
            title="Avg. Delivery" 
            value="32m" 
            icon={Clock} 
            color="orange" 
            trend="-2m improvement" 
          />
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-12 gap-8">
          <div className="lg:col-span-12 bg-white rounded-3xl shadow-sm border border-gray-100 overflow-hidden">
            <div className="px-8 py-6 border-b border-gray-50 flex items-center justify-between">
              <h3 className="text-xl font-black text-gray-900">Live Order Queue</h3>
              <button type="button" className="text-[#f97316] text-sm font-bold hover:underline">View All History</button>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-left">
                <thead>
                  <tr className="bg-gray-50/50 text-[10px] font-black text-gray-400 uppercase tracking-widest">
                    <th className="px-8 py-4">Order ID</th>
                    <th className="px-8 py-4">Customer</th>
                    <th className="px-8 py-4">Status</th>
                    <th className="px-8 py-4">Partner</th>
                    <th className="px-8 py-4">Total</th>
                    <th className="px-8 py-4">Time</th>
                    <th className="px-8 py-4 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-50">
                  {filteredOrders.map((order) => {
                    const statusUI = getStatusUI(order.status);
                    const customerName = order?.customer_name || order?.customer?.name || 'Unknown';
                    const firstInitial = String(customerName)?.[0] || '?';
                    const riderName = order?.rider_name || order?.rider?.name;
                    return (
                      <tr key={order.order_id} className="hover:bg-gray-50/50 transition-colors group">
                        <td className="px-8 py-5 font-black text-gray-900 text-sm">#{order.order_id}</td>
                        <td className="px-8 py-5">
                          <div className="flex items-center gap-3">
                            <div className="w-8 h-8 bg-orange-100 rounded-full flex items-center justify-center text-[#f97316] font-bold text-xs uppercase">
                              {firstInitial}
                            </div>
                            <span className="font-bold text-gray-700">{customerName}</span>
                          </div>
                        </td>
                        <td className="px-8 py-5">
                          <span className={`px-3 py-1 rounded-full text-[10px] font-black border ${statusUI.color}`}>
                            {normalizeStatus(order.status).replace(/_/g, ' ')}
                          </span>
                        </td>
                        <td className="px-8 py-5">
                          {riderName ? (
                            <div className="flex items-center gap-2 text-gray-600 font-bold text-xs">
                              <Bike className="w-3.5 h-3.5" />
                              {riderName}
                            </div>
                          ) : (
                            <span className="text-amber-500 font-bold text-[10px] uppercase flex items-center gap-1.5">
                              <AlertCircle className="w-3.5 h-3.5" />
                              Unassigned
                            </span>
                          )}
                        </td>
                        <td className="px-8 py-5 font-black text-gray-900">₹{order.total_amount}</td>
                        <td className="px-8 py-5 text-gray-400 text-xs font-bold">
                          {order.created_at
                            ? new Date(order.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
                            : '—'}
                        </td>
                        <td className="px-8 py-5 text-right">
                          <div className="flex items-center justify-end gap-2">
                            <button type="button" className="p-2 text-gray-400 hover:text-[#f97316] transition-colors">
                              <MoreVertical className="w-4 h-4" />
                            </button>
                            <button type="button" className="p-2 bg-gray-50 text-gray-400 rounded-lg hover:bg-[#f97316] hover:text-white transition-all">
                              <ChevronRight className="w-4 h-4" />
                            </button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

const StatCard = memo(({ title, value, icon: Icon, color, trend }) => {
  const colorMap = {
    blue: 'bg-blue-50 text-blue-600',
    green: 'bg-green-50 text-green-600',
    purple: 'bg-purple-50 text-purple-600',
    orange: 'bg-orange-50 text-orange-600',
  };

  const safeTrend = typeof trend === 'string' ? trend : '';
  const trendFirstToken = safeTrend.split(' ')?.[0] || '';

  return (
    <div className="bg-white p-6 rounded-3xl shadow-sm border border-gray-100 hover:shadow-md transition-shadow">
      <div className="flex items-start justify-between mb-4">
        <div className={`p-3 rounded-2xl ${colorMap[color]}`}>
          <Icon className="w-6 h-6" />
        </div>
        <div className="text-[10px] font-black text-green-500 bg-green-50 px-2 py-1 rounded-lg flex items-center gap-1">
          <ArrowUpRight className="w-3 h-3" />
          {trendFirstToken}
        </div>
      </div>
      <p className="text-sm font-bold text-gray-400 uppercase tracking-widest">{title}</p>
      <h4 className="text-3xl font-black text-gray-900 mt-1">{value}</h4>
      <p className="text-[10px] text-gray-400 mt-2 font-medium">{safeTrend}</p>
    </div>
  );
});

StatCard.displayName = 'StatCard';

export default AdminDashboard;
