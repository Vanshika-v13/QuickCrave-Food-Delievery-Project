import React, { useState } from 'react';
import { ShoppingCart, User, LogOut, Menu as MenuIcon, Search, X, Package } from 'lucide-react';
import { NavLink, Link, useNavigate, useLocation } from 'react-router-dom';
import { useCart } from '../hooks/useCart';
import { useAuth } from '../hooks/useAuth';
import { ENABLE_NEARBY_FEATURE } from '../config/featureFlags';

const Navbar = ({ onCartClick, onSearchChange, searchTerm }) => {
  const { cartCount = 0 } = useCart() || {};
  const { customerUser: user = null, customerToken: token = null, logoutCustomer: logout = () => {} } = useAuth() || {};
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);
  const isAuthenticated = !!token;
  const navigate = useNavigate();
  const location = useLocation();

  const handleLogout = () => {
    logout();
    navigate('/');
    setIsMobileMenuOpen(false);
  };

  const isHome = location.pathname === '/' || location.pathname === '/home';
  const isMenu = location.pathname === '/menu';

  const navLinkClass = ({ isActive }) => 
    `transition-colors ${isActive ? 'text-[#ff6b00]' : 'hover:text-[#ff6b00]'}`;

  return (
    <nav className="sticky top-0 left-0 right-0 bg-white/80 backdrop-blur-xl z-50 border-b border-gray-100">
      <div className="max-w-7xl mx-auto px-4 md:px-10 h-20 flex items-center justify-between gap-4">
        {/* Logo */}
        <div className="flex items-center shrink-0">
          <Link to="/" className="flex items-center" onClick={() => setIsMobileMenuOpen(false)}>
            <h1 className="text-2xl font-black tracking-tight text-gray-900">
              Quick<span className="text-[#ff6b00]">Crave</span>
            </h1>
          </Link>
        </div>

        {/* Search Bar */}
        {isMenu && (
          <div className="flex-1 max-w-xl hidden md:block">
            <div className="relative group">
              <div className="absolute inset-y-0 left-0 pl-4 flex items-center pointer-events-none">
                <Search className="h-5 w-5 text-gray-400 group-focus-within:text-[#ff6b00] transition-colors" />
              </div>
              <input
                type="text"
                placeholder="Search for delicious food..."
                value={searchTerm}
                onChange={(e) => onSearchChange(e.target.value)}
                className="block w-full pl-11 pr-11 py-3 bg-gray-50 border border-transparent rounded-2xl text-sm placeholder-gray-400 focus:outline-none focus:bg-white focus:border-orange-200 focus:ring-4 focus:ring-orange-50 transition-all"
              />
            </div>
          </div>
        )}

        {/* Actions */}
        <div className="flex items-center gap-2 sm:gap-4 shrink-0">
          <div className="hidden lg:flex items-center gap-6 mr-4 text-sm font-bold text-gray-600">
            {!isHome && <NavLink to={user ? "/home" : "/"} className={navLinkClass}>Home</NavLink>}
            {user && (
              <>
                <NavLink to="/menu" className={navLinkClass}>Menu</NavLink>
                <NavLink to="/orders" className={navLinkClass}>Orders</NavLink>
                <NavLink to="/track-order" className={navLinkClass}>Track Order</NavLink>
                {ENABLE_NEARBY_FEATURE && (
                  <NavLink to="/nearby" className={navLinkClass}>Nearby</NavLink>
                )}
              </>
            )}
          </div>

          {isAuthenticated && (
            <button 
              onClick={onCartClick}
              className="relative p-3 bg-orange-50 text-[#ff6b00] rounded-2xl hover:bg-[#ff6b00] hover:text-white transition-all duration-300 group shadow-sm shadow-orange-100"
            >
              <ShoppingCart className="w-5.5 h-5.5" />
              {cartCount > 0 && (
                <span className="absolute -top-1.5 -right-1.5 bg-gray-900 text-white text-[10px] font-black w-5 h-5 flex items-center justify-center rounded-full border-2 border-white">
                  {cartCount}
                </span>
              )}
            </button>
          )}

          {isAuthenticated ? (
            <div className="flex items-center gap-2">
              <Link 
                to="/profile" 
                onClick={(e) => e.stopPropagation()}
                className="hidden sm:flex items-center gap-2.5 bg-gray-50 hover:bg-orange-50/50 px-3 py-2 rounded-2xl border border-gray-100 hover:border-orange-100 transition-all duration-300 group cursor-pointer"
              >
                <div className="w-7 h-7 bg-white rounded-full flex items-center justify-center overflow-hidden border border-gray-200 group-hover:border-orange-200 transition-all shrink-0">
                  {user?.profile_pic ? (
                    <img src={user.profile_pic} alt="" className="w-full h-full object-cover" />
                  ) : (
                    <User className="w-4 h-4 text-gray-400 group-hover:text-[#ff6b00] transition-colors" />
                  )}
                </div>
                <span className="text-xs font-bold text-gray-700 group-hover:text-[#ff6b00] transition-colors">{user?.name ? user.name.split(' ')[0] : 'User'}</span>
              </Link>
              <button 
                onClick={handleLogout}
                className="hidden sm:flex p-3 hover:bg-red-50 text-gray-400 hover:text-red-500 rounded-2xl transition-all"
              >
                <LogOut className="w-5 h-5" />
              </button>
            </div>
          ) : (
            <div className="flex items-center gap-2">
              <Link to="/login" className="px-5 py-2.5 rounded-2xl text-sm font-bold text-gray-600 hover:bg-gray-50 transition-all">
                Login
              </Link>
              <Link to="/signup" className="bg-[#ff6b00] text-white px-6 py-2.5 rounded-2xl text-sm font-bold hover:bg-[#e65c00] transition-all shadow-md shadow-orange-100">
                Signup
              </Link>
            </div>
          )}
          
          <button 
            className="lg:hidden p-2 hover:bg-gray-50 rounded-xl"
            onClick={() => setIsMobileMenuOpen(!isMobileMenuOpen)}
          >
            {isMobileMenuOpen ? <X className="w-6 h-6 text-gray-700" /> : <MenuIcon className="w-6 h-6 text-gray-700" />}
          </button>
        </div>
      </div>

      {/* Mobile Menu */}
      {isMobileMenuOpen && (
        <div className="lg:hidden bg-white border-t border-gray-100 px-4 py-6 space-y-4 animate-in slide-in-from-top duration-300">
          <div className="flex flex-col gap-4 font-bold text-gray-600">
            <NavLink 
              to={user ? "/home" : "/"} 
              className={navLinkClass}
              onClick={() => setIsMobileMenuOpen(false)}
            >
              Home
            </NavLink>
            {user && (
              <>
                <NavLink 
                  to="/menu" 
                  className={navLinkClass}
                  onClick={() => setIsMobileMenuOpen(false)}
                >
                  Menu
                </NavLink>
                <NavLink 
                  to="/orders" 
                  className={navLinkClass}
                  onClick={() => setIsMobileMenuOpen(false)}
                >
                  Orders
                </NavLink>
                <NavLink 
                  to="/track-order" 
                  className={navLinkClass}
                  onClick={() => setIsMobileMenuOpen(false)}
                >
                  Track Order
                </NavLink>
                <NavLink 
                  to="/profile" 
                  className={navLinkClass}
                  onClick={() => setIsMobileMenuOpen(false)}
                >
                  Profile
                </NavLink>
              </>
            )}
            {isAuthenticated && (
              <button 
                onClick={handleLogout}
                className="flex items-center gap-2 text-red-500 pt-4 border-t border-gray-50"
              >
                <LogOut className="w-5 h-5" />
                Logout
              </button>
            )}
          </div>
        </div>
      )}

      {/* Mobile Search Bar */}
      {isMenu && (
        <div className="md:hidden px-4 pb-4">
          <div className="relative">
            <div className="absolute inset-y-0 left-0 pl-4 flex items-center pointer-events-none">
              <Search className="h-4 w-4 text-gray-400" />
            </div>
            <input
              type="text"
              placeholder="Search food..."
              value={searchTerm}
              onChange={(e) => onSearchChange(e.target.value)}
              className="block w-full pl-10 pr-4 py-2.5 bg-gray-50 border-none rounded-xl text-sm focus:ring-2 focus:ring-orange-200"
            />
          </div>
        </div>
      )}
    </nav>
  );
};

export default Navbar;
