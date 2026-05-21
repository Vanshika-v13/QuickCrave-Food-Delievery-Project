import React, { useState, useEffect } from 'react';
import { ShoppingBag, Loader2, IndianRupee, Search, Star, ArrowRight, ChevronLeft, ChevronRight, Heart } from 'lucide-react';
import { useCart } from '../hooks/useCart';
import { useAuth } from '../hooks/useAuth';
import { toast } from 'react-hot-toast';
import { Link } from 'react-router-dom';
import apiClient from '../services/apiClient';
import SkeletonCard from './SkeletonCard';

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

const genZDescriptions = {
  "Pav Bhaji": "Rich, buttery street-style flavor with a homely twist 🔥",
  "Pizza": "Perfect cheese melt with a classic comfort bite 🍕",
  "Mango Lassi": "Cool, creamy refreshment for any time of day 🥭",
  "Chole Bhature": "Piping hot, pillow-soft bhature served with rich, spiced chickpeas. Pure foodie heaven! 🌶️✨",
  "Masala Dosa": "Crispy, golden-perfection crepe stuffed with perfectly spiced potato masala. A true classic! 🥞🔥",
  "Vegetable Biryani": "Layers of fragrant, aromatic basmati rice and perfectly spiced veggies. Scent-sational goodness! 🍚🌿",
  "Vada Pav": "The ultimate Mumbai street food experience. 🍔",
  "Samosa": "Golden crispy triangles filled with spicy potato goodness. 🥟",
  "default": "Authentic flavors delivered straight to your doorstep. 🍴"
};

const FeaturedCard = ({ item, index, items, getFoodImage, genZDescriptions }) => {
  const cardItems = React.useMemo(() => {
    const subset = [];
    for (let i = index; i < items.length; i += 3) {
      subset.push(items[i]);
    }
    return subset;
  }, [items, index]);

  const [localIndex, setLocalIndex] = useState(0);
  const [isDesktop, setIsDesktop] = useState(false);

  useEffect(() => {
    const checkViewport = () => {
      setIsDesktop(window.innerWidth >= 1024);
    };
    checkViewport();
    window.addEventListener('resize', checkViewport);
    return () => window.removeEventListener('resize', checkViewport);
  }, []);

  useEffect(() => {
    if (!isDesktop || cardItems.length <= 1) {
      setLocalIndex(0);
      return;
    }

    const interval = setInterval(() => {
      setLocalIndex((prev) => (prev + 1) % cardItems.length);
    }, 5000); // Auto-rotate every 5 seconds within the card's subset on desktop

    return () => clearInterval(interval);
  }, [isDesktop, cardItems]);

  const activeItem = cardItems[localIndex] || item;

  return (
    <div
      className="bg-white rounded-[2.5rem] overflow-hidden shadow-sm border border-gray-100 flex flex-col w-full sm:w-[65%] md:w-[55%] lg:w-[calc(33.333%-16px)] flex-shrink-0 snap-center lg:snap-start transition-all duration-300 hover:shadow-md"
    >
      {/* Top: Immersive Food Image */}
      <div className="w-full aspect-[16/10] sm:aspect-[16/9] lg:aspect-[16/10] overflow-hidden shadow-inner bg-gray-50">
        <img
          src={getFoodImage(activeItem.name)}
          alt={activeItem.name}
          className="w-full h-full object-cover transition-transform duration-500 hover:scale-105"
          onError={(e) => { e.target.src = '/images/biryani.jpg'; }}
        />
      </div>
      
      {/* Bottom: Only Short Description Text */}
      <div className="p-8 sm:p-10 flex flex-col justify-center items-center flex-grow">
        <p className="text-gray-600 text-base sm:text-lg font-medium leading-relaxed text-center px-4 sm:px-6">
          {genZDescriptions[activeItem.name] || genZDescriptions.default}
        </p>
      </div>
    </div>
  );
};

