import React, { useState } from 'react';
import { Link, Outlet, useLocation } from 'react-router-dom';
import { MapPin, Phone, Mail } from 'lucide-react';
import Navbar from '../components/Navbar';
import CartDrawer from '../components/CartDrawer';

const MainLayout = () => {
  const location = useLocation();
  const [isCartOpen, setIsCartOpen] = useState(false);
  const [searchTerm, setSearchTerm] = useState('');

  return (
    <div className="min-h-screen bg-white">
      <Navbar 
        onCartClick={() => setIsCartOpen(true)}
        searchTerm={searchTerm}
        onSearchChange={setSearchTerm}
      />
      
      <main>
        <Outlet context={{ searchTerm }} />
      </main>

      <footer className="bg-gray-900 text-white pt-20 pb-10 mt-20">
        <div className="max-w-7xl mx-auto px-4 md:px-10 grid grid-cols-1 md:grid-cols-3 gap-16">
          <div className="space-y-6">
            <h2 className="text-3xl font-black tracking-tight">
              Quick<span className="text-[#ff6b00]">Crave</span>
            </h2>
            <p className="text-gray-400 leading-relaxed max-w-xs">
              Serving happiness through delicious, authentic Indian and global cuisines delivered fresh to your doorstep.
            </p>
          </div>
          
          <div className="space-y-8">
            <h4 className="font-bold text-white text-lg relative inline-block">
              Quick Links
              <span className="absolute -bottom-2 left-0 w-8 h-1 bg-[#ff6b00] rounded-full"></span>
            </h4>
            <div className="flex flex-col gap-4 text-gray-400 font-medium">
              <Link to="/" className="hover:text-[#ff6b00] transition-colors">Home</Link>
              <Link to="/menu" className="hover:text-[#ff6b00] transition-colors">Order Menu</Link>
              <Link to="/orders" className="hover:text-[#ff6b00] transition-colors">My Orders</Link>
            </div>
          </div>

          <div className="space-y-8">
            <h4 className="font-bold text-white text-lg relative inline-block">
              Contact Info
              <span className="absolute -bottom-2 left-0 w-8 h-1 bg-[#ff6b00] rounded-full"></span>
            </h4>
            <div className="flex flex-col gap-6">
              <div className="flex items-start gap-4">
                <MapPin className="w-5 h-5 text-[#ff6b00] shrink-0" />
                <p className="text-gray-400">Patli Gali, Delhi, India</p>
              </div>
              <div className="flex items-start gap-4">
                <Phone className="w-5 h-5 text-[#ff6b00] shrink-0" />
                <p className="text-gray-400">+91 98765 43210</p>
              </div>
              <div className="flex items-start gap-4">
                <Mail className="w-5 h-5 text-[#ff6b00] shrink-0" />
                <p className="text-gray-400">support@quickcrave.com</p>
              </div>
            </div>
          </div>
        </div>
        <div className="max-w-7xl mx-auto px-4 md:px-10 pt-10 mt-16 border-t border-gray-800 flex flex-col md:flex-row items-center justify-between gap-6 text-gray-500 text-sm font-medium">
          <p>© 2026 QuickCrave. All rights reserved.</p>
        </div>
      </footer>

      <CartDrawer isOpen={isCartOpen} onClose={() => setIsCartOpen(false)} />
    </div>
  );
};

export default MainLayout;
