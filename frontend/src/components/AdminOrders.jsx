import React, { useState, useEffect, useMemo, useRef, useCallback } from 'react';
import { 
  ShoppingBag, Search, ChevronDown, 
  AlertCircle, Package, CheckCircle2,
  XCircle, Clock, RefreshCw, ChevronLeft, ChevronRight
} from 'lucide-react';
import { toast } from 'react-hot-toast';
import { getStatusUI, normalizeStatus } from '../services/statusService';
import apiClient from '../services/apiClient';
import { API_BASE_URL, WS_BASE_URL } from '../config/constants';
import { useAuth } from '../hooks/useAuth';

const AdminOrders = () => {
  const { adminToken, loading: authLoading } = useAuth();
  const [orders, setOrders] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [searchTerm, setSearchTerm] = useState('');
  const [statusFilter, setStatusFilter] = useState('ALL');
  const [currentPage, setCurrentPage] = useState(1);
  const ordersPerPage = 15;

  const [riders, setRiders] = useState([]);
  const [isUpdating, setIsUpdating] = useState({}); // orderId -> boolean
  const processedOrderIds = useRef(new Set());
  // Concurrent assignment protection: tracks in-flight assign calls per orderId
  const pendingAssignmentRef = useRef(new Set());
  const [filterTab, setFilterTab] = useState('PLACED'); // PLACED (Active) vs DELIVERED

  const fetchRiders = async () => {
    if (authLoading || !adminToken) return;
    try {
      const response = await apiClient.get('/api/admin/riders');
      setRiders(response?.success ? response.data : []);
    } catch (err) {
      if (err?.silent) return;
      console.error("Failed to fetch riders:", err);
    }
  };

  const assignRider = useCallback(async (orderId, riderId, isAuto = false) => {
    // CONCURRENT ASSIGNMENT PROTECTION:
    // If an assignment call is already in-flight for this order, drop the extra click silently.
    if (pendingAssignmentRef.current.has(orderId)) {
      return;
    }
    pendingAssignmentRef.current.add(orderId);
    try {
      setIsUpdating(prev => ({ ...prev, [orderId]: true }));
      const response = await apiClient.put(`/api/admin/orders/${orderId}/assign-rider`, { rider_id: riderId });
      
      if (response?.success) {
        if (!isAuto) toast.success(`Rider assigned to #${orderId}`);
        // Update only the rider fields locally; do NOT touch order.status
        // (status is the backend's source of truth — will sync on next poll)
        setOrders(prev => prev.map(o => 
          o.order_id === orderId 
            ? { ...o, rider_id: riderId, rider: { ...(o.rider || {}), id: riderId, riderId, name: riders.find(r => r.id === riderId)?.name } } 
            : o
        ));
        // Refresh riders list so busy/available status is up to date
        fetchRiders();
      } else {
        if (!isAuto) toast.error(response?.message || "Failed to assign rider");
      }
    } catch (err) {
      // Surface the real backend error message (e.g. "This rider already has an active delivery")
      const backendMsg =
        err?.response?.data?.message ||
        err?.response?.data?.detail ||
        err?.message ||
        "Connection error during assignment";
      console.error("Assignment error:", {
        status: err?.response?.status,
        data: err?.response?.data,
        message: err?.message,
        orderId,
        riderId
      });
      if (!isAuto) toast.error(backendMsg);
    } finally {
      pendingAssignmentRef.current.delete(orderId);
      setIsUpdating(prev => ({ ...prev, [orderId]: false }));
    }
  }, [riders]);

  const autoAssignRiders = useCallback((allOrders) => {
    // Frontend must not interpret workflow rules. Auto-assignment is disabled.
    return;
  }, [riders, assignRider]);

  const fetchOrders = async () => {
    if (authLoading || !adminToken) return;
    try {
      setError(null);
      const response = await apiClient.get('/api/admin/orders');
      const data = response?.success ? response.data : (Array.isArray(response) ? response : []);
      setOrders(data);
    } catch (err) {
      console.error("Failed to fetch admin orders:", err);
      setError("Failed to load orders. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchRiders();
    fetchOrders();
    const interval = setInterval(fetchOrders, 15000);
    return () => {
      console.log('[ADMIN][ORDERS] Cleaning up intervals...');
      clearInterval(interval);
    };
  }, []);

  useEffect(() => {
    if (authLoading || !adminToken) return undefined;
    let socket = null;
    let pingTimer = null;
    let stopped = false;

    const connect = () => {
      if (stopped) return;
      socket = new WebSocket(`${WS_BASE_URL}/ws/admin?token=${adminToken}`);
      socket.onopen = () => {
        pingTimer = setInterval(() => {
          if (socket?.readyState === WebSocket.OPEN) socket.send('ping');
        }, 20000);
      };
      socket.onmessage = (ev) => {
        if (ev.data === 'pong') return;
        try {
          const data = JSON.parse(ev.data);
          if (data.event === 'ORDER_REMOVED' && data.order_id != null) {
            setOrders((prev) => prev.filter((o) => o.order_id !== data.order_id));
          }
        } catch (_) { /* ignore */ }
      };
      socket.onclose = () => {
        if (pingTimer) clearInterval(pingTimer);
        pingTimer = null;
      };
    };

    connect();
    return () => {
      stopped = true;
      if (pingTimer) clearInterval(pingTimer);
      if (socket && socket.readyState === WebSocket.OPEN) socket.close();
    };
  }, [adminToken, authLoading]);

  const handleUpdateStatus = async (orderId, nextStatus) => {
    try {
      setIsUpdating(prev => ({ ...prev, [orderId]: true }));
      const res = await apiClient.put(`/api/admin/orders/${orderId}/status`, { status: nextStatus });
      if (res.success) {
        toast.success(`Order #${orderId} moved to ${nextStatus.replace(/_/g, ' ')}`);
        // STRICT BACKEND SOURCE-OF-TRUTH:
        // Do NOT optimistically assume the new status for button rendering.
        // Immediately refetch from backend so buttons reflect the authoritative state.
        await fetchOrders();
      } else {
        toast.error(res.message || "Failed to update status");
        // BACKEND REJECTION SYNC:
        // On any failure the backend has rejected our transition.
        // Immediately resync so stale buttons are replaced with real backend state.
        await fetchOrders();
      }
    } catch (err) {
      const status = err?.response?.status;
      if (status === 400 || status === 409) {
        // 400 = invalid transition, 409 = optimistic lock conflict
        // In both cases, immediately resync from backend to clear stale buttons.
        toast.error(err?.response?.data?.detail || "Status update rejected. Refreshing...");
        await fetchOrders();
      } else {
        toast.error("Error updating status");
      }
    } finally {
      setIsUpdating(prev => ({ ...prev, [orderId]: false }));
    }
  };

  const statusOptions = useMemo(() => {
    const statuses = new Set(orders.map(o => normalizeStatus(o.status)));
    return ['ALL', ...Array.from(statuses)];
  }, [orders]);

  const filteredOrders = useMemo(() => {
    return orders.filter(order => {
      const status = normalizeStatus(order.status);

      const customer = order.customer || {
        name: order.customer_name || order.name,
        phone: order.customer_phone || order.phone,
        address: {
          address_line: order.address_line,
          city: order.city,
          pincode: order.pincode
        }
      };
      const customerNameForSearch = (customer?.name || '').toString();
      const riderNameForSearch = (order?.rider?.name || order?.rider_name || '').toString();
      
      // Tab Filtering
      const matchesTab = filterTab === 'PLACED' 
        ? !['DELIVERED', 'DELIVERED_SUCCESS'].includes(status)
        : ['DELIVERED', 'DELIVERED_SUCCESS'].includes(status);

      const matchesSearch = 
        order.order_id?.toString().includes(searchTerm) || 
        customerNameForSearch.toLowerCase().includes(searchTerm.toLowerCase()) ||
        riderNameForSearch.toLowerCase().includes(searchTerm.toLowerCase());
      
      const matchesStatus = statusFilter === 'ALL' || status === statusFilter;
      
      return matchesTab && matchesSearch && matchesStatus;
    });
  }, [orders, searchTerm, statusFilter, filterTab]);

  const totalPages = Math.ceil(filteredOrders.length / ordersPerPage);
  const paginatedOrders = filteredOrders.slice(
    (currentPage - 1) * ordersPerPage, 
    currentPage * ordersPerPage
  );

  const orderStats = useMemo(() => ({
    total: orders.length,
    active: orders.filter(o => !['DELIVERED', 'CANCELLED'].includes(normalizeStatus(o.status))).length,
    delivered: orders.filter(o => normalizeStatus(o.status) === 'DELIVERED').length,
    cancelled: orders.filter(o => normalizeStatus(o.status) === 'CANCELLED').length,
  }), [orders]);

  if (loading) return (
    <div className="min-h-[60vh] flex items-center justify-center">
      <div className="flex flex-col items-center gap-4">
        <div className="w-12 h-12 border-4 border-[#f97316] border-t-transparent rounded-full animate-spin"></div>
        <p className="text-gray-400 font-bold text-sm">Loading orders...</p>
      </div>
    </div>
  );

  if (error) return (
    <div className="min-h-[60vh] flex items-center justify-center">
      <div className="text-center">
        <AlertCircle className="w-16 h-16 text-red-300 mx-auto mb-4" />
        <h3 className="text-xl font-bold text-gray-700 mb-2">Failed to Load</h3>
        <p className="text-gray-400 mb-6">{error}</p>
        <button 
          onClick={() => { setLoading(true); fetchOrders(); }} 
          className="px-6 py-3 bg-[#f97316] text-white rounded-xl font-bold hover:bg-[#ea580c] transition-colors flex items-center gap-2 mx-auto"
        >
          <RefreshCw className="w-4 h-4" /> Try Again
        </button>
      </div>
    </div>
  );

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-black text-gray-900 tracking-tight flex items-center gap-3">
            <ShoppingBag className="w-7 h-7 text-[#f97316]" />
            Order Management
          </h1>
          <p className="text-gray-400 font-medium mt-1 text-sm">Track and manage all ecosystem orders</p>
        </div>
        <button 
          onClick={() => { setLoading(true); fetchOrders(); }}
          className="flex items-center gap-2 px-4 py-2 bg-white border border-gray-200 rounded-xl text-sm font-bold text-gray-600 hover:bg-gray-50 transition-all"
        >
          <RefreshCw className="w-4 h-4" /> Refresh
        </button>
      </div>

      {/* Quick Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <MiniStat label="Total Orders" value={orderStats.total} icon={Package} color="blue" />
        <MiniStat label="Active" value={orderStats.active} icon={Clock} color="orange" />
        <MiniStat label="Delivered" value={orderStats.delivered} icon={CheckCircle2} color="green" />
        <MiniStat label="Cancelled" value={orderStats.cancelled} icon={XCircle} color="red" />
      </div>

      {/* Filtering Tabs */}
      <div className="flex items-center p-1 bg-gray-100 rounded-2xl w-fit">
        <button 
          onClick={() => { setFilterTab('PLACED'); setCurrentPage(1); }}
          className={`px-6 py-2.5 rounded-xl text-sm font-black transition-all ${
            filterTab === 'PLACED' 
              ? 'bg-white text-[#f97316] shadow-sm' 
              : 'text-gray-400 hover:text-gray-600'
          }`}
        >
          Orders Placed
        </button>
        <button 
          onClick={() => { setFilterTab('DELIVERED'); setCurrentPage(1); }}
          className={`px-6 py-2.5 rounded-xl text-sm font-black transition-all ${
            filterTab === 'DELIVERED' 
              ? 'bg-white text-[#f97316] shadow-sm' 
              : 'text-gray-400 hover:text-gray-600'
          }`}
        >
          Delivered
        </button>
      </div>

      {/* Filters */}
      <div className="flex flex-col sm:flex-row gap-3">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
          <input 
            type="text" 
            placeholder="Search by ID, customer, or rider..." 
            className="w-full pl-10 pr-4 py-2.5 bg-white border border-gray-200 rounded-xl focus:ring-2 focus:ring-[#f97316]/20 focus:border-[#f97316] outline-none transition-all text-sm font-medium"
            value={searchTerm}
            onChange={(e) => { setSearchTerm(e.target.value); setCurrentPage(1); }}
          />
        </div>
        <div className="relative">
          <select 
            value={statusFilter}
            onChange={(e) => { setStatusFilter(e.target.value); setCurrentPage(1); }}
            className="appearance-none pl-4 pr-10 py-2.5 bg-white border border-gray-200 rounded-xl text-sm font-bold text-gray-600 focus:ring-2 focus:ring-[#f97316]/20 focus:border-[#f97316] outline-none cursor-pointer"
          >
            {statusOptions.map(s => (
              <option key={s} value={s}>{s === 'ALL' ? 'All Statuses' : s.replace(/_/g, ' ')}</option>
            ))}
          </select>
          <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400 pointer-events-none" />
        </div>
      </div>

      {/* Orders Table */}
      <div className="bg-white rounded-2xl shadow-sm border border-gray-100 overflow-hidden">
        {filteredOrders.length === 0 ? (
          <div className="py-20 text-center">
            <ShoppingBag className="w-16 h-16 text-gray-200 mx-auto mb-4" />
            <h3 className="text-lg font-bold text-gray-400">No orders found</h3>
            <p className="text-gray-300 text-sm mt-1">
              {searchTerm || statusFilter !== 'ALL' ? 'Try adjusting your filters' : 'Orders will appear here when customers place them'}
            </p>
          </div>
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full text-left">
                <thead>
                  <tr className="bg-gray-50/80 text-[10px] font-black text-gray-400 uppercase tracking-widest">
                    <th className="px-6 py-4">Order ID</th>
                    <th className="px-6 py-4">Customer</th>
                    <th className="px-6 py-4">Status</th>
                    <th className="px-6 py-4">Rider</th>
                    <th className="px-6 py-4">Payment</th>
                    <th className="px-6 py-4">Total</th>
                    <th className="px-6 py-4">Date</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-50">
                  {paginatedOrders.map((order) => {
                    const statusUI = getStatusUI(order.status);
                    const customer = order.customer || {
                      name: order.customer_name || order.name,
                      phone: order.customer_phone || order.phone,
                      address: {
                        address_line: order.address_line,
                        city: order.city,
                        pincode: order.pincode
                      }
                    };
                    const riderName = order?.rider?.name || order.rider_name;
                    const riderId = order?.rider?.id || order.rider_id || "";
                    return (
                      <tr key={order.order_id} className="hover:bg-gray-50/50 transition-colors">
                        <td className="px-6 py-4 font-black text-gray-900 text-sm">#{order.order_id}</td>
                        <td className="px-6 py-4">
                          <div className="flex items-center gap-3">
                            <div className="w-8 h-8 bg-orange-100 rounded-full flex items-center justify-center text-[#f97316] font-bold text-xs uppercase shrink-0">
                              {customer?.name?.[0] || '?'}
                            </div>
                            <span className="font-bold text-gray-700 text-sm truncate max-w-[140px]">{customer?.name || 'Unknown'}</span>
                          </div>
                        </td>
                        <td className="px-6 py-4">
                          <div className="flex flex-col gap-2">
                            <span className={`inline-block px-3 py-1 rounded-full text-[10px] font-black border whitespace-nowrap w-fit ${statusUI.color}`}>
                              {normalizeStatus(order.status).replace(/_/g, ' ')}
                            </span>
                            
                            {normalizeStatus(order.status) === 'ORDER_PLACED' && (
                              <button 
                                onClick={() => handleUpdateStatus(order.order_id, 'RESTAURANT_CONFIRMED')}
                                disabled={isUpdating[order.order_id]}
                                className="text-[9px] font-black uppercase tracking-widest text-[#f97316] hover:text-[#ea580c] transition-colors flex items-center gap-1"
                              >
                                <CheckCircle2 className="w-3 h-3" /> Confirm Shop
                              </button>
                            )}
                            
                            {normalizeStatus(order.status) === 'RESTAURANT_CONFIRMED' && (
                              <button 
                                onClick={() => handleUpdateStatus(order.order_id, 'FOOD_READY')}
                                disabled={isUpdating[order.order_id]}
                                className="text-[9px] font-black uppercase tracking-widest text-green-500 hover:text-green-600 transition-colors flex items-center gap-1"
                              >
                                <Package className="w-3 h-3" /> Mark Ready
                              </button>
                            )}
                          </div>
                        </td>
                        <td className="px-6 py-4">
                          {normalizeStatus(order.status) === 'DELIVERED' || normalizeStatus(order.status) === 'DELIVERED_SUCCESS' ? (
                            <div className="flex items-center gap-2">
                              <RiderAvatar name={riderName} src={order?.rider?.profile_pic || order.rider_profile_pic} />
                              <div>
                                <p className="text-xs font-black text-gray-700">{riderName || 'Rider'}</p>
                                <p className="text-[10px] text-green-500 font-bold uppercase tracking-tight">Delivered By</p>
                              </div>
                            </div>
                          ) : (
                            <div className="relative min-w-[140px]">
                              {isUpdating[order.order_id] && (
                                <div className="absolute inset-0 bg-white/50 z-10 flex items-center justify-center rounded-lg">
                                  <div className="w-4 h-4 border-2 border-[#f97316] border-t-transparent rounded-full animate-spin"></div>
                                </div>
                              )}
                              <select 
                                value={riderId || ""}
                                disabled={isUpdating[order.order_id]}
                                onChange={(e) => assignRider(order.order_id, parseInt(e.target.value))}
                                className={`w-full pl-3 pr-8 py-1.5 bg-gray-50 border border-gray-200 rounded-xl text-[11px] font-black text-gray-600 outline-none focus:ring-2 focus:ring-[#f97316]/20 focus:border-[#f97316] appearance-none transition-all ${
                                  isUpdating[order.order_id] ? 'cursor-not-allowed opacity-40' : 'cursor-pointer'
                                }`}
                              >
                                <option value="" disabled>Select Rider</option>
                                {riders.filter(r => r.is_active && r.rider_status === 'available').map(r => {
                                  const isBusy = (r.active_orders || 0) > 0;
                                  return (
                                    <option 
                                      key={r.id} 
                                      value={r.id}
                                      disabled={isBusy && r.id !== riderId}
                                    >
                                      {r.name}{isBusy ? ` (Busy: ${r.active_orders})` : ' ✓ Available'}
                                    </option>
                                  );
                                })}
                                {riders.filter(r => r.is_active && r.rider_status === 'available').length === 0 && (
                                  <option value="" disabled>No available riders</option>
                                )}
                              </select>
                              <ChevronDown className="absolute right-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400 pointer-events-none" />
                            </div>
                          )}
                        </td>
                        <td className="px-6 py-4">
                          <span className="text-xs font-bold text-gray-500 bg-gray-50 px-2 py-1 rounded-lg">
                            {order.payment_method || 'COD'}
                          </span>
                        </td>
                        <td className="px-6 py-4 font-black text-gray-900 text-sm">₹{order.total_amount || order.total_price}</td>
                        <td className="px-6 py-4 text-gray-400 text-xs font-bold whitespace-nowrap">
                          {order.created_at ? new Date(order.created_at).toLocaleString([], { 
                            month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' 
                          }) : '—'}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            {/* Pagination */}
            {totalPages > 1 && (
              <div className="px-6 py-4 border-t border-gray-50 flex items-center justify-between">
                <p className="text-xs text-gray-400 font-bold">
                  Showing {(currentPage - 1) * ordersPerPage + 1}–{Math.min(currentPage * ordersPerPage, filteredOrders.length)} of {filteredOrders.length}
                </p>
                <div className="flex items-center gap-2">
                  <button 
                    onClick={() => setCurrentPage(p => Math.max(1, p - 1))} 
                    disabled={currentPage === 1}
                    className="p-2 rounded-lg border border-gray-200 text-gray-400 hover:text-gray-600 disabled:opacity-30 transition-all"
                  >
                    <ChevronLeft className="w-4 h-4" />
                  </button>
                  {Array.from({ length: Math.min(5, totalPages) }, (_, i) => {
                    const page = i + 1;
                    return (
                      <button 
                        key={page} 
                        onClick={() => setCurrentPage(page)}
                        className={`w-8 h-8 rounded-lg text-xs font-black transition-all ${
                          currentPage === page 
                            ? 'bg-[#f97316] text-white' 
                            : 'text-gray-400 hover:bg-gray-50'
                        }`}
                      >
                        {page}
                      </button>
                    );
                  })}
                  <button 
                    onClick={() => setCurrentPage(p => Math.min(totalPages, p + 1))} 
                    disabled={currentPage === totalPages}
                    className="p-2 rounded-lg border border-gray-200 text-gray-400 hover:text-gray-600 disabled:opacity-30 transition-all"
                  >
                    <ChevronRight className="w-4 h-4" />
                  </button>
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
};

const MiniStat = ({ label, value, icon: Icon, color }) => {
  const colorMap = {
    blue: 'bg-blue-50 text-blue-600',
    orange: 'bg-orange-50 text-orange-600',
    green: 'bg-green-50 text-green-600',
    red: 'bg-red-50 text-red-600',
  };

  return (
    <div className="bg-white p-4 rounded-2xl border border-gray-100 flex items-center gap-4">
      <div className={`p-2.5 rounded-xl ${colorMap[color]}`}>
        <Icon className="w-5 h-5" />
      </div>
      <div>
        <p className="text-[10px] font-black text-gray-400 uppercase tracking-wider">{label}</p>
        <p className="text-xl font-black text-gray-900">{value}</p>
      </div>
    </div>
  );
};

const RiderAvatar = ({ name, src }) => {
  const initials = name?.split(' ').map(n => n[0]).join('').slice(0, 2).toUpperCase() || '?';
  
  return (
    <div className="w-8 h-8 rounded-full overflow-hidden bg-gray-100 flex items-center justify-center shrink-0 border border-gray-200">
      {src ? (
        <img 
          src={src.startsWith('http') ? src : `${API_BASE_URL}${src}`} 
          alt={name} 
          className="w-full h-full object-cover"
          onError={(e) => { e.target.style.display = 'none'; e.target.parentElement.innerHTML = `<span class="text-[10px] font-black text-gray-400">${initials}</span>`; }}
        />
      ) : (
        <span className="text-[10px] font-black text-gray-400">{initials}</span>
      )}
    </div>
  );
};

export default AdminOrders;
