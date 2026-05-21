import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { X, ShoppingBag, Trash2, Plus, Minus, ArrowRight, Loader2, MapPin, IndianRupee } from 'lucide-react';
import { useCart } from '../hooks/useCart';
import { useAuth } from '../hooks/useAuth';
import axios from 'axios';
import { toast } from 'react-hot-toast';

// Image is resolved from the backend cart API which JOINs food_items.
// We must NEVER map images by name — food_items is the sole source of truth.
const normalizeFoodImage = (imageUrl) => {
  if (!imageUrl) return '/images/samosa.jpg';
  // Strip any backend host prefix just in case
  const path = imageUrl.replace(/^https?:\/\/[^/]+/, '').replace(/^\/+/, '');
  if (path.startsWith('images/')) return `/${path}`;
  return `/images/${path}`;
};

const CartDrawer = ({ isOpen, onClose }) => {
  const { cart = [], removeFromCart = () => {}, updateQuantity = () => {}, cartTotal = 0, clearCart = () => {} } = useCart() || {};
  const { user = null, isAuthenticated = false, loading: authLoading = false, isCustomer = () => false } = useAuth() || {};
  const navigate = useNavigate();
  const [isCheckoutLoading, setIsCheckoutLoading] = useState(false);

  // Lock body scroll when drawer is open
  useEffect(() => {
    if (isOpen) {
      document.body.style.overflow = 'hidden';
    } else {
      document.body.style.overflow = 'unset';
    }
    return () => {
      document.body.style.overflow = 'unset';
    };
  }, [isOpen]);

  if (!isOpen) return null;

  const handleCheckout = () => {
    if (cart.length === 0) return;
    
    // Wait for auth to restore
    if (authLoading) return;

    if (!isAuthenticated || !isCustomer()) {
      toast.error("Please login to checkout");
      navigate('/login');
      onClose();
      return;
    }

    navigate('/checkout');
    onClose();
  };

  const handleAddressSelect = (address) => {
    setSelectedAddress(address);
  };

  return (
    <div className="fixed inset-0 z-[60] flex justify-end">
      {/* Backdrop */}
      <div 
        onClick={onClose}
        className="absolute inset-0 bg-black/40"
      />
      
      {/* Drawer Content - Responsive width, No animation */}
      <div className="relative h-full w-full sm:max-w-md bg-white shadow-2xl flex flex-col z-[70]">
        <div className="p-4 sm:p-6 border-b flex items-center justify-between">
          <div className="flex items-center gap-3">
            <ShoppingBag className="text-[#ff6b00]" />
            <h2 className="text-xl font-bold">Your Cart</h2>
          </div>
          <button 
            onClick={onClose} 
            className="p-2 hover:bg-gray-100 rounded-full transition-colors duration-200"
          >
            <X className="w-6 h-6" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-4 sm:px-6 py-4">
          {cart.length === 0 ? (
              <div className="h-full flex flex-col items-center justify-center text-center space-y-6">
                <div className="w-20 h-20 bg-orange-50 rounded-full flex items-center justify-center">
                  <ShoppingBag className="w-10 h-10 text-[#ff6b00]" />
                </div>
                <div>
                  <p className="text-lg font-bold text-gray-900">Your cart is empty</p>
                </div>
                <button 
                  onClick={onClose}
                  className="px-8 py-3 bg-[#ff6b00] text-white rounded-full font-bold hover:bg-[#e65c00] transition-colors"
                >
                  Browse Menu
                </button>
              </div>
            ) : (
              <div className="space-y-4">
                {cart.map((item) => (
                  <div key={item.id || item.item_id} className="flex gap-3 sm:gap-4 p-3 sm:p-4 bg-white rounded-xl border border-gray-100 shadow-sm">
                    <div className="w-16 h-16 sm:w-20 sm:h-20 rounded-lg overflow-hidden flex-shrink-0 border border-gray-100">
                      <img 
                        src={normalizeFoodImage(item.image_url)} 
                        alt={item.name} 
                        className="w-full h-full object-cover"
                        onError={(e) => { e.target.src = '/images/samosa.jpg' }}
                      />
                    </div>
                    
                    <div className="flex-1 flex flex-col justify-between">
                      <div className="flex justify-between items-start">
                        <div>
                          <h4 className="font-bold text-sm sm:text-base text-gray-900 leading-tight">{item.name}</h4>
                          <div className="flex items-center text-[#ff6b00] font-bold text-xs sm:text-sm mt-1">
                            <IndianRupee className="w-3 h-3" />
                            <span>{item.price}</span>
                          </div>
                        </div>
                        <button 
                          onClick={() => removeFromCart(item.id || item.item_id)}
                          className="p-1.5 text-gray-400 hover:text-red-500 transition-colors"
                        >
                          <Trash2 className="w-4 h-4" />
                        </button>
                      </div>
                      
                      <div className="flex items-center justify-between mt-2">
                        <div className="flex items-center gap-2 sm:gap-3 bg-gray-50 rounded-lg p-0.5 sm:p-1 border border-gray-100">
                          <button 
                            onClick={() => updateQuantity(item.id || item.item_id, item.quantity - 1)}
                            className="w-6 h-6 sm:w-7 sm:h-7 rounded bg-white flex items-center justify-center hover:bg-[#ff6b00] hover:text-white transition-colors"
                          >
                            <Minus className="w-2.5 h-2.5 sm:w-3 sm:h-3" />
                          </button>
                          <span className="font-bold text-gray-900 w-4 text-center text-xs sm:text-sm">{item.quantity}</span>
                          <button 
                            onClick={() => updateQuantity(item.id || item.item_id, item.quantity + 1)}
                            className="w-6 h-6 sm:w-7 sm:h-7 rounded bg-white flex items-center justify-center hover:bg-[#ff6b00] hover:text-white transition-colors"
                          >
                            <Plus className="w-2.5 h-2.5 sm:w-3 sm:h-3" />
                          </button>
                        </div>
                        <div className="text-gray-900 text-sm sm:text-base font-bold">
                          ₹{Math.round(item.price * item.quantity)}
                        </div>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
        </div>

        {cart.length > 0 && (
          <div className="p-4 sm:p-6 border-t bg-white space-y-4 shadow-[0_-4px_20px_rgba(0,0,0,0.05)]">
            <div className="space-y-2">
              <div className="flex justify-between items-center">
                <span className="text-base sm:text-lg font-bold text-gray-900">Total Amount</span>
                <div className="flex items-center text-[#ff6b00] text-lg sm:text-xl font-black">
                   <IndianRupee className="w-4 h-4 sm:w-5 sm:h-5" />
                   <span>{cartTotal}</span>
                </div>
              </div>
            </div>

            <button
              disabled={isCheckoutLoading}
              onClick={handleCheckout}
              className="w-full bg-gray-900 hover:bg-[#ff6b00] text-white py-3 sm:py-4 rounded-full text-sm sm:text-base font-bold flex items-center justify-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {isCheckoutLoading ? (
                <Loader2 className="w-5 h-5 animate-spin" />
              ) : (
                <>
                  Proceed to Checkout
                  <ArrowRight className="w-4 h-4" />
                </>
              )}
            </button>
          </div>
        )}
      </div>
    </div>
  );
};

export default CartDrawer;
