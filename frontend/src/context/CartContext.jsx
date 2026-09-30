import React, { createContext, useContext, useEffect, useState } from "react";

const CartContext = createContext(null);
const KEY = "sogil_cart";

export const CartProvider = ({ children }) => {
  const [items, setItems] = useState(() => {
    try { return JSON.parse(localStorage.getItem(KEY)) || []; } catch { return []; }
  });

  useEffect(() => { localStorage.setItem(KEY, JSON.stringify(items)); }, [items]);

  const addItem = (item) => {
    // If cart contains locked invoice items, regular items cannot be mixed into invoice bundle
    if (items.some((i) => i.is_invoice_locked)) {
      setItems([{ ...item, cartId: Date.now() + "-" + Math.random().toString(36).slice(2, 7) }]);
      return;
    }
    setItems((prev) => [...prev, { ...item, cartId: Date.now() + "-" + Math.random().toString(36).slice(2, 7) }]);
  };

  const removeItem = (cartId) => {
    // If this item is part of an invoice bundle, remove the whole bundle
    const target = items.find((i) => i.cartId === cartId);
    if (target?.is_invoice_locked) {
      setItems([]);
      return;
    }
    setItems((prev) => prev.filter((i) => i.cartId !== cartId));
  };

  const updateQty = (cartId, quantity) => {
    const target = items.find((i) => i.cartId === cartId);
    if (target?.is_invoice_locked) {
      // Locked items cannot have quantity mutated
      return;
    }
    setItems((prev) =>
      prev.map((i) =>
        i.cartId === cartId
          ? {
              ...i,
              quantity: Math.max(1, quantity),
              breakdown: { ...i.breakdown, subtotal: i.breakdown.unit * Math.max(1, quantity) },
            }
          : i
      )
    );
  };

  const clear = () => setItems([]);

  const isInvoiceCart = items.length > 0 && Boolean(items[0]?.is_invoice_locked);
  const activeInvoice = isInvoiceCart
    ? {
        invoice_id: items[0].invoice_id,
        invoice_number: items[0].invoice_number,
        invoice_discount_le: items[0].invoice_discount_le || 0,
      }
    : null;

  const loadInvoiceBundle = (invoice) => {
    if (!invoice || !Array.isArray(invoice.items)) return;
    const invId = invoice._id || invoice.id;
    const bundleItems = invoice.items.map((it, idx) => ({
      cartId: `inv-${invId}-${idx}`,
      is_invoice_locked: true,
      invoice_id: invId,
      invoice_number: invoice.invoice_number,
      invoice_discount_le: Number(invoice.discount_amount) || 0,
      product: {
        id: it.product_id || invId,
        name: it.name,
        category: it.item_type === "custom" || !it.product_id ? "custom" : "catalog",
        image: null,
      },
      name: it.name,
      quantity: Number(it.quantity) || 1,
      breakdown: {
        unit: Number(it.unit_price) || 0,
        subtotal: Number(it.line_total) || 0,
      },
      config: {
        invoice_number: invoice.invoice_number,
        dimensions: it.dimensions || {},
        material: it.material || "",
        finishing: it.finishing || "",
        notes: it.notes || "",
        description: it.description || "",
      },
    }));
    setItems(bundleItems);
  };

  const count = items.reduce((s, i) => s + (i.quantity || 1), 0);
  const productSubtotal = items.reduce((s, i) => s + (i.breakdown?.subtotal || 0), 0);

  return (
    <CartContext.Provider
      value={{
        items,
        addItem,
        removeItem,
        updateQty,
        clear,
        count,
        productSubtotal,
        isInvoiceCart,
        activeInvoice,
        loadInvoiceBundle,
      }}
    >
      {children}
    </CartContext.Provider>
  );
};

export const useCart = () => useContext(CartContext);
