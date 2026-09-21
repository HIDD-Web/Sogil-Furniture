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
import { ChevronLeft, MapPin, Copy, MessageCircle, Trash2, Pencil, X, Sparkles } from "lucide-react";
import { toast } from "sonner";
import { useAuth } from "../../context/AuthContext";
import PublishCustomCollectionModal from "../../components/admin/PublishCustomCollectionModal";

export default function AdminOrderDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { user } = useAuth();
  const canDelete = user?.role === "owner" || user?.permissions?.delete_data;
  const canEditPrice = user?.role === "owner" || user?.permissions?.access_finance;
  const canModifyProducts = user?.role === "owner" || user?.permissions?.modify_products;
  const [order, setOrder] = useState(null);
  const [note, setNote] = useState("");
  const [priceModalOpen, setPriceModalOpen] = useState(false);
  const [publishModalOpen, setPublishModalOpen] = useState(false);
  const [priceForm, setPriceForm] = useState({
    subtotal_le: 0,
    delivery_fee_le: 0,
    discount_le: 0,
    reason: "",
  });

  const load = () => api.get(`/admin/orders/${id}`).then((r) => { setOrder(r.data); setNote(r.data.admin_note || ""); });
  useEffect(() => { load(); }, [id]);

  const update = async (patch) => {
    try { const { data } = await api.patch(`/admin/orders/${id}`, patch); setOrder((o) => ({ ...o, ...data })); toast.success("Pesanan diperbarui"); }
    catch { toast.error("Gagal memperbarui"); }
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
  if (!order) return <div className="text-[#8B7355]">Memuat...</div>;
  const items = order.items || [order.item];
  const phoneNum = (order.customer_phone || "").replace(/[^0-9]/g, "");
  const copySummary = async () => {
    await copyToClipboard(order.whatsapp_message || "");
    toast.success("Ringkasan disalin");
  };
  const doDelete = async () => {
    const paid = order.payment_status === "lunas";
    const msg = paid ? "Pesanan ini sudah LUNAS. Menghapus akan menghapus/membalik pendapatan otomatis terkait dan tidak dapat dibatalkan. Lanjutkan?" : "Apakah Anda yakin ingin menghapus pesanan ini? Tindakan ini tidak dapat dibatalkan.";
    if (!window.confirm(msg)) return;
    try { await api.delete(`/admin/orders/${id}`); toast.success("Pesanan dihapus"); navigate("/admin/orders"); }
    catch (e) { toast.error(e.response?.data?.detail || "Gagal menghapus"); }
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
            <div><Label className="mb-1.5 block text-sm font-semibold">Status Pembayaran</Label>
              <Select value={order.payment_status} onValueChange={(v) => update({ payment_status: v })}><SelectTrigger data-testid="select-payment-status" className="h-11 bg-white"><SelectValue /></SelectTrigger><SelectContent>{Object.entries(PAYMENT_STATUS).map(([k, v]) => <SelectItem key={k} value={k}>{v.label}</SelectItem>)}</SelectContent></Select></div>
            <div><Label className="mb-1.5 block text-sm font-semibold">Metode Pembayaran</Label>
              <Select value={order.payment_method || "cash"} onValueChange={(v) => update({ payment_method: v })}><SelectTrigger data-testid="select-payment-method" className="h-11 bg-white"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="cash">Cash (Tunai — EGP)</SelectItem><SelectItem value="transfer">Transfer (IDR)</SelectItem></SelectContent></Select></div>
          </div>
          <div className="mt-4"><Label className="mb-1.5 block text-sm font-semibold">Catatan Admin</Label>
            <Textarea value={note} onChange={(e) => setNote(e.target.value)} data-testid="admin-note-input" className="min-h-[70px] bg-white" />
            <Button onClick={() => update({ admin_note: note })} data-testid="save-admin-note" className="mt-2 rounded-xl bg-[#8B5A2B] hover:bg-[#6B4423]">Simpan Catatan</Button></div>
          <div className="mt-4 flex flex-wrap gap-2">
            <a href={`https://wa.me/${phoneNum}`} target="_blank" rel="noreferrer"><Button variant="outline" className="rounded-xl border-[#25D366] text-[#25D366]"><MessageCircle size={16} className="mr-1" /> WhatsApp</Button></a>
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
            {canDelete && <Button variant="outline" onClick={doDelete} data-testid="delete-order" className="rounded-xl border-red-300 text-red-600 hover:bg-red-50"><Trash2 size={16} className="mr-1" /> Hapus Pesanan</Button>}
          </div>
        </div>

        <Block title="Customer"><Row k="Nama" v={order.customer_name} /><Row k="No HP" v={order.customer_phone} /><Row k="Alamat" v={order.customer_address} />{order.customer_maps_url && <Row k="Maps" v={order.customer_maps_url} />}</Block>

        <Block title="Produk">
          {items.map((it, i) => it && (
            <div key={i} className="border-b border-[#F1EBE0] pb-2 last:border-0">
              <Row k={it.product_name_snapshot} v={`×${it.quantity}`} />
              <div className="text-xs text-[#8B7355]">{config_summary_client(it.category, it.configuration_snapshot)}</div>
              <div className="text-xs text-[#8B7355]">{fmtLE(it.subtotal_le)} LE</div>
            </div>
          ))}
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
          <Row k="Status Bayar" v={PAYMENT_STATUS[order.payment_status]?.label} />
          <Row k="Pengiriman" v={order.delivery_method === "delivery" ? "Delivery" : "Ambil di Toko"} />
          {order.delivery_zone_name && <Row k="Zona" v={order.delivery_zone_name} />}
        </Block>
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
        onSuccess={() => {
          load();
        }}
      />
    </div>
  );
}

const Block = ({ title, children }) => (
  <div className="rounded-2xl border border-[#E5DCC5] bg-white p-5 shadow-sm"><div className="mb-2 font-heading text-sm font-bold uppercase tracking-wide text-[#8B5A2B]">{title}</div><div className="space-y-1">{children}</div></div>
);
const Row = ({ k, v }) => (<div className="flex justify-between gap-4 text-sm"><span className="shrink-0 text-[#8B7355]">{k}</span><span className="break-all text-right font-medium text-[#2C1E16]">{v}</span></div>);