const Menu = ({ previewOnly = false, searchTerm = '' }) => {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const { addToCart } = useCart();
  const { isAuthenticated, user } = useAuth();

  const handleAddToCart = async (item) => {
    console.log("🛒 ADD CLICKED", item.id || item.item_id);
    await addToCart(item);
  };
  
  // Slider state and ref
  const [currentIndex, setCurrentIndex] = useState(0);
  const sliderRef = React.useRef(null);

  const scrollToSlide = (index) => {
    if (sliderRef.current) {
      const cardWidth = sliderRef.current.children[0]?.clientWidth || 0;
      const gap = 24; // gap-6 is 24px
      sliderRef.current.scrollTo({
        left: index * (cardWidth + gap),
        behavior: 'smooth'
      });
      setCurrentIndex(index);
    }
  };

  const handleScroll = () => {
    if (sliderRef.current) {
      const { scrollLeft, clientWidth } = sliderRef.current;
      const cardWidth = sliderRef.current.children[0]?.clientWidth || clientWidth;
      const gap = 24;
      const index = Math.round(scrollLeft / (cardWidth + gap));
      const slideCount = previewOnly ? 3 : items.length;
      const clampedIndex = Math.max(0, Math.min(slideCount - 1, index));
      setCurrentIndex(clampedIndex);
    }
  };

  const prevSlide = () => {
    const slideCount = previewOnly ? 3 : items.length;
    const nextIndex = (currentIndex - 1 + slideCount) % slideCount;
    scrollToSlide(nextIndex);
  };

  const nextSlide = () => {
    const slideCount = previewOnly ? 3 : items.length;
    const nextIndex = (currentIndex + 1) % slideCount;
    scrollToSlide(nextIndex);
  };

  useEffect(() => {
    const fetchItems = async () => {
      try {
        setError(false);
        const response = await apiClient.get('/api/menu');
        
        // Handle standardized response { success, message, data }
        if (response?.success) {
          const menuItems = response.data || [];
          if (previewOnly) {
            const allItems = Array.isArray(menuItems) ? menuItems : [];
            const firstThreeNames = ["Chole Bhature", "Masala Dosa", "Vegetable Biryani"];
            const firstThree = allItems.filter(item => firstThreeNames.includes(item.name));
            const remaining = allItems.filter(item => !firstThreeNames.includes(item.name));
            const orderedFirstThree = firstThreeNames.map(name => 
              firstThree.find(item => item.name === name)
            ).filter(Boolean);
            setItems([...orderedFirstThree, ...remaining]);
          } else {
            setItems(Array.isArray(menuItems) ? menuItems : []);
          }
        }
      } catch (error) {
        // Ignore silent auth rejections (already handled by interceptor)
        if (error?.silent) return;

        console.error("Error fetching food items:", error);
        setError(true);
        setItems([]);
      } finally {
        setLoading(false);
      }
    };
    fetchItems();
  }, [previewOnly]);

  // All mobile/tablet carousel auto-rotation has been completely disabled per responsive requirements

  const filteredItems = items.filter(item => 
    item.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
    (item.category && item.category.toLowerCase().includes(searchTerm.toLowerCase()))
  );

  if (loading) {
    return (
      <section className="py-20 bg-white">
        <div className="max-w-7xl mx-auto px-4 md:px-10">
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-8">
            {[1, 2, 3, 4, 5, 6, 7, 8].map((i) => <SkeletonCard key={i} />)}
          </div>
        </div>
      </section>
    );
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center py-32 space-y-4 px-4 text-center">
        <div className="bg-red-50 p-6 rounded-full">
          <Loader2 className="w-12 h-12 text-red-400" />
        </div>
        <h3 className="text-xl font-bold text-gray-800">Unable to load items</h3>
        <button onClick={() => window.location.reload()} className="px-6 py-2 bg-[#ff6b00] text-white rounded-xl font-bold">Retry</button>
      </div>
    );
  }

  return (
    <section id="menu" className="pt-12 pb-24 md:pt-16 md:pb-32 bg-transparent overflow-hidden">
      <div className="max-w-7xl mx-auto px-4 md:px-10">
        <div className="mb-12 sm:mb-16 text-center">
          <span className="inline-block bg-orange-50 px-4 py-1.5 rounded-full border border-orange-100 text-xs sm:text-sm font-black text-[#ff6b00] uppercase tracking-[0.2em] mb-3">
            Curated For Your Cravings
          </span>
          <h3 className="text-3xl sm:text-4xl md:text-5xl font-black text-gray-900 tracking-tight mt-3">
            Deliciously <span className="text-[#ff6b00]">Fresh</span>
          </h3>
        </div>

        {previewOnly && items.length > 0 ? (
          <div className="relative max-w-7xl mx-auto px-4 sm:px-6">
            {/* Horizontal Scroll Snap Container */}
            <div 
              ref={sliderRef}
              onScroll={handleScroll}
              className="flex overflow-x-auto scroll-smooth snap-x snap-mandatory scrollbar-hide gap-6 pb-6 w-full select-none"
            >
              {items.slice(0, 3).map((item, index) => (
                <FeaturedCard
                  key={item.id || index}
                  item={item}
                  index={index}
                  items={items}
                  getFoodImage={getFoodImage}
                  genZDescriptions={genZDescriptions}
                />
              ))}
            </div>

            {/* Slider Navigation Dots (Hidden on Large Screens) */}
            <div className="flex justify-center gap-2 mt-8 lg:hidden">
              {items.slice(0, 3).map((_, i) => (
                <button
                  key={i}
                  onClick={() => scrollToSlide(i)}
                  className={`h-1.5 rounded-full transition-all duration-300 ${
                    currentIndex === i ? 'w-8 bg-[#ff6b00]' : 'w-4 bg-gray-200'
                  }`}
                  aria-label={`Go to slide ${i + 1}`}
                />
              ))}
            </div>

            {/* Next/Prev Navigation Arrows (Hidden on Large Screens) */}
            <button 
              onClick={prevSlide}
              className="absolute left-0 top-1/2 -translate-y-1/2 -translate-x-4 md:-translate-x-12 w-12 h-12 bg-white rounded-full shadow-lg flex items-center justify-center hover:bg-gray-50 z-20 border border-gray-100 lg:hidden"
              aria-label="Previous slide"
            >
              <ChevronLeft className="w-6 h-6 text-gray-600" />
            </button>
            <button 
              onClick={nextSlide}
              className="absolute right-0 top-1/2 -translate-y-1/2 translate-x-4 md:translate-x-12 w-12 h-12 bg-white rounded-full shadow-lg flex items-center justify-center hover:bg-gray-50 z-20 border border-gray-100 lg:hidden"
              aria-label="Next slide"
            >
              <ChevronRight className="w-6 h-6 text-gray-600" />
            </button>
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-8">
            {filteredItems.map((item) => (
              <div
                key={item.id}
                className="bg-white rounded-[2.5rem] overflow-hidden transition-shadow duration-300 shadow-sm hover:shadow-xl border border-gray-50 flex flex-col h-full"
              >
                <div className="relative h-64 m-2 rounded-[2rem] overflow-hidden">
                  <img
                    src={getFoodImage(item.name)}
                    alt={item.name}
                    className="w-full h-full object-cover"
                    onError={(e) => { e.target.src = '/images/biryani.jpg'; }}
                  />
                  <div className="absolute top-4 left-4 flex gap-2">
                    <div className="bg-white/90 backdrop-blur-md px-3.5 py-1.5 rounded-2xl flex items-center gap-1.5 shadow-sm">
                      <Star className="w-3.5 h-3.5 text-yellow-500 fill-yellow-500" />
                      <span className="text-xs font-black text-gray-800">{item.rating || 4.5}</span>
                    </div>
                  </div>
                </div>

                <div className="p-6 pt-2 flex flex-col flex-1">
                  <h4 className="text-xl font-black text-gray-900 mb-2 line-clamp-1">{item.name}</h4>
                  <p className="text-sm text-gray-500 line-clamp-2 leading-relaxed mb-6 flex-1">
                    {item.description || genZDescriptions[item.name] || genZDescriptions.default}
                  </p>

                  <div className="flex items-center justify-between gap-4 mt-auto pt-4 border-t border-gray-50">
                    <div className="flex items-center text-[#ff6b00] font-black text-2xl">
                      <IndianRupee className="w-5 h-5" />
                      <span>{Math.round(item.price)}</span>
                    </div>
                    <button
                      onClick={() => handleAddToCart(item)}
                      className="bg-gray-900 hover:bg-[#ff6b00] text-white px-6 py-3.5 rounded-2xl text-sm font-black transition-colors"
                    >
                      Add to Cart
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
        
        {previewOnly && (
          <div className="mt-12 sm:mt-16 text-center px-4">
            <Link to="/menu" className="inline-flex items-center justify-center gap-3 px-8 sm:px-10 py-4 sm:py-4.5 bg-gray-900 text-white rounded-2xl font-bold hover:bg-[#ff6b00] transition-all group w-full sm:w-auto min-h-[52px]">
              View All Deliciousness
              <ArrowRight className="w-5 h-5 group-hover:translate-x-1 transition-transform flex-shrink-0" />
            </Link>
          </div>
        )}
      </div>
    </section>
  );
};

export default Menu;
