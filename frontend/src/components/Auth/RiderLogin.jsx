import React, { useState, useEffect, useRef } from 'react';
import { useAuth } from '../../hooks/useAuth';
import { useNavigate } from 'react-router-dom';
import { Mail, Lock, Bike } from 'lucide-react';
import { toast } from 'react-hot-toast';
import { ROLES } from '../../config/constants';

const RiderLogin = () => {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const didLoginRef = useRef(false);

  const { loginRider, riderToken, loading: authLoading, isRider } = useAuth();
  const navigate = useNavigate();

  // ── Navigate once token is committed to state ──────────────────
  useEffect(() => {
    if (!authLoading && riderToken && isRider()) {
      console.log('[RIDER LOGIN] Redirecting to dashboard...');
      // Small timeout to ensure state is fully committed and avoid route guard races
      const timer = setTimeout(() => {
        navigate('/rider/dashboard', { replace: true });
      }, 50);
      return () => clearTimeout(timer);
    }
  }, [riderToken, authLoading, isRider, navigate]);

  // ── Form submit ──────────────────────────────────────────────────────────
  const handleSubmit = async (e) => {
    e.preventDefault();
    if (submitting) return; // Prevent duplicate submissions
    setSubmitting(true);
    setError('');

    try {
      const result = await loginRider(email, password);
      if (result.success) {
        // SUCCESS: Show green toast exactly as requested
        toast.success("Rider login successful");
        didLoginRef.current = true;
        // Navigation is handled by the useEffect above
      } else {
        // ERROR: Show red toast
        const msg = result.message || 'Invalid partner credentials';
        setError(msg);
        toast.error(msg);
      }
    } catch (err) {
      const msg = 'An unexpected error occurred. Please try again.';
      setError(msg);
      toast.error(msg);
    } finally {
      setSubmitting(false);
    }
  };

  const handleInputChange = (setter) => (e) => {
    setter(e.target.value);
    if (error) setError('');
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50 py-12 px-4 sm:px-6 lg:px-8 font-sans">
      <div className="max-w-md w-full space-y-8 bg-white p-10 rounded-lg shadow-sm border border-gray-100">
        <div className="text-center">
          <div className="mx-auto h-20 w-20 bg-orange-50 rounded-full flex items-center justify-center mb-6">
            <Bike className="h-10 w-10 text-[#f97316]" />
          </div>
          <h2 className="text-3xl font-black text-gray-900 tracking-tight">Rider Login</h2>
          <p className="mt-2 text-sm font-medium text-gray-500 uppercase tracking-widest">
            Logistics Partner Portal
          </p>
        </div>
        <form className="mt-8 space-y-6" onSubmit={handleSubmit}>
          {error && (
            <div className="bg-red-50 border border-red-200 text-red-600 px-4 py-3 rounded-lg text-sm font-medium animate-in fade-in slide-in-from-top-1 duration-200">
              {error}
            </div>
          )}
          <div className="space-y-4">
            <div className="relative">
              <Mail className="absolute left-4 top-1/2 -translate-y-1/2 text-gray-400 w-5 h-5" />
              <input
                type="email"
                required
                value={email}
                onChange={handleInputChange(setEmail)}
                disabled={submitting}
                className="appearance-none block w-full pl-12 pr-4 py-4 border border-gray-200 placeholder-gray-400 text-gray-900 rounded-lg focus:outline-none focus:ring-1 focus:ring-[#f97316] focus:border-[#f97316] transition-all bg-gray-50/50 disabled:opacity-50"
                placeholder="Partner Email"
              />
            </div>
            <div className="relative">
              <Lock className="absolute left-4 top-1/2 -translate-y-1/2 text-gray-400 w-5 h-5" />
              <input
                type="password"
                required
                value={password}
                onChange={handleInputChange(setPassword)}
                disabled={submitting}
                className="appearance-none block w-full pl-12 pr-4 py-4 border border-gray-200 placeholder-gray-400 text-gray-900 rounded-lg focus:outline-none focus:ring-1 focus:ring-[#f97316] focus:border-[#f97316] transition-all bg-gray-50/50 disabled:opacity-50"
                placeholder="Password"
              />
            </div>
          </div>

          <div>
            <button
              type="submit"
              disabled={submitting}
              className="group relative w-full flex justify-center py-4 px-4 border border-transparent text-sm font-black rounded-lg text-white bg-gradient-to-r from-[#f97316] to-[#fb923c] hover:opacity-90 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-orange-500 transition-all disabled:opacity-50 uppercase tracking-widest shadow-lg shadow-orange-500/20"
            >
              {submitting ? 'Checking details...' : 'START RIDING'}
            </button>
          </div>

          <div className="text-center mt-6">
            <p className="text-xs text-gray-400 font-medium uppercase tracking-tighter">
              Authorized Delivery Partners Only
            </p>
          </div>
        </form>
      </div>
    </div>
  );
};

export default RiderLogin;
