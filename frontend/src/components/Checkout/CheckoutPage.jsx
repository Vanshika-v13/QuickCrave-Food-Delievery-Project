import React, { useState, useEffect } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { ShoppingBag, MapPin, CreditCard, ChevronRight, IndianRupee, Trash2, Plus, Minus, Loader2, ArrowLeft, PlusCircle, CheckCircle2, Home } from 'lucide-react';
import { useCart } from '../../hooks/useCart';
import { useAuth } from '../../hooks/useAuth';
import { toast } from 'react-hot-toast';
import apiClient from '../../services/apiClient';

const getFoodImage = (name) => {
  const mapping = {
    "Pav Bhaji": "pavbhaji.jpg",
    "Chole Bhature": "chholeBhature.avif",
    "Pizza": "pizza.webp",
    "Mango Lassi": "mangoLassi.jpg",
    "Masala Dosa": "MasalaDosa.jpg",
    "Vegetable Biryani": "biryani.jpg",
    "Vada Pav": "vadaPav.jpg",
    "Rava Dosa": "ravaDosa.webp",
    "Samosa": "samosa.jpg"
  };
  return `/images/${mapping[name] || 'biryani.jpg'}`;
};

const CheckoutPage = () => {
  const { cart, cartTotal, updateQuantity, removeFromCart, clearCart } = useCart();
  const { customerToken, customerUser, loading: authLoading, isCustomer } = useAuth();
  const isAuthenticated = !!customerToken;
  const user = customerUser;
  const navigate = useNavigate();
  
  const [addresses, setAddresses] = useState([]);
  const [selectedAddress, setSelectedAddress] = useState(null);
  const [paymentMethod, setPaymentMethod] = useState('COD');
  const [isPlacingOrder, setIsPlacingOrder] = useState(false);
  const [loadingAddresses, setLoadingAddresses] = useState(true);
  const [isLoaded, setIsLoaded] = useState(false);

  const deliveryFee = 40;
  const grandTotal = cartTotal + deliveryFee;

  useEffect(() => {
    // Small timeout to allow cart state to settle
    const timer = setTimeout(() => {
      setIsLoaded(true);
    }, 500);
    return () => clearTimeout(timer);
  }, []);

  useEffect(() => {
    // Wait for auth to restore session
    if (authLoading) return;

    // Use customerToken (the actual AuthContext export) — isAuthenticated is derived from it
    if (!customerToken || !isCustomer()) {
      toast.error("Please login to proceed with checkout");
      navigate('/login');
      return;
    }
    
    if (isLoaded && cart.length === 0 && !isPlacingOrder) {
      navigate('/menu');
      return;
    }
    
    if (customerToken) {
      fetchAddresses();
    }
  }, [customerToken, authLoading, isCustomer, cart.length, navigate, isLoaded]);

  const fetchAddresses = async () => {
    try {
      const response = await apiClient.get('/api/address');
      
      const addrData = response?.success ? (response.data || []) : (Array.isArray(response) ? response : []);
      setAddresses(addrData);
      
      // Selection logic: prioritize default, then saved selected, then first
      const defaultAddr = addrData.find(a => a.is_default);
      const savedSelected = localStorage.getItem("selectedAddress");
      
      if (defaultAddr) {
        setSelectedAddress(defaultAddr);
      } else if (savedSelected) {
        const parsed = JSON.parse(savedSelected);
        const exists = addrData.find(a => a.id === parsed.id);
        setSelectedAddress(exists || addrData[0]);
      } else if (addrData.length > 0) {
        setSelectedAddress(addrData[0]);
      }
    } catch (error) {
      console.error("Error fetching addresses:", error);
      toast.error("Failed to load addresses");
      setAddresses([]);
    } finally {
      setLoadingAddresses(false);
    }
  };

  const handlePlaceOrder = async () => {
    if (!selectedAddress) {
      toast.error("Please select or add a delivery address");
      return;
    }

    setIsPlacingOrder(true);
    try {
      const payload = {
        address_id: selectedAddress.id,
        payment_method: paymentMethod || 'COD',
        items: cart
      };

      const response = await apiClient.post('/api/order/place', payload);

      toast.success("Order placed successfully!");
      clearCart();
      
      const orderId = response?.success ? response.data?.order_id : response?.order_id;
      navigate('/order-success', { state: { orderId } });
    } catch (error) {
      console.error("Order placement error:", {
        status: error.response?.status || error.status,
        data: error.response?.data || error.data,
        message: error.message,
        networkError: !!error.networkError
      });
      
      let errMsg = "Failed to place order. Please try again.";
      
      if (error.networkError) {
        errMsg = "Connection failed. The server might be down or unreachable. Your cart is preserved.";
      } else if (error.response?.data?.message) {
        errMsg = error.response.data.message;
      } else if (error.message === "Network Error") {
        errMsg = "Connection failed. Please check your internet or try again later.";
      } else if (error.response?.data?.detail) {
        errMsg = error.response.data.detail;
      } else if (error.detail) {
        errMsg = error.detail;
      }
      
      toast.error(errMsg, { duration: 5000 });
    } finally {
      setIsPlacingOrder(false);
    }
  };

  return (
    <div className="min-h-screen bg-gray-50 pt-12 pb-20">
      <div className="max-w-[1200px] mx-auto px-4 mt-4 mb-6">
        {/* Header */}
        <div className="flex items-center gap-4 mb-4">
          <button 
            onClick={() => navigate(-1)}
            className="p-2 bg-white border border-gray-200 rounded-md hover:bg-gray-50 transition-colors shadow-sm"
          >
            <ArrowLeft className="w-5 h-5 text-gray-600" />
          </button>
          <div>
            <h1 className="text-2xl font-semibold text-gray-800">Checkout</h1>
            <p className="text-sm text-gray-500 font-medium">Complete your order details below</p>
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 items-start">
          {/* Main Content (Left) */}
          <div className="md:col-span-2 space-y-6">
            
            {/* Delivery Address Section */}
            <div className="bg-white border border-gray-200 rounded-lg shadow-sm p-5">
              <div className="flex items-center justify-between mb-4">
                <div className="flex items-center gap-2">
                  <MapPin className="w-5 h-5 text-orange-500" />
                  <h2 className="text-lg font-semibold text-gray-800">Delivery Address</h2>
                </div>
                <Link 
                  to="/add-address"
                  className="flex items-center gap-1 text-orange-500 font-medium text-sm hover:text-orange-600"
                >
                  <PlusCircle className="w-4 h-4" />
                  Add New
                </Link>
              </div>

              {loadingAddresses ? (
                <div className="flex items-center gap-3 py-6">
                  <Loader2 className="w-5 h-5 text-orange-500 animate-spin" />
                  <span className="text-sm font-medium text-gray-400">Loading your addresses...</span>
                </div>
              ) : addresses.length > 0 ? (
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  {addresses.map((addr) => (
                    <div 
                      key={addr.id}
                      onClick={() => {
                        setSelectedAddress(addr);
                        localStorage.setItem("selectedAddress", JSON.stringify(addr));
                      }}
                      className={`relative p-4 rounded-md border cursor-pointer transition-all ${
                        selectedAddress?.id === addr.id 
                        ? 'border-orange-500 bg-orange-50' 
                        : 'border-gray-200 bg-white hover:border-gray-300'
                      }`}
                    >
                      {selectedAddress?.id === addr.id && (
                        <div className="absolute top-3 right-3">
                          <CheckCircle2 className="w-4 h-4 text-orange-500" />
                        </div>
                      )}
                      <div className="space-y-1">
                        <div className="flex items-center gap-2">
                          <Home className="w-3.5 h-3.5 text-gray-400" />
                          <p className="font-semibold text-gray-800 text-sm">{addr.name || addr.full_name}</p>
                          {addr.is_default && (
                            <span className="px-1.5 py-0.5 bg-green-100 text-green-700 text-[10px] font-bold rounded uppercase">Default</span>
                          )}
                        </div>
                        <p className="text-sm text-gray-500 leading-relaxed font-medium">
                          {addr.address_line}, {addr.city}, {addr.state} - {addr.pincode}
                        </p>
                        <p className="text-sm font-semibold text-gray-700 pt-1">
                          {addr.phone}
                        </p>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="p-8 text-center bg-gray-50 rounded-md border border-dashed border-gray-300">
                  <MapPin className="w-10 h-10 text-gray-300 mx-auto mb-3" />
                  <p className="text-gray-500 font-medium text-sm mb-4">No saved addresses found</p>
                  <Link 
                    to="/add-address"
                    className="inline-block px-6 py-2 bg-orange-500 text-white rounded-md text-sm font-medium hover:bg-orange-600 transition-colors"
                  >
                    Add Your First Address
                  </Link>
                </div>
              )}
            </div>

            {/* Payment Method Section */}
            <div className="bg-white border border-gray-200 rounded-lg shadow-sm p-5">
              <div className="flex items-center gap-2 mb-4">
                <CreditCard className="w-5 h-5 text-orange-500" />
                <h2 className="text-lg font-semibold text-gray-800">Payment Method</h2>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div 
                  onClick={() => setPaymentMethod('COD')}
                  className={`p-4 rounded-md border cursor-pointer transition-all flex items-center gap-3 ${
                    paymentMethod === 'COD' 
                    ? 'border-orange-500 bg-orange-50' 
                    : 'border-gray-200 bg-white hover:border-gray-300'
                  }`}
                >
                  <div className={`w-4 h-4 rounded-full border flex items-center justify-center ${
                    paymentMethod === 'COD' ? 'border-orange-500' : 'border-gray-300'
                  }`}>
                    {paymentMethod === 'COD' && <div className="w-2 h-2 bg-orange-500 rounded-full" />}
                  </div>
                  <div>
                    <p className="font-semibold text-gray-800 text-sm">Cash on Delivery</p>
                    <p className="text-[10px] text-gray-500 uppercase font-bold tracking-wider">Pay at your doorstep</p>
                  </div>
                </div>

                <div 
                  className={`p-4 rounded-md border opacity-50 flex items-center gap-3 border-gray-100 bg-gray-50 cursor-not-allowed`}
                >
                  <div className="w-4 h-4 rounded-full border border-gray-300" />
                  <div>
                    <p className="font-semibold text-gray-400 text-sm">Online Payment</p>
                    <p className="text-[10px] text-gray-400 uppercase font-bold tracking-wider">UPI/Cards (Coming Soon)</p>
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Sticky Sidebar (Right) */}
          <div className="md:col-span-1 sticky top-24">
            <div className="bg-white border border-gray-200 rounded-lg shadow-sm p-5">
              <div className="flex items-center gap-2 mb-4">
                <ShoppingBag className="w-5 h-5 text-orange-500" />
                <h3 className="text-lg font-semibold text-gray-800">Order Summary</h3>
              </div>
              
              <div className="space-y-4 mb-6 max-h-[300px] overflow-y-auto pr-2 scrollbar-thin scrollbar-thumb-gray-200">
                {cart.map((item) => (
                  <div key={item.id || item.item_id} className="flex gap-3">
                    <div className="w-14 h-14 rounded-md overflow-hidden shrink-0 border border-gray-100">
                      <img 
                        src={getFoodImage(item.name)} 
                        alt={item.name} 
                        className="w-full h-full object-cover"
                      />
                    </div>
                    <div className="flex-1 flex flex-col justify-center">
                      <div className="flex justify-between items-start">
                        <p className="font-semibold text-gray-800 text-sm line-clamp-1">{item.name}</p>
                        <p className="font-semibold text-gray-800 text-sm">₹{Math.round(item.price * item.quantity)}</p>
                      </div>
                      <p className="text-[10px] text-gray-500 font-bold uppercase tracking-wider">Qty: {item.quantity}</p>
                    </div>
                  </div>
                ))}
              </div>

              <div className="space-y-2 pt-4 border-t border-gray-100">
                <div className="flex justify-between items-center text-sm font-semibold text-gray-500 uppercase tracking-wider">
                  <span>Subtotal</span>
                  <span className="text-gray-800">₹{cartTotal}</span>
                </div>
                <div className="flex justify-between items-center text-sm font-semibold text-gray-500 uppercase tracking-wider">
                  <span>Delivery Fee</span>
                  <span className="text-green-600">₹{deliveryFee}</span>
                </div>
                
                <div className="pt-4 mt-2 border-t border-gray-100 flex justify-between items-center">
                  <span className="text-sm font-semibold text-gray-800">Total</span>
                  <span className="text-xl font-bold text-orange-500">₹{grandTotal}</span>
                </div>
              </div>

              <div className="mt-6">
                <button 
                  onClick={handlePlaceOrder}
                  disabled={isPlacingOrder || !selectedAddress}
                  className="w-full py-2 bg-orange-500 text-white rounded-md text-sm font-medium hover:bg-orange-600 transition-colors flex items-center justify-center gap-2 shadow-sm disabled:opacity-50 disabled:bg-gray-300"
                >
                  {isPlacingOrder ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    <>
                      Place Order
                      <ChevronRight className="w-4 h-4" />
                    </>
                  )}
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default CheckoutPage;
