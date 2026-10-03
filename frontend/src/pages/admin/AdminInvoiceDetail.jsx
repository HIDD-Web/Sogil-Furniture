import React, { useEffect, useState } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import api from "../../lib/api";
import { fmtLE, formatApiError } from "../../lib/format";
import { INVOICE_STATUS } from "../../lib/constants";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Textarea } from "../../components/ui/textarea";
import { Label } from "../../components/ui/label";
import {
  ChevronLeft,
  Printer,
  Pencil,
  Send,
  CheckCircle,
  Ban,
  Trash2,
  Phone,
  MapPin,
  Lock,
  MessageCircle,
  ExternalLink,
  Layers,
  Sparkles,
  ShoppingBag,
  X,
  AlertTriangle,
  KeyRound,
  Copy,
} from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../context/AuthContext";
import PermanentDeleteModal from "../../components/admin/PermanentDeleteModal";

export default function AdminInvoiceDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { user } = useAuth();
  const canDelete = user?.role === "owner" || user?.permissions?.delete_data;

  const [invoice, setInvoice] = useState(null);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState(false);
  const [deleteModalOpen, setDeleteModalOpen] = useState(false);
  const [deleteLoading, setDeleteLoading] = useState(false);

  // Conversion Modal State
  const [convertModalOpen, setConvertModalOpen] = useState(false);
  const [convertSubmitting, setConvertSubmitting] = useState(false);
  const [convertedOrderResult, setConvertedOrderResult] = useState(null);
  const [deliveryZones, setDeliveryZones] = useState([]);
  const [convertForm, setConvertForm] = useState({
    delivery_method: "pickup",
    delivery_zone_id: "",
    payment_method: "transfer",
    customer_address: "",
    customer_maps_url: "",
    notes: "",
  });

  // Claim Code Modal State
  const [claimCodeModalOpen, setClaimCodeModalOpen] = useState(false);
  const [claimCodeResult, setClaimCodeResult] = useState(null);
  const [claimCodeLoading, setClaimCodeLoading] = useState(false);

  const handleGenerateClaimCode = async () => {
    if (!window.confirm("Buat kode klaim baru untuk invoice ini? Kode klaim sebelumnya (jika ada) akan kedaluwarsa.")) {
      return;
    }
    setClaimCodeLoading(true);
    try {
      const { data } = await api.post(`/admin/invoices/${id}/claim-code`);
      setClaimCodeResult(data);
      setClaimCodeModalOpen(true);
      toast.success("Kode klaim baru berhasil dibuat!");
      loadInvoice();
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail) || "Gagal membuat kode klaim");
    } finally {
      setClaimCodeLoading(false);
    }
  };

  const loadInvoice = () => {
    setLoading(true);
    api.get(`/admin/invoices/${id}`)
      .then((r) => {
        setInvoice(r.data);
        setConvertForm((prev) => ({
          ...prev,
          customer_address: r.data.customer?.address || "",
        }));
      })
      .catch((err) => {
        toast.error(err.response?.data?.detail || "Gagal memuat invoice");
        navigate("/admin/invoices");
      })
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    loadInvoice();
    api.get("/delivery-zones")
      .then((r) => setDeliveryZones(Array.isArray(r.data) ? r.data : []))
      .catch(() => {});
  }, [id]);

  const handleSend = async () => {
    if (!window.confirm("Invoice akan ditandai sebagai invoice yang sudah siap diberikan kepada customer. Lanjutkan?")) {
      return;
    }
    setActionLoading(true);
    try {
      const { data } = await api.post(`/admin/invoices/${id}/send`);
      setInvoice(data);
      toast.success("Invoice ditandai Menunggu Konfirmasi");
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail) || "Gagal memperbarui status invoice");
    } finally {
      setActionLoading(false);
    }
  };

  const handleCancel = async () => {
    if (!window.confirm("Batalkan invoice ini? Invoice yang dibatalkan tidak dapat dikonversi menjadi pesanan.")) {
      return;
    }
    setActionLoading(true);
    try {
      const { data } = await api.post(`/admin/invoices/${id}/cancel`);
      setInvoice(data);
      toast.success("Invoice berhasil dibatalkan");
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail) || "Gagal membatalkan invoice");
    } finally {
      setActionLoading(false);
    }
  };

  const handlePermanentDelete = async (reason) => {
    setDeleteLoading(true);
    try {
      const targetId = invoice?.id || invoice?._id || id;
      await api.post(`/admin/invoices/${targetId}/permanent-delete`, {
        confirmation_phrase: "HAPUS PERMANEN",
        reason: reason || undefined,
      });
      toast.success("Invoice berhasil dihapus secara permanen");
      setDeleteModalOpen(false);
      navigate("/admin/invoices");
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail) || "Gagal menghapus invoice");
    } finally {
      setDeleteLoading(false);
    }
  };

  const handleConvertSubmit = async (e) => {
    e.preventDefault();
    setConvertSubmitting(true);
    try {
      const payload = {
        delivery_method: convertForm.delivery_method,
        delivery_zone_id: convertForm.delivery_zone_id || null,
        payment_method: convertForm.payment_method,
        customer_address: convertForm.customer_address?.trim() || null,
        customer_maps_url: convertForm.customer_maps_url?.trim() || null,
        notes: convertForm.notes?.trim() || null,
      };

      const { data } = await api.post(`/admin/invoices/${id}/convert`, payload);
      setConvertedOrderResult(data.order);
      setInvoice(data.invoice);
      toast.success(data.message || "Invoice berhasil dikonversi ke pesanan!");
    } catch (err) {
      const msg = formatApiError(err.response?.data?.detail);
      toast.error(msg || "Gagal mengonversi invoice");
      // If backend says already converted, refresh invoice to show existing order
      loadInvoice();
    } finally {
      setConvertSubmitting(false);
    }
  };

  if (loading || !invoice) {
    return <div className="py-16 text-center text-sm text-[#8B7355]">Memuat detail invoice...</div>;
  }

  const statusCfg = INVOICE_STATUS[invoice.status] || INVOICE_STATUS.DRAFT;
  const isDraft = invoice.status === "DRAFT";
  const isSent = invoice.status === "SENT";
  const isClaimed = invoice.status === "CLAIMED";
  const isConverted = invoice.status === "CONVERTED" || Boolean(invoice.order_id);
  const isCancelled = invoice.status === "CANCELLED";

  const waRaw = (invoice.customer?.whatsapp || "").replace(/[^0-9]/g, "");
  const waLink = waRaw ? `https://wa.me/${waRaw}` : null;

  return (
    <div className="max-w-4xl mx-auto space-y-6 pb-12">
      {/* Top Bar */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[#E5DCC5] pb-4">
        <div className="flex items-center gap-3">
          <Button
            variant="outline"
            size="sm"
            onClick={() => navigate("/admin/invoices")}
            className="h-8 rounded-lg border-[#E5DCC5] text-xs text-[#5C4A3D]"
          >
            <ChevronLeft size={15} className="mr-1" /> Semua Invoice
          </Button>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="font-heading font-mono text-xl sm:text-2xl font-bold text-[#8B5A2B]">
                {invoice.invoice_number}
              </h1>
              <Badge variant="outline" className={`px-2.5 py-0.5 text-xs ${statusCfg.color}`}>
                {statusCfg.label}
              </Badge>
            </div>
            <p className="text-xs text-[#8B7355]">
              Dibuat {new Date(invoice.created_at).toLocaleDateString("id-ID", {
                day: "numeric",
                month: "long",
                year: "numeric",
              })} oleh {invoice.created_by || "Admin"}
            </p>
          </div>
        </div>

        {/* Action Buttons */}
        <div className="flex flex-wrap items-center gap-2">
          {/* Print is always available */}
          <Button
            variant="outline"
            size="sm"
            onClick={() => navigate(`/admin/invoices/${id}/print`)}
            className="rounded-xl border-[#8B5A2B]/40 text-[#8B5A2B] text-xs font-semibold hover:bg-[#FAF5EE]"
          >
            <Printer size={14} className="mr-1.5" /> Cetak Invoice
          </Button>

          {/* DRAFT Actions */}
          {isDraft && (
            <>
              <Button
                variant="outline"
                size="sm"
                onClick={() => navigate(`/admin/invoices/${id}/edit`)}
                className="rounded-xl border-[#E5DCC5] text-xs font-semibold text-[#5C4A3D]"
              >
                <Pencil size={14} className="mr-1.5" /> Edit
              </Button>
              <Button
                size="sm"
                disabled={actionLoading}
                onClick={handleSend}
                className="rounded-xl bg-blue-700 hover:bg-blue-800 text-xs font-semibold text-white"
              >
                <Send size={14} className="mr-1.5" /> Tandai Menunggu Konfirmasi
              </Button>
            </>
          )}

          {/* SENT Actions */}
          {isSent && (
            <>
              <Button
                variant="outline"
                size="sm"
                onClick={() => navigate(`/admin/invoices/${id}/edit`)}
                className="rounded-xl border-[#E5DCC5] text-xs font-semibold text-[#5C4A3D]"
              >
                <Pencil size={14} className="mr-1.5" /> Edit
              </Button>
              <Button
                variant="outline"
                size="sm"
                disabled={claimCodeLoading}
                onClick={handleGenerateClaimCode}
                className="rounded-xl border-[#8B5A2B] text-xs font-semibold text-[#8B5A2B] hover:bg-[#FAF5EE]"
              >
                <KeyRound size={14} className="mr-1.5" /> Buat Kode Klaim
              </Button>
              <Button
                size="sm"
                disabled={actionLoading}
                onClick={() => setConvertModalOpen(true)}
                className="rounded-xl bg-[#8B5A2B] hover:bg-[#6B4423] text-xs font-semibold text-white shadow-xs"
              >
                <CheckCircle size={14} className="mr-1.5" /> Konversi ke Pesanan
              </Button>
              <Button
                variant="outline"
                size="sm"
                disabled={actionLoading}
                onClick={handleCancel}
                className="rounded-xl border-red-200 text-xs text-red-600 hover:bg-red-50"
              >
                <Ban size={14} className="mr-1.5" /> Batalkan
              </Button>
            </>
          )}

          {/* CLAIMED Actions */}
          {isClaimed && (
            <>
              <Button
                variant="outline"
                size="sm"
                onClick={() => navigate(`/admin/invoices/${id}/edit`)}
                className="rounded-xl border-[#E5DCC5] text-xs font-semibold text-[#5C4A3D]"
              >
                <Pencil size={14} className="mr-1.5" /> Edit
              </Button>
              <Button
                variant="outline"
                size="sm"
                disabled={claimCodeLoading}
                onClick={handleGenerateClaimCode}
                className="rounded-xl border-[#8B5A2B] text-xs font-semibold text-[#8B5A2B] hover:bg-[#FAF5EE]"
              >
                <KeyRound size={14} className="mr-1.5" /> Buat Kode Klaim Baru
              </Button>
              <Button
                size="sm"
                disabled={actionLoading}
                onClick={() => setConvertModalOpen(true)}
                className="rounded-xl bg-[#8B5A2B] hover:bg-[#6B4423] text-xs font-semibold text-white shadow-xs"
              >
                <CheckCircle size={14} className="mr-1.5" /> Konversi ke Pesanan
              </Button>
              <Button
                variant="outline"
                size="sm"
                disabled={actionLoading}
                onClick={handleCancel}
                className="rounded-xl border-red-200 text-xs text-red-600 hover:bg-red-50"
              >
                <Ban size={14} className="mr-1.5" /> Batalkan
              </Button>
            </>
          )}

          {/* CONVERTED Actions */}
          {isConverted && invoice.order_id && (
            <Button
              size="sm"
              onClick={async () => {
                try {
                  await api.get(`/admin/orders/${invoice.order_id}`);
                  navigate(`/admin/orders/${invoice.order_id}`);
                } catch {
                  toast.error(`Pesanan ${invoice.order_number || ""} telah dihapus secara permanen`);
                }
              }}
              className="rounded-xl bg-purple-700 hover:bg-purple-800 text-xs font-semibold text-white shadow-xs"
            >
              <ShoppingBag size={14} className="mr-1.5" /> Lihat Pesanan ({invoice.order_number})
            </Button>
          )}
        </div>
      </div>

      {/* Converted Order Banner */}
      {isConverted && (
        <div className="rounded-2xl border border-emerald-200 bg-emerald-50/70 p-4 sm:p-5 flex flex-col sm:flex-row sm:items-center justify-between gap-3 shadow-xs">
          <div className="flex items-start gap-3">
            <CheckCircle className="h-5 w-5 text-emerald-600 shrink-0 mt-0.5" />
            <div>
              <div className="font-semibold text-sm text-emerald-900">
                Invoice Ini Sudah Dikonversi Menjadi Pesanan Resmi
              </div>
              <p className="text-xs text-emerald-700 mt-0.5">
                Nomor Pesanan: <strong className="font-mono">{invoice.order_number}</strong>
                {invoice.converted_at && ` · Dikonversi pada ${new Date(invoice.converted_at).toLocaleDateString("id-ID")}`}
              </p>
            </div>
          </div>
          {invoice.order_id && (
            <Button
              size="sm"
              onClick={async () => {
                try {
                  await api.get(`/admin/orders/${invoice.order_id}`);
                  navigate(`/admin/orders/${invoice.order_id}`);
                } catch {
                  toast.error(`Pesanan ${invoice.order_number || ""} telah dihapus secara permanen`);
                }
              }}
              className="rounded-xl bg-emerald-700 hover:bg-emerald-800 text-xs text-white shrink-0"
            >
              Buka Pesanan <ExternalLink size={12} className="ml-1" />
            </Button>
          )}
        </div>
      )}

      {/* Claimed Banner */}
      {isClaimed && (
        <div className="rounded-2xl border border-amber-300 bg-amber-50/80 p-4 sm:p-5 flex flex-col sm:flex-row sm:items-center justify-between gap-3 shadow-xs">
          <div className="flex items-start gap-3">
            <Lock className="h-5 w-5 text-amber-700 shrink-0 mt-0.5" />
            <div>
              <div className="font-semibold text-sm text-amber-950">
                Invoice Ini Sudah Diklaim oleh Pelanggan
              </div>
              <p className="text-xs text-amber-800 mt-0.5">
                Terkoneksi ke Akun ID: <strong className="font-mono">{invoice.claim?.claimed_by_customer_id || invoice.customer?.customer_id}</strong>
                {invoice.claim?.claimed_at && ` · Diklaim pada ${new Date(invoice.claim.claimed_at).toLocaleString("id-ID")}`}
              </p>
              <p className="text-[11px] text-amber-700 mt-0.5">
                Item invoice terkunci untuk proses checkout mandiri pelanggan via website. Anda tetap dapat menekan "Konversi ke Pesanan" jika customer meminta bantuan admin.
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Custom Request Linked Banner */}
      {invoice.source?.custom_request_id && (
        <div className="rounded-2xl border border-[#8B5A2B]/20 bg-[#FAF5EE] p-3.5 flex items-center justify-between text-xs">
          <div className="flex items-center gap-2">
            <Sparkles size={16} className="text-[#8B5A2B]" />
            <span className="text-[#5C4A3D]">
              Dibuat dari <strong>Request Custom #{invoice.source.custom_request_id}</strong>
            </span>
          </div>
          <Link
            to="/admin/custom-requests"
            className="text-[#8B5A2B] font-semibold hover:underline flex items-center gap-1"
          >
            Lihat Request <ExternalLink size={12} />
          </Link>
        </div>
      )}

      {/* Grid: Customer Info & Summary */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        {/* Customer Snapshot */}
        <div className="md:col-span-2 rounded-2xl border border-[#E5DCC5] bg-white p-5 shadow-xs space-y-3">
          <h2 className="font-heading text-sm font-bold uppercase tracking-wide text-[#8B5A2B] border-b border-[#F1EBE0] pb-2">
            Customer Snapshot
          </h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
            <div>
              <span className="text-[#8B7355]">Nama Pelanggan:</span>
              <p className="font-semibold text-sm text-[#2C1E16] mt-0.5">
                {invoice.customer?.name || "-"}
              </p>
            </div>

            <div>
              <span className="text-[#8B7355]">WhatsApp:</span>
              <div className="flex items-center gap-2 mt-0.5">
                <span className="font-mono font-medium text-[#2C1E16]">
                  {invoice.customer?.whatsapp || "-"}
                </span>
                {waLink && (
                  <a
                    href={waLink}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center gap-1 rounded-md bg-green-100 px-2 py-0.5 text-[11px] font-semibold text-green-800 hover:bg-green-200"
                  >
                    <MessageCircle size={11} /> Chat WA
                  </a>
                )}
              </div>
            </div>

            {invoice.customer?.egypt_phone && (
              <div>
                <span className="text-[#8B7355]">Nomor Telepon Mesir:</span>
                <p className="font-mono text-[#2C1E16] mt-0.5">
                  {invoice.customer.egypt_phone}
                </p>
              </div>
            )}

            <div className="sm:col-span-2">
              <span className="text-[#8B7355]">Alamat Pengiriman:</span>
              <p className="text-[#2C1E16] mt-0.5">
                {invoice.customer?.address || "-"}
              </p>
            </div>
          </div>
        </div>

        {/* Financial Totals Card */}
        <div className="rounded-2xl border border-[#E5DCC5] bg-[#FAF8F5] p-5 shadow-xs space-y-3">
          <h2 className="font-heading text-sm font-bold uppercase tracking-wide text-[#8B5A2B] border-b border-[#E5DCC5]/60 pb-2">
            Rincian Harga
          </h2>
          <div className="space-y-1.5 text-xs">
            <div className="flex justify-between text-[#5C4A3D]">
              <span>Subtotal</span>
              <span className="font-semibold">{fmtLE(invoice.subtotal)} LE</span>
            </div>
            {invoice.discount_amount > 0 && (
              <div className="flex justify-between text-red-600">
                <span>Diskon</span>
                <span>-{fmtLE(invoice.discount_amount)} LE</span>
              </div>
            )}
            {invoice.delivery_fee > 0 && (
              <div className="flex justify-between text-[#5C4A3D]">
                <span>Ongkir</span>
                <span>+{fmtLE(invoice.delivery_fee)} LE</span>
              </div>
            )}
            {invoice.additional_fee > 0 && (
              <div className="flex justify-between text-[#5C4A3D]">
                <span>Biaya Tambahan</span>
                <span>+{fmtLE(invoice.additional_fee)} LE</span>
              </div>
            )}
            <div className="border-t border-[#E5DCC5] pt-2 flex justify-between items-baseline">
              <span className="font-heading font-bold text-sm text-[#2C1E16]">TOTAL</span>
              <span className="font-heading font-bold text-lg text-[#8B5A2B]">
                {fmtLE(invoice.total)} LE
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* Items List */}
      <div className="rounded-2xl border border-[#E5DCC5] bg-white p-5 sm:p-6 shadow-xs space-y-4">
        <div className="flex items-center justify-between border-b border-[#F1EBE0] pb-3">
          <h2 className="font-heading text-base font-bold text-[#2C1E16]">
            Daftar Item ({invoice.items?.length || 0})
          </h2>
          <span className="text-xs text-[#8B7355]">
            Mata Uang: <strong>EGP (LE)</strong>
          </span>
        </div>

        <div className="divide-y divide-[#F1EBE0]">
          {(invoice.items || []).map((it, idx) => {
            const dims = it.dimensions || {};
            const dimsArr = [
              dims.length && `P: ${dims.length} cm`,
              dims.width && `L: ${dims.width} cm`,
              dims.height && `T: ${dims.height} cm`,
              dims.notes,
            ].filter(Boolean);

            return (
              <div key={it.item_id || idx} className="py-4 first:pt-0 last:pb-0 space-y-2">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="font-bold text-sm text-[#2C1E16]">{it.name}</span>
                      <span
                        className={`rounded-full px-2 py-0.5 text-[10px] font-semibold border ${
                          it.item_type === "catalog"
                            ? "bg-purple-100 text-purple-800 border-purple-200"
                            : "bg-amber-100 text-amber-800 border-amber-200"
                        }`}
                      >
                        {it.item_type === "catalog" ? "Produk Katalog" : "Custom Order"}
                      </span>
                    </div>
                    {it.description && (
                      <p className="text-xs text-[#5C4A3D] mt-0.5">{it.description}</p>
                    )}
                  </div>
                  <div className="text-right">
                    <span className="font-heading font-bold text-sm text-[#8B5A2B]">
                      {fmtLE(it.line_total)} LE
                    </span>
                    <p className="text-[11px] text-[#8B7355]">
                      {it.quantity} × {fmtLE(it.unit_price)} LE
                    </p>
                  </div>
                </div>

                {/* Specs Pill Badges */}
                <div className="flex flex-wrap gap-1.5 text-[11px] text-[#5C4A3D]">
                  {dimsArr.length > 0 && (
                    <span className="rounded-lg bg-[#FAF5EE] px-2 py-0.5 border border-[#E5DCC5]/70">
                      Dimensi: {dimsArr.join(" · ")}
                    </span>
                  )}
                  {it.material && (
                    <span className="rounded-lg bg-[#FAF5EE] px-2 py-0.5 border border-[#E5DCC5]/70">
                      Material: {it.material}
                    </span>
                  )}
                  {it.finishing && (
                    <span className="rounded-lg bg-[#FAF5EE] px-2 py-0.5 border border-[#E5DCC5]/70">
                      Finishing: {it.finishing}
                    </span>
                  )}
                  {it.notes && (
                    <span className="rounded-lg bg-amber-50 px-2 py-0.5 border border-amber-200 text-amber-800">
                      Catatan: {it.notes}
                    </span>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Notes Section */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        {/* Customer Note */}
        <div className="rounded-2xl border border-[#E5DCC5] bg-white p-4 shadow-xs space-y-1.5">
          <span className="text-xs font-semibold text-[#8B5A2B] uppercase tracking-wide">
            Catatan untuk Customer
          </span>
          <p className="text-xs text-[#2C1E16] whitespace-pre-wrap">
            {invoice.customer_note || "Tidak ada catatan khusus."}
          </p>
          <span className="text-[10px] text-[#8B7355]">
            * Tampil di cetakan invoice/PDF untuk pelanggan.
          </span>
        </div>

        {/* Internal Note */}
        <div className="rounded-2xl border border-amber-200 bg-amber-50/40 p-4 shadow-xs space-y-1.5">
          <div className="flex items-center gap-1.5 text-xs font-semibold text-amber-900 uppercase tracking-wide">
            <Lock size={12} />
            <span>Catatan Internal Admin</span>
          </div>
          <p className="text-xs text-amber-900 whitespace-pre-wrap">
            {invoice.internal_note || "Tidak ada catatan internal."}
          </p>
          <span className="text-[10px] text-amber-700">
            * Khusus tim Sogil. Dijamin TIDAK tampil di cetakan pelanggan.
          </span>
        </div>
      </div>

      {/* Conversion Modal */}
      {convertModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div className="w-full max-w-lg rounded-3xl border border-[#E5DCC5] bg-white p-5 sm:p-7 shadow-2xl space-y-4">
            <div className="flex items-start justify-between border-b border-[#F1EBE0] pb-3">
              <div>
                <h3 className="font-heading text-lg font-bold text-[#2C1E16]">
                  Konfirmasi & Masukkan ke Pesanan
                </h3>
                <p className="text-xs text-[#8B7355]">
                  Invoice {invoice.invoice_number} · Total {fmtLE(invoice.total)} LE
                </p>
              </div>
              <button
                onClick={() => setConvertModalOpen(false)}
                className="rounded-lg p-1 text-[#8B7355] hover:bg-[#F1EBE0]"
              >
                <X size={18} />
              </button>
            </div>

            {convertedOrderResult ? (
              <div className="space-y-4 py-2">
                <div className="rounded-2xl border border-emerald-200 bg-emerald-50 p-4 text-center space-y-2">
                  <CheckCircle className="h-8 w-8 text-emerald-600 mx-auto" />
                  <div className="font-heading text-base font-bold text-emerald-900">
                    Pesanan Berhasil Dibuat!
                  </div>
                  <div className="font-mono text-lg font-bold text-purple-800">
                    {convertedOrderResult.order_number}
                  </div>
                  <p className="text-xs text-emerald-700">
                    Invoice sekarang terhubung langsung dengan pesanan produksi.
                  </p>
                </div>
                <div className="flex justify-end gap-2 pt-2">
                  <Button
                    variant="outline"
                    onClick={() => {
                      setConvertModalOpen(false);
                      setConvertedOrderResult(null);
                    }}
                    className="rounded-xl border-[#E5DCC5] text-xs"
                  >
                    Tutup
                  </Button>
                  <Button
                    onClick={() => navigate(`/admin/orders/${convertedOrderResult.id || convertedOrderResult._id}`)}
                    className="rounded-xl bg-purple-700 text-xs font-semibold text-white hover:bg-purple-800"
                  >
                    Buka Halaman Pesanan &rarr;
                  </Button>
                </div>
              </div>
            ) : (
              <form onSubmit={handleConvertSubmit} className="space-y-4">
                <div className="rounded-xl bg-[#FAF5EE] p-3 text-xs text-[#5C4A3D] space-y-1.5 border border-[#E5DCC5]">
                  <p className="font-medium text-[#2C1E16]">
                    Invoice ini akan dikonversi menjadi pesanan produksi.
                  </p>
                  <p className="text-[11px] text-[#8B7355]">
                    Sistem akan membuat nomor pesanan baru (format SGF-YYYYMMDD-XXX) dan data invoice akan terhubung dengan pesanan tersebut.
                  </p>
                  <div className="pt-1 font-mono text-[11px] text-[#8B5A2B]">
                    Customer: {invoice.customer?.name} ({invoice.customer?.whatsapp})
                  </div>
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
                  <div>
                    <Label className="text-xs font-semibold text-[#5C4A3D]">Metode Pengiriman</Label>
                    <select
                      value={convertForm.delivery_method}
                      onChange={(e) => setConvertForm({ ...convertForm, delivery_method: e.target.value })}
                      className="mt-1 w-full rounded-xl border border-[#E5DCC5] bg-white px-3 py-2 text-xs"
                    >
                      <option value="pickup">Ambil Sendiri (Pickup)</option>
                      <option value="delivery">Kirim ke Alamat (Delivery)</option>
                    </select>
                  </div>

                  <div>
                    <Label className="text-xs font-semibold text-[#5C4A3D]">Metode Pembayaran</Label>
                    <select
                      value={convertForm.payment_method}
                      onChange={(e) => setConvertForm({ ...convertForm, payment_method: e.target.value })}
                      className="mt-1 w-full rounded-xl border border-[#E5DCC5] bg-white px-3 py-2 text-xs"
                    >
                      <option value="transfer">Transfer Bank</option>
                      <option value="cash">Tunai (Cash)</option>
                    </select>
                  </div>

                  {convertForm.delivery_method === "delivery" && deliveryZones.length > 0 && (
                    <div className="sm:col-span-2">
                      <Label className="text-xs font-semibold text-[#5C4A3D]">Wilayah / Zona Pengiriman</Label>
                      <select
                        value={convertForm.delivery_zone_id}
                        onChange={(e) => setConvertForm({ ...convertForm, delivery_zone_id: e.target.value })}
                        className="mt-1 w-full rounded-xl border border-[#E5DCC5] bg-white px-3 py-2 text-xs"
                      >
                        <option value="">-- Pilih Zona Pengiriman --</option>
                        {deliveryZones.map((z) => (
                          <option key={z.id || z._id} value={z.id || z._id}>
                            {z.name} ({fmtLE(z.fee_le)} LE)
                          </option>
                        ))}
                      </select>
                    </div>
                  )}

                  <div className="sm:col-span-2">
                    <Label className="text-xs font-semibold text-[#5C4A3D]">Alamat Pengiriman</Label>
                    <Input
                      value={convertForm.customer_address}
                      onChange={(e) => setConvertForm({ ...convertForm, customer_address: e.target.value })}
                      placeholder="Alamat lengkap tujuan kirim"
                      className="mt-1 text-xs"
                    />
                  </div>

                  <div className="sm:col-span-2">
                    <Label className="text-xs font-semibold text-[#5C4A3D]">Catatan Tambahan Pesanan</Label>
                    <Textarea
                      value={convertForm.notes}
                      onChange={(e) => setConvertForm({ ...convertForm, notes: e.target.value })}
                      rows={2}
                      placeholder="Catatan pengerjaan atau instruksi pengiriman khusus..."
                      className="mt-1 text-xs"
                    />
                  </div>
                </div>

                <div className="flex items-center justify-end gap-2 border-t border-[#F1EBE0] pt-3">
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => setConvertModalOpen(false)}
                    className="rounded-xl border-[#E5DCC5] text-xs text-[#5C4A3D]"
                  >
                    Batal
                  </Button>
                  <Button
                    type="submit"
                    disabled={convertSubmitting}
                    className="rounded-xl bg-[#8B5A2B] text-xs font-semibold text-white hover:bg-[#6B4423]"
                  >
                    {convertSubmitting ? "Memproses..." : "Konfirmasi & Masukkan ke Pesanan"}
                  </Button>
                </div>
              </form>
            )}
          </div>
        </div>
      )}

      {/* Claim Code Modal */}
      {claimCodeModalOpen && claimCodeResult && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-xs p-4">
          <div className="w-full max-w-lg rounded-2xl bg-white p-6 shadow-xl space-y-4">
            <div className="flex items-center justify-between border-b border-[#F1EBE0] pb-3">
              <div className="flex items-center gap-2">
                <KeyRound size={20} className="text-[#8B5A2B]" />
                <h3 className="font-heading text-lg font-bold text-[#2C1E16]">
                  Kode Klaim Invoice
                </h3>
              </div>
              <button
                onClick={() => setClaimCodeModalOpen(false)}
                className="p-1 rounded-lg text-stone-400 hover:text-stone-700 hover:bg-stone-100"
              >
                <X size={18} />
              </button>
            </div>

            <p className="text-xs text-[#5C4A3D]">
              Berikan kode klaim ini atau bagikan link langsung kepada pelanggan untuk menghubungkan invoice ke akun mereka.
            </p>

            {/* Big Code Box */}
            <div className="rounded-xl border border-amber-300 bg-amber-50 p-4 text-center space-y-1">
              <div className="text-xs font-medium text-amber-800 uppercase tracking-wider">
                Kode Klaim Rahasia
              </div>
              <div className="font-mono text-3xl font-extrabold tracking-widest text-[#8B5A2B]">
                {claimCodeResult.claim_code}
              </div>
              <p className="text-[11px] text-amber-700">
                Hanya ditampilkan sekali. Segera simpan atau bagikan ke pelanggan.
              </p>
            </div>

            {/* Copy Link Section */}
            {(() => {
              const customerBaseUrl = process.env.REACT_APP_CUSTOMER_URL || (window.location.hostname === "team.sogilfurniture.com" ? "https://sogilfurniture.com" : window.location.origin);
              const claimLink = `${customerBaseUrl}/klaim-invoice?invoice=${invoice.invoice_number}&code=${claimCodeResult.claim_code}`;
              const waText = `Halo Kak ${invoice.customer?.name || ""}, berikut invoice penawaran pesanan Anda dari Sogil Furniture:\n\nNomor Invoice: ${invoice.invoice_number}\nKode Klaim: ${claimCodeResult.claim_code}\n\nSilakan klik link berikut untuk mengklaim invoice dan menyelesaikan pesanan:\n${claimLink}\n\nTerima kasih!`;

              return (
                <>
                  <div className="space-y-1.5">
                    <Label className="text-xs font-semibold text-[#2C1E16]">Link Klaim Langsung</Label>
                    <div className="flex gap-2">
                      <Input
                        readOnly
                        value={claimLink}
                        className="h-10 text-xs font-mono bg-stone-50"
                      />
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => {
                          navigator.clipboard.writeText(claimLink);
                          toast.success("Link klaim berhasil disalin!");
                        }}
                        className="rounded-xl border-[#8B5A2B] text-xs text-[#8B5A2B] shrink-0"
                      >
                        <Copy size={13} className="mr-1" /> Salin Link
                      </Button>
                    </div>
                  </div>

                  {/* WhatsApp Message Preview */}
                  <div className="space-y-1.5">
                    <Label className="text-xs font-semibold text-[#2C1E16]">Pesan WhatsApp Siap Kirim</Label>
                    <Textarea
                      readOnly
                      rows={4}
                      value={waText}
                      className="text-xs font-mono bg-stone-50"
                    />
                    <div className="flex justify-end gap-2 pt-1">
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => {
                          navigator.clipboard.writeText(waText);
                          toast.success("Pesan WhatsApp berhasil disalin!");
                        }}
                        className="rounded-xl text-xs"
                      >
                        <Copy size={13} className="mr-1" /> Salin Pesan WA
                      </Button>
                      {invoice.customer?.whatsapp && (
                        <a
                          href={`https://wa.me/${invoice.customer.whatsapp.replace(/\+/g, "")}?text=${encodeURIComponent(waText)}`}
                          target="_blank"
                          rel="noreferrer"
                        >
                          <Button size="sm" className="rounded-xl bg-emerald-600 hover:bg-emerald-700 text-xs text-white">
                            <MessageCircle size={13} className="mr-1" /> Kirim via WhatsApp
                          </Button>
                        </a>
                      )}
                    </div>
                  </div>
                </>
              );
            })()}

            <div className="flex justify-end border-t border-[#F1EBE0] pt-3">
              <Button
                size="sm"
                onClick={() => setClaimCodeModalOpen(false)}
                className="rounded-xl bg-[#8B5A2B] hover:bg-[#6B4423] text-xs text-white"
              >
                Selesai
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Zona Berbahaya (Permanent Delete) */}
      {canDelete && (
        <div className="rounded-2xl border border-red-200 bg-red-50/40 p-5 shadow-xs" data-testid="danger-zone-invoice">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
            <div>
              <h3 className="text-sm font-bold text-red-950 flex items-center gap-2">
                <AlertTriangle className="h-4 w-4 text-red-600 shrink-0" />
                Zona Berbahaya
              </h3>
              <p className="text-xs text-red-700 mt-1">
                Hapus invoice ini secara permanen dari database. Pesanan atau transaksi keuangan terkait TIDAK akan ikut dihapus.
              </p>
            </div>
            <Button
              variant="destructive"
              onClick={() => setDeleteModalOpen(true)}
              data-testid="permanent-delete-invoice-btn"
              className="rounded-xl bg-red-600 hover:bg-red-700 text-white font-semibold text-xs shrink-0"
            >
              <Trash2 size={14} className="mr-1.5" /> Hapus Permanen
            </Button>
          </div>
        </div>
      )}

      {/* Permanent Delete Modal */}
      <PermanentDeleteModal
        open={deleteModalOpen}
        onClose={() => setDeleteModalOpen(false)}
        onConfirm={handlePermanentDelete}
        title="Hapus Invoice Permanen"
        entityType="Invoice"
        entityIdentifier={invoice.invoice_number}
        warningMessages={[
          invoice.status === "CONVERTED"
            ? `Invoice ini telah dikonversi menjadi Pesanan (${invoice.order_number || ""}). Menghapus invoice TIDAK akan menghapus pesanan terkait. Pesanan tetap ada dan dapat diproses normal.`
            : null,
          invoice.status === "CLAIMED"
            ? "Invoice ini telah diklaim oleh pelanggan. Menghapus invoice akan menghapus ketersediaannya untuk checkout."
            : null,
        ].filter(Boolean)}
        loading={deleteLoading}
      />
    </div>
  );
}
