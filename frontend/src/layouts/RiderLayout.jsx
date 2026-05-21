import React, { useState } from 'react';
import { Link, useNavigate, Outlet, useLocation } from 'react-router-dom';
import { 
  Bike, 
  History, 
  User, 
  LogOut,
  ChevronLeft,
  LayoutDashboard,
  IndianRupee,
  Menu,
  X,
  CreditCard
} from 'lucide-react';
import { useAuth } from '../hooks/useAuth';

const RiderLayout = () => {
  const { riderUser: user, logoutRider } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);

  const handleLogout = () => {
    console.log('[RIDER] Initiating logout...');
    logoutRider();
    navigate('/rider/login', { replace: true });
  };

  const navItems = [
    { icon: LayoutDashboard, label: 'Active Orders', path: '/rider/dashboard' },
    { icon: History, label: 'History', path: '/rider/history' },
    { icon: CreditCard, label: 'Earnings', path: '/rider/earnings' },
  ];

  const NavLink = ({ item }) => {
    const isActive = location.pathname === item.path;
    return (
      <Link
        to={item.path}
        onClick={() => setIsSidebarOpen(false)}
        className={`flex items-center gap-3 px-4 py-3 rounded-lg transition-all mb-1 ${
          isActive 
          ? 'bg-orange-50 text-[#f97316] font-black' 
          : 'text-gray-500 hover:bg-gray-50 font-bold'
        }`}
      >
        <item.icon className={`w-5 h-5 ${isActive ? 'text-[#f97316]' : 'text-gray-400'}`} />
        <span className="text-sm uppercase tracking-wider">{item.label}</span>
      </Link>
    );
  };

  return (
    <div className="min-h-screen bg-[#f8f9fa] flex font-sans">
      {/* Sidebar - Desktop */}
      <aside className="hidden lg:flex w-64 bg-white border-r border-gray-100 flex-col sticky top-0 h-screen z-50">
        <div className="p-6 flex items-center gap-3 border-b border-gray-50">
          <div className="w-10 h-10 bg-[#f97316] rounded-lg flex items-center justify-center text-white shadow-lg shadow-orange-500/20">
            <Bike className="w-6 h-6" />
          </div>
          <div>
            <h1 className="text-sm font-black text-gray-900 uppercase tracking-tight">Rider Portal</h1>
            <div className="flex items-center gap-1.5">
              <span className="w-1.5 h-1.5 bg-green-500 rounded-full animate-pulse"></span>
              <span className="text-[10px] font-black text-green-600 uppercase tracking-widest">Online</span>
            </div>
          </div>
        </div>

        <nav className="flex-1 p-4 mt-4">
          {navItems.map((item) => (
            <NavLink key={item.path} item={item} />
          ))}
        </nav>

        <div className="p-4 border-t border-gray-50">
          <div className="bg-gray-50 rounded-lg p-4 mb-4">
            <p className="text-[10px] font-black text-gray-400 uppercase tracking-widest mb-1">Signed in as</p>
            <p className="text-xs font-bold text-gray-900 truncate">{user?.email}</p>
          </div>
          <button 
            onClick={handleLogout}
            className="flex items-center gap-3 px-4 py-3 rounded-lg text-red-500 hover:bg-red-50 font-black w-full transition-all"
          >
            <LogOut className="w-5 h-5" />
            <span className="text-sm uppercase tracking-wider">Logout</span>
          </button>
        </div>
      </aside>

      {/* Mobile Sidebar (Drawer) */}
      <div className={`lg:hidden fixed inset-0 bg-black/50 z-[60] transition-opacity duration-300 ${isSidebarOpen ? 'opacity-100 pointer-events-auto' : 'opacity-0 pointer-events-none'}`} onClick={() => setIsSidebarOpen(false)} />
      <aside className={`lg:hidden fixed inset-y-0 left-0 w-72 bg-white z-[70] transition-transform duration-300 transform ${isSidebarOpen ? 'translate-x-0' : '-translate-x-full'}`}>
        <div className="p-6 flex items-center justify-between border-b border-gray-50">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 bg-[#f97316] rounded-lg flex items-center justify-center text-white shadow-lg shadow-orange-500/20">
              <Bike className="w-6 h-6" />
            </div>
            <h1 className="text-sm font-black text-gray-900 uppercase tracking-tight">Rider Portal</h1>
          </div>
          <button onClick={() => setIsSidebarOpen(false)} className="p-2 text-gray-400">
            <X className="w-6 h-6" />
          </button>
        </div>
        <nav className="p-4 mt-4">
          {navItems.map((item) => (
            <NavLink key={item.path} item={item} />
          ))}
          <button 
            onClick={handleLogout}
            className="flex items-center gap-3 px-4 py-3 rounded-lg text-red-500 hover:bg-red-50 font-black w-full mt-4 transition-all"
          >
            <LogOut className="w-5 h-5" />
            <span className="text-sm uppercase tracking-wider">Logout</span>
          </button>
        </nav>
      </aside>

      {/* Main Content Area */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Mobile Header */}
        <header className="lg:hidden h-16 bg-white border-b border-gray-100 flex items-center justify-between px-4 sticky top-0 z-40">
          <button onClick={() => setIsSidebarOpen(true)} className="p-2 -ml-2 text-gray-600">
            <Menu className="w-6 h-6" />
          </button>
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 bg-[#f97316] rounded flex items-center justify-center text-white">
              <Bike className="w-5 h-5" />
            </div>
            <span className="text-xs font-black uppercase tracking-widest text-gray-900">Partner</span>
          </div>
          <div className="w-10" /> {/* Spacer */}
        </header>

        <main className="flex-1 p-4 lg:p-8 max-w-7xl w-full mx-auto">
          <Outlet />
        </main>
      </div>
    </div>
  );
};

export default RiderLayout;
