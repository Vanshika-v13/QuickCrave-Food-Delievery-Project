import React, { useState, useEffect } from 'react';
import { MapPin, Phone, User, Home, Building, Hash, ArrowLeft, CheckCircle2 } from 'lucide-react';
import axios from 'axios';
import { useAuth } from '../../hooks/useAuth';
import { toast } from 'react-hot-toast';

const AddressForm = ({ onSubmit, onCancel }) => {
  const { user } = useAuth();
  const [addresses, setAddresses] = useState([]);
  const [showForm, setShowForm] = useState(false);
  const [formData, setFormData] = useState({
    name: user?.name || '',
    phone: '',
    address: '',
    city: '',
    pincode: ''
  });

  useEffect(() => {
    fetchAddresses();
  }, []);

  const fetchAddresses = async () => {
    try {
      const response = await axios.get('/api/address');
      setAddresses(response.data);
      if (response.data.length === 0) {
        setShowForm(true);
      }
    } catch (error) {
      console.error("Error fetching addresses:", error);
    }
  };

  const handleInputChange = (e) => {
    setFormData({ ...formData, [e.target.name]: e.target.value });
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    try {
      const response = await axios.post('/api/address/add', {
        ...formData,
        full_name: formData.name
      });
      const newAddress = { ...formData, id: response.data.address_id };
      toast.success("Address saved!");
      onSubmit(newAddress);
    } catch (error) {
      toast.error("Failed to save address");
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between mb-8">
        <h3 className="text-2xl font-bold text-gray-900">Delivery Address</h3>
        {addresses.length > 0 && (
          <button 
            onClick={() => setShowForm(!showForm)}
            className="text-primary font-bold text-sm hover:underline"
          >
            {showForm ? "Select Existing" : "Add New Address"}
          </button>
        )}
      </div>

      {!showForm ? (
        <div className="grid gap-4">
          {addresses.map((addr) => (
            <button
              key={addr.id}
              onClick={() => onSubmit(addr)}
              className="flex items-start gap-4 p-6 bg-white border-2 border-gray-100 rounded-3xl hover:border-primary hover:bg-orange-50/30 transition-all text-left group"
            >
              <div className="w-10 h-10 bg-orange-100 rounded-full flex items-center justify-center flex-shrink-0 group-hover:bg-primary group-hover:text-white transition-colors">
                <MapPin className="w-5 h-5" />
              </div>
              <div className="flex-1">
                <p className="font-bold text-gray-900">{addr.name}</p>
                <p className="text-sm text-gray-600 mt-1">{addr.address}</p>
                <p className="text-sm text-gray-600">{addr.city} - {addr.pincode}</p>
                <p className="text-sm font-medium text-gray-900 mt-2">Phone: {addr.phone}</p>
              </div>
              <CheckCircle2 className="w-6 h-6 text-primary opacity-0 group-hover:opacity-100 transition-opacity" />
            </button>
          ))}
        </div>
      ) : (
        <form onSubmit={handleSubmit} className="space-y-4 bg-gray-50 p-8 rounded-3xl border border-gray-200">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="space-y-2">
              <label className="text-sm font-bold text-gray-700 ml-1">Full Name</label>
              <div className="relative">
                <User className="absolute left-3 top-3.5 text-gray-400 w-4 h-4" />
                <input
                  type="text"
                  name="name"
                  required
                  value={formData.name}
                  onChange={handleInputChange}
                  className="w-full pl-10 pr-4 py-3 bg-white border border-gray-200 rounded-2xl focus:ring-2 focus:ring-primary focus:border-transparent outline-none"
                  placeholder="John Doe"
                />
              </div>
            </div>
            <div className="space-y-2">
              <label className="text-sm font-bold text-gray-700 ml-1">Phone Number</label>
              <div className="relative">
                <Phone className="absolute left-3 top-3.5 text-gray-400 w-4 h-4" />
                <input
                  type="text"
                  name="phone"
                  required
                  value={formData.phone}
                  onChange={handleInputChange}
                  className="w-full pl-10 pr-4 py-3 bg-white border border-gray-200 rounded-2xl focus:ring-2 focus:ring-primary focus:border-transparent outline-none"
                  placeholder="9876543210"
                />
              </div>
            </div>
          </div>

          <div className="space-y-2">
            <label className="text-sm font-bold text-gray-700 ml-1">Full Address</label>
            <div className="relative">
              <Home className="absolute left-3 top-3.5 text-gray-400 w-4 h-4" />
              <textarea
                name="address"
                required
                rows="3"
                value={formData.address}
                onChange={handleInputChange}
                className="w-full pl-10 pr-4 py-3 bg-white border border-gray-200 rounded-2xl focus:ring-2 focus:ring-primary focus:border-transparent outline-none resize-none"
                placeholder="House No, Building, Street..."
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <label className="text-sm font-bold text-gray-700 ml-1">City</label>
              <div className="relative">
                <Building className="absolute left-3 top-3.5 text-gray-400 w-4 h-4" />
                <input
                  type="text"
                  name="city"
                  required
                  value={formData.city}
                  onChange={handleInputChange}
                  className="w-full pl-10 pr-4 py-3 bg-white border border-gray-200 rounded-2xl focus:ring-2 focus:ring-primary focus:border-transparent outline-none"
                  placeholder="Mumbai"
                />
              </div>
            </div>
            <div className="space-y-2">
              <label className="text-sm font-bold text-gray-700 ml-1">Pincode</label>
              <div className="relative">
                <Hash className="absolute left-3 top-3.5 text-gray-400 w-4 h-4" />
                <input
                  type="text"
                  name="pincode"
                  required
                  value={formData.pincode}
                  onChange={handleInputChange}
                  className="w-full pl-10 pr-4 py-3 bg-white border border-gray-200 rounded-2xl focus:ring-2 focus:ring-primary focus:border-transparent outline-none"
                  placeholder="400001"
                />
              </div>
            </div>
          </div>

          <div className="flex gap-4 pt-4">
            <button
              type="submit"
              className="flex-1 btn btn-primary"
            >
              Save and Continue
            </button>
            {addresses.length > 0 && (
              <button
                type="button"
                onClick={() => setShowForm(false)}
                className="px-6 py-3 border-2 border-gray-200 text-gray-600 rounded-2xl font-bold hover:bg-gray-100 transition-all"
              >
                Cancel
              </button>
            )}
          </div>
        </form>
      )}
    </div>
  );
};

export default AddressForm;
