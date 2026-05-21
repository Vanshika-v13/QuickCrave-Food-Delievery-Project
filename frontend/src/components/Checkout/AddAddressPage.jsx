import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { MapPin, Phone, User, Home, Building, Hash, ArrowLeft, Loader2, Globe, Trash2 } from 'lucide-react';
import apiClient from '../../services/apiClient';
import { useAuth } from '../../hooks/useAuth';
import { toast } from 'react-hot-toast';

const NOM_HEADERS = {
  Accept: 'application/json',
  'Accept-Language': 'en',
  'User-Agent': 'FoodChatbotAddress/1.0 (delivery-address-geocode)',
};

function normalizePinDigits(pincode) {
  return String(pincode || '').replace(/\D/g, '');
}

function nominatimResultInIndia(r) {
  const cc = r.address?.country_code?.toLowerCase();
  if (cc === 'in') return true;
  const lat = parseFloat(r.lat);
  const lon = parseFloat(r.lon);
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) return false;
  return lat >= 6 && lat <= 37 && lon >= 68 && lon <= 98;
}

function pincodeMatchesResult(r, pincode) {
  const want = normalizePinDigits(pincode);
  if (!want) return false;
  const postcode = normalizePinDigits(r.address?.postcode || '');
  if (postcode && (postcode === want || postcode.endsWith(want) || want.endsWith(postcode))) {
    return true;
  }
  const name = String(r.display_name || '');
  const digitsInName = name.replace(/\D/g, '');
  return digitsInName.includes(want);
}

/** Prefer matching PIN, India bbox/country_code, then Nominatim importance (higher first). */
function pickBestGeocodeCandidate(results, pincode) {
  if (!Array.isArray(results) || results.length === 0) return null;
  const sorted = [...results].sort((a, b) => {
    const pcA = pincodeMatchesResult(a, pincode) ? 1 : 0;
    const pcB = pincodeMatchesResult(b, pincode) ? 1 : 0;
    if (pcB !== pcA) return pcB - pcA;
    const inA = nominatimResultInIndia(a) ? 1 : 0;
    const inB = nominatimResultInIndia(b) ? 1 : 0;
    if (inB !== inA) return inB - inA;
    const impA = parseFloat(a.importance);
    const impB = parseFloat(b.importance);
    const ia = Number.isFinite(impA) ? impA : 0;
    const ib = Number.isFinite(impB) ? impB : 0;
    return ib - ia;
  });
  return sorted[0];
}

function coordsFromNominatimResult(r) {
  if (!r) return null;
  const lat = parseFloat(r.lat);
  const lon = parseFloat(r.lon);
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) return null;
  if (lat < -90 || lat > 90 || lon < -180 || lon > 180) return null;
  return { latitude: lat, longitude: lon };
}

async function nominatimSearch(q) {
  const url = `https://nominatim.openstreetmap.org/search?format=json&addressdetails=1&q=${encodeURIComponent(q)}&limit=15`;
  const res = await fetch(url, { headers: NOM_HEADERS });
  if (!res.ok) return [];
  const data = await res.json();
  return Array.isArray(data) ? data : [];
}

/**
 * Forward-geocode saved address text so orders.user_lat/user_lng match the address when possible.
 * Tries progressively broader queries; returns null coordinates if nothing resolves.
 */
async function geocodeAddressForSave({ address_line, city, state, pincode }) {
  const line = String(address_line || '').trim();
  const c = String(city || '').trim();
  const s = String(state || '').trim();
  const pc = String(pincode || '').trim();

  const queries = [
    [line, c, s, pc, 'India'].filter(Boolean).join(', '),
    [line, c, pc, 'India'].filter(Boolean).join(', '),
    [c, pc, 'India'].filter(Boolean).join(', '),
    pc ? `${pc}, India` : '',
  ].map((qq) => qq.trim()).filter((qq) => qq.length > 0);

  const seen = new Set();
  for (const q of queries) {
    if (seen.has(q)) continue;
    seen.add(q);

    let rows;
    try {
      rows = await nominatimSearch(q);
    } catch {
      rows = [];
    }
    const best = pickBestGeocodeCandidate(rows, pc);
    const coords = coordsFromNominatimResult(best);
    if (coords) return coords;
  }
  return null;
}

