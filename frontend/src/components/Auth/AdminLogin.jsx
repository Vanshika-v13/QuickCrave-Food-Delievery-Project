import React, { useState, useEffect, useRef } from 'react';
import { useAuth } from '../../hooks/useAuth';
import { useNavigate } from 'react-router-dom';
import { Mail, Lock, ShieldCheck } from 'lucide-react';
import { toast } from 'react-hot-toast';
import { ROLES } from '../../config/constants';

const AdminLogin = () => {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const didLoginRef = useRef(false);

  const { loginAdmin, adminToken, adminUser, loading: authLoading, isAdmin } = useAuth();
  const navigate = useNavigate();

  // ── Navigate once token + roles are committed to state ──────────────────
  useEffect(() => {
    if (!authLoading && adminToken && isAdmin()) {
      console.log('[ADMIN LOGIN] Auth confirmed — navigating to dashboard');
      navigate('/admin/dashboard', { replace: true });
    }
  }, [adminToken, adminUser, authLoading, isAdmin, navigate]);

  // ── Form submit ──────────────────────────────────────────────────────────
  const handleSubmit = async (e) => {
    e.preventDefault();
    if (submitting) return; // prevent duplicate submissions
    setSubmitting(true);
    setError('');

    try {
      const result = await loginAdmin(email, password);
      if (result.success) {
        // Toast first, then let the useEffect above handle navigation
        toast.success('Admin login successful');
        didLoginRef.current = true;
      } else {
        const msg = result.message || 'Invalid admin credentials';
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
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-orange-50 via-white to-orange-100 py-12 px-4 sm:px-6 lg:px-8">
      <div className="max-w-md w-full space-y-8 bg-white p-10 rounded-3xl shadow-2xl">
        <div className="text-center">
          <div className="mx-auto h-16 w-16 bg-orange-100 rounded-2xl flex items-center justify-center mb-4">
            <ShieldCheck className="h-10 w-10 text-orange-600" />
          </div>
          <h2 className="text-3xl font-black text-gray-900 uppercase tracking-tight">Admin Portal</h2>
          <p className="mt-2 text-sm font-bold text-gray-500 italic">
            Secure Administrator Access Only
          </p>
        </div>
        <form className="mt-8 space-y-6" onSubmit={handleSubmit}>
          {error && (
            <div className="bg-red-50 border border-red-200 text-red-600 px-4 py-3 rounded-2xl text-sm font-medium animate-in fade-in slide-in-from-top-1 duration-200">
              {error}
            </div>
          )}
          <div className="space-y-4">
            <div className="relative">
              <Mail className="absolute left-3 top-3 text-gray-400 w-5 h-5" />
              <input
                type="email"
                required
                value={email}
                onChange={handleInputChange(setEmail)}
                className="appearance-none block w-full px-12 py-3 border border-gray-200 placeholder-gray-400 text-gray-900 rounded-2xl focus:outline-none focus:ring-2 focus:ring-orange-500 focus:border-transparent sm:text-sm transition-all"
                placeholder="Admin Email"
              />
            </div>
            <div className="relative">
              <Lock className="absolute left-3 top-3 text-gray-400 w-5 h-5" />
              <input
                type="password"
                required
                value={password}
                onChange={handleInputChange(setPassword)}
                className="appearance-none block w-full px-12 py-3 border border-gray-200 placeholder-gray-400 text-gray-900 rounded-2xl focus:outline-none focus:ring-2 focus:ring-orange-500 focus:border-transparent sm:text-sm transition-all"
                placeholder="Password"
              />
            </div>
          </div>

          <div>
            <button
              type="submit"
              disabled={submitting}
              className="group relative w-full flex justify-center py-4 px-4 border border-transparent text-sm font-black rounded-2xl text-white bg-[#f97316] hover:bg-[#ea580c] focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-orange-500 transition-all disabled:opacity-50 uppercase tracking-widest shadow-lg shadow-orange-200"
            >
              {submitting ? 'Authenticating...' : 'Login to Dashboard'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};

export default AdminLogin;
