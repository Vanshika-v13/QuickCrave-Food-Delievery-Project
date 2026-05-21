import { useContext } from 'react';
import { CartContext } from '../context/CartContext';
import { logProviderWarning } from '../utils/contextLogger';

export function useCart() {
  const context = useContext(CartContext);
  
  if (!context) {
    logProviderWarning('Cart');
    
    // Return a strict fallback object that indicates failure
    return {
      _isProviderMissing: true,
      cart: [],
      addToCart: async () => { throw new Error('[CART] Provider missing'); },
      removeFromCart: async () => { throw new Error('[CART] Provider missing'); },
      updateQuantity: async () => { throw new Error('[CART] Provider missing'); },
      clearCart: async () => { throw new Error('[CART] Provider missing'); },
      cartTotal: 0,
      cartCount: 0,
    };
  }
  
  return context;
}
