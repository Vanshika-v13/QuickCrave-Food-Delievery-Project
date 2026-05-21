import React, { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { 
  Package, MapPin, Clock, IndianRupee, ChevronRight, 
  ShoppingBag, Search, Filter, Loader2, AlertCircle,
  Calendar, CreditCard, ArrowRight, Home, Trash2
} from 'lucide-react';
import { toast } from 'react-hot-toast';
import { useAuth } from '../hooks/useAuth';
import { normalizeStatus, getStatusUI } from '../services/statusService';
import apiClient from '../services/apiClient';

const OrdersPage = () => {
  const [orders, setOrders] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [deleteTarget, setDeleteTarget] = useState(null);
  const [deletingOrderId, setDeletingOrderId] = useState(null);
  const [deleteSubmitting, setDeleteSubmitting] = useState(false);
  const deleteInFlightRef = useRef(false);
  const { isCustomer, customerToken: token, loading: authLoading } = useAuth();
  const navigate = useNavigate();
  const isAuthenticated = !!token;

  useEffect(() => {
    if (authLoading) return;

    if (!isAuthenticated) {
      navigate('/login');
      return;
    }

    const fetchOrders = async () => {
      try {
        const response = await apiClient.get('/api/user_orders');
        // Handle standardized response { success, data }
        const orderData = response?.success ? (response.data?.orders || []) : (response?.orders || []);
        setOrders(orderData);
      } catch (err) {
        console.error("Error fetching orders:", err);
        setError("Failed to load your order history. Please try again.");
        toast.error("Failed to load orders");
      } finally {
        setLoading(false);
      }
    };

    fetchOrders();
  }, [isAuthenticated, authLoading, token, navigate]);

  const openDeleteModal = (order) => {
    if (deleteInFlightRef.current || deletingOrderId != null) return;
    setDeletingOrderId(order.order_id);
    setDeleteTarget(order);
  };

  const closeDeleteModal = () => {
    if (deleteInFlightRef.current || deleteSubmitting) return;
    setDeleteTarget(null);
    setDeletingOrderId(null);
  };

  const confirmDeleteOrder = async () => {
    const id = deleteTarget?.order_id;
    if (!id || deleteInFlightRef.current) return;
    deleteInFlightRef.current = true;
    setDeleteSubmitting(true);
    try {
      const res = await apiClient.delete(`/api/order/${id}`);
      if (res?.success) {
        setOrders((prev) => prev.filter((o) => o.order_id !== id));
        toast.success(res?.message || 'Order deleted successfully');
        setDeleteTarget(null);
        setDeletingOrderId(null);
      } else {
        toast.error(res?.message || 'Could not delete order');
      }
    } catch (err) {
      const msg =
        (typeof err?.detail === 'string' && err.detail) ||
        err?.message ||
        'Could not delete order';
      toast.error(msg);
    } finally {
      deleteInFlightRef.current = false;
      setDeleteSubmitting(false);
      setDeletingOrderId(null);
      setDeleteTarget(null);
    }
  };

  // Removed per-component normalization logic (Rule 2)

  if (loading) {
    return (
      <div className="min-h-screen bg-[#F8F9FA] pt-24 pb-20 flex flex-col items-center justify-center">
        <Loader2 className="w-10 h-10 text-[#ff6b00] animate-spin mb-4" />
        <p className="text-gray-500 font-medium tracking-tight">Fetching your delicious history...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen bg-[#F8F9FA] pt-24 pb-20 flex flex-col items-center justify-center px-6 text-center">
        <div className="w-20 h-20 bg-red-50 rounded-full flex items-center justify-center mb-6">
          <AlertCircle className="w-10 h-10 text-red-500" />
        </div>
        <h2 className="text-2xl font-black text-gray-900 mb-4 tracking-tight">{error}</h2>
        <button 
          onClick={() => window.location.reload()}
          className="px-10 py-4 bg-gray-900 text-white rounded-2xl font-black hover:bg-[#ff6b00] transition-all"
        >
          Try Again
        </button>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-[#FDFDFD] pt-24 pb-24">
      {deleteTarget && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center p-4 bg-black/40">
          <div className="bg-white rounded-2xl max-w-md w-full p-8 shadow-2xl border border-gray-100">
            <h3 className="text-xl font-black text-gray-900 mb-3">Delete order?</h3>
            <p className="text-gray-600 font-medium mb-8">
              Are you sure you want to delete this order?
            </p>
            <div className="flex gap-3 justify-end">
              <button
                type="button"
                disabled={deleteSubmitting}
                onClick={closeDeleteModal}
                className="px-6 py-3 rounded-xl font-bold text-gray-700 bg-gray-100 hover:bg-gray-200 transition-all disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                type="button"
                disabled={deleteSubmitting}
                onClick={confirmDeleteOrder}
                className="px-6 py-3 rounded-xl font-black text-white bg-red-600 hover:bg-red-700 transition-all disabled:opacity-50"
              >
                {deleteSubmitting ? 'Deleting…' : 'Delete'}
              </button>
            </div>
          </div>
        </div>
      )}
      <div className="max-w-6xl mx-auto px-4 md:px-6">
        
        {/* Page Header */}
        <div className="mb-12">
          <h1 className="text-3xl font-black text-gray-900 tracking-tight mb-2">Order History</h1>
          <div className="h-1 w-12 bg-[#ff6b00] rounded-full mb-3"></div>
          <p className="text-gray-500 font-medium">Manage and track your recent food journeys</p>
        </div>

        {(orders || []).length === 0 ? (
          <div className="bg-white rounded-2xl p-20 text-center border border-gray-100 shadow-sm">
            <div className="w-24 h-24 bg-orange-50 rounded-full flex items-center justify-center mx-auto mb-6">
              <ShoppingBag className="w-12 h-12 text-[#ff6b00]" />
            </div>
            <h2 className="text-2xl font-black text-gray-900 mb-3">No orders placed yet</h2>
            <p className="text-gray-500 mb-10 max-w-sm mx-auto">Hungry? Discover the best food from top restaurants and get it delivered fast.</p>
            <button 
              onClick={() => navigate('/menu')}
              className="px-10 py-4 bg-gray-900 text-white rounded-xl font-bold hover:bg-[#ff6b00] transition-all transform hover:scale-[1.02] active:scale-[0.98]"
            >
              Explore Menu
            </button>
          </div>
        ) : (
          <div className="space-y-8">
            {orders.map((order) => (
              <div
                key={order?.order_id || Math.random()}
                className="bg-white border border-gray-100 rounded-2xl overflow-hidden hover:shadow-2xl hover:shadow-gray-200/50 transition-all duration-500"
              >
                {/* Card Header: ID & Date */}
                <div className="px-4 sm:px-8 py-4 bg-gray-50/50 border-b border-gray-100 flex flex-wrap items-center justify-between gap-4">
                  <div className="flex items-center gap-4 sm:gap-6">
                    <div className="flex items-center gap-2">
                      <span className="text-[10px] font-black text-gray-400 uppercase tracking-widest">Order</span>
                      <span className="text-sm font-black text-gray-900">#{order?.order_id || 'N/A'}</span>
                    </div>
                    <div className="flex items-center gap-2 border-l border-gray-200 pl-4 sm:pl-6">
                      <Calendar className="w-3.5 h-3.5 text-gray-400" />
                      <span className="text-sm font-bold text-gray-600">
                        {order?.created_at ? new Date(order.created_at).toLocaleDateString(undefined, { day: '2-digit', month: 'short', year: 'numeric' }) : 'N/A'}
                      </span>
                    </div>
                  </div>
                  <div className={`px-4 py-1.5 rounded-lg border text-[10px] font-black uppercase tracking-widest ${getStatusUI(order?.status).color}`}>
                    {normalizeStatus(order?.status)}
                  </div>
                </div>

                {/* Main Card Content */}
                <div className="p-4 sm:p-8">
                  <div className="flex flex-col lg:flex-row gap-6 sm:gap-12">
                    
                    {/* LEFT SECTION: Items List */}
                    <div className="flex-1 space-y-6 sm:space-y-8">
                      {(order?.items || []).map((item, idx) => (
                        <div key={idx} className="flex items-center gap-4 sm:gap-6 group">
                          <div className="w-20 h-20 sm:w-24 sm:h-24 rounded-xl overflow-hidden border border-gray-100 shrink-0 shadow-sm group-hover:scale-105 transition-transform duration-500 bg-gray-50">
                            <img 
                              src={item?.image || '/images/samosa.jpg'} 
                              alt={item?.name || 'Food item'} 
                              className="w-full h-full object-cover"
                              onError={(e) => { e.target.src = '/images/samosa.jpg'; }}
                            />
                          </div>
                          <div className="flex-1 min-w-0">
                            <h4 className="text-base sm:text-xl font-black text-gray-900 mb-1 truncate group-hover:text-[#ff6b00] transition-colors">{item?.name || 'Unknown Item'}</h4>
                            <div className="flex items-center gap-3">
                              <span className="text-xs font-bold text-gray-500 bg-gray-100 px-2 py-0.5 rounded uppercase tracking-tighter">Qty: {item?.quantity || 0}</span>
                              <span className="text-xs text-gray-300">•</span>
                              <span className="text-sm font-bold text-gray-600 flex items-center">
                                <IndianRupee className="w-3.5 h-3.5" />
                                {item?.unit_price || 0}
                              </span>
                            </div>
                          </div>
                          <div className="text-right hidden sm:block">
                            <p className="text-lg font-black text-gray-900 flex items-center justify-end">
                              <IndianRupee className="w-4 h-4" />
                              {Math.round(item?.total_price || 0)}
                            </p>
                          </div>
                        </div>
                      ))}
                      
                      {/* Delivery Address Peek */}
                      <div className="pt-6 border-t border-gray-50 flex items-start gap-4">
                        <div className="w-10 h-10 bg-orange-50 rounded-xl flex items-center justify-center shrink-0">
                          <MapPin className="w-5 h-5 text-[#ff6b00]" />
                        </div>
                        <div className="min-w-0">
                          <p className="text-[10px] font-black text-gray-400 uppercase tracking-widest mb-1">Delivering To</p>
                          <p className="text-sm font-bold text-gray-700 truncate max-w-md">
                            {order?.address?.address_line || 'N/A'}, {order?.address?.city || ''}
                          </p>
                        </div>
                      </div>
                    </div>

                    {/* RIGHT SECTION: Summary & Actions */}
                    <div className="lg:w-80 shrink-0">
                      <div className="bg-gray-50/70 rounded-2xl p-6 border border-gray-100">
                        <div className="space-y-3 mb-6">
                          <div className="flex justify-between items-center text-[11px] font-black text-gray-400 uppercase tracking-widest">
                            <span>Subtotal</span>
                            <span className="text-gray-900">₹{Math.round(order?.pricing?.subtotal || 0)}</span>
                          </div>
                          <div className="flex justify-between items-center text-[11px] font-black text-gray-400 uppercase tracking-widest">
                            <span>Delivery Fee</span>
                            <span className="text-gray-900">₹{Math.round(order?.pricing?.delivery_fee || 0)}</span>
                          </div>
                          <div className="pt-3 border-t border-gray-200 flex justify-between items-end">
                            <span className="text-xs font-black text-gray-900 uppercase">Grand Total</span>
                            <span className="text-3xl font-black text-[#ff6b00] leading-none">₹{Math.round(order?.pricing?.total || 0)}</span>
                          </div>
                        </div>
                        
                        <div className="flex items-center gap-2 py-3 px-4 bg-white rounded-xl border border-gray-100 mb-6">
                           <CreditCard className="w-4 h-4 text-gray-400" />
                           <span className="text-[10px] font-black text-gray-500 uppercase tracking-widest">{order?.payment_method || 'COD'}</span>
                        </div>

                        <div className="space-y-3">
                          {normalizeStatus(order?.status) !== 'DELIVERED' && normalizeStatus(order?.status) !== 'CANCELLED' && (
                            <button 
                              onClick={() => navigate(`/track-order/${order?.order_id}`)}
                              className="w-full py-4 bg-[#ff6b00] text-white rounded-xl font-black hover:bg-[#e66000] transition-all flex items-center justify-center gap-2 shadow-lg shadow-orange-100 transform hover:scale-[1.02] active:scale-[0.98]"
                            >
                              Track Order
                              <ArrowRight className="w-5 h-5" />
                            </button>
                          )}
                          {normalizeStatus(order?.status) === 'ORDER_PLACED' && (
                            <button
                              type="button"
                              disabled={deleteSubmitting || deletingOrderId != null}
                              onClick={() => openDeleteModal(order)}
                              className="w-full py-4 bg-white border-2 border-red-100 text-red-600 rounded-xl font-bold hover:bg-red-50 transition-all flex items-center justify-center gap-2 disabled:opacity-50"
                            >
                              <Trash2 className="w-5 h-5" />
                              Delete Order
                            </button>
                          )}
                          <button 
                            className="w-full py-4 bg-white border-2 border-gray-100 text-gray-700 rounded-xl font-bold hover:bg-gray-50 transition-all flex items-center justify-center gap-2"
                          >
                            View Receipt
                          </button>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};

export default OrdersPage;
