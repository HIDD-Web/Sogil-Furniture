import React, { useState, useEffect } from "react";
import { useSearchParams, useNavigate, useLocation, Link } from "react-router-dom";
import api from "../lib/api";
import { fmtLE, formatApiError } from "../lib/format";
import { useCustomer } from "../context/CustomerContext";
import { useCart } from "../context/CartContext";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Badge } from "../components/ui/badge";
import { toast } from "sonner";
import {
  FileText,
  KeyRound,
  CheckCircle2,
  Lock,
  ArrowRight,
  ShoppingCart,
  AlertCircle,
  LogIn,
  Package,
  Layers,
} from "lucide-react";

export default function InvoiceClaim() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const location = useLocation();
  const { customer, checked: customerChecked } = useCustomer();
  const { items, isInvoiceCart, loadInvoiceBundle } = useCart();

  const initialInv = (searchParams.get("invoice") || searchParams.get("inv") || "").trim().toUpperCase();
  const initialCode = (searchParams.get("code") || "").trim().toUpperCase();

  const [invoiceNumber, setInvoiceNumber] = useState(initialInv);
  const [claimCode, setClaimCode] = useState(initialCode);
  const [loading, setLoading] = useState(false);
  const [claimedInvoice, setClaimedInvoice] = useState(null);
  const [confirmReplaceModal, setConfirmReplaceModal] = useState(false);

  // Auto-fill from query params if changed
  useEffect(() => {
    if (initialInv) setInvoiceNumber(initialInv);
    if (initialCode) setClaimCode(initialCode);
  }, [initialInv, initialCode]);

  const handleClaim = async (e) => {
    if (e) e.preventDefault();
    const invNum = invoiceNumber.trim().toUpperCase();
    const code = claimCode.trim().toUpperCase();

    if (!invNum) return toast.error("Nomor invoice wajib diisi.");
    if (!code) return toast.error("Kode klaim wajib diisi.");

    if (!customer) {
      toast.info("Silakan masuk atau daftar terlebih dahulu untuk mengklaim invoice.");
      const currentQuery = `?invoice=${encodeURIComponent(invNum)}&code=${encodeURIComponent(code)}`;
      navigate(`/akun?returnUrl=${encodeURIComponent("/klaim-invoice" + currentQuery)}`);
      return;
    }

    setLoading(true);
    try {
      const res = await api.post("/customer/invoices/claim", {
        invoice_number: invNum,
        claim_code: code,
      });

      const invData = res.data?.invoice || res.data;
      setClaimedInvoice(invData);
      toast.success("Invoice berhasil diverifikasi dan terhubung ke akun Anda!");
    } catch (err) {
      const errMsg = formatApiError(err.response?.data?.detail) || "Gagal mengklaim invoice.";
      toast.error(errMsg);
    } finally {
      setLoading(false);
    }
  };

  const proceedToCheckout = (inv) => {
    const targetInv = inv || claimedInvoice;
    if (!targetInv) return;

    // Check if cart has regular items
    if (items.length > 0 && !isInvoiceCart) {
      setConfirmReplaceModal(true);
      return;
    }

    loadInvoiceBundle(targetInv);
    navigate("/checkout");
  };

  const proceedToCart = (inv) => {
    const targetInv = inv || claimedInvoice;
    if (!targetInv) return;

    if (items.length > 0 && !isInvoiceCart) {
      setConfirmReplaceModal(true);
      return;
    }

    loadInvoiceBundle(targetInv);
    navigate("/keranjang");
  };

  const handleConfirmReplace = (destination) => {
    setConfirmReplaceModal(false);
    if (claimedInvoice) {
      loadInvoiceBundle(claimedInvoice);
      navigate(destination === "cart" ? "/keranjang" : "/checkout");
    }
  };

  return (
    <div className="mx-auto max-w-3xl px-4 py-10 sm:px-6">
      {/* Header */}
      <div className="text-center">
        <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-[#EFE6D5] text-[#8B5A2B]">
          <FileText size={28} />
        </div>
        <h1 className="mt-3 font-heading text-2xl sm:text-3xl font-bold text-[#2C1E16]">
          Klaim Invoice Pesanan
        </h1>
        <p className="mt-1.5 text-xs sm:text-sm text-[#8B7355] max-w-md mx-auto">
          Hubungkan penawaran atau invoice khusus dari admin ke akun Anda untuk menyelesaikan pemesanan mandiri.
        </p>
      </div>

      {/* Guest Notice */}
      {customerChecked && !customer && (
        <div className="mt-6 rounded-2xl border border-blue-200 bg-blue-50/80 p-4 sm:p-5 text-sm text-blue-900 shadow-xs flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div className="flex items-start gap-3">
            <LogIn className="h-5 w-5 text-blue-600 shrink-0 mt-0.5" />
            <div>
              <div className="font-semibold text-blue-950">Masuk / Daftar Akun Diperlukan</div>
              <p className="text-xs text-blue-800 mt-0.5">
                Invoice akan otomatis tertaut ke riwayat akun Anda agar aman dan dapat dilacak kapan saja.
              </p>
            </div>
          </div>
          <Button
            size="sm"
            onClick={() => {
              const currentQuery = invoiceNumber
                ? `?invoice=${encodeURIComponent(invoiceNumber)}&code=${encodeURIComponent(claimCode)}`
                : "";
              navigate(`/akun?returnUrl=${encodeURIComponent("/klaim-invoice" + currentQuery)}`);
            }}
            className="rounded-xl bg-blue-700 hover:bg-blue-800 text-xs text-white shrink-0 font-semibold"
          >
            Masuk / Daftar
          </Button>
        </div>
      )}

      {/* Form Card */}
      {!claimedInvoice && (
        <div className="mt-6 rounded-2xl border border-[#E5DCC5] bg-white p-5 sm:p-8 shadow-sm">
          <form onSubmit={handleClaim} className="space-y-4">
            <div>
              <Label className="block text-xs font-semibold text-[#2C1E16] mb-1.5">
                Nomor Invoice <span className="text-red-500">*</span>
              </Label>
              <div className="relative">
                <FileText size={16} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-[#8B7355]" />
                <Input
                  value={invoiceNumber}
                  onChange={(e) => setInvoiceNumber(e.target.value.toUpperCase())}
                  placeholder="Contoh: INV-2026-0001"
                  className="h-12 pl-10 font-mono text-sm tracking-wide bg-[#FAF5EE]/50 uppercase"
                  required
                />
              </div>
              <p className="mt-1 text-[11px] text-[#8B7355]">
                Dapat dilihat pada pesan WhatsApp penawaran atau file invoice PDF Anda.
              </p>
            </div>

            <div>
              <Label className="block text-xs font-semibold text-[#2C1E16] mb-1.5">
                Kode Klaim (8 Karakter) <span className="text-red-500">*</span>
              </Label>
              <div className="relative">
                <KeyRound size={16} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-[#8B7355]" />
                <Input
                  value={claimCode}
                  onChange={(e) => setClaimCode(e.target.value.toUpperCase())}
                  placeholder="Contoh: 7K9MX2QP"
                  maxLength={8}
                  className="h-12 pl-10 font-mono text-sm tracking-widest bg-[#FAF5EE]/50 uppercase font-bold"
                  required
                />
              </div>
              <p className="mt-1 text-[11px] text-[#8B7355]">
                Kode rahasia 8 karakter unik yang diberikan admin bersama link penawaran.
              </p>
            </div>

            <Button
              type="submit"
              disabled={loading}
              className="mt-2 h-12 w-full rounded-full bg-[#8B5A2B] hover:bg-[#6B4423] text-sm font-semibold text-white shadow-sm"
            >
              {loading ? "Memverifikasi..." : "Verifikasi & Klaim Invoice"}
            </Button>
          </form>

          <div className="mt-6 border-t border-[#F1EBE0] pt-4 text-center">
            <p className="text-xs text-[#8B7355]">
              Sudah pernah mengklaim invoice ini sebelumnya?{" "}
              <Link to="/akun" className="text-[#8B5A2B] font-semibold hover:underline">
                Buka menu Invoice Saya di Akun
              </Link>
            </p>
          </div>
        </div>
      )}

      {/* Claimed Invoice Preview Card */}
      {claimedInvoice && (
        <div className="mt-6 rounded-2xl border border-emerald-300 bg-white p-5 sm:p-7 shadow-sm space-y-5 animate-in fade-in duration-300">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-[#F1EBE0] pb-4">
            <div>
              <div className="flex items-center gap-2">
                <CheckCircle2 className="h-5 w-5 text-emerald-600" />
                <h2 className="font-heading text-xl font-bold text-[#2C1E16]">
                  Invoice #{claimedInvoice.invoice_number}
                </h2>
              </div>
              <p className="text-xs text-[#8B7355] mt-0.5">
                Status: <span className="font-semibold text-emerald-800">Sudah Diklaim & Siap Dipesan</span>
              </p>
            </div>
            <Badge className="bg-emerald-100 text-emerald-800 border-emerald-300 text-xs px-3 py-1 self-start sm:self-auto">
              Siap Checkout
            </Badge>
          </div>

          {/* Items Summary Table */}
          <div>
            <h3 className="font-heading text-xs font-bold uppercase tracking-wider text-[#8B7355] mb-2.5">
              Rincian Item Invoice
            </h3>
            <div className="rounded-xl border border-[#E5DCC5] overflow-hidden">
              <table className="w-full text-left text-xs">
                <thead className="bg-[#FAF5EE] text-[#5C4A3D] font-semibold border-b border-[#E5DCC5]">
                  <tr>
                    <th className="p-3">Item</th>
                    <th className="p-3 text-center w-16">Qty</th>
                    <th className="p-3 text-right">Harga</th>
                    <th className="p-3 text-right">Total</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#F1EBE0]">
                  {(claimedInvoice.items || []).map((it, idx) => {
                    const customDims = it.dimensions;
                    const dimsStr = customDims?.length && customDims?.width && customDims?.height
                      ? `${customDims.length} × ${customDims.width} × ${customDims.height} cm`
                      : null;

                    return (
                      <tr key={idx} className="hover:bg-[#FAF5EE]/30">
                        <td className="p-3">
                          <div className="font-semibold text-[#2C1E16]">{it.name}</div>
                          {it.description && <div className="text-[11px] text-[#8B7355] mt-0.5">{it.description}</div>}
                          {dimsStr && <div className="text-[11px] text-[#8B7355] font-mono">{dimsStr}</div>}
                          {it.material && <div className="text-[11px] text-[#8B7355]">Bahan: {it.material}</div>}
                        </td>
                        <td className="p-3 text-center font-medium">{it.quantity}</td>
                        <td className="p-3 text-right font-mono text-[#5C4A3D]">{fmtLE(it.unit_price)} LE</td>
                        <td className="p-3 text-right font-mono font-semibold text-[#2C1E16]">{fmtLE(it.line_total)} LE</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>

          {/* Pricing Totals */}
          <div className="rounded-xl bg-[#FAF5EE] p-4 text-xs space-y-2">
            <div className="flex justify-between text-[#5C4A3D]">
              <span>Subtotal Produk:</span>
              <span className="font-semibold font-mono">{fmtLE(claimedInvoice.subtotal)} LE</span>
            </div>
            {Number(claimedInvoice.discount_amount) > 0 && (
              <div className="flex justify-between text-green-700 font-medium">
                <span>Diskon Khusus Invoice:</span>
                <span className="font-semibold font-mono">-{fmtLE(claimedInvoice.discount_amount)} LE</span>
              </div>
            )}
            {Number(claimedInvoice.additional_fee) > 0 && (
              <div className="flex justify-between text-[#5C4A3D]">
                <span>Biaya Tambahan:</span>
                <span className="font-semibold font-mono">+{fmtLE(claimedInvoice.additional_fee)} LE</span>
              </div>
            )}
            <div className="border-t border-[#E5DCC5] pt-2 flex justify-between items-center text-sm font-bold text-[#2C1E16]">
              <span>Total Estimasi Invoice:</span>
              <span className="font-heading text-lg text-[#8B5A2B]">{fmtLE(claimedInvoice.total)} LE</span>
            </div>
            <p className="text-[11px] text-[#8B7355] pt-1">
              * Biaya pengiriman akan dihitung otomatis sesuai zona alamat yang Anda pilih di Checkout.
            </p>
          </div>

          {/* CTA Actions */}
          <div className="flex flex-col sm:flex-row gap-2.5 pt-2">
            <Button
              onClick={() => proceedToCheckout()}
              className="h-12 flex-1 rounded-full bg-[#8B5A2B] hover:bg-[#6B4423] text-sm font-semibold text-white shadow-sm flex items-center justify-center gap-2"
            >
              <span>Lanjutkan ke Pesanan</span>
              <ArrowRight size={16} />
            </Button>
            <Button
              variant="outline"
              onClick={() => proceedToCart()}
              className="h-12 rounded-full border-[#8B5A2B] text-[#8B5A2B] text-sm font-medium hover:bg-[#FAF5EE]"
            >
              <ShoppingCart size={16} className="mr-1.5" /> Lihat di Keranjang
            </Button>
          </div>
        </div>
      )}

      {/* Confirmation Modal if Cart contains regular items */}
      {confirmReplaceModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-xs p-4">
          <div className="w-full max-w-md rounded-2xl bg-white p-6 shadow-xl space-y-4">
            <div className="flex items-center gap-3 text-amber-700">
              <AlertCircle size={24} />
              <h3 className="font-heading text-lg font-bold text-[#2C1E16]">Ganti Isi Keranjang?</h3>
            </div>
            <p className="text-xs text-[#5C4A3D] leading-relaxed">
              Keranjang belanja Anda saat ini berisi produk lain. Memproses paket invoice ini akan menggantikan item keranjang Anda dengan item invoice <strong>#{claimedInvoice?.invoice_number}</strong>.
            </p>
            <div className="flex gap-2 justify-end pt-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => setConfirmReplaceModal(false)}
                className="rounded-xl border-[#E5DCC5] text-xs"
              >
                Batal
              </Button>
              <Button
                size="sm"
                onClick={() => handleConfirmReplace("checkout")}
                className="rounded-xl bg-[#8B5A2B] hover:bg-[#6B4423] text-xs text-white"
              >
                Lanjutkan Ganti & Checkout
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
