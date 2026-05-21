import React, { useState, useEffect, useMemo, useCallback, useRef } from 'react';
import { 
  Users, Search, Plus, Filter, Bike, 
  Mail, Phone, Shield, CheckCircle2, 
  XCircle, Trash2, Edit2, Loader2, 
  RefreshCw, AlertCircle, MoreVertical,
  UserPlus, MapPin, Camera
} from 'lucide-react';
import { useAuth } from '../hooks/useAuth';
import { toast } from 'react-hot-toast';
import apiClient from '../services/apiClient';

const AdminRiders = () => {
  const { adminToken, loading: authLoading } = useAuth();
  const [riders, setRiders] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [searchTerm, setSearchTerm] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [showAddForm, setShowAddForm] = useState(false);

  // Hardening Refs
  const mountedRef = useRef(true);
  const lastFetchRef = useRef(0);
  const abortControllerRef = useRef(null);

  // Form State
  const [formData, setFormData] = useState({
    name: '',
    email: '',
    password: '',
    phone: '',
    vehicle_type: 'Bike',
    license_number: '',
    profile_pic: '',
    is_active: true
  });

  const fetchRiders = useCallback(async (force = false) => {
    // 1. Hydration & Auth Guard
    if (authLoading || !adminToken) {
      if (!authLoading) setLoading(false);
      return;
    }

    // 2. Duplicate Request Prevention (1s throttle)
    const now = Date.now();
    if (!force && now - lastFetchRef.current < 1000) return;
    lastFetchRef.current = now;

    // 3. Cleanup existing request
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    abortControllerRef.current = new AbortController();

    try {
      setLoading(true);
      setError(null);
      
      const response = await apiClient.get('/api/admin/riders', {
        signal: abortControllerRef.current.signal
      });

      if (!mountedRef.current) return;

      // 4. Safe Normalization
      const ridersData = response?.data?.riders || response?.data || [];
      setRiders(Array.isArray(ridersData) ? ridersData : []);
      
      if (!response.success && response.message) {
        setError(response.message);
      }
    } catch (err) {
      if (err.name === 'AbortError') return;
      if (!mountedRef.current) return;
      
      console.error("[ADMIN][RIDERS] Fetch failure:", err);
      setError(err.message || "An error occurred while fetching riders");
      toast.error("Failed to load riders list");
    } finally {
      if (mountedRef.current) {
        setLoading(false);
      }
    }
  }, [adminToken, authLoading]);

  useEffect(() => {
    mountedRef.current = true;
    fetchRiders();

    return () => {
      mountedRef.current = false;
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
    };
  }, [fetchRiders]);

  const handleInputChange = (e) => {
    const { name, value, type, checked } = e.target;
    setFormData(prev => ({
      ...prev,
      [name]: type === 'checkbox' ? checked : value
    }));
  };

  const validateForm = () => {
    if (!formData.name.trim()) return "Full Name is required";
    if (!formData.email.trim() || !formData.email.includes('@')) return "Valid Email is required";
    if (!formData.password || formData.password.length < 6) return "Password must be at least 6 characters";
    if (!formData.phone.trim()) return "Phone Number is required";
    if (!formData.vehicle_type) return "Vehicle Type is required";
    if (!formData.license_number.trim()) return "License Number is required";
    return null;
  };

  const handleCreateRider = async (e) => {
    e.preventDefault();
    const errorMsg = validateForm();
    if (errorMsg) {
      toast.error(errorMsg);
      return;
    }

    setIsSubmitting(true);
    try {
      const response = await apiClient.post('/api/admin/riders', formData);
      if (response.success) {
        toast.success("Rider created successfully!");
        setFormData({
          name: '',
          email: '',
          password: '',
          phone: '',
          vehicle_type: 'Bike',
          license_number: '',
          profile_pic: '',
          is_active: true
        });
        setShowAddForm(false);
        fetchRiders();
      } else {
        toast.error(response.message || "Failed to create rider");
      }
    } catch (err) {
      toast.error(err.message || "Email already exists or server error");
    } finally {
      setIsSubmitting(false);
    }
  };

  const toggleRiderStatus = async (riderId, currentStatus) => {
    try {
      const newStatus = !currentStatus;
      const response = await apiClient.put(`/api/admin/riders/${riderId}/status`, { 
        is_active: newStatus 
      });
      if (response.success) {
        toast.success(`Rider ${newStatus ? 'enabled' : 'disabled'} successfully`);
        setRiders(prev => prev.map(r => r.id === riderId ? { ...r, is_active: newStatus ? 1 : 0 } : r));
      }
    } catch (err) {
      toast.error("Failed to update rider status");
    }
  };

  const softDeleteRider = async (riderId) => {
    if (!window.confirm("Are you sure you want to soft-delete this rider? They will be disabled and hidden from active lists.")) return;
    
    try {
      const response = await apiClient.delete(`/api/admin/riders/${riderId}`);
      if (response.success) {
        toast.success("Rider deleted successfully");
        setRiders(prev => prev.map(r => r.id === riderId ? { ...r, is_active: 0 } : r));
      }
    } catch (err) {
      toast.error("Failed to delete rider");
    }
  };

  const filteredRiders = useMemo(() => {
    return riders.filter(rider => 
      rider.name?.toLowerCase().includes(searchTerm.toLowerCase()) ||
      rider.email?.toLowerCase().includes(searchTerm.toLowerCase()) ||
      rider.phone?.includes(searchTerm)
    );
  }, [riders, searchTerm]);

  if (loading && riders.length === 0) {
    return (
      <div className="min-h-[60vh] flex items-center justify-center">
        <div className="flex flex-col items-center gap-4">
          <Loader2 className="w-12 h-12 text-[#f97316] animate-spin" />
          <p className="text-gray-400 font-bold text-sm">Loading riders...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-black text-gray-900 tracking-tight flex items-center gap-3">
            <Users className="w-7 h-7 text-[#f97316]" />
            Rider Management
          </h1>
          <p className="text-gray-400 font-medium mt-1 text-sm">Onboard and manage delivery partners</p>
        </div>
        <div className="flex items-center gap-3">
          <button 
            onClick={() => fetchRiders(true)}
            disabled={loading}
            className="p-2.5 bg-white border border-gray-200 rounded-xl text-gray-400 hover:text-gray-600 transition-all shadow-sm disabled:opacity-50"
          >
            <RefreshCw className={`w-5 h-5 ${loading ? 'animate-spin' : ''}`} />
          </button>
          <button 
            onClick={() => setShowAddForm(!showAddForm)}
            className={`flex items-center gap-2 px-6 py-2.5 rounded-xl font-bold transition-all shadow-lg ${
              showAddForm 
              ? 'bg-gray-100 text-gray-600 hover:bg-gray-200' 
              : 'bg-[#ff6b00] text-white hover:bg-[#e06000] shadow-orange-200'
            }`}
          >
            {showAddForm ? <XCircle className="w-5 h-5" /> : <UserPlus className="w-5 h-5" />}
            {showAddForm ? 'Cancel' : 'Add New Rider'}
          </button>
        </div>
      </div>

      {/* Add Rider Form */}
      {showAddForm && (
        <div className="bg-white rounded-2xl p-8 border border-gray-100 shadow-sm animate-in fade-in slide-in-from-top-4 duration-300">
          <h2 className="text-lg font-black text-gray-900 mb-6 flex items-center gap-2">
            <Plus className="w-5 h-5 text-[#f97316]" />
            Register New Delivery Partner
          </h2>
          <form onSubmit={handleCreateRider} className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            <div className="space-y-2">
              <label className="text-xs font-black text-gray-400 uppercase tracking-widest ml-1">Full Name</label>
              <div className="relative">
                <Users className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
                <input 
                  type="text" 
                  name="name"
                  value={formData.name}
                  onChange={handleInputChange}
                  placeholder="John Doe"
                  className="w-full pl-10 pr-4 py-3 bg-gray-50 border-none rounded-xl text-sm focus:ring-2 focus:ring-[#f97316]/20 outline-none transition-all"
                />
              </div>
            </div>

            <div className="space-y-2">
              <label className="text-xs font-black text-gray-400 uppercase tracking-widest ml-1">Email Address</label>
              <div className="relative">
                <Mail className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
                <input 
                  type="email" 
                  name="email"
                  value={formData.email}
                  onChange={handleInputChange}
                  placeholder="rider@example.com"
                  className="w-full pl-10 pr-4 py-3 bg-gray-50 border-none rounded-xl text-sm focus:ring-2 focus:ring-[#f97316]/20 outline-none transition-all"
                />
              </div>
            </div>

            <div className="space-y-2">
              <label className="text-xs font-black text-gray-400 uppercase tracking-widest ml-1">Password</label>
              <div className="relative">
                <Shield className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
                <input 
                  type="password" 
                  name="password"
                  value={formData.password}
                  onChange={handleInputChange}
                  placeholder="••••••••"
                  className="w-full pl-10 pr-4 py-3 bg-gray-50 border-none rounded-xl text-sm focus:ring-2 focus:ring-[#ff6b00]/20 outline-none transition-all"
                />
              </div>
            </div>

            <div className="space-y-2">
              <label className="text-xs font-black text-gray-400 uppercase tracking-widest ml-1">Phone Number</label>
              <div className="relative">
                <Phone className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
                <input 
                  type="text" 
                  name="phone"
                  value={formData.phone}
                  onChange={handleInputChange}
                  placeholder="+91 9999999999"
                  className="w-full pl-10 pr-4 py-3 bg-gray-50 border-none rounded-xl text-sm focus:ring-2 focus:ring-[#ff6b00]/20 outline-none transition-all"
                />
              </div>
            </div>

            <div className="space-y-2">
              <label className="text-xs font-black text-gray-400 uppercase tracking-widest ml-1">Vehicle Type</label>
              <div className="relative">
                <Bike className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
                <select 
                  name="vehicle_type"
                  value={formData.vehicle_type}
                  onChange={handleInputChange}
                  className="w-full pl-10 pr-4 py-3 bg-gray-50 border-none rounded-xl text-sm focus:ring-2 focus:ring-[#f97316]/20 outline-none appearance-none cursor-pointer"
                >
                  <option value="Bike">Bike</option>
                  <option value="Scooter">Scooter</option>
                  <option value="Electric Cycle">Electric Cycle</option>
                </select>
              </div>
            </div>

            <div className="space-y-2">
              <label className="text-xs font-black text-gray-400 uppercase tracking-widest ml-1">License Number</label>
              <div className="relative">
                <MapPin className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
                <input 
                  type="text" 
                  name="license_number"
                  value={formData.license_number}
                  onChange={handleInputChange}
                  placeholder="DL-123456789"
                  className="w-full pl-10 pr-4 py-3 bg-gray-50 border-none rounded-xl text-sm focus:ring-2 focus:ring-[#f97316]/20 outline-none transition-all"
                />
              </div>
            </div>

            <div className="space-y-2 md:col-span-2">
              <label className="text-xs font-black text-gray-400 uppercase tracking-widest ml-1">Profile Image URL (Optional)</label>
              <div className="relative">
                <Camera className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
                <input 
                  type="text" 
                  name="profile_pic"
                  value={formData.profile_pic}
                  onChange={handleInputChange}
                  placeholder="https://example.com/image.jpg"
                  className="w-full pl-10 pr-4 py-3 bg-gray-50 border-none rounded-xl text-sm focus:ring-2 focus:ring-[#ff6b00]/20 outline-none transition-all"
                />
              </div>
            </div>

            <div className="flex items-end pb-1 ml-1">
              <label className="flex items-center gap-3 cursor-pointer group">
                <div className="relative">
                  <input 
                    type="checkbox" 
                    name="is_active"
                    checked={formData.is_active}
                    onChange={handleInputChange}
                    className="sr-only"
                  />
                  <div className={`w-12 h-6 rounded-full transition-all duration-300 ${formData.is_active ? 'bg-green-500' : 'bg-gray-200'}`}></div>
                  <div className={`absolute top-1 left-1 w-4 h-4 bg-white rounded-full transition-all duration-300 ${formData.is_active ? 'translate-x-6' : 'translate-x-0'}`}></div>
                </div>
                <span className="text-xs font-black text-gray-400 uppercase tracking-widest group-hover:text-gray-600 transition-colors">
                  Initial Status: {formData.is_active ? 'Active' : 'Inactive'}
                </span>
              </label>
            </div>

            <div className="md:col-span-3 flex justify-end pt-4">
              <button 
                type="submit"
                disabled={isSubmitting}
                className="bg-[#f97316] text-white px-10 py-3 rounded-xl font-bold hover:bg-[#ea580c] transition-all flex items-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed shadow-lg shadow-orange-200"
              >
                {isSubmitting ? <Loader2 className="w-5 h-5 animate-spin" /> : <Plus className="w-5 h-5" />}
                {isSubmitting ? 'Onboarding...' : 'Onboard Rider'}
              </button>
            </div>
          </form>
        </div>
      )}

      {/* Filters & Search */}
      <div className="flex flex-col sm:flex-row gap-3">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
          <input 
            type="text" 
            placeholder="Search by name, email, or phone..." 
            className="w-full pl-10 pr-4 py-3 bg-white border border-gray-100 rounded-2xl focus:ring-2 focus:ring-[#ff6b00]/10 outline-none transition-all shadow-sm text-sm"
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
          />
        </div>
        <button className="flex items-center gap-2 px-6 py-3 bg-white border border-gray-100 rounded-2xl text-sm font-bold text-gray-500 hover:bg-gray-50 transition-all shadow-sm">
          <Filter className="w-4 h-4" /> Filter
        </button>
      </div>

      {/* Riders Table */}
      <div className="bg-white rounded-3xl border border-gray-50 shadow-sm overflow-hidden">
        {filteredRiders.length === 0 ? (
          <div className="py-20 text-center">
            <Users className="w-16 h-16 text-gray-100 mx-auto mb-4" />
            <h3 className="text-lg font-bold text-gray-400">No riders found</h3>
            <p className="text-gray-300 text-sm mt-1">Try adjusting your search or add a new rider</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left">
              <thead>
                <tr className="bg-gray-50/50 text-[10px] font-black text-gray-400 uppercase tracking-widest border-b border-gray-50">
                  <th className="px-8 py-5">Partner</th>
                  <th className="px-6 py-5">Contact</th>
                  <th className="px-6 py-5">Vehicle & License</th>
                  <th className="px-6 py-5">Status</th>
                  <th className="px-6 py-5">Availability</th>
                  <th className="px-6 py-5">Onboarded</th>
                  <th className="px-6 py-5 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {filteredRiders.map((rider) => (
                  <tr key={rider.id} className="hover:bg-gray-50/50 transition-colors group">
                    <td className="px-8 py-4">
                      <div className="flex items-center gap-4">
                        <div className="w-12 h-12 rounded-2xl bg-orange-100 flex items-center justify-center text-[#f97316] font-black overflow-hidden relative">
                          {rider.profile_pic ? (
                            <img src={rider.profile_pic} alt={rider.name} className="w-full h-full object-cover" />
                          ) : (
                            rider.name?.[0] || 'R'
                          )}
                        </div>
                        <div>
                          <p className="font-black text-gray-900 text-sm">{rider.name}</p>
                          <p className="text-[10px] font-bold text-gray-400 uppercase tracking-wider">ID: #{rider.id}</p>
                        </div>
                      </div>
                    </td>
                    <td className="px-6 py-4">
                      <div className="space-y-1">
                        <div className="flex items-center gap-2 text-xs font-bold text-gray-600">
                          <Mail className="w-3.5 h-3.5 text-gray-300" />
                          {rider.email}
                        </div>
                        <div className="flex items-center gap-2 text-xs font-bold text-gray-400">
                          <Phone className="w-3.5 h-3.5 text-gray-300" />
                          {rider.phone}
                        </div>
                      </div>
                    </td>
                    <td className="px-6 py-4">
                      <div className="space-y-1">
                        <div className="flex items-center gap-2 text-xs font-black text-gray-700 uppercase">
                          <Bike className="w-3.5 h-3.5 text-[#f97316]" />
                          {rider.vehicle_type}
                        </div>
                        <div className="text-[10px] font-bold text-gray-400 ml-5">
                          {rider.license_number}
                        </div>
                      </div>
                    </td>
                    <td className="px-6 py-4">
                      <span className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-[10px] font-black uppercase tracking-wider border ${
                        rider.is_active 
                          ? 'bg-green-50 text-green-600 border-green-100' 
                          : 'bg-red-50 text-red-600 border-red-100'
                      }`}>
                        <div className={`w-1.5 h-1.5 rounded-full ${rider.is_active ? 'bg-green-500' : 'bg-red-500'}`}></div>
                        {rider.is_active ? 'Active' : 'Disabled'}
                      </span>
                    </td>
                    <td className="px-6 py-4">
                      <span className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-[10px] font-black uppercase tracking-wider border ${
                        rider.rider_status === 'busy'
                          ? 'bg-orange-50 text-orange-600 border-orange-100' 
                          : 'bg-blue-50 text-blue-600 border-blue-100'
                      }`}>
                        <div className={`w-1.5 h-1.5 rounded-full ${rider.rider_status === 'busy' ? 'bg-orange-500' : 'bg-blue-500'}`}></div>
                        {rider.rider_status === 'busy' ? `Busy (${rider.active_orders || 0})` : 'Available'}
                      </span>
                    </td>
                    <td className="px-6 py-4">
                      <p className="text-xs font-bold text-gray-500">
                        {rider.created_at ? new Date(rider.created_at).toLocaleDateString('en-IN', { 
                          day: '2-digit', month: 'short', year: 'numeric' 
                        }) : '—'}
                      </p>
                    </td>
                    <td className="px-6 py-4 text-right">
                      <div className="flex items-center justify-end gap-2">
                        <button 
                          onClick={() => toggleRiderStatus(rider.id, !!rider.is_active)}
                          title={rider.is_active ? 'Disable Rider' : 'Enable Rider'}
                          className={`p-2 rounded-xl border transition-all ${
                            rider.is_active 
                              ? 'text-amber-500 border-amber-100 hover:bg-amber-50' 
                              : 'text-green-500 border-green-100 hover:bg-green-50'
                          }`}
                        >
                          {rider.is_active ? <XCircle className="w-4 h-4" /> : <CheckCircle2 className="w-4 h-4" />}
                        </button>
                        <button 
                          onClick={() => softDeleteRider(rider.id)}
                          title="Delete Rider"
                          className="p-2 text-red-500 border border-red-100 rounded-xl hover:bg-red-50 transition-all"
                        >
                          <Trash2 className="w-4 h-4" />
                        </button>
                        <button className="p-2 text-gray-400 border border-gray-100 rounded-xl hover:bg-gray-50 transition-all">
                          <MoreVertical className="w-4 h-4" />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
};

export default AdminRiders;
