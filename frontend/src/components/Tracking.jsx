import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Search, Package, MapPin, Loader2, ArrowRight, ShoppingBag } from 'lucide-react';

const Tracking = () => {
  const [orderId, setOrderId] = useState('');
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  const handleTrack = (e) => {
    e.preventDefault();
    if (!orderId.trim()) return;

    setLoading(true);
    // Simulate a brief check then redirect to the detailed tracking page
    setTimeout(() => {
      navigate(`/track/${orderId.trim()}`);
      setLoading(false);
    }, 600);
  };

  return (
    <div className="min-h-[70vh] flex flex-col items-center justify-center bg-transparent px-4">
      <div className="max-w-2xl w-full bg-white rounded-[2.5rem] shadow-xl shadow-gray-200/50 border border-gray-100 p-8 md:p-12 text-center">
        <div className="w-20 h-20 bg-orange-50 rounded-3xl flex items-center justify-center mx-auto mb-8 transform -rotate-3 group hover:rotate-0 transition-transform duration-300">
          <Package className="w-10 h-10 text-[#ff6b00]" />
        </div>
        
        <h2 className="text-3xl md:text-4xl font-black text-gray-900 tracking-tight mb-4">
          Where's your <span className="text-[#ff6b00]">Food?</span>
        </h2>
        <p className="text-gray-500 font-medium mb-10 max-w-md mx-auto">
          Enter your Order ID below to see the real-time movement of our delivery partner.
        </p>

        <form onSubmit={handleTrack} className="space-y-4">
          <div className="relative group">
            <div className="absolute inset-y-0 left-0 pl-6 flex items-center pointer-events-none">
              <Search className="h-6 w-6 text-gray-300 group-focus-within:text-[#ff6b00] transition-colors" />
            </div>
            <input
              type="text"
              placeholder="Enter Order ID (e.g. 101)"
              value={orderId}
              onChange={(e) => setOrderId(e.target.value)}
              className="block w-full pl-16 pr-6 py-5 bg-gray-50 border-2 border-transparent rounded-2xl text-lg font-bold placeholder-gray-300 focus:outline-none focus:bg-white focus:border-orange-200 focus:ring-4 focus:ring-orange-50 transition-all"
            />
          </div>
          
          <button
            type="submit"
            disabled={loading || !orderId.trim()}
            className="w-full py-5 bg-gray-900 text-white rounded-2xl text-lg font-black hover:bg-[#ff6b00] transition-all flex items-center justify-center gap-3 shadow-lg disabled:opacity-50 disabled:hover:bg-gray-900 group"
          >
            {loading ? (
              <Loader2 className="w-6 h-6 animate-spin" />
            ) : (
              <>
                Track My Order
                <ArrowRight className="w-6 h-6 group-hover:translate-x-1 transition-transform" />
              </>
            )}
          </button>
        </form>

        <div className="mt-12 pt-8 border-t border-gray-50 flex items-center justify-center gap-8">
          <div className="flex flex-col items-center gap-2">
            <div className="w-10 h-10 rounded-full bg-blue-50 flex items-center justify-center text-blue-600">
               <ShoppingBag className="w-5 h-5" />
            </div>
            <span className="text-[10px] font-black text-gray-400 uppercase tracking-widest">Fresh Prep</span>
          </div>
          <div className="flex flex-col items-center gap-2">
            <div className="w-10 h-10 rounded-full bg-green-50 flex items-center justify-center text-green-600">
               <MapPin className="w-5 h-5" />
            </div>
            <span className="text-[10px] font-black text-gray-400 uppercase tracking-widest">Live Map</span>
          </div>
        </div>
      </div>
    </div>
  );
};

export default Tracking;
