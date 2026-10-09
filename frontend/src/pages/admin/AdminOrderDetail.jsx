import React, { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import api from "../../lib/api";
import { fmtLE, fmtIDR, copyToClipboard } from "../../lib/format";
import { config_summary_client } from "../../lib/summary";
import { ORDER_STATUS, PAYMENT_STATUS } from "../../lib/constants";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Textarea } from "../../components/ui/textarea";
import { Label } from "../../components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../../components/ui/select";
import { ChevronLeft, MapPin, Copy, MessageCircle, Trash2, Pencil, X, Sparkles, Phone, FileText, AlertTriangle, CreditCard, CheckCircle2, History, Wrench, UserCheck, ShieldCheck, CheckSquare } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../context/AuthContext";
import PublishCustomCollectionModal from "../../components/admin/PublishCustomCollectionModal";
import PermanentDeleteModal from "../../components/admin/PermanentDeleteModal";

export default function AdminOrderDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { user } = useAuth();
  const canDelete = user?.role === "owner" || user?.permissions?.delete_data;
  const canEditPrice = user?.role === "owner" || user?.permissions?.access_finance;
  const canModifyProducts = user?.role === "owner" || user?.permissions?.modify_products;
  const [order, setOrder] = useState(null);
  const [note, setNote] = useState("");
  const [loadError, setLoadError] = useState(null);
  const [priceModalOpen, setPriceModalOpen] = useState(false);
  const [publishModalOpen, setPublishModalOpen] = useState(false);
  const [deleteModalOpen, setDeleteModalOpen] = useState(false);
  const [deleteLoading, setDeleteLoading] = useState(false);
  const [payments, setPayments] = useState([]);
  const [paymentModalOpen, setPaymentModalOpen] = useState(false);
  const [paymentLoading, setPaymentLoading] = useState(false);
  const [paymentForm, setPaymentForm] = useState({
    amount: "",
    payment_method: "cash",
    reference: "",
    notes: "",
    alloc_product: "",
    alloc_shipping: "",
    alloc_credit: "",
    use_custom_alloc: false,
  });
  const [priceForm, setPriceForm] = useState({
    subtotal_le: 0,
    delivery_fee_le: 0,
    discount_le: 0,
    reason: "",
  });

  // Phase 2 Work Assignments State
  const [assignments, setAssignments] = useState([]);
  const [workers, setWorkers] = useState([]);
  const [wageRules, setWageRules] = useState([]);
  const [assignModalOpen, setAssignModalOpen] = useState(false);
  const [assignLoading, setAssignLoading] = useState(false);
  const [selectedOrderItem, setSelectedOrderItem] = useState(null);
  const [assignForm, setAssignForm] = useState({
    worker_id: "",
    task_category: "whole_item",
    pricing_basis: "per_unit",
    agreed_rate_le: "",
    target_quantity: 1,
    rate_source: "standard_rule", // "standard_rule" | "manual_override"
    rate_override_reason: "",
    task_notes: "",
  });

  const [verifyModalOpen, setVerifyModalOpen] = useState(false);
  const [verifyingAssignment, setVerifyingAssignment] = useState(null);
  const [verifyAcceptedQty, setVerifyAcceptedQty] = useState(1);
  const [verifyNotes, setVerifyNotes] = useState("");
  const [verifyLoading, setVerifyLoading] = useState(false);

  const loadAssignments = () => {
    api.get(`/admin/orders/${id}/assignments`)
      .then((r) => { setAssignments(r.data || []); })
      .catch(() => {});
  };

  const loadWorkersAndRules = () => {
    api.get("/admin/workers")
      .then((r) => { setWorkers(r.data || []); })
      .catch(() => {});
    api.get("/admin/wage-rules")
      .then((r) => { setWageRules(r.data || []); })
      .catch(() => {});
  };

  const loadPayments = () => {
    api.get(`/admin/orders/${id}/payments`)
      .then((r) => { setPayments(r.data.payments || []); })
      .catch(() => {});
  };

  const load = () => {
    api.get(`/admin/orders/${id}`)
      .then((r) => { setOrder(r.data); setNote(r.data.admin_note || ""); setLoadError(null); })
      .catch((err) => {
        const msg = err.response?.data?.detail || "Pesanan tidak ditemukan atau telah dihapus";
        setLoadError(msg);
        toast.error(msg);
      });
    loadPayments();
    loadAssignments();
  };
  useEffect(() => {
    load();
    loadWorkersAndRules();
  }, [id]);

  const update = async (patch) => {
    try { const { data } = await api.patch(`/admin/orders/${id}`, patch); setOrder((o) => ({ ...o, ...data })); toast.success("Pesanan diperbarui"); }
    catch { toast.error("Gagal memperbarui"); }
  };

  const handleOpenAssignModal = (it) => {
    setSelectedOrderItem(it);
    // Find matching default wage rule if any
    const defaultRule = wageRules.find((r) => r.task_category === "whole_item" && r.pricing_basis === "per_unit");
    setAssignForm({
      worker_id: workers[0]?.id || "",
      task_category: "whole_item",
      pricing_basis: "per_unit",
      agreed_rate_le: defaultRule ? defaultRule.standard_rate_le : "",
      target_quantity: it?.quantity || 1,
      rate_source: defaultRule ? "standard_rule" : "manual_override",
      rate_override_reason: "",
      task_notes: "",
    });
    setAssignModalOpen(true);
  };

  const handleCategoryBasisChange = (newCat, newBasis) => {
    const matched = wageRules.find((r) => r.task_category === newCat && r.pricing_basis === newBasis);
    setAssignForm((prev) => ({
      ...prev,
      task_category: newCat,
      pricing_basis: newBasis,
      agreed_rate_le: matched ? matched.standard_rate_le : prev.agreed_rate_le,
      rate_source: matched ? "standard_rule" : "manual_override",
    }));
  };

  const handleCreateAssignment = async (e) => {
    e.preventDefault();
    if (!assignForm.worker_id) {
      toast.error("Silakan pilih pekerja/pengrajin");
      return;
    }
    const rate = parseFloat(assignForm.agreed_rate_le);
    if (!rate || rate <= 0) {
      toast.error("Tarif upah harus lebih besar dari 0");
      return;
    }
    const qty = parseInt(assignForm.target_quantity, 10);
    if (!qty || qty <= 0) {
      toast.error("Target kuantitas harus minimal 1");
      return;
    }
    if (assignForm.rate_source === "manual_override" && !assignForm.rate_override_reason.trim()) {
      toast.error("Alasan penyesuaian tarif manual wajib diisi");
      return;
    }

    setAssignLoading(true);
    try {
      const payload = {
        worker_id: assignForm.worker_id,
        order_item_id: selectedOrderItem?.item_id,
        task_category: assignForm.task_category,
        pricing_basis: assignForm.pricing_basis,
        agreed_rate_le: rate,
        target_quantity: qty,
        rate_override_reason: assignForm.rate_source === "manual_override" ? assignForm.rate_override_reason.trim() : undefined,
        task_notes: assignForm.task_notes.trim() || undefined,
      };
      await api.post(`/admin/orders/${id}/assignments`, payload);
      toast.success("Penugasan kerja berhasil dibuat");
      setAssignModalOpen(false);
      loadAssignments();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Gagal membuat penugasan kerja");
    } finally {
      setAssignLoading(false);
    }
  };

  const handleProgressChange = async (asnId, newStatus) => {
    try {
      await api.patch(`/admin/assignments/${asnId}/progress`, { status: newStatus });
      toast.success(`Status penugasan diubah ke ${newStatus}`);
      loadAssignments();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Gagal memperbarui status penugasan");
    }
  };

  const handleOpenVerifyModal = (asn) => {
    setVerifyingAssignment(asn);
    setVerifyAcceptedQty(asn.target_quantity || 1);
    setVerifyNotes("");
    setVerifyModalOpen(true);
  };

  const handleVerifySubmit = async (e) => {
    e.preventDefault();
    if (!verifyingAssignment) return;
    const qty = parseInt(verifyAcceptedQty, 10);
    if (!qty || qty <= 0) {
      toast.error("Kuantitas diterima harus minimal 1");
      return;
    }
    if (verifyingAssignment.pricing_basis === "lump_sum" && qty < verifyingAssignment.target_quantity) {
      toast.error(`Pekerjaan borongan (lump-sum) wajib diselesaikan 100% (target: ${verifyingAssignment.target_quantity})`);
      return;
    }

    setVerifyLoading(true);
    try {
      await api.post(`/admin/assignments/${verifyingAssignment.id || verifyingAssignment._id}/verify`, {
        accepted_quantity: qty,
        notes: verifyNotes.trim() || undefined,
      });
      toast.success("Penugasan berhasil diverifikasi dan upah terakru!");
      setVerifyModalOpen(false);
      loadAssignments();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Gagal memverifikasi penugasan");
    } finally {
      setVerifyLoading(false);
    }
  };

  const handleCancelAssignment = async (asnId) => {
    const reason = window.prompt("Masukkan alasan pembatalan penugasan kerja:");
    if (!reason || !reason.trim()) return;

    try {
      await api.post(`/admin/assignments/${asnId}/cancel`, { reason: reason.trim() });
      toast.success("Penugasan kerja berhasil dibatalkan");
      loadAssignments();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Gagal membatalkan penugasan kerja");
    }
  };

  const handleRecordPayment = async (e) => {
    e.preventDefault();
    const amt = parseFloat(paymentForm.amount);
    if (!amt || amt <= 0) {
      toast.error("Nominal pembayaran harus lebih besar dari 0");
      return;
    }

    const payload = {
      amount: amt,
      currency: "EGP",
      payment_method: paymentForm.payment_method,
      reference: paymentForm.reference || undefined,
      notes: paymentForm.notes || undefined,
    };

    if (paymentForm.use_custom_alloc) {
      const pAmt = parseFloat(paymentForm.alloc_product) || 0;
      const sAmt = parseFloat(paymentForm.alloc_shipping) || 0;
      const cAmt = parseFloat(paymentForm.alloc_credit) || 0;
      const sum = Math.round((pAmt + sAmt + cAmt) * 100) / 100;
      if (sum !== Math.round(amt * 100) / 100) {
        toast.error(`Jumlah alokasi (${sum} LE) harus sama persis dengan total (${amt} LE)`);
        return;
      }
      payload.allocations = [
        { target_type: "product", amount: pAmt, notes: "Alokasi Produk" },
        { target_type: "shipping", amount: sAmt, notes: "Alokasi Ongkir" },
        { target_type: "unallocated_credit", amount: cAmt, notes: "Kredit Belum Teralokasi" },
      ].filter((a) => a.amount > 0);
    }

    setPaymentLoading(true);
    try {
      await api.post(`/admin/orders/${id}/payments`, payload);
      toast.success("Pembayaran berhasil dicatat & masuk kas keuangan");
      setPaymentModalOpen(false);
      setPaymentForm({
        amount: "",
        payment_method: "cash",
        reference: "",
        notes: "",
        alloc_product: "",
        alloc_shipping: "",
        alloc_credit: "",
        use_custom_alloc: false,
      });
      load();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Gagal mencatat pembayaran");
    } finally {
      setPaymentLoading(false);
    }
  };

  const handleVoidPayment = async (paymentId) => {
    const reason = window.prompt("Masukkan alasan pembatalan pembayaran ini:");
    if (!reason || !reason.trim()) return;

    try {
      await api.post(`/admin/orders/${id}/payments/${paymentId}/void`, { reason: reason.trim() });
      toast.success("Pembayaran berhasil dibatalkan");
      load();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Gagal membatalkan pembayaran");
    }
  };

  const openPriceModal = () => {
    setPriceForm({
      subtotal_le: order.subtotal_le || 0,
      delivery_fee_le: order.delivery_fee_le || 0,
      discount_le: order.discount_le || 0,
      reason: "",
    });
    setPriceModalOpen(true);
  };

  const savePrice = async () => {
    const sub = Number(priceForm.subtotal_le) || 0;
    const del = Number(priceForm.delivery_fee_le) || 0;
    const disc = Number(priceForm.discount_le) || 0;
    const refDisc = Number(order.referral_discount_le) || 0;
    const pts = Number(order.points_redeemed_le) || 0;
    const newTotal = Math.max(0, sub - disc - refDisc - pts + del);

    const payload = {
      subtotal_le: sub,
      delivery_fee_le: del,
      discount_le: disc,
      total_le: newTotal,
    };

    if (priceForm.reason) {
      const timeStr = new Date().toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit" });
      const noteEntry = `[${timeStr}] Penyesuaian harga: ${priceForm.reason}`;
      payload.admin_note = order.admin_note ? `${order.admin_note}\n${noteEntry}` : noteEntry;
    }

    try {
      const { data } = await api.patch(`/admin/orders/${id}`, payload);
      setOrder((o) => ({ ...o, ...data }));
      if (payload.admin_note) setNote(payload.admin_note);
      setPriceModalOpen(false);
      toast.success("Harga pesanan & data keuangan berhasil disesuaikan");
    } catch (err) {
      toast.error(err.response?.data?.detail || "Gagal menyesuaikan harga");
    }
  };
  if (loadError) {
    return (
      <div className="max-w-4xl py-12 text-center" data-testid="order-load-error">
        <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-amber-100 text-amber-800">
          <AlertTriangle size={28} />
        </div>
        <h2 className="font-heading text-xl font-bold text-[#2C1E16]">
          Pesanan Tidak Ditemukan
        </h2>
        <p className="mt-1 text-sm text-[#8B7355]">
          {loadError}
        </p>
        <Button
          onClick={() => navigate("/admin/orders")}
          className="mt-6 rounded-xl bg-[#8B5A2B] hover:bg-[#6B4423] text-white text-xs font-semibold"
        >
          <ChevronLeft size={16} className="mr-1" /> Kembali ke Daftar Pesanan
        </Button>
      </div>
    );
  }
  if (!order) return <div className="text-[#8B7355] py-8">Memuat...</div>;
  const items = order.items || [order.item];
  const phoneNum = (order.customer_phone || "").replace(/[^0-9]/g, "");
  const copySummary = async () => {
    await copyToClipboard(order.whatsapp_message || "");
    toast.success("Ringkasan disalin");
  };
  const handlePermanentDelete = async (reason) => {
    setDeleteLoading(true);
    try {
      await api.post(`/admin/orders/${id}/permanent-delete`, {
        confirmation_phrase: "HAPUS PERMANEN",
        reason: reason || undefined,
      });
      toast.success("Pesanan berhasil dihapus secara permanen");
      setDeleteModalOpen(false);
      navigate("/admin/orders");
    } catch (e) {
      toast.error(e.response?.data?.detail || "Gagal menghapus pesanan");
    } finally {
      setDeleteLoading(false);
    }
  };

  return (
    <div className="max-w-4xl">
      <button onClick={() => navigate("/admin/orders")} className="mb-4 inline-flex items-center gap-1 text-sm text-[#8B5A2B]" data-testid="admin-back-orders"><ChevronLeft size={16} /> Kembali</button>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div><h1 className="font-heading text-2xl font-bold text-[#8B5A2B]">{order.order_number}</h1><p className="text-sm text-[#8B7355]">{new Date(order.created_at).toLocaleString("id-ID")}{order.updated_by_name ? ` · diperbarui oleh ${order.updated_by_name}` : ""}</p></div>
        {order.requires_admin_confirmation && <span className="rounded-full bg-amber-100 px-3 py-1 text-xs font-medium text-amber-800">Perlu Konfirmasi Admin</span>}
      </div>

      <div className="mt-6 grid gap-4 lg:grid-cols-2">
        <div className="rounded-2xl border border-[#E5DCC5] bg-white p-5 shadow-sm lg:col-span-2">
          <div className="grid gap-4 sm:grid-cols-3">
            <div><Label className="mb-1.5 block text-sm font-semibold">Status Pesanan</Label>
              <Select value={order.order_status} onValueChange={(v) => update({ order_status: v })}><SelectTrigger data-testid="select-order-status" className="h-11 bg-white"><SelectValue /></SelectTrigger><SelectContent>{Object.entries(ORDER_STATUS).map(([k, v]) => <SelectItem key={k} value={k}>{v.label}</SelectItem>)}</SelectContent></Select></div>
            <div>
              <Label className="mb-1.5 block text-sm font-semibold">Status Pembayaran</Label>
              <Select value={order.payment_status} disabled={true}>
                <SelectTrigger data-testid="select-payment-status" className="h-11 bg-stone-100 cursor-not-allowed opacity-75">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {Object.entries(PAYMENT_STATUS).map(([k, v]) => <SelectItem key={k} value={k}>{v.label}</SelectItem>)}
                </SelectContent>
              </Select>
              <p className="mt-1 text-[11px] text-[#8B7355]">Status pembayaran dihitung otomatis dari riwayat pembayaran.</p>
            </div>
            <div><Label className="mb-1.5 block text-sm font-semibold">Metode Pembayaran</Label>
              <Select value={order.payment_method || "cash"} onValueChange={(v) => update({ payment_method: v })}><SelectTrigger data-testid="select-payment-method" className="h-11 bg-white"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="cash">Cash (Tunai — EGP)</SelectItem><SelectItem value="transfer">Transfer (IDR)</SelectItem></SelectContent></Select></div>
          </div>
          <div className="mt-4"><Label className="mb-1.5 block text-sm font-semibold">Catatan Admin</Label>
            <Textarea value={note} onChange={(e) => setNote(e.target.value)} data-testid="admin-note-input" className="min-h-[70px] bg-white" />
            <Button onClick={() => update({ admin_note: note })} data-testid="save-admin-note" className="mt-2 rounded-xl bg-[#8B5A2B] hover:bg-[#6B4423]">Simpan Catatan</Button></div>
          <div className="mt-4 flex flex-wrap gap-2">
            <a href={`https://wa.me/${phoneNum}`} target="_blank" rel="noreferrer"><Button variant="outline" className="rounded-xl border-[#25D366] text-[#25D366]"><MessageCircle size={16} className="mr-1" /> WhatsApp</Button></a>
            {order.phone_number && (
              <a href={`tel:${order.phone_number}`}>
                <Button variant="outline" data-testid="admin-call-button" className="rounded-xl border-[#8B5A2B] text-[#8B5A2B] hover:bg-[#FAF5EE]">
                  <Phone size={16} className="mr-1" /> Telepon
                </Button>
              </a>
            )}
            {order.customer_maps_url && <a href={order.customer_maps_url} target="_blank" rel="noreferrer"><Button variant="outline" className="rounded-xl border-[#E5DCC5] text-[#5C4A3D]"><MapPin size={16} className="mr-1" /> Maps</Button></a>}
            <Button variant="outline" onClick={copySummary} data-testid="admin-copy-summary" className="rounded-xl border-[#E5DCC5] text-[#5C4A3D]"><Copy size={16} className="mr-1" /> Salin Ringkasan</Button>
            {canModifyProducts && (
              <Button
                variant="outline"
                onClick={() => setPublishModalOpen(true)}
                className={`rounded-xl ${
                  order.custom_collection_published
                    ? "border-emerald-300 text-emerald-700 bg-emerald-50 hover:bg-emerald-100"
                    : "border-[#8B5A2B]/40 text-[#8B5A2B] bg-[#FAF5EE] hover:bg-[#F3ECE0]"
                }`}
              >
                <Sparkles size={16} className="mr-1.5" />
                {order.custom_collection_published
                  ? `✓ Terbit: ${order.custom_collection_title || "Koleksi Custom"}`
                  : "Publikasikan ke Koleksi Custom"}
              </Button>
            )}
          </div>
        </div>

        {order.invoice_number && (
          <div className="rounded-2xl border border-[#8B5A2B]/20 bg-[#FAF5EE] p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-3 shadow-xs">
            <div className="flex items-center gap-2.5">
              <FileText className="h-5 w-5 text-[#8B5A2B] shrink-0" />
              <div>
                <span className="text-xs text-[#8B7355]">Sumber Invoice:</span>
                <div className="font-mono text-sm font-bold text-[#8B5A2B]">
                  {order.invoice_number}
                </div>
              </div>
            </div>
            {order.invoice_id && (
              <Button
                variant="outline"
                size="sm"
                onClick={async () => {
                  try {
                    await api.get(`/admin/invoices/${order.invoice_id}`);
                    navigate(`/admin/invoices/${order.invoice_id}`);
                  } catch {
                    toast.error(`Invoice ${order.invoice_number} telah dihapus secara permanen`);
                  }
                }}
                className="h-8 rounded-xl border-[#8B5A2B]/40 text-[#8B5A2B] text-xs font-semibold hover:bg-[#8B5A2B] hover:text-white"
              >
                Lihat Invoice &rarr;
              </Button>
            )}
          </div>
        )}

        <Block title="Customer">
          <Row k="Nama" v={order.customer_name} />
          <Row k="No WhatsApp" v={order.customer_phone} />
          {order.phone_number && <Row k="No Telepon" v={order.phone_number} />}
          <Row k="Alamat" v={order.customer_address} />
          {order.customer_maps_url && <Row k="Maps" v={order.customer_maps_url} />}
        </Block>

        <Block title="Produk & Penugasan Pengrajin">
          {items.map((it, i) => {
            if (!it) return null;
            const itId = it.item_id;
            const itemAssignments = assignments.filter((a) => a.order_item_id === itId);
            return (
              <div key={i} className="border-b border-[#F1EBE0] pb-4 last:border-0 mb-3">
                <div className="flex justify-between items-start gap-2">
                  <div>
                    <Row k={it.product_name_snapshot} v={`×${it.quantity}`} />
                    <div className="text-xs text-[#8B7355]">{config_summary_client(it.category, it.configuration_snapshot)}</div>
                    <div className="text-xs text-[#8B7355]">{fmtLE(it.subtotal_le)} LE</div>
                  </div>
                  {itId && (
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => handleOpenAssignModal(it)}
                      data-testid={`btn-assign-item-${i}`}
                      className="rounded-xl border-[#8B5A2B]/40 text-[#8B5A2B] text-xs font-semibold hover:bg-[#8B5A2B] hover:text-white"
                    >
                      <Wrench size={13} className="mr-1.5" /> Tugaskan Pengrajin
                    </Button>
                  )}
                </div>

                {/* Assignment list for this item */}
                {itemAssignments.length > 0 && (
                  <div className="mt-3 bg-[#FAF5EE] rounded-xl p-3 border border-[#E5DCC5]">
                    <div className="text-xs font-bold text-[#8B5A2B] mb-2 flex items-center gap-1.5">
                      <UserCheck size={14} /> Daftar Penugasan Kerja ({itemAssignments.length})
                    </div>
                    <div className="space-y-2">
                      {itemAssignments.map((asn) => {
                        const statusColors = {
                          assigned: "bg-stone-100 text-stone-700 border-stone-300",
                          in_progress: "bg-blue-100 text-blue-800 border-blue-200",
                          ready_for_review: "bg-amber-100 text-amber-800 border-amber-200",
                          accruing: "bg-purple-100 text-purple-800 border-purple-200",
                          completed: "bg-emerald-100 text-emerald-800 border-emerald-200",
                          cancelled: "bg-red-100 text-red-700 border-red-200",
                        };
                        return (
                          <div key={asn.id || asn._id} className="bg-white rounded-lg p-2.5 border border-[#E5DCC5] flex flex-wrap justify-between items-center gap-2 text-xs">
                            <div>
                              <div className="font-semibold text-[#2C1E16] flex items-center gap-2">
                                <span>{asn.worker_name}</span>
                                <span className={`px-2 py-0.5 rounded-full text-[10px] font-semibold border ${statusColors[asn.status] || "bg-stone-100"}`}>
                                  {asn.status}
                                </span>
                                {asn.is_owner_bypass && (
                                  <span className="bg-amber-100 text-amber-800 border border-amber-200 px-1.5 py-0.5 rounded text-[9px] font-bold">
                                    Owner Self-Approval
                                  </span>
                                )}
                              </div>
                              <div className="text-[#8B7355] text-[11px] mt-0.5">
                                Kategori: <span className="font-medium text-[#5C4A3D]">{asn.task_category}</span> | Basis: {asn.pricing_basis} | Tarif: {fmtLE(asn.agreed_rate_le)} LE | Target: {asn.target_quantity}
                                {asn.accepted_quantity > 0 && ` | Diterima: ${asn.accepted_quantity}`}
                              </div>
                              {asn.wage_obligation_number && (
                                <div className="text-emerald-700 text-[11px] font-medium mt-0.5">
                                  No. Kewajiban: {asn.wage_obligation_number}
                                </div>
                              )}
                            </div>

                            {/* Actions based on status */}
                            <div className="flex items-center gap-1.5">
                              {asn.status === "assigned" && (
                                <Button
                                  size="sm"
                                  variant="outline"
                                  onClick={() => handleProgressChange(asn.id || asn._id, "in_progress")}
                                  className="h-7 text-[11px] rounded-lg border-blue-300 text-blue-700 hover:bg-blue-50"
                                >
                                  Mulai Kerjakan
                                </Button>
                              )}
                              {asn.status === "in_progress" && (
                                <Button
                                  size="sm"
                                  variant="outline"
                                  onClick={() => handleProgressChange(asn.id || asn._id, "ready_for_review")}
                                  className="h-7 text-[11px] rounded-lg border-amber-300 text-amber-700 hover:bg-amber-50"
                                >
                                  Siap Review
                                </Button>
                              )}
                              {asn.status === "ready_for_review" && (
                                <Button
                                  size="sm"
                                  onClick={() => handleOpenVerifyModal(asn)}
                                  className="h-7 text-[11px] rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white font-semibold"
                                >
                                  <ShieldCheck size={12} className="mr-1" /> Verifikasi & Akru Upah
                                </Button>
                              )}
                              {asn.status !== "cancelled" && (
                                <Button
                                  size="sm"
                                  variant="ghost"
                                  onClick={() => handleCancelAssignment(asn.id || asn._id)}
                                  className="h-7 text-[11px] text-red-600 hover:bg-red-50 hover:text-red-700"
                                >
                                  Batalkan
                                </Button>
                              )}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}
              </div>
            );
          })}
          {order.notes && <Row k="Catatan" v={order.notes} />}
        </Block>

        <div className="rounded-2xl border border-[#E5DCC5] bg-white p-5 shadow-sm">
          <div className="mb-2 flex items-center justify-between">
            <span className="font-heading text-sm font-bold uppercase tracking-wide text-[#8B5A2B]">
              Rincian Harga
            </span>
            {canEditPrice && (
              <button
                type="button"
                onClick={openPriceModal}
                data-testid="btn-edit-order-price"
                className="flex items-center gap-1 rounded-lg border border-[#E5DCC5] bg-[#FBF9F4] px-2.5 py-1 text-xs font-semibold text-[#8B5A2B] hover:bg-[#EFE6D5] transition-colors"
                title="Sesuaikan Harga Pesanan"
              >
                <Pencil size={12} /> Sesuaikan Harga
              </button>
            )}
          </div>
          <div className="space-y-1">
            <Row k="Subtotal Produk" v={`${fmtLE(order.subtotal_le)} LE`} />
            {order.discount_le > 0 && <Row k={`Diskon${order.discount_code ? ` (${order.discount_code})` : ""}`} v={`-${fmtLE(order.discount_le)} LE`} />}
            {order.referral_discount_le > 0 && <Row k={`Diskon Referral${order.referral?.code ? ` (${order.referral.code})` : ""}`} v={`-${fmtLE(order.referral_discount_le)} LE`} />}
            {order.points_redeemed_le > 0 && <Row k="Penukaran Poin" v={`-${fmtLE(order.points_redeemed_le)} LE`} />}
            <Row k="Ongkir" v={`${fmtLE(order.delivery_fee_le)} LE`} />
            <div className="my-1 border-t border-dashed border-[#E5DCC5]" />
            <Row k="Total LE" v={<span className="font-bold text-[#8B5A2B]">{fmtLE(order.total_le)} LE</span>} />
            <Row k="Rate" v={`Rp${fmtLE(order.exchange_rate_idr_per_le)}/LE`} />
            <Row k="Estimasi IDR" v={fmtIDR(order.estimated_total_idr)} />
            <div className="mt-2 pt-2 border-t border-[#F1EBE0]">
              <div className="flex items-center justify-between text-xs">
                <span className="text-[#8B7355]">Kas Keuangan Masuk:</span>
                <span className="font-bold text-[#2C1E16]" data-testid="order-real-revenue">
                  {order.payment_method === "transfer"
                    ? `${fmtIDR(order.estimated_total_idr)} (IDR)`
                    : `${fmtLE(order.total_le)} LE (EGP)`}
                </span>
              </div>
              <div className="flex items-center justify-between text-[11px] text-[#8B7355] mt-0.5">
                <span>Nilai Referensi:</span>
                <span data-testid="order-counterpart-ref">
                  {order.payment_method === "transfer"
                    ? `≈ ${fmtLE(order.total_le)} LE (EGP)`
                    : `≈ ${fmtIDR(order.estimated_total_idr)} (IDR)`}
                </span>
              </div>
            </div>
          </div>
        </div>

        {order.referral && (
          <Block title="Promo & Referral">
            <Row k="Kode Referral" v={order.referral.code} />
            <Row k="Referral Owner" v={order.referral.owner_name || "-"} />
            <Row k="Persentase Diskon" v={`${fmtLE(order.referral.percentage)}%`} />
            <Row k="Jumlah Diskon" v={`${fmtLE(order.referral_discount_le)} LE`} />
            <Row k="Poin untuk Referrer" v={`${fmtLE(order.referral.points_per_order)} poin`} />
          </Block>
        )}

        <Block title="Pembayaran & Pengiriman">
          <Row
            k="Metode Bayar"
            v={
              <span className="font-medium">
                {order.payment_method === "transfer" ? "Transfer (Kas IDR)" : "Cash (Kas EGP)"}
              </span>
            }
          />
          <Row
            k="Status Bayar"
            v={
              <div className="flex flex-col items-end gap-1">
                <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold ${PAYMENT_STATUS[order.payment_status]?.color || "bg-stone-100 text-stone-700"}`}>
                  {PAYMENT_STATUS[order.payment_status]?.label || order.payment_status}
                </span>
                {order.legacy_dp_unknown && (
                  <span className="text-[11px] text-amber-700 font-medium">
                    (DP — Nominal Historis Tidak Tersedia)
                  </span>
                )}
                {order.is_legacy_derived && !order.legacy_dp_unknown && (
                  <span className="text-[10px] text-[#8B7355]">
                    (Berdasarkan Status Historis)
                  </span>
                )}
              </div>
            }
          />
          <Row
            k="Terbayar"
            v={
              order.has_unrecorded_legacy_dp && order.canonical_paid_amount_le !== undefined && order.canonical_paid_amount_le !== null
                ? <span>{fmtLE(order.canonical_paid_amount_le)} LE <span className="text-amber-700 text-[11px]">(Tercatat Baru) + DP Historis (Nominal Tidak Diketahui)</span></span>
                : order.paid_amount_le !== null && order.paid_amount_le !== undefined
                  ? `${fmtLE(order.paid_amount_le)} LE`
                  : <span className="text-amber-700 font-medium">Tidak Tersedia (Unknown)</span>
            }
          />
          <Row
            k="Sisa Tagihan"
            v={
              order.has_unrecorded_legacy_dp
                ? <span className="text-amber-700 font-medium">Belum Direkonsiliasi (Unknown)</span>
                : order.outstanding_amount_le !== null && order.outstanding_amount_le !== undefined
                  ? `${fmtLE(order.outstanding_amount_le)} LE`
                  : <span className="text-amber-700 font-medium">Tidak Tersedia (Unknown)</span>
            }
          />
          <Row k="Pengiriman" v={order.delivery_method === "delivery" ? "Delivery" : "Ambil di Toko"} />
          {order.delivery_zone_name && <Row k="Zona" v={order.delivery_zone_name} />}
        </Block>

        {/* Riwayat Pembayaran (Phase 1) */}
        <div className="rounded-2xl border border-[#E5DCC5] bg-white p-5 shadow-sm lg:col-span-2">
          <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
            <div>
              <h3 className="font-heading text-base font-bold text-[#8B5A2B] flex items-center gap-2">
                <CreditCard size={18} />
                Riwayat Pembayaran
              </h3>
              <p className="text-xs text-[#8B7355]">
                Setiap pembayaran yang dicatat secara otomatis membentuk arus kas masuk (Cash Receipt) di Keuangan.
              </p>
            </div>
            {canEditPrice && (
              <div className="flex items-center gap-2">
                {order.outstanding_amount_le > 0 && !order.has_unrecorded_legacy_dp && (
                  <Button
                    onClick={() => {
                      setPaymentForm({
                        amount: String(order.outstanding_amount_le),
                        payment_method: order.payment_method || "cash",
                        reference: "",
                        notes: "Pelunasan Pesanan",
                        alloc_product: "",
                        alloc_shipping: "",
                        alloc_credit: "",
                        use_custom_alloc: false,
                      });
                      setPaymentModalOpen(true);
                    }}
                    data-testid="btn-quick-settlement"
                    className="rounded-xl bg-[#8B5A2B] hover:bg-[#6B4423] text-white text-xs font-semibold"
                  >
                    <CheckCircle2 size={14} className="mr-1.5" /> Lunaskan Pesanan ({fmtLE(order.outstanding_amount_le)} LE)
                  </Button>
                )}
                <Button
                  onClick={() => setPaymentModalOpen(true)}
                  data-testid="btn-record-payment"
                  className="rounded-xl bg-emerald-600 hover:bg-emerald-700 text-white text-xs font-semibold"
                >
                  <CreditCard size={14} className="mr-1.5" /> Catat Pembayaran Baru
                </Button>
              </div>
            )}
          </div>

          {order.has_unrecorded_legacy_dp && (
            <div className="mb-4 rounded-xl border border-amber-300 bg-amber-50 p-3 text-xs text-amber-900 flex items-start gap-2" data-testid="banner-unreconciled-dp">
              <AlertTriangle size={16} className="text-amber-700 shrink-0 mt-0.5" />
              <div>
                <p className="font-semibold">Perhatian: Nominal DP Historis Belum Direkonsiliasi</p>
                <p className="mt-0.5 text-amber-800 text-[11px]">
                  Pesanan ini memiliki status DP historis dengan nominal yang belum tercatat di sistem kasir. Pelunasan otomatis dinonaktifkan untuk mencegah kekeliruan perhitungan. Silakan catat pelunasan aktual secara manual.
                </p>
              </div>
            </div>
          )}

          {payments.length === 0 ? (
            <div className="rounded-xl border border-dashed border-[#E5DCC5] p-6 text-center text-xs text-[#8B7355]">
              {order.is_legacy_derived ? (
                <div>
                  <p className="font-medium text-[#5C4A3D]">Belum ada pencatatan transaksi pembayaran individual untuk pesanan ini.</p>
                  <p className="mt-1 text-stone-500">
                    Status pembayaran saat ini berasal dari data historis sebelum modul kasir & pembayaran aktif.
                  </p>
                </div>
              ) : (
                <p>Belum ada pembayaran yang dicatat untuk pesanan ini.</p>
              )}
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead>
                  <tr className="border-b border-[#F1EBE0] text-[#8B7355] font-semibold">
                    <th className="py-2.5 px-3">No. Bayar</th>
                    <th className="py-2.5 px-3">Tanggal</th>
                    <th className="py-2.5 px-3">Metode</th>
                    <th className="py-2.5 px-3">Nominal (LE)</th>
                    <th className="py-2.5 px-3">Alokasi</th>
                    <th className="py-2.5 px-3">Status</th>
                    {canEditPrice && <th className="py-2.5 px-3 text-right">Aksi</th>}
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#F1EBE0]">
                  {payments.map((p) => {
                    const isVoid = p.status === "voided";
                    return (
                      <tr key={p.id || p._id} className={isVoid ? "opacity-50 line-through bg-stone-50" : ""}>
                        <td className="py-2.5 px-3 font-mono font-medium text-[#8B5A2B]">{p.payment_number}</td>
                        <td className="py-2.5 px-3 text-stone-600">
                          {p.payment_date ? new Date(p.payment_date).toLocaleDateString("id-ID") : "-"}
                        </td>
                        <td className="py-2.5 px-3 capitalize">
                          {p.payment_method === "transfer" ? "Transfer (IDR)" : "Cash (EGP)"}
                        </td>
                        <td className="py-2.5 px-3 font-bold text-[#2C1E16]">
                          {fmtLE(p.amount_le)} LE
                        </td>
                        <td className="py-2.5 px-3 text-stone-600">
                          {(p.allocations || []).map((a, idx) => (
                            <span key={idx} className="mr-2 inline-block">
                              {a.target_type === "product" && `Produk: ${fmtLE(a.amount_le)} LE`}
                              {a.target_type === "shipping" && `Ongkir: ${fmtLE(a.amount_le)} LE`}
                              {a.target_type === "unallocated_credit" && `Kredit: ${fmtLE(a.amount_le)} LE`}
                            </span>
                          ))}
                        </td>
                        <td className="py-2.5 px-3">
                          <span className={`inline-block px-2 py-0.5 rounded text-[11px] font-semibold ${isVoid ? "bg-red-100 text-red-700" : "bg-emerald-100 text-emerald-800"}`}>
                            {isVoid ? "Dibatalkan (Void)" : "Tercatat (Recorded)"}
                          </span>
                        </td>
                        {canEditPrice && (
                          <td className="py-2.5 px-3 text-right">
                            {!isVoid && (
                              <Button
                                variant="ghost"
                                size="sm"
                                onClick={() => handleVoidPayment(p.id || p._id)}
                                className="h-7 px-2 text-red-600 hover:text-red-800 hover:bg-red-50 text-xs"
                              >
                                Batalkan
                              </Button>
                            )}
                          </td>
                        )}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>

      {priceModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-md rounded-2xl border border-[#E5DCC5] bg-white p-5 shadow-xl">
            <div className="flex items-center justify-between border-b border-[#F1EBE0] pb-3">
              <div>
                <h3 className="font-heading text-lg font-bold text-[#2C1E16]">Sesuaikan Harga Pesanan</h3>
                <p className="text-xs text-[#8B7355]">Ubah harga untuk pesanan custom atau kesepakatan khusus</p>
              </div>
              <button onClick={() => setPriceModalOpen(false)} className="rounded-lg p-1 text-[#8B7355] hover:bg-[#F1EBE0]">
                <X size={18} />
              </button>
            </div>

            <div className="mt-4 space-y-3">
              <div>
                <Label className="text-xs font-semibold text-[#5C4A3D]">Subtotal Produk (LE)</Label>
                <Input
                  type="number"
                  value={priceForm.subtotal_le}
                  onChange={(e) => setPriceForm({ ...priceForm, subtotal_le: e.target.value })}
                  className="mt-1"
                  data-testid="input-edit-subtotal"
                />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <Label className="text-xs font-semibold text-[#5C4A3D]">Ongkir (LE)</Label>
                  <Input
                    type="number"
                    value={priceForm.delivery_fee_le}
                    onChange={(e) => setPriceForm({ ...priceForm, delivery_fee_le: e.target.value })}
                    className="mt-1"
                    data-testid="input-edit-delivery"
                  />
                </div>
                <div>
                  <Label className="text-xs font-semibold text-[#5C4A3D]">Diskon (LE)</Label>
                  <Input
                    type="number"
                    value={priceForm.discount_le}
                    onChange={(e) => setPriceForm({ ...priceForm, discount_le: e.target.value })}
                    className="mt-1"
                    data-testid="input-edit-discount"
                  />
                </div>
              </div>

              <div className="rounded-xl border border-[#E5DCC5] bg-[#FBF9F4] p-3 text-xs space-y-1">
                <div className="flex justify-between text-[#8B7355]">
                  <span>Total Baru (LE):</span>
                  <span className="font-bold text-[#8B5A2B] text-sm">
                    {fmtLE(Math.max(0, (Number(priceForm.subtotal_le) || 0) - (Number(priceForm.discount_le) || 0) - (Number(order.referral_discount_le) || 0) - (Number(order.points_redeemed_le) || 0) + (Number(priceForm.delivery_fee_le) || 0)))} LE
                  </span>
                </div>
                <div className="flex justify-between text-[#8B7355]">
                  <span>Estimasi IDR:</span>
                  <span className="font-medium text-[#2C1E16]">
                    {fmtIDR(Math.round(Math.max(0, (Number(priceForm.subtotal_le) || 0) - (Number(priceForm.discount_le) || 0) - (Number(order.referral_discount_le) || 0) - (Number(order.points_redeemed_le) || 0) + (Number(priceForm.delivery_fee_le) || 0)) * (order.exchange_rate_idr_per_le || 357)))}
                  </span>
                </div>
                {order.payment_status === "lunas" && (
                  <p className="mt-1.5 text-[11px] font-medium text-emerald-700">
                    ✓ Transaksi di data Keuangan akan otomatis diperbarui ke total baru ini.
                  </p>
                )}
              </div>

              <div>
                <Label className="text-xs font-semibold text-[#5C4A3D]">Catatan / Alasan Penyesuaian (Opsional)</Label>
                <Input
                  placeholder="Contoh: Kesepakatan ukuran custom meja 100x60"
                  value={priceForm.reason}
                  onChange={(e) => setPriceForm({ ...priceForm, reason: e.target.value })}
                  className="mt-1 text-xs"
                  data-testid="input-edit-reason"
                />
              </div>
            </div>

            <div className="mt-5 flex gap-2">
              <Button variant="outline" onClick={() => setPriceModalOpen(false)} className="flex-1 rounded-xl border-[#E5DCC5]">
                Batal
              </Button>
              <Button onClick={savePrice} data-testid="btn-save-custom-price" className="flex-1 rounded-xl bg-[#8B5A2B] hover:bg-[#6B4423]">
                Simpan Penyesuaian
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Modal Publikasikan ke Koleksi Custom */}
      <PublishCustomCollectionModal
        isOpen={publishModalOpen}
        onClose={() => setPublishModalOpen(false)}
        initialData={{
          title: order.custom_collection_title || items[0]?.product_name_snapshot || "Desain Custom Sogil",
          price_le: order.subtotal_le || 0,
          spesifikasi: items[0]
            ? config_summary_client(items[0].category, items[0].configuration_snapshot)
            : order.notes || "",
          photo_urls: [],
          order_id: order.id || order._id,
        }}
      />

      {/* Zona Berbahaya (Permanent Delete) */}
      {canDelete && (
        <div className="mt-8 rounded-2xl border border-red-200 bg-red-50/40 p-5 shadow-xs" data-testid="danger-zone-order">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
            <div>
              <h3 className="text-sm font-bold text-red-950 flex items-center gap-2">
                <AlertTriangle className="h-4 w-4 text-red-600 shrink-0" />
                Zona Berbahaya
              </h3>
              <p className="text-xs text-red-700 mt-1">
                Hapus pesanan ini secara permanen dari database. Transaksi finance dan invoice terkait TIDAK akan ikut dihapus.
              </p>
            </div>
            <Button
              variant="destructive"
              onClick={() => setDeleteModalOpen(true)}
              data-testid="permanent-delete-order-btn"
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
        title="Hapus Pesanan Permanen"
        entityType="Pesanan"
        entityIdentifier={order.order_number || id}
        warningMessages={[
          order.payment_status === "lunas" ? "Pesanan ini sudah LUNAS. Catatan transaksi di finance TIDAK akan dihapus." : null,
          order.invoice_id ? `Pesanan ini berasal dari Invoice ${order.invoice_number}. Invoice terkait TIDAK akan dihapus.` : null,
        ].filter(Boolean)}
        loading={deleteLoading}
      />

      {/* Modal Pencatatan Pembayaran (Phase 1) */}
      {paymentModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-md rounded-2xl border border-[#E5DCC5] bg-white p-5 shadow-xl max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between border-b border-[#F1EBE0] pb-3">
              <div>
                <h3 className="font-heading text-lg font-bold text-[#2C1E16]">Catat Pembayaran Masuk</h3>
                <p className="text-xs text-[#8B7355]">Penerimaan kas/transfer nyata dari pelanggan</p>
              </div>
              <button onClick={() => setPaymentModalOpen(false)} className="rounded-lg p-1 text-[#8B7355] hover:bg-[#F1EBE0]">
                <X size={18} />
              </button>
            </div>

            <form onSubmit={handleRecordPayment} className="mt-4 space-y-3">
              <div>
                <Label className="text-xs font-semibold text-[#5C4A3D]">Nominal Pembayaran (LE) *</Label>
                <Input
                  type="number"
                  step="0.01"
                  required
                  placeholder="Contoh: 500"
                  value={paymentForm.amount}
                  onChange={(e) => setPaymentForm({ ...paymentForm, amount: e.target.value })}
                  className="mt-1"
                  data-testid="input-payment-amount"
                />
              </div>

              <div>
                <Label className="text-xs font-semibold text-[#5C4A3D]">Metode Pembayaran *</Label>
                <Select
                  value={paymentForm.payment_method}
                  onValueChange={(v) => setPaymentForm({ ...paymentForm, payment_method: v })}
                >
                  <SelectTrigger className="h-10 bg-white mt-1">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="cash">Cash / Tunai (Kas EGP)</SelectItem>
                    <SelectItem value="transfer">Transfer Bank (Kas IDR)</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <div>
                <Label className="text-xs font-semibold text-[#5C4A3D]">No. Referensi / Transfer (Opsional)</Label>
                <Input
                  placeholder="Contoh: Bukti transfer BCA 12345"
                  value={paymentForm.reference}
                  onChange={(e) => setPaymentForm({ ...paymentForm, reference: e.target.value })}
                  className="mt-1 text-xs"
                />
              </div>

              <div>
                <Label className="text-xs font-semibold text-[#5C4A3D]">Catatan (Opsional)</Label>
                <Input
                  placeholder="Contoh: Pembayaran DP 50%"
                  value={paymentForm.notes}
                  onChange={(e) => setPaymentForm({ ...paymentForm, notes: e.target.value })}
                  className="mt-1 text-xs"
                />
              </div>

              <div className="pt-2 border-t border-[#F1EBE0]">
                <label className="flex items-center gap-2 cursor-pointer text-xs font-semibold text-[#5C4A3D]">
                  <input
                    type="checkbox"
                    checked={paymentForm.use_custom_alloc}
                    onChange={(e) => setPaymentForm({ ...paymentForm, use_custom_alloc: e.target.checked })}
                    className="rounded border-[#E5DCC5] text-[#8B5A2B]"
                  />
                  Atur Klasifikasi Alokasi Manual
                </label>
                <p className="text-[11px] text-[#8B7355] mt-0.5">
                  Secara default, sistem otomatis mengalokasikan pembayaran ke produk, ongkir, lalu kelebihan ke kredit.
                </p>

                {paymentForm.use_custom_alloc && (
                  <div className="mt-3 p-3 bg-[#FAF5EE] rounded-xl space-y-2 text-xs">
                    <div>
                      <Label className="text-[11px] text-[#5C4A3D]">Alokasi ke Produk (LE)</Label>
                      <Input
                        type="number"
                        step="0.01"
                        placeholder="0"
                        value={paymentForm.alloc_product}
                        onChange={(e) => setPaymentForm({ ...paymentForm, alloc_product: e.target.value })}
                        className="mt-0.5 bg-white h-8 text-xs"
                      />
                    </div>
                    <div>
                      <Label className="text-[11px] text-[#5C4A3D]">Alokasi ke Ongkir (LE)</Label>
                      <Input
                        type="number"
                        step="0.01"
                        placeholder="0"
                        value={paymentForm.alloc_shipping}
                        onChange={(e) => setPaymentForm({ ...paymentForm, alloc_shipping: e.target.value })}
                        className="mt-0.5 bg-white h-8 text-xs"
                      />
                    </div>
                    <div>
                      <Label className="text-[11px] text-[#5C4A3D]">Kredit Belum Teralokasi (LE)</Label>
                      <Input
                        type="number"
                        step="0.01"
                        placeholder="0"
                        value={paymentForm.alloc_credit}
                        onChange={(e) => setPaymentForm({ ...paymentForm, alloc_credit: e.target.value })}
                        className="mt-0.5 bg-white h-8 text-xs"
                      />
                    </div>
                  </div>
                )}
              </div>

              <div className="mt-5 flex gap-2">
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => setPaymentModalOpen(false)}
                  className="flex-1 rounded-xl border-[#E5DCC5]"
                >
                  Batal
                </Button>
                <Button
                  type="submit"
                  disabled={paymentLoading}
                  data-testid="btn-submit-payment"
                  className="flex-1 rounded-xl bg-emerald-600 hover:bg-emerald-700 text-white font-semibold text-xs"
                >
                  {paymentLoading ? "Menyimpan..." : "Simpan Pembayaran"}
                </Button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Modal Penugasan Pengrajin (Phase 2) */}
      {assignModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4 backdrop-blur-xs">
          <div className="w-full max-w-md rounded-2xl bg-white p-6 shadow-xl border border-[#E5DCC5] max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between pb-3 border-b border-[#F1EBE0]">
              <div className="font-heading text-base font-bold text-[#8B5A2B] flex items-center gap-2">
                <Wrench size={18} /> Penugasan Kerja Pengrajin
              </div>
              <button
                type="button"
                onClick={() => setAssignModalOpen(false)}
                className="text-stone-400 hover:text-stone-600"
              >
                <X size={18} />
              </button>
            </div>

            <form onSubmit={handleCreateAssignment} className="mt-4 space-y-4 text-xs">
              <div>
                <Label className="text-xs font-semibold text-[#5C4A3D]">Item Pesanan</Label>
                <div className="mt-1 p-2 bg-[#FAF5EE] rounded-lg border border-[#E5DCC5] text-[#2C1E16]">
                  <div className="font-medium">{selectedOrderItem?.product_name_snapshot}</div>
                  <div className="text-[11px] text-[#8B7355]">Kuantitas Pesanan: {selectedOrderItem?.quantity} unit</div>
                </div>
              </div>

              <div>
                <Label className="text-xs font-semibold text-[#5C4A3D]">Pilih Pengrajin / Pekerja</Label>
                <select
                  value={assignForm.worker_id}
                  onChange={(e) => setAssignForm({ ...assignForm, worker_id: e.target.value })}
                  className="mt-1 w-full rounded-xl border border-[#E5DCC5] p-2 text-xs focus:ring-1 focus:ring-[#8B5A2B]"
                  required
                >
                  <option value="">-- Pilih Pekerja --</option>
                  {workers.map((w) => (
                    <option key={w.id} value={w.id}>
                      {w.name} ({w.role})
                    </option>
                  ))}
                </select>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <Label className="text-xs font-semibold text-[#5C4A3D]">Kategori Tugas</Label>
                  <select
                    value={assignForm.task_category}
                    onChange={(e) => handleCategoryBasisChange(e.target.value, assignForm.pricing_basis)}
                    className="mt-1 w-full rounded-xl border border-[#E5DCC5] p-2 text-xs"
                  >
                    <option value="whole_item">Borongan Penuh (whole_item)</option>
                    <option value="assembly">Perakitan (assembly)</option>
                    <option value="finishing">Finishing / Cat</option>
                    <option value="cutting">Pemotongan (cutting)</option>
                    <option value="custom">Tugas Khusus (custom)</option>
                  </select>
                </div>
                <div>
                  <Label className="text-xs font-semibold text-[#5C4A3D]">Dasar Tarif</Label>
                  <select
                    value={assignForm.pricing_basis}
                    onChange={(e) => handleCategoryBasisChange(assignForm.task_category, e.target.value)}
                    className="mt-1 w-full rounded-xl border border-[#E5DCC5] p-2 text-xs"
                  >
                    <option value="per_unit">Per Unit</option>
                    <option value="lump_sum">Borongan Total (Lump-Sum)</option>
                  </select>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <Label className="text-xs font-semibold text-[#5C4A3D]">Tarif Disepakati (LE)</Label>
                  <Input
                    type="number"
                    step="0.01"
                    min="0.01"
                    value={assignForm.agreed_rate_le}
                    onChange={(e) => setAssignForm({ ...assignForm, agreed_rate_le: e.target.value, rate_source: "manual_override" })}
                    placeholder="0.00"
                    className="mt-1"
                    required
                  />
                </div>
                <div>
                  <Label className="text-xs font-semibold text-[#5C4A3D]">Target Kuantitas</Label>
                  <Input
                    type="number"
                    min="1"
                    max={selectedOrderItem?.quantity || 1}
                    value={assignForm.target_quantity}
                    onChange={(e) => setAssignForm({ ...assignForm, target_quantity: e.target.value })}
                    className="mt-1"
                    required
                  />
                </div>
              </div>

              {assignForm.rate_source === "manual_override" && (
                <div>
                  <Label className="text-xs font-semibold text-amber-800">Alasan Penyesuaian Tarif Manual *</Label>
                  <Input
                    type="text"
                    value={assignForm.rate_override_reason}
                    onChange={(e) => setAssignForm({ ...assignForm, rate_override_reason: e.target.value })}
                    placeholder="Contoh: Model kayu lebih keras / detail custom rumit"
                    className="mt-1 border-amber-300 focus:ring-amber-500"
                    required
                  />
                </div>
              )}

              <div>
                <Label className="text-xs font-semibold text-[#5C4A3D]">Catatan Tugas (Opsional)</Label>
                <Textarea
                  value={assignForm.task_notes}
                  onChange={(e) => setAssignForm({ ...assignForm, task_notes: e.target.value })}
                  placeholder="Instruksi khusus untuk pengrajin..."
                  rows={2}
                  className="mt-1"
                />
              </div>

              <div className="mt-5 flex gap-2">
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => setAssignModalOpen(false)}
                  className="flex-1 rounded-xl border-[#E5DCC5]"
                >
                  Batal
                </Button>
                <Button
                  type="submit"
                  disabled={assignLoading}
                  className="flex-1 rounded-xl bg-[#8B5A2B] hover:bg-[#724a23] text-white font-semibold text-xs"
                >
                  {assignLoading ? "Menyimpan..." : "Buat Penugasan"}
                </Button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Modal Verifikasi & Akru Upah (Phase 2) */}
      {verifyModalOpen && verifyingAssignment && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4 backdrop-blur-xs">
          <div className="w-full max-w-md rounded-2xl bg-white p-6 shadow-xl border border-[#E5DCC5]">
            <div className="flex items-center justify-between pb-3 border-b border-[#F1EBE0]">
              <div className="font-heading text-base font-bold text-emerald-800 flex items-center gap-2">
                <ShieldCheck size={18} /> Verifikasi Hasil Kerja & Akru Upah
              </div>
              <button
                type="button"
                onClick={() => setVerifyModalOpen(false)}
                className="text-stone-400 hover:text-stone-600"
              >
                <X size={18} />
              </button>
            </div>

            <form onSubmit={handleVerifySubmit} className="mt-4 space-y-4 text-xs">
              <div className="bg-[#FAF5EE] rounded-xl p-3 border border-[#E5DCC5] space-y-1">
                <div>Pekerja: <span className="font-semibold text-[#2C1E16]">{verifyingAssignment.worker_name}</span></div>
                <div>Kategori: <span className="font-semibold text-[#2C1E16]">{verifyingAssignment.task_category}</span> ({verifyingAssignment.pricing_basis})</div>
                <div>Tarif Disepakati: <span className="font-semibold text-[#2C1E16]">{fmtLE(verifyingAssignment.agreed_rate_le)} LE</span></div>
                <div>Target Kuantitas: <span className="font-semibold text-[#2C1E16]">{verifyingAssignment.target_quantity}</span></div>
              </div>

              {verifyingAssignment.pricing_basis === "lump_sum" && (
                <div className="rounded-lg bg-amber-50 border border-amber-200 p-2.5 text-[11px] text-amber-800">
                  <strong>Aturan Borongan (B-1):</strong> Pekerjaan lump-sum wajib diselesaikan 100% ({verifyingAssignment.target_quantity} unit). Verifikasi parsial tidak diizinkan.
                </div>
              )}

              <div>
                <Label className="text-xs font-semibold text-[#5C4A3D]">Kuantitas Diterima</Label>
                <Input
                  type="number"
                  min="1"
                  max={verifyingAssignment.target_quantity}
                  value={verifyAcceptedQty}
                  onChange={(e) => setVerifyAcceptedQty(e.target.value)}
                  className="mt-1"
                  required
                />
              </div>

              <div>
                <Label className="text-xs font-semibold text-[#5C4A3D]">Catatan Verifikasi (Opsional)</Label>
                <Textarea
                  value={verifyNotes}
                  onChange={(e) => setVerifyNotes(e.target.value)}
                  placeholder="Catatan inspeksi kualitas..."
                  rows={2}
                  className="mt-1"
                />
              </div>

              <div className="mt-5 flex gap-2">
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => setVerifyModalOpen(false)}
                  className="flex-1 rounded-xl border-[#E5DCC5]"
                >
                  Batal
                </Button>
                <Button
                  type="submit"
                  disabled={verifyLoading}
                  className="flex-1 rounded-xl bg-emerald-600 hover:bg-emerald-700 text-white font-semibold text-xs"
                >
                  {verifyLoading ? "Memverifikasi..." : "Konfirmasi Verifikasi"}
                </Button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}

const Block = ({ title, children }) => (
  <div className="rounded-2xl border border-[#E5DCC5] bg-white p-5 shadow-sm"><div className="mb-2 font-heading text-sm font-bold uppercase tracking-wide text-[#8B5A2B]">{title}</div><div className="space-y-1">{children}</div></div>
);
const Row = ({ k, v }) => (<div className="flex justify-between gap-4 text-sm"><span className="shrink-0 text-[#8B7355]">{k}</span><span className="break-all text-right font-medium text-[#2C1E16]">{v}</span></div>);
