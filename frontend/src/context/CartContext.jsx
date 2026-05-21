import React, { createContext, useContext, useState, useEffect } from 'react';
import { toast } from 'react-hot-toast';
import { useAuth } from '../hooks/useAuth';
import apiClient from '../services/apiClient';

export const CartContext = createContext();

export function CartProvider({ children }) {
  const [cart, setCart] = useState(() => {
    const saved = localStorage.getItem("cart");
    return saved ? JSON.parse(saved) : [];
  });
  const { customerToken: token, isCustomer } = useAuth();
  const isAuthenticated = !!token;

  // Fetch cart from backend on mount or when auth status changes
  useEffect(() => {
    const fetchCart = async () => {
      // RULE: Only customers should fetch the cart (Fixes 403 for Riders/Admins)
      if (isAuthenticated && isCustomer()) {
        try {
          const response = await apiClient.get('/api/cart');
          const cartData = response?.success ? (response.data || []) : (Array.isArray(response) ? response : []);
          setCart(cartData);
        } catch (error) {
          if (error?.networkError) {
            // Backend temporarily unreachable — preserve existing cart state, do NOT reset auth
            console.warn('[CART] Backend unavailable. Preserving existing cart state.');
            // Cart state remains unchanged — no setCart([]) here
          } else if (error?.response?.status === 401 || error?.status === 401) {
            // Genuine auth failure — clear cart
            setCart([]);
          } else {
            // Other API error (400, 500, etc.) — preserve existing cart state
            console.error('[CART] Error fetching cart:', error);
          }
        }
      } else if (!isAuthenticated) {
        // Only load guest cart if NOT authenticated
        const savedCart = localStorage.getItem('cart');
        if (savedCart) {
          try { setCart(JSON.parse(savedCart)); } catch { setCart([]); }
        }
      } else {
        // Authenticated but NOT a customer (Rider/Admin) - Keep cart empty
        setCart([]);
      }
    };
    fetchCart();
  }, [isAuthenticated, isCustomer]);


  // Sync localStorage for guest mode or as secondary cache
  useEffect(() => {
    localStorage.setItem('cart', JSON.stringify(cart));
  }, [cart]);

  const addToCart = async (item) => {
    console.log("🔥 ADDING ITEM TO CART:", item.id || item.item_id);
    if (isAuthenticated) {
      try {
        const response = await apiClient.post('/api/cart/add', { 
          item_id: item.id || item.item_id, 
          quantity: 1 
         });
        const cartData = response?.success ? (response.data || []) : (Array.isArray(response) ? response : []);
        setCart(cartData);
        toast.success(`${item.name} added to cart`);
      } catch (error) {
        console.error("Error adding to cart:", error);
        if (error?.status === 401 || error?.response?.status === 401) {
            toast.error("Please login to add items to cart");
        } else {
            toast.error("Failed to add item to cart");
        }
      }
    } else {
      setCart((prevCart) => {
        const existingItem = prevCart.find((i) => (i.id || i.item_id) === (item.id || item.item_id));
        if (existingItem) {
          return prevCart.map((i) =>
            (i.id || i.item_id) === (item.id || item.item_id) ? { ...i, quantity: i.quantity + 1 } : i
          );
        }
        return [...prevCart, { ...item, quantity: 1 }];
      });
      toast.success(`${item.name} added to cart`);
    }
  };

  const removeFromCart = async (itemId) => {
    if (isAuthenticated) {
      try {
        const response = await apiClient.delete(`/api/cart/remove/${itemId}`);
        const cartData = response?.success ? (response.data || []) : (Array.isArray(response) ? response : []);
        setCart(cartData);
        toast.success("Item removed");
      } catch (error) {
        console.error("Error removing item:", error);
      }
    } else {
      setCart((prevCart) => prevCart.filter((i) => (i.id || i.item_id) !== itemId));
    }
  };

  const updateQuantity = async (itemId, quantity) => {
    if (quantity < 1) {
      removeFromCart(itemId);
      return;
    }

    if (isAuthenticated) {
      try {
        const response = await apiClient.put('/api/cart/update', { item_id: itemId, quantity });
        const cartData = response?.success ? (response.data || []) : (Array.isArray(response) ? response : []);
        setCart(cartData);
      } catch (error) {
        console.error("Error updating quantity:", error);
      }
    } else {
      setCart((prevCart) =>
        prevCart.map((i) => ((i.id || i.item_id) === itemId ? { ...i, quantity } : i))
      );
    }
  };

  const clearCart = async () => {
    if (isAuthenticated) {
      try {
        await apiClient.delete('/api/cart/clear');
        setCart([]);
      } catch (error) {
        console.error("Error clearing cart:", error);
      }
    } else {
      setCart([]);
    }
  };

  const cartTotal = cart.reduce((sum, item) => sum + (item.price || 0) * (item.quantity || 0), 0);
  const cartCount = cart.reduce((sum, item) => sum + (item.quantity || 0), 0);

  return (
    <CartContext.Provider
      value={{
        cart,
        addToCart,
        removeFromCart,
        updateQuantity,
        clearCart,
        cartTotal,
        cartCount,
      }}
    >
      {children}
    </CartContext.Provider>
  );
}

