import React, { useState, useEffect } from 'react';
import { 
  IndianRupee, 
  TrendingUp, 
  Calendar,
  Wallet,
  ArrowUpRight,
  ArrowDownRight,
  CreditCard
} from 'lucide-react';
import apiClient from '../services/apiClient';

const RiderEarnings = () => {
  const [stats, setStats] = useState({
    totalEarnings: 0,
    totalDeliveries: 0,
    weeklyEarnings: 0,
    pendingPayments: 0
  });
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchEarnings = async () => {
      try {
        const res = await apiClient.get('/api/rider/completed_orders');
        if (res.success) {
          const completed = res.data.filter(o => o.status === 'DELIVERED');
          const earnings = completed.reduce((sum, o) => sum + (o.total_price * 0.15), 0);
          setStats({
            totalEarnings: earnings,
            totalDeliveries: completed.length,
            weeklyEarnings: earnings * 0.7, // Simulated weekly
            pendingPayments: 450.00 // Simulated pending
          });
        }
      } catch (err) {
        console.error("Failed to fetch earnings:", err);
      } finally {
        setLoading(false);
      }
    };
    fetchEarnings();
  }, []);

  const StatCard = ({ icon: Icon, label, value, subValue, trend, trendValue }) => (
    <div className="bg-white border border-gray-100 rounded-lg p-6 shadow-sm">
      <div className="flex justify-between items-start mb-4">
        <div className="w-12 h-12 bg-orange-50 rounded-lg flex items-center justify-center text-[#f97316]">
          <Icon className="w-6 h-6" />
        </div>
        {trend && (
          <div className={`flex items-center gap-1 text-[10px] font-black uppercase tracking-widest px-2 py-1 rounded ${trend === 'up' ? 'bg-green-50 text-green-600' : 'bg-red-50 text-red-600'}`}>
            {trend === 'up' ? <ArrowUpRight className="w-3 h-3" /> : <ArrowDownRight className="w-3 h-3" />}
            {trendValue}
          </div>
        )}
      </div>
      <p className="text-[10px] font-black text-gray-400 uppercase tracking-[0.2em] mb-1">{label}</p>
      <h3 className="text-2xl font-black text-gray-900">{value}</h3>
      <p className="text-xs font-bold text-gray-500 mt-1">{subValue}</p>
    </div>
  );

  return (
    <div className="max-w-5xl mx-auto pb-12 font-sans">
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-6 mb-8">
        <div>
          <h1 className="text-2xl font-black text-gray-900 uppercase tracking-tight">Earnings Overview</h1>
          <p className="text-gray-500 font-bold text-[10px] uppercase tracking-widest mt-1">Track your income and bonuses</p>
        </div>
        
        <button className="flex items-center gap-2 px-6 py-3 bg-[#f97316] text-white rounded-lg font-black uppercase tracking-widest text-xs shadow-lg shadow-orange-500/20 hover:opacity-90 transition-all">
          <Wallet className="w-4 h-4" />
          Request Payout
        </button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-10">
        <StatCard 
          icon={IndianRupee} 
          label="Total Earnings" 
          value={`₹${stats.totalEarnings.toFixed(2)}`} 
          subValue="Lifetime income"
          trend="up"
          trendValue="+12%"
        />
        <StatCard 
          icon={TrendingUp} 
          label="This Week" 
          value={`₹${stats.weeklyEarnings.toFixed(2)}`} 
          subValue="Last 7 days"
          trend="up"
          trendValue="+5.4%"
        />
        <StatCard 
          icon={CreditCard} 
          label="Pending" 
          value={`₹${stats.pendingPayments.toFixed(2)}`} 
          subValue="Ready for payout"
        />
        <StatCard 
          icon={Calendar} 
          label="Deliveries" 
          value={stats.totalDeliveries} 
          subValue="Completed orders"
        />
      </div>

      <div className="bg-white border border-gray-100 rounded-lg overflow-hidden shadow-sm">
        <div className="p-6 border-b border-gray-50 flex items-center justify-between">
          <h3 className="text-sm font-black text-gray-900 uppercase tracking-widest">Recent Transactions</h3>
          <button className="text-[10px] font-black text-[#f97316] uppercase tracking-widest hover:underline">View All</button>
        </div>
        <div className="divide-y divide-gray-50">
          {[1, 2, 3].map(i => (
            <div key={i} className="p-6 flex items-center justify-between hover:bg-gray-50 transition-colors">
              <div className="flex items-center gap-4">
                <div className="w-10 h-10 bg-green-50 rounded-full flex items-center justify-center text-green-600">
                  <ArrowDownRight className="w-5 h-5 rotate-180" />
                </div>
                <div>
                  <p className="text-sm font-black text-gray-900">Weekly Payout</p>
                  <p className="text-[10px] font-bold text-gray-400 uppercase tracking-widest">Bank Transfer • May {12 - i}, 2026</p>
                </div>
              </div>
              <p className="text-sm font-black text-green-600">+₹{(1200 + i * 50).toFixed(2)}</p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};

export default RiderEarnings;
