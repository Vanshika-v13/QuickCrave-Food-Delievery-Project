import React, { useState, useEffect } from 'react';
import { IndianRupee, ShoppingBag, AlertCircle } from 'lucide-react';
import { useCart } from '../hooks/useCart';
import apiClient from '../services/apiClient';

const MenuPage = ({ previewOnly = false }) => {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const { addToCart } = useCart();

  useEffect(() => {
    const fetchItems = async () => {
      try {
        setLoading(true);
        const response = await apiClient.get('/api/menu');
        
        // Handle standardized response { success, message, data }
        // apiClient interceptor already returns response.data
        const menuItems = response?.success ? (response.data || []) : [];
        
        if (previewOnly) {
          setItems(Array.isArray(menuItems) ? menuItems.slice(0, 3) : []);
        } else {
          setItems(Array.isArray(menuItems) ? menuItems : []);
        }
      } catch (error) {
        console.error("Error fetching menu items:", error);
        setError("Failed to load menu. Please try again later.");
        setItems([]);
      } finally {
        setLoading(false);
      }
    };
    fetchItems();
  }, [previewOnly]);

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

  return (
    <div className="flex flex-col w-full">
      {/* Hero Section - Fluid Height */}
      {!previewOnly && (
        <section className="relative w-full h-[320px] sm:h-[400px] md:h-[450px] flex items-center overflow-hidden">
          {/* Background with Blur and Rich Contrast */}
          <div 
            className="absolute inset-0 bg-cover bg-center bg-no-repeat"
            style={{ 
              backgroundImage: "url('/images/menuHeroSection.png')",
              filter: "blur(3px) contrast(1.1)", // Added contrast for appetizing look
              opacity: "1" // Removed fading to keep image rich
            }}
          />
          {/* Darker Overlay for Depth and Readability */}
          <div className="absolute inset-0 bg-black/30" /> 
          <div className="absolute inset-0 bg-[#ff6b00]/10" /> {/* Subtle orange tint */}
          
          {/* Hero Content - Left Aligned and Vertically Centered */}
          <div className="relative z-10 max-w-[1200px] mx-auto px-6 sm:px-10 w-full">
            <div className="max-w-xl text-left">
              <h1 className="text-3xl sm:text-4xl md:text-5xl font-bold text-white mb-1 drop-shadow-md">
                Are you hungry?
              </h1>
              <h2 className="text-2xl sm:text-3xl md:text-4xl font-bold text-[#ff6b00] mb-3 drop-shadow-sm">
                Don’t wait!!!
              </h2>
              <p className="text-sm sm:text-base md:text-lg text-gray-100 mb-6 font-semibold drop-shadow-sm">
                Let start to order food now!
              </p>
              <button 
                onClick={() => document.getElementById('food-menu').scrollIntoView({ behavior: 'smooth' })}
                className="bg-[#ff6b00] hover:bg-[#e65c00] text-white px-8 py-3.5 sm:px-10 sm:py-4 rounded-full font-bold transition-colors duration-0 text-sm sm:text-base"
                style={{ transition: 'background-color 0.2s ease' }}
              >
                Explore Menu
              </button>
            </div>
          </div>
        </section>
      )}

      {/* Food Menu Section */}
      <section id="food-menu" className="py-20 bg-transparent">
        <div className="max-w-[1200px] mx-auto px-4">
          <div className="text-center mb-16">
            <h2 className="text-4xl font-bold text-[#1f2937] mb-4">Explore Our Dishes</h2>
            <p className="text-[#6b7280] text-lg">Freshly prepared & delivered fast to your doorstep</p>
          </div>

          {loading ? (
            <div className="flex flex-col justify-center items-center py-20 gap-4">
              <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-[#ff6b00]"></div>
              <p className="text-gray-400 font-medium animate-pulse">Loading delicious dishes...</p>
            </div>
          ) : error ? (
            <div className="flex flex-col items-center justify-center py-20 bg-red-50 rounded-3xl border border-red-100">
              <AlertCircle className="w-12 h-12 text-red-400 mb-4" />
              <p className="text-red-800 font-bold text-xl mb-2">Oops! Something went wrong</p>
              <p className="text-red-600 mb-6">{error}</p>
              <button 
                onClick={() => window.location.reload()}
                className="px-6 py-2 bg-red-600 text-white rounded-full font-bold hover:bg-red-700 transition-colors"
              >
                Try Again
              </button>
            </div>
          ) : (Array.isArray(items) && items.length > 0) ? (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-8">
              {items.map((item) => (
                <div key={item.id} className="bg-white rounded-2xl overflow-hidden shadow-sm flex flex-col h-full border border-orange-50 hover:shadow-xl hover:shadow-orange-100/50 transition-all duration-500 group">
                  <div className="h-56 overflow-hidden relative">
                    <img 
                      src={getFoodImage(item.name)} 
                      alt={item.name} 
                      className="w-full h-full object-cover group-hover:scale-110 transition-transform duration-700"
                      onError={(e) => { e.target.src = '/images/biryani.jpg' }}
                    />
                  </div>
                  <div className="p-6 flex flex-col flex-1">
                    <h3 className="text-xl font-bold text-[#1f2937] mb-2 group-hover:text-orange-600 transition-colors">{item.name}</h3>
                    <p className="text-[#6b7280] text-sm mb-6 flex-1 line-clamp-2">
                      {item.description || "Authentic flavors delivered straight to your doorstep."}
                    </p>
                    <div className="flex items-center justify-between mt-auto pt-4 border-t border-gray-50">
                      <div className="flex items-center text-[#ff6b00] font-bold text-xl">
                        <IndianRupee className="w-5 h-5 mr-1" />
                        {Math.round(item.price)}
                      </div>
                      <button 
                        onClick={() => addToCart(item)}
                        className="bg-[#ff6b00] hover:bg-[#e65c00] text-white px-5 py-2 rounded-full font-semibold text-sm transition-colors duration-300 flex items-center gap-2 shadow-lg shadow-orange-100"
                      >
                        <ShoppingBag className="w-4 h-4" />
                        Add to Cart
                      </button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="text-center py-20 bg-gray-50 rounded-3xl border border-dashed border-gray-200">
              <p className="text-gray-400 font-bold text-xl">No dishes available right now</p>
              <p className="text-gray-400 mt-2">Check back soon for more delicious options!</p>
            </div>
          )}
        </div>
      </section>
    </div>
  );
};

export default MenuPage;
