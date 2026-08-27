import React, { createContext, useContext, useEffect, useState } from "react";

const CartContext = createContext(null);
const KEY = "sogil_cart";

export const CartProvider = ({ children }) => {
  const [items, setItems] = useState(() => {
    try { return JSON.parse(localStorage.getItem(KEY)) || []; } catch { return []; }
  });

  useEffect(() => { localStorage.setItem(KEY, JSON.stringify(items)); }, [items]);

  const addItem = (item) => {
    setItems((prev) => [...prev, { ...item, cartId: Date.now() + "-" + Math.random().toString(36).slice(2, 7) }]);
  };
  const removeItem = (cartId) => setItems((prev) => prev.filter((i) => i.cartId !== cartId));
  const updateQty = (cartId, quantity) =>
    setItems((prev) => prev.map((i) => (i.cartId === cartId ? { ...i, quantity: Math.max(1, quantity), breakdown: { ...i.breakdown, subtotal: i.breakdown.unit * Math.max(1, quantity) } } : i)));
  const clear = () => setItems([]);

  const count = items.reduce((s, i) => s + (i.quantity || 1), 0);
  const productSubtotal = items.reduce((s, i) => s + (i.breakdown?.subtotal || 0), 0);

  return (
    <CartContext.Provider value={{ items, addItem, removeItem, updateQty, clear, count, productSubtotal }}>
      {children}
    </CartContext.Provider>
  );
};

export const useCart = () => useContext(CartContext);
