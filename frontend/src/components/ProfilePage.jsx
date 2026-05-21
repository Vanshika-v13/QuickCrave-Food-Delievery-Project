import React, { useState, useEffect } from 'react';
import { 
  MapPin, 
  Phone, 
  User, 
  Mail, 
  Plus, 
  Trash2, 
  Edit2, 
  X, 
  Check, 
  Loader2, 
  Home, 
  Building2, 
  Sparkles,
  ShieldCheck,
  CheckCircle,
  HelpCircle
} from 'lucide-react';
import apiClient from '../services/apiClient';
import { useAuth } from '../hooks/useAuth';
import { toast } from 'react-hot-toast';

export default function ProfilePage() {
  const { customerUser: user = null, customerToken: token = null } = useAuth() || {};
  const [addresses, setAddresses] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  
  // Inline Add Form State
  const [addingInline, setAddingInline] = useState(false);
  const [addLoading, setAddLoading] = useState(false);
  const [addForm, setAddForm] = useState({
    name: '',
    phone: '',
    address_line: '',
    city: '',
    state: '',
    pincode: '',
    is_default: false
  });

  // Inline Edit Row State
  const [editingId, setEditingId] = useState(null); // id of address being edited
  const [editLoading, setEditLoading] = useState(false);
  const [editForm, setEditForm] = useState({
    name: '',
    phone: '',
    address_line: '',
    city: '',
    state: '',
    pincode: '',
    is_default: false
  });

  // Fetch addresses on mount
  useEffect(() => {
    if (token) {
      fetchAddresses();
    }
  }, [token]);

  const fetchAddresses = async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await apiClient.get('/api/user/address');
      if (response?.success) {
        setAddresses(response?.data?.addresses || []);
      } else {
        setError('Failed to fetch addresses. Please refresh.');
      }
    } catch (err) {
      console.error('[PROFILE] Fetch error:', err);
      setError(err?.message || 'Connection failed.');
    } finally {
      setLoading(false);
    }
  };

  // Toggle Add Inline Form
  const handleOpenAdd = () => {
    setAddingInline(true);
    setEditingId(null); // Close any active row editor
    setAddForm({
      name: '',
      phone: '',
      address_line: '',
      city: '',
      state: '',
      pincode: '',
      is_default: addresses.length === 0 // default if first address
    });
  };

  const handleCloseAdd = () => {
    setAddingInline(false);
  };

  // Start Editing a row
  const handleOpenEdit = (addr) => {
    setAddingInline(false); // Close add form
    setEditingId(addr.id);
    setEditForm({
      name: addr.name || '',
      phone: addr.phone || '',
      address_line: addr.address_line || '',
      city: addr.city || '',
      state: addr.state || '',
      pincode: addr.pincode || '',
      is_default: addr.is_default === 1 || addr.is_default === true
    });
  };

  const handleCloseEdit = () => {
    setEditingId(null);
  };

  // Field change handlers
  const handleAddChange = (e) => {
    const { name, value, type, checked } = e.target;
    setAddForm(prev => ({
      ...prev,
      [name]: type === 'checkbox' ? checked : value
    }));
  };

  const handleEditChange = (e) => {
    const { name, value, type, checked } = e.target;
    setEditForm(prev => ({
      ...prev,
      [name]: type === 'checkbox' ? checked : value
    }));
  };

  // POST Add Address Inline
  const handleAddSubmit = async (e) => {
    e.preventDefault();
    
    // Validation
    const cleanPhone = addForm.phone.replace(/\D/g, '');
    if (cleanPhone.length < 10) {
      toast.error('Please enter a valid 10-digit mobile number.');
      return;
    }
    const cleanPincode = addForm.pincode.replace(/\D/g, '');
    if (cleanPincode.length < 6) {
      toast.error('Please enter a valid 6-digit pincode.');
      return;
    }

    const payload = {
      name: addForm.name.trim(),
      phone: cleanPhone,
      address_line: addForm.address_line.trim(),
      city: addForm.city.trim(),
      state: addForm.state.trim(),
      pincode: cleanPincode,
      is_default: addForm.is_default
    };

    if (!payload.name || !payload.address_line || !payload.city || !payload.state) {
      toast.error('All address fields are required.');
      return;
    }

    setAddLoading(true);
    try {
      const res = await apiClient.post('/api/user/address', payload);
      if (res?.success) {
        toast.success('New address added successfully.');
        setAddingInline(false);
        fetchAddresses();
      } else {
        toast.error(res?.message || 'Failed to save address.');
      }
    } catch (err) {
      console.error('[PROFILE] Add error:', err);
      toast.error(err?.response?.data?.detail || err?.message || 'Network error.');
    } finally {
      setAddLoading(false);
    }
  };

  // PUT Edit Address Inline
  const handleEditSubmit = async (e, addressId) => {
    e.preventDefault();

    // Validation
    const cleanPhone = editForm.phone.replace(/\D/g, '');
    if (cleanPhone.length < 10) {
      toast.error('Please enter a valid 10-digit mobile number.');
      return;
    }
    const cleanPincode = editForm.pincode.replace(/\D/g, '');
    if (cleanPincode.length < 6) {
      toast.error('Please enter a valid 6-digit pincode.');
      return;
    }

    const payload = {
      name: editForm.name.trim(),
      phone: cleanPhone,
      address_line: editForm.address_line.trim(),
      city: editForm.city.trim(),
      state: editForm.state.trim(),
      pincode: cleanPincode,
      is_default: editForm.is_default
    };

    if (!payload.name || !payload.address_line || !payload.city || !payload.state) {
      toast.error('All fields are required.');
      return;
    }

    setEditLoading(true);
    try {
      const res = await apiClient.put(`/api/user/address/${addressId}`, payload);
      if (res?.success) {
        toast.success('Address details updated.');
        setEditingId(null);
        fetchAddresses();
      } else {
        toast.error(res?.message || 'Failed to update address.');
      }
    } catch (err) {
      console.error('[PROFILE] Edit error:', err);
      toast.error(err?.response?.data?.detail || err?.message || 'Network error.');
    } finally {
      setEditLoading(false);
    }
  };

  // DELETE Address
  const handleDelete = async (addressId) => {
    if (!window.confirm('Delete this saved location?')) return;

    const original = [...addresses];
    setAddresses(prev => prev.filter(a => a.id !== addressId)); // Optimistic UI

    try {
      const res = await apiClient.delete(`/api/user/address/${addressId}`);
      if (res?.success) {
        toast.success('Address removed.');
        fetchAddresses();
      } else {
        setAddresses(original);
        toast.error(res?.message || 'Failed to delete address.');
      }
    } catch (err) {
      setAddresses(original);
      console.error('[PROFILE] Delete error:', err);
      toast.error('Failed to delete address.');
    }
  };

  // POST Set Default Address
  const [defaultLoadingId, setDefaultLoadingId] = useState(null);

  const handleSetDefault = async (addressId) => {
    if (defaultLoadingId !== null) return;
    setDefaultLoadingId(addressId);

    const original = [...addresses];
    
    // 1. Optimistic UI Update: immediately mark the selected address as default and reset others in React state
    setAddresses(prev => prev.map(addr =>
      addr.id === addressId
        ? { ...addr, is_default: true }
        : { ...addr, is_default: false }
    ));

    try {
      // 2. Trigger default-setting API call
      const res = await apiClient.post(`/api/user/address/${addressId}/default`);
      if (res?.success) {
        toast.success('Default delivery spot updated.');
        
        // 3. Perfect Re-sync: immediately fetch updated list to align local state with server truth
        const response = await apiClient.get('/api/user/address');
        if (response?.success) {
          setAddresses(response?.data?.addresses || []);
        } else {
          // fallback inline update if GET fails
          setAddresses(prev => prev.map(addr =>
            addr.id === addressId
              ? { ...addr, is_default: true }
              : { ...addr, is_default: false }
          ));
        }
      } else {
        setAddresses(original);
        toast.error(res?.message || 'Failed to set default.');
      }
    } catch (err) {
      setAddresses(original);
      console.error('[PROFILE] Default error:', err);
      toast.error('Failed to set default.');
    } finally {
      setDefaultLoadingId(null);
    }
  };

  // User credentials
  const name = user?.name || 'QuickCrave Customer';
  const email = user?.email || 'customer@quickcrave.com';
  const phone = user?.phone || '';
  
  // Initials
  const initials = name
    .split(' ')
    .map(n => n[0])
    .join('')
    .substring(0, 2)
    .toUpperCase();

  // Helper to resolve tag icons
  const getTagIcon = (tagName) => {
    const tag = String(tagName || '').toLowerCase();
    if (tag.includes('home')) return <Home className="w-4 h-4" />;
    if (tag.includes('office') || tag.includes('work')) return <Building2 className="w-4 h-4" />;
    return <MapPin className="w-4 h-4" />;
  };

  return (
    <div className="min-h-screen bg-[#fafafa] pt-10 pb-20 font-sans text-gray-900 antialiased">
      <div className="max-w-4xl mx-auto px-4 sm:px-6">
        
        {/* ================= HEADER SECTION ================= */}
        <div className="bg-white rounded-2xl border border-gray-100 p-6 shadow-xs flex flex-col sm:flex-row items-center sm:items-start gap-5 mb-8">
          {/* Circular gradient initials avatar */}
          <div className="w-20 h-20 rounded-full shrink-0 bg-gradient-to-tr from-[#f97316] to-[#fb923c] flex items-center justify-center text-white text-2xl font-black shadow-inner select-none">
            {initials}
          </div>
          
          {/* Identity details */}
          <div className="text-center sm:text-left flex-1 space-y-1.5 pt-1">
            <div className="flex flex-col sm:flex-row sm:items-center gap-2">
              <h2 className="text-2xl font-black tracking-tight text-gray-900">{name}</h2>
              <span className="inline-flex items-center gap-1 self-center sm:self-auto px-2.5 py-0.5 rounded-full text-xs font-bold bg-orange-50 text-[#f97316] border border-orange-100/50">
                <ShieldCheck className="w-3 h-3 shrink-0" />
                Customer
              </span>
            </div>
            
            <p className="text-sm font-medium text-gray-500">{email}</p>
          </div>
        </div>

        {/* ================= ACCOUNT INFO SECTION (Stripe-Style Settings) ================= */}
        <div className="bg-white rounded-2xl border border-gray-100 p-6 shadow-xs mb-8 space-y-6">
          <div>
            <h3 className="text-base font-extrabold text-gray-900">Personal Information</h3>
            <p className="text-xs text-gray-500 font-semibold mt-0.5">Manage your account identity details</p>
          </div>

          <div className="border-t border-gray-50">
            {/* Row 1: Full Name */}
            <div className="flex flex-col sm:flex-row py-4 border-b border-gray-100 gap-1 sm:gap-4">
              <span className="text-xs font-bold text-gray-400 uppercase tracking-wider w-full sm:w-1/4 select-none">
                Full Name
              </span>
              <span className="text-sm font-semibold text-gray-800 flex-1">
                {name}
              </span>
            </div>

            {/* Row 2: Email */}
            <div className="flex flex-col sm:flex-row py-4 border-b border-gray-100 gap-1 sm:gap-4">
              <span className="text-xs font-bold text-gray-400 uppercase tracking-wider w-full sm:w-1/4 select-none">
                Email Address
              </span>
              <span className="text-sm font-semibold text-gray-800 flex-1">
                {email}
              </span>
            </div>

            {/* Row 3: Account Type */}
            <div className="flex flex-col sm:flex-row py-4 border-b border-gray-100 gap-1 sm:gap-4">
              <span className="text-xs font-bold text-gray-400 uppercase tracking-wider w-full sm:w-1/4 select-none">
                Account Type
              </span>
              <span className="text-sm font-semibold text-gray-800 flex-1 flex items-center gap-1.5">
                Customer account
              </span>
            </div>

            {/* Row 4: Phone (conditional) */}
            {phone && (
              <div className="flex flex-col sm:flex-row py-4 border-b border-gray-100 gap-1 sm:gap-4">
                <span className="text-xs font-bold text-gray-400 uppercase tracking-wider w-full sm:w-1/4 select-none">
                  Phone Number
                </span>
                <span className="text-sm font-semibold text-gray-800 flex-1">
                  {phone}
                </span>
              </div>
            )}
          </div>
        </div>

        {/* ================= ADDRESS SECTION (INLINE ONLY) ================= */}
        <div className="bg-white rounded-2xl border border-gray-100 p-6 shadow-xs space-y-6">
          <div className="flex items-center justify-between gap-4">
            <div>
              <h3 className="text-base font-extrabold text-gray-900">Delivery Addresses</h3>
              <p className="text-xs text-gray-500 font-semibold mt-0.5">Manage your standard delivery spots</p>
            </div>
            
            {!addingInline && (
              <button
                onClick={handleOpenAdd}
                className="flex items-center gap-1.5 text-xs font-extrabold text-[#f97316] hover:text-[#e65c00] transition-colors cursor-pointer"
              >
                <Plus className="w-4 h-4 shrink-0" />
                Add New Address
              </button>
            )}
          </div>

          <div className="border-t border-gray-50">
            
            {/* ================= 1. INLINE ADD FORM ================= */}
            {addingInline && (
              <div className="py-6 border-b border-gray-100 bg-[#fafafa]/50 px-4 -mx-6 sm:-mx-6 sm:px-6 rounded-t-xl transition-all duration-300">
                <form onSubmit={handleAddSubmit} className="space-y-4">
                  <div className="flex items-center justify-between">
                    <h4 className="text-xs font-black text-gray-400 uppercase tracking-wider">
                      Add New Delivery Location
                    </h4>
                    <button
                      type="button"
                      onClick={handleCloseAdd}
                      className="p-1 hover:bg-gray-100 rounded-lg text-gray-400 hover:text-gray-600 transition-all cursor-pointer"
                    >
                      <X className="w-4 h-4" />
                    </button>
                  </div>

                  {/* Form Layout */}
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                    <div className="space-y-1">
                      <label className="text-[10px] font-bold text-gray-400 uppercase tracking-wide">
                        Label Tag (e.g. Home, Office, Work)
                      </label>
                      <input
                        type="text"
                        name="name"
                        required
                        value={addForm.name}
                        onChange={handleAddChange}
                        className="w-full px-3.5 py-2.5 bg-white border border-gray-100 rounded-xl text-sm placeholder-gray-400 focus:outline-none focus:border-[#f97316] focus:ring-2 focus:ring-orange-50 font-bold text-gray-800 transition-all"
                        placeholder="Home, Office..."
                      />
                    </div>
                    <div className="space-y-1">
                      <label className="text-[10px] font-bold text-gray-400 uppercase tracking-wide">
                        10-Digit Mobile Phone
                      </label>
                      <input
                        type="tel"
                        name="phone"
                        required
                        maxLength="10"
                        value={addForm.phone}
                        onChange={handleAddChange}
                        className="w-full px-3.5 py-2.5 bg-white border border-gray-100 rounded-xl text-sm placeholder-gray-400 focus:outline-none focus:border-[#f97316] focus:ring-2 focus:ring-orange-50 font-bold text-gray-800 transition-all"
                        placeholder="9876543210"
                      />
                    </div>
                  </div>

                  <div className="space-y-1">
                    <label className="text-[10px] font-bold text-gray-400 uppercase tracking-wide">
                      Street details / Flat / Address line
                    </label>
                    <input
                      type="text"
                      name="address_line"
                      required
                      value={addForm.address_line}
                      onChange={handleAddChange}
                      className="w-full px-3.5 py-2.5 bg-white border border-gray-100 rounded-xl text-sm placeholder-gray-400 focus:outline-none focus:border-[#f97316] focus:ring-2 focus:ring-orange-50 font-bold text-gray-800 transition-all"
                      placeholder="Room No., Building Name, Street, Landmark"
                    />
                  </div>

                  <div className="grid grid-cols-3 gap-3">
                    <div className="space-y-1">
                      <label className="text-[10px] font-bold text-gray-400 uppercase tracking-wide">
                        City
                      </label>
                      <input
                        type="text"
                        name="city"
                        required
                        value={addForm.city}
                        onChange={handleAddChange}
                        className="w-full px-3 py-2.5 bg-white border border-gray-100 rounded-xl text-xs placeholder-gray-400 focus:outline-none focus:border-[#f97316] focus:ring-2 focus:ring-orange-50 font-bold text-gray-800 transition-all"
                        placeholder="City"
                      />
                    </div>
                    <div className="space-y-1">
                      <label className="text-[10px] font-bold text-gray-400 uppercase tracking-wide">
                        State
                      </label>
                      <input
                        type="text"
                        name="state"
                        required
                        value={addForm.state}
                        onChange={handleAddChange}
                        className="w-full px-3 py-2.5 bg-white border border-gray-100 rounded-xl text-xs placeholder-gray-400 focus:outline-none focus:border-[#f97316] focus:ring-2 focus:ring-orange-50 font-bold text-gray-800 transition-all"
                        placeholder="State"
                      />
                    </div>
                    <div className="space-y-1">
                      <label className="text-[10px] font-bold text-gray-400 uppercase tracking-wide">
                        Pincode
                      </label>
                      <input
                        type="text"
                        name="pincode"
                        required
                        maxLength="6"
                        value={addForm.pincode}
                        onChange={handleAddChange}
                        className="w-full px-3 py-2.5 bg-white border border-gray-100 rounded-xl text-xs placeholder-gray-400 focus:outline-none focus:border-[#f97316] focus:ring-2 focus:ring-orange-50 font-bold text-gray-800 transition-all"
                        placeholder="400001"
                      />
                    </div>
                  </div>

                  <div className="flex items-center gap-2 pt-1">
                    <input
                      type="checkbox"
                      id="add-inline-is-default"
                      name="is_default"
                      checked={addForm.is_default}
                      disabled={addresses.length === 0}
                      onChange={handleAddChange}
                      className="w-4 h-4 text-[#f97316] border-gray-200 rounded focus:ring-[#f97316] cursor-pointer accent-[#f97316]"
                    />
                    <label 
                      htmlFor="add-inline-is-default" 
                      className="text-xs font-bold text-gray-600 cursor-pointer select-none"
                    >
                      Set as default delivery spot
                    </label>
                  </div>

                  {/* Actions */}
                  <div className="flex items-center gap-3 pt-2">
                    <button
                      type="button"
                      disabled={addLoading}
                      onClick={handleCloseAdd}
                      className="px-4 py-2 bg-gray-100 hover:bg-gray-200 text-gray-600 rounded-xl text-xs font-bold transition-all cursor-pointer disabled:opacity-50"
                    >
                      Cancel
                    </button>
                    <button
                      type="submit"
                      disabled={addLoading}
                      className="px-5 py-2 bg-[#f97316] hover:bg-[#e65c00] text-white rounded-xl text-xs font-bold transition-all shadow-xs flex items-center gap-1.5 cursor-pointer disabled:opacity-50"
                    >
                      {addLoading ? (
                        <>
                          <Loader2 className="w-3.5 h-3.5 animate-spin" />
                          Saving...
                        </>
                      ) : (
                        'Save Address'
                      )}
                    </button>
                  </div>
                </form>
              </div>
            )}

            {/* ================= 2. SKELETON LOADERS ================= */}
            {loading && (
              <div className="divide-y divide-gray-100">
                {[1, 2].map(n => (
                  <div key={n} className="py-6 animate-pulse space-y-3">
                    <div className="flex items-center gap-3">
                      <div className="h-4 bg-gray-100 rounded w-16"></div>
                      <div className="h-3.5 bg-gray-100 rounded w-20"></div>
                    </div>
                    <div className="h-4 bg-gray-100 rounded w-5/6"></div>
                    <div className="h-3 bg-gray-100 rounded w-1/3"></div>
                  </div>
                ))}
              </div>
            )}

            {/* ================= 3. ERROR BANNER ================= */}
            {!loading && error && (
              <div className="py-8 text-center text-sm font-semibold text-red-500 bg-red-50/50 rounded-xl p-4 mt-4 border border-red-100/50 space-y-2">
                <p>Failed to retrieve saved locations.</p>
                <button 
                  onClick={fetchAddresses}
                  className="px-4 py-1.5 bg-red-100 text-red-700 rounded-lg text-xs font-bold hover:bg-red-200 transition-all cursor-pointer"
                >
                  Retry Connection
                </button>
              </div>
            )}

            {/* ================= 4. EMPTY STATE ================= */}
            {!loading && !error && addresses.length === 0 && !addingInline && (
              <div className="py-12 text-center space-y-4">
                <div className="w-14 h-14 bg-gray-50 rounded-full flex items-center justify-center mx-auto border border-gray-100">
                  <MapPin className="w-6 h-6 text-gray-400" />
                </div>
                <div className="space-y-1">
                  <p className="text-sm font-bold text-gray-800">No saved addresses yet</p>
                  <p className="text-xs text-gray-500 font-semibold">Add standard places to easily pick locations at checkout.</p>
                </div>
                <button
                  onClick={handleOpenAdd}
                  className="inline-flex items-center gap-1.5 px-4 py-2 bg-[#f97316] hover:bg-[#e65c00] text-white rounded-xl text-xs font-bold transition-all shadow-xs cursor-pointer"
                >
                  <Plus className="w-3.5 h-3.5" />
                  Add Your First Address
                </button>
              </div>
            )}

            {/* ================= 5. ADDRESS ROW LIST ================= */}
            {!loading && !error && addresses.length > 0 && (
              <div className="divide-y divide-gray-100">
                {addresses.map((addr) => {
                  const isDefault = addr.is_default === 1 || addr.is_default === true || addr.is_default === '1';
                  const isEditing = editingId === addr.id;

                  // 5A. ROW IN EDITING MODE
                  if (isEditing) {
                    return (
                      <div key={addr.id} className="py-6 bg-[#fafafa]/50 px-4 -mx-6 sm:-mx-6 sm:px-6 transition-all duration-300">
                        <form onSubmit={(e) => handleEditSubmit(e, addr.id)} className="space-y-4">
                          <div className="flex items-center justify-between">
                            <h4 className="text-xs font-black text-gray-400 uppercase tracking-wider">
                              Modify Address Details
                            </h4>
                            <button
                              type="button"
                              onClick={handleCloseEdit}
                              className="p-1 hover:bg-gray-100 rounded-lg text-gray-400 hover:text-gray-600 transition-all cursor-pointer"
                            >
                              <X className="w-4 h-4" />
                            </button>
                          </div>

                          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                            <div className="space-y-1">
                              <label className="text-[10px] font-bold text-gray-400 uppercase tracking-wide">
                                Label Tag (e.g. Home, Office, Work)
                              </label>
                              <input
                                type="text"
                                name="name"
                                required
                                value={editForm.name}
                                onChange={handleEditChange}
                                className="w-full px-3.5 py-2.5 bg-white border border-gray-100 rounded-xl text-sm placeholder-gray-400 focus:outline-none focus:border-[#f97316] focus:ring-2 focus:ring-orange-50 font-bold text-gray-800 transition-all"
                              />
                            </div>
                            <div className="space-y-1">
                              <label className="text-[10px] font-bold text-gray-400 uppercase tracking-wide">
                                10-Digit Mobile Phone
                              </label>
                              <input
                                type="tel"
                                name="phone"
                                required
                                maxLength="10"
                                value={editForm.phone}
                                onChange={handleEditChange}
                                className="w-full px-3.5 py-2.5 bg-white border border-gray-100 rounded-xl text-sm placeholder-gray-400 focus:outline-none focus:border-[#f97316] focus:ring-2 focus:ring-orange-50 font-bold text-gray-800 transition-all"
                              />
                            </div>
                          </div>

                          <div className="space-y-1">
                            <label className="text-[10px] font-bold text-gray-400 uppercase tracking-wide">
                              Street details / Flat / Address line
                            </label>
                            <input
                              type="text"
                              name="address_line"
                              required
                              value={editForm.address_line}
                              onChange={handleEditChange}
                              className="w-full px-3.5 py-2.5 bg-white border border-gray-100 rounded-xl text-sm placeholder-gray-400 focus:outline-none focus:border-[#f97316] focus:ring-2 focus:ring-orange-50 font-bold text-gray-800 transition-all"
                            />
                          </div>

                          <div className="grid grid-cols-3 gap-3">
                            <div className="space-y-1">
                              <label className="text-[10px] font-bold text-gray-400 uppercase tracking-wide">
                                City
                              </label>
                              <input
                                type="text"
                                name="city"
                                required
                                value={editForm.city}
                                onChange={handleEditChange}
                                className="w-full px-3 py-2.5 bg-white border border-gray-100 rounded-xl text-xs placeholder-gray-400 focus:outline-none focus:border-[#f97316] focus:ring-2 focus:ring-orange-50 font-bold text-gray-800 transition-all"
                              />
                            </div>
                            <div className="space-y-1">
                              <label className="text-[10px] font-bold text-gray-400 uppercase tracking-wide">
                                State
                              </label>
                              <input
                                type="text"
                                name="state"
                                required
                                value={editForm.state}
                                onChange={handleEditChange}
                                className="w-full px-3 py-2.5 bg-white border border-gray-100 rounded-xl text-xs placeholder-gray-400 focus:outline-none focus:border-[#f97316] focus:ring-2 focus:ring-orange-50 font-bold text-gray-800 transition-all"
                              />
                            </div>
                            <div className="space-y-1">
                              <label className="text-[10px] font-bold text-gray-400 uppercase tracking-wide">
                                Pincode
                              </label>
                              <input
                                type="text"
                                name="pincode"
                                required
                                maxLength="6"
                                value={editForm.pincode}
                                onChange={handleEditChange}
                                className="w-full px-3 py-2.5 bg-white border border-gray-100 rounded-xl text-xs placeholder-gray-400 focus:outline-none focus:border-[#f97316] focus:ring-2 focus:ring-orange-50 font-bold text-gray-800 transition-all"
                              />
                            </div>
                          </div>

                          <div className="flex items-center gap-2 pt-1">
                            <input
                              type="checkbox"
                              id={`edit-inline-is-default-${addr.id}`}
                              name="is_default"
                              checked={editForm.is_default}
                              disabled={isDefault}
                              onChange={handleEditChange}
                              className="w-4 h-4 text-[#f97316] border-gray-200 rounded focus:ring-[#f97316] cursor-pointer accent-[#f97316] disabled:opacity-50"
                            />
                            <label 
                              htmlFor={`edit-inline-is-default-${addr.id}`} 
                              className="text-xs font-bold text-gray-600 cursor-pointer select-none"
                            >
                              Set as default delivery spot
                            </label>
                          </div>

                          {/* Actions */}
                          <div className="flex items-center gap-3 pt-2">
                            <button
                              type="button"
                              disabled={editLoading}
                              onClick={handleCloseEdit}
                              className="px-4 py-2 bg-gray-100 hover:bg-gray-200 text-gray-600 rounded-xl text-xs font-bold transition-all cursor-pointer disabled:opacity-50"
                            >
                              Cancel
                            </button>
                            <button
                              type="submit"
                              disabled={editLoading}
                              className="px-5 py-2 bg-[#f97316] hover:bg-[#e65c00] text-white rounded-xl text-xs font-bold transition-all shadow-xs flex items-center gap-1.5 cursor-pointer disabled:opacity-50"
                            >
                              {editLoading ? (
                                <>
                                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                                  Saving...
                                </>
                              ) : (
                                'Save Details'
                              )}
                            </button>
                          </div>
                        </form>
                      </div>
                    );
                  }

                  // 5B. ROW IN STANDARD TEXT DISPLAY MODE
                  return (
                    <div 
                      key={addr.id} 
                      className={`py-6 flex flex-col md:flex-row md:items-start justify-between gap-4 transition-all group ${
                        isDefault ? 'bg-gradient-to-r from-orange-50/20 to-transparent' : ''
                      }`}
                    >
                      {/* Left: Tag Badge & Full Address Info */}
                      <div className="space-y-2 flex-1">
                        <div className="flex items-center gap-2">
                          <span className={`inline-flex items-center gap-1 px-2.5 py-0.5 rounded-lg text-xs font-extrabold uppercase tracking-wide ${
                            isDefault 
                              ? 'bg-orange-50 text-[#f97316] border border-orange-100' 
                              : 'bg-gray-50 text-gray-500 border border-gray-100'
                          }`}>
                            {getTagIcon(addr.name)}
                            {addr.name}
                          </span>

                          {isDefault && (
                            <span className="px-2 py-0.5 bg-orange-100 text-[#f97316] text-[10px] font-black rounded-md uppercase tracking-wider border border-orange-200/50 select-none">
                              Default
                            </span>
                          )}
                        </div>

                        {/* Address Details block */}
                        <div className="space-y-1">
                          <p className="text-sm font-semibold text-gray-800 break-words leading-relaxed">
                            {addr.address_line}
                          </p>
                          <p className="text-xs text-gray-400 font-bold">
                            {addr.city}, {addr.state} — {addr.pincode}
                          </p>
                        </div>

                        {/* Contact details */}
                        {addr.phone && (
                          <div className="flex items-center gap-1.5 text-xs text-gray-500 font-bold pt-0.5">
                            <Phone className="w-3.5 h-3.5 text-gray-400" />
                            <span>{addr.phone}</span>
                          </div>
                        )}
                      </div>

                      {/* Right: Inline Actions */}
                      <div className="flex items-center gap-2 sm:gap-4 shrink-0 self-start md:pt-1">
                        {!isDefault ? (
                          <button
                            disabled={defaultLoadingId !== null}
                            onClick={(e) => {
                              e.preventDefault();
                              e.stopPropagation();
                              handleSetDefault(addr.id);
                            }}
                            className="text-xs font-extrabold text-[#f97316] hover:text-[#e65c00] transition-colors cursor-pointer select-none disabled:opacity-50 px-3 py-1.5 hover:bg-orange-50 rounded-lg border border-transparent hover:border-orange-100/50"
                          >
                            {defaultLoadingId === addr.id ? 'Setting...' : 'Set as Default'}
                          </button>
                        ) : (
                          <span className="text-[11px] font-extrabold text-green-600 flex items-center gap-1 select-none px-3 py-1.5 bg-green-50/50 rounded-lg border border-green-100">
                            <CheckCircle className="w-3.5 h-3.5" />
                            Active Spot
                          </span>
                        )}

                        {/* Action Dividers */}
                        <div className="h-3 w-px bg-gray-200"></div>

                        {/* Edit Action */}
                        <button
                          onClick={(e) => {
                            e.preventDefault();
                            e.stopPropagation();
                            handleOpenEdit(addr);
                          }}
                          className="flex items-center gap-1 text-xs font-extrabold text-gray-400 hover:text-[#f97316] transition-colors cursor-pointer select-none px-2 py-1.5 hover:bg-gray-50 rounded-lg"
                        >
                          <Edit2 className="w-3.5 h-3.5" />
                          Edit
                        </button>

                        <div className="h-3 w-px bg-gray-200"></div>

                        {/* Delete Action */}
                        <button
                          onClick={(e) => {
                            e.preventDefault();
                            e.stopPropagation();
                            handleDelete(addr.id);
                          }}
                          className="flex items-center gap-1 text-xs font-extrabold text-gray-400 hover:text-red-500 transition-colors cursor-pointer select-none px-2 py-1.5 hover:bg-red-50/50 rounded-lg"
                        >
                          <Trash2 className="w-3.5 h-3.5 animate-pulse" />
                          Delete
                        </button>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}

          </div>
        </div>

      </div>
    </div>
  );
}
