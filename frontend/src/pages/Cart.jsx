import React from "react";
import { Link, useNavigate } from "react-router-dom";
import { fmtLE } from "../lib/format";
import { config_summary_client } from "../lib/summary";
import { useCart } from "../context/CartContext";
import { useLang } from "../context/LanguageContext";
import { imgUrl } from "../lib/api";
import { ProductImage } from "../components/ProductImage";
import { Button } from "../components/ui/button";
import { Minus, Plus, Trash2, ShoppingCart, Lock, Info } from "lucide-react";

export default function Cart() {
  const { items, removeItem, updateQty, productSubtotal, isInvoiceCart, activeInvoice, clear } = useCart();
  const { t } = useLang();
  const navigate = useNavigate();

  if (!items.length) {
    return (
      <div className="mx-auto max-w-2xl px-4 py-16 text-center sm:px-6">
        <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-full bg-[#EFE6D5] text-[#8B5A2B]"><ShoppingCart size={30} /></div>
        <h1 className="mt-4 font-heading text-2xl font-bold text-[#2C1E16]">{t("cart.title")}</h1>
        <p className="mt-2 text-[#5C4A3D]">{t("cart.empty")}</p>
        <Link to="/"><Button className="mt-5 h-12 rounded-full bg-[#8B5A2B] px-8 hover:bg-[#6B4423]">{t("cart.belanja")}</Button></Link>
      </div>
    );
  }

  const invoiceDiscount = activeInvoice?.invoice_discount_le || 0;
  const netSubtotal = Math.max(0, productSubtotal - invoiceDiscount);

  return (
    <div className="mx-auto max-w-4xl px-4 py-8 sm:px-6">
      <div className="flex items-center justify-between">
        <h1 className="font-heading text-2xl font-bold text-[#2C1E16]">{t("cart.title")}</h1>
        {isInvoiceCart && (
          <Button
            variant="ghost"
            size="sm"
            onClick={clear}
            className="text-xs text-red-600 hover:text-red-700 hover:bg-red-50 rounded-xl"
          >
            Keluarkan Paket Invoice
          </Button>
        )}
      </div>

      {/* Invoice Bundle Notice */}
      {isInvoiceCart && (
        <div className="mt-4 rounded-2xl border border-amber-300 bg-amber-50 p-4 text-sm text-amber-900 shadow-xs flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div className="flex items-start gap-2.5">
            <Lock className="text-amber-700 h-5 w-5 shrink-0 mt-0.5" />
            <div>
              <div className="font-semibold text-amber-950">
                Paket Invoice #{activeInvoice?.invoice_number}
              </div>
              <p className="text-xs text-amber-800 mt-0.5">
                Item dan spesifikasi terkunci sesuai kesepakatan invoice. Pengiriman dan pembayaran akan dipilih di Checkout.
              </p>
            </div>
          </div>
        </div>
      )}

      <div className="mt-6 space-y-3" data-testid="cart-items">
        {items.map((it) => {
          const isLocked = Boolean(it.is_invoice_locked);
          const customDims = it.config?.dimensions;
          const dimsStr = customDims?.length && customDims?.width && customDims?.height
            ? `${customDims.length} × ${customDims.width} × ${customDims.height} cm`
            : null;

          return (
            <div key={it.cartId} className="flex gap-3 rounded-2xl border border-[#E5DCC5] bg-white p-3 shadow-sm" data-testid={`cart-item-${it.cartId}`}>
              <div className="h-24 w-24 shrink-0 overflow-hidden rounded-xl border border-[#E5DCC5] bg-[#FAF5EE] flex items-center justify-center">
                {it.product?.image ? (
                  <img src={imgUrl(it.product.image)} alt="" className="h-full w-full object-cover" />
                ) : (
                  <ProductImage ratio="aspect-square" />
                )}
              </div>
              <div className="flex flex-1 flex-col">
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <div className="font-heading font-semibold text-[#2C1E16] flex items-center gap-1.5">
                      {it.name || it.product?.name}
                      {isLocked && <Lock size={13} className="text-amber-700" title="Item terkunci dalam invoice" />}
                    </div>
                    {isLocked ? (
                      <div className="mt-1 space-y-0.5 text-xs text-[#8B7355]">
                        {it.config?.description && <p>{it.config.description}</p>}
                        {dimsStr && <p className="font-mono">{dimsStr}</p>}
                        {it.config?.material && <p>Bahan: {it.config.material}</p>}
                        {it.config?.finishing && <p>Finishing: {it.config.finishing}</p>}
                      </div>
                    ) : (
                      <div className="text-xs text-[#8B7355]">{config_summary_client(it.product?.category, it.config, t)}</div>
                    )}
                  </div>
                  {!isLocked && (
                    <button onClick={() => removeItem(it.cartId)} data-testid={`cart-remove-${it.cartId}`} className="p-1 text-red-500">
                      <Trash2 size={18} />
                    </button>
                  )}
                </div>
                <div className="mt-auto flex items-center justify-between pt-2">
                  {isLocked ? (
                    <div className="inline-flex items-center gap-1.5 rounded-lg bg-[#FAF5EE] border border-[#E5DCC5] px-2.5 py-1 text-xs font-semibold text-[#5C4A3D]">
                      <Lock size={11} className="text-amber-700" />
                      <span>{it.quantity} unit</span>
                    </div>
                  ) : (
                    <div className="flex items-center gap-2">
                      <button onClick={() => updateQty(it.cartId, it.quantity - 1)} data-testid={`cart-minus-${it.cartId}`} className="flex h-9 w-9 items-center justify-center rounded-lg border border-[#E5DCC5]"><Minus size={14} /></button>
                      <span className="w-7 text-center text-sm font-semibold">{it.quantity}</span>
                      <button onClick={() => updateQty(it.cartId, it.quantity + 1)} data-testid={`cart-plus-${it.cartId}`} className="flex h-9 w-9 items-center justify-center rounded-lg border border-[#E5DCC5]"><Plus size={14} /></button>
                    </div>
                  )}
                  <div className="font-heading font-bold text-[#8B5A2B]">
                    {it.breakdown?.requiresConfirm ? "—" : `${fmtLE(it.breakdown?.subtotal || 0)} LE`}
                  </div>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      <div className="mt-6 rounded-2xl border border-[#E5DCC5] bg-white p-5 shadow-sm space-y-3">
        <div className="flex justify-between text-sm">
          <span className="text-[#5C4A3D]">{t("cart.total_produk")}</span>
          <span className="font-heading text-lg font-bold text-[#2C1E16]" data-testid="cart-subtotal">{fmtLE(productSubtotal)} LE</span>
        </div>

        {invoiceDiscount > 0 && (
          <div className="flex justify-between text-sm text-green-700 font-medium">
            <span>Diskon Invoice #{activeInvoice?.invoice_number}</span>
            <span>-{fmtLE(invoiceDiscount)} LE</span>
          </div>
        )}

        {invoiceDiscount > 0 && (
          <div className="border-t border-[#F1EBE0] pt-2 flex justify-between text-sm font-semibold text-[#2C1E16]">
            <span>Total Produk Setelah Diskon Invoice</span>
            <span className="font-heading text-lg text-[#8B5A2B]">{fmtLE(netSubtotal)} LE</span>
          </div>
        )}

        <p className="text-xs text-[#8B7355]">{t("sum.disclaimer")}</p>
        <div className="mt-4 flex flex-col gap-2 sm:flex-row pt-2">
          {!isInvoiceCart && (
            <Button variant="outline" onClick={() => navigate("/produk")} data-testid="cart-add-more" className="h-12 flex-1 rounded-full border-[#8B5A2B] text-[#8B5A2B]">
              {t("cart.tambah_lagi")}
            </Button>
          )}
          <Button onClick={() => navigate("/checkout")} data-testid="cart-checkout" className="h-12 flex-1 rounded-full bg-[#8B5A2B] hover:bg-[#6B4423]">
            {t("cart.lanjut_checkout")}
          </Button>
        </div>
      </div>
    </div>
  );
}