const AddAddressPage = () => {
  const { user, isAuthenticated } = useAuth();
  const navigate = useNavigate();
  const [loading, setLoading] = useState(false);
  const [addresses, setAddresses] = useState([]);
  const [selectedAddress, setSelectedAddress] = useState(null);

  useEffect(() => {
    if (isAuthenticated) {
      fetchAddresses();
    }
  }, [isAuthenticated]);

  const fetchAddresses = async () => {
    try {
      const response = await apiClient.get('/api/address');
      const addrData = response?.success ? (response.data || []) : (Array.isArray(response) ? response : []);
      setAddresses(addrData);
      
      const savedSelected = localStorage.getItem("selectedAddress");
      if (savedSelected) {
        setSelectedAddress(JSON.parse(savedSelected));
      }
    } catch (error) {
      console.error("Error fetching addresses:", error);
      toast.error("Failed to load addresses");
    }
  };

  const [formData, setFormData] = useState({
    fullName: user?.name || '',
    phone: '',
    addressLine: '',
    city: '',
    state: '',
    pincode: '',
    isDefault: false
  });

  const handleInputChange = (e) => {
    const { name, value, type, checked } = e.target;
    setFormData(prev => ({ 
      ...prev, 
      [name]: type === 'checkbox' ? checked : value 
    }));
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    
    // Validation & Trimming
    const trimmedData = {
      full_name: formData.fullName.trim(),
      phone: formData.phone.trim(),
      address_line: formData.addressLine.trim(),
      city: formData.city.trim(),
      state: formData.state.trim(),
      pincode: formData.pincode.trim(),
      is_default: formData.isDefault
    };

    if (Object.values(trimmedData).some(val => val === '' && typeof val !== 'boolean')) {
      toast.error("Please fill in all required fields");
      return;
    }

    setLoading(true);
    try {
      const coords = await geocodeAddressForSave({
        address_line: trimmedData.address_line,
        city: trimmedData.city,
        state: trimmedData.state,
        pincode: trimmedData.pincode,
      });

      const response = await apiClient.post('/api/address/add', {
        ...trimmedData,
        latitude: coords?.latitude ?? null,
        longitude: coords?.longitude ?? null,
      });

      const addressId = response?.address_id ?? response?.data?.address_id;
      const newAddress = {
        id: addressId,
        ...trimmedData,
        latitude: coords?.latitude ?? null,
        longitude: coords?.longitude ?? null,
        is_default: trimmedData.is_default || addresses.length === 0
      };

      setAddresses(prev => [...prev, newAddress]);
      setSelectedAddress(newAddress);
      localStorage.setItem("selectedAddress", JSON.stringify(newAddress));

      if (coords) {
        toast.success("Address saved successfully!");
      } else {
        toast("Address saved, but map location could not be verified.", {
          duration: 5000,
          icon: "⚠️",
        });
      }
      setFormData({
        fullName: user?.name || '',
        phone: '',
        addressLine: '',
        city: '',
        state: '',
        pincode: '',
        isDefault: false
      });
    } catch (error) {
      console.error("Error adding address:", error);
      toast.error(error.response?.data?.detail || "Failed to save address");
    } finally {
      setLoading(false);
    }
  };

  const handleDelete = async (e, addressId) => {
    e.stopPropagation();
    const originalAddresses = [...addresses];
    
    // Optimistic Update
    setAddresses(prev => prev.filter(a => a.id !== addressId));
    if (selectedAddress?.id === addressId) {
      setSelectedAddress(null);
      localStorage.removeItem("selectedAddress");
    }

    try {
      await apiClient.delete(`/api/address/delete/${addressId}`);
      toast.success("Address deleted");
      fetchAddresses(); // Sync back for auto-reassigned default
    } catch (error) {
      setAddresses(originalAddresses);
      toast.error("Failed to delete address");
    }
  };

  const handleSetDefault = async (e, addressId) => {
    e.stopPropagation();
    const originalAddresses = [...addresses];

    // Optimistic Update
    setAddresses(prev => prev.map(a => ({
      ...a,
      is_default: a.id === addressId
    })));

    try {
      await apiClient.post(`/api/address/set_default/${addressId}`, {});
      toast.success("Default address updated");
    } catch (error) {
      setAddresses(originalAddresses);
      toast.error("Failed to update default address");
    }
  };

  return (
    <div className="min-h-screen bg-gray-50 pt-12 pb-20">
      <div className="max-w-[1100px] mx-auto px-4 mt-4">
        {/* Header */}
        <div className="flex items-center gap-4 mb-6">
          <button 
            onClick={() => navigate(-1)}
            className="p-2 bg-white border border-gray-200 rounded-md hover:bg-gray-50 transition-colors shadow-sm"
          >
            <ArrowLeft className="w-5 h-5 text-gray-600" />
          </button>
          <div>
            <h1 className="text-2xl font-semibold text-gray-800">Delivery Details</h1>
            <p className="text-sm text-gray-500 font-medium">Manage your addresses and delivery info</p>
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-6 items-start">
          {/* Part 4: Address List (Left Side) */}
          <div className="space-y-4">
            <h2 className="text-lg font-semibold text-gray-800 mb-2">Saved Addresses</h2>
            {addresses.length > 0 ? (
              <div className="space-y-3">
                {addresses.map((addr) => (
                  <div 
                    key={addr.id}
                    onClick={() => {
                      setSelectedAddress(addr);
                      localStorage.setItem("selectedAddress", JSON.stringify(addr));
                    }}
                    className={`p-4 border rounded-md cursor-pointer transition-all relative group ${
                      selectedAddress?.id === addr.id 
                      ? 'border-orange-500 bg-orange-50 ring-1 ring-orange-500' 
                      : 'border-gray-200 bg-white hover:border-gray-300'
                    }`}
                  >
                    <div className="flex justify-between items-start">
                      <div className="flex-1">
                        <div className="flex items-center gap-2 mb-1">
                          <p className="font-semibold text-gray-800 text-sm">{addr.name || addr.full_name}</p>
                          {addr.is_default && (
                            <span className="px-1.5 py-0.5 bg-green-100 text-green-700 text-[10px] font-bold rounded uppercase">Default</span>
                          )}
                        </div>
                        <p className="text-xs text-gray-500">
                          {addr.address_line}, {addr.city}, {addr.state} - {addr.pincode}
                        </p>
                        <p className="text-xs font-medium text-gray-700 mt-2">{addr.phone}</p>
                        
                        <div className="mt-3 flex items-center gap-3 opacity-100 lg:opacity-0 lg:group-hover:opacity-100 transition-opacity flex-wrap">
                          {!addr.is_default && (
                            <button 
                              onClick={(e) => handleSetDefault(e, addr.id)}
                              className="text-[11px] font-bold text-orange-500 hover:text-orange-600 uppercase tracking-tight"
                            >
                              Set as Default
                            </button>
                          )}
                          <button 
                            onClick={(e) => handleDelete(e, addr.id)}
                            className="text-[11px] font-bold text-red-500 hover:text-red-600 uppercase tracking-tight flex items-center gap-1"
                          >
                            <Trash2 className="w-3 h-3" />
                            Delete
                          </button>
                        </div>
                      </div>
                      {selectedAddress?.id === addr.id && (
                        <div className="w-4 h-4 rounded-full bg-orange-500 flex items-center justify-center shrink-0">
                          <div className="w-1.5 h-1.5 bg-white rounded-full"></div>
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="p-8 text-center bg-white border border-gray-200 rounded-lg">
                <MapPin className="w-10 h-10 text-gray-300 mx-auto mb-3" />
                <p className="text-gray-500 text-sm">No saved addresses yet</p>
              </div>
            )}
          </div>

          {/* Existing Form (Right Side) */}
          <div className="space-y-4">
            <h2 className="text-lg font-semibold text-gray-800 mb-2">Add New Address</h2>
            <form onSubmit={handleSubmit} className="bg-white border border-gray-200 rounded-lg shadow-sm p-6 space-y-4">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="flex flex-col">
                  <label className="text-sm font-medium text-gray-700 mb-1">Full Name</label>
                  <div className="relative">
                    <User className="absolute left-3 top-2.5 text-gray-400 w-4 h-4" />
                    <input
                      type="text"
                      name="fullName"
                      required
                      value={formData.fullName}
                      onChange={handleInputChange}
                      className="w-full pl-9 pr-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-1 focus:ring-orange-500 focus:border-orange-500 font-medium text-gray-900 transition-all"
                      placeholder="John Doe"
                    />
                  </div>
                </div>
                <div className="flex flex-col">
                  <label className="text-sm font-medium text-gray-700 mb-1">Phone Number</label>
                  <div className="relative">
                    <Phone className="absolute left-3 top-2.5 text-gray-400 w-4 h-4" />
                    <input
                      type="text"
                      name="phone"
                      required
                      value={formData.phone}
                      onChange={handleInputChange}
                      className="w-full pl-9 pr-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-1 focus:ring-orange-500 focus:border-orange-500 font-medium text-gray-900 transition-all"
                      placeholder="9876543210"
                    />
                  </div>
                </div>
              </div>

              <div className="flex flex-col">
                <label className="text-sm font-medium text-gray-700 mb-1">Address Line</label>
                <div className="relative">
                  <Home className="absolute left-3 top-3 text-gray-400 w-4 h-4" />
                  <textarea
                    name="addressLine"
                    required
                    rows="3"
                    value={formData.addressLine}
                    onChange={handleInputChange}
                    className="w-full pl-9 pr-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-1 focus:ring-orange-500 focus:border-orange-500 font-medium text-gray-900 transition-all resize-none"
                    placeholder="House No, Building, Street..."
                  />
                </div>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                <div className="flex flex-col">
                  <label className="text-sm font-medium text-gray-700 mb-1">City</label>
                  <div className="relative">
                    <Building className="absolute left-3 top-2.5 text-gray-400 w-4 h-4" />
                    <input
                      type="text"
                      name="city"
                      required
                      value={formData.city}
                      onChange={handleInputChange}
                      className="w-full pl-9 pr-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-1 focus:ring-orange-500 focus:border-orange-500 font-medium text-gray-900 transition-all"
                      placeholder="Mumbai"
                    />
                  </div>
                </div>
                <div className="flex flex-col">
                  <label className="text-sm font-medium text-gray-700 mb-1">State</label>
                  <div className="relative">
                    <Globe className="absolute left-3 top-2.5 text-gray-400 w-4 h-4" />
                    <input
                      type="text"
                      name="state"
                      required
                      value={formData.state}
                      onChange={handleInputChange}
                      className="w-full pl-9 pr-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-1 focus:ring-orange-500 focus:border-orange-500 font-medium text-gray-900 transition-all"
                      placeholder="Maharashtra"
                    />
                  </div>
                </div>
                <div className="flex flex-col">
                  <label className="text-sm font-medium text-gray-700 mb-1">Pincode</label>
                  <div className="relative">
                    <Hash className="absolute left-3 top-2.5 text-gray-400 w-4 h-4" />
                    <input
                      type="text"
                      name="pincode"
                      required
                      value={formData.pincode}
                      onChange={handleInputChange}
                      className="w-full pl-9 pr-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-1 focus:ring-orange-500 focus:border-orange-500 font-medium text-gray-900 transition-all"
                      placeholder="400001"
                    />
                  </div>
                </div>
              </div>

              <div className="flex items-center gap-2 pt-2">
                <input
                  type="checkbox"
                  id="isDefault"
                  name="isDefault"
                  checked={formData.isDefault}
                  onChange={handleInputChange}
                  className="w-4 h-4 text-orange-500 border-gray-300 rounded focus:ring-orange-500 cursor-pointer"
                />
                <label htmlFor="isDefault" className="text-sm font-medium text-gray-700 cursor-pointer">
                  Set as Default Address
                </label>
              </div>

              <div className="pt-2">
                <button
                  type="submit"
                  disabled={loading}
                  className="w-full py-2.5 bg-orange-500 text-white rounded-md text-sm font-medium hover:bg-orange-600 transition-colors flex items-center justify-center gap-2 shadow-sm disabled:opacity-50"
                >
                  {loading ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    "Save Address"
                  )}
                </button>
              </div>
            </form>
          </div>
        </div>
      </div>
    </div>
  );
};

export default AddAddressPage;
