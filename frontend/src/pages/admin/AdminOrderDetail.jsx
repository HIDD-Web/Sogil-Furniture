import React, { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import api from "../../lib/api";
import { fmtLE, fmtIDR } from "../../lib/format";
import { config_summary_client } from "../../lib/summary";
import { ORDER_STATUS, PAYMENT_STATUS } from "../../lib/constants";
import { Button } from "../../components/ui/button";
import { Textarea } from "../../components/ui/textarea";
import { Label } from "../../components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../../components/ui/select";
import { ChevronLeft, MapPin, Copy, MessageCircle } from "lucide-react";
import { toast } from "sonner";

export default function AdminOrderDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [order, setOrder] = useState(null);
  const [note, setNote] = useState("");

  const load = () => api.get(`/admin/orders/${id}`).then((r) => { setOrder(r.data); setNote(r.data.admin_note || ""); });
  useEffect(() => { load(); }, [id]);

  const update = async (patch) => {
    try { const { data } = await api.patch(`/admin/orders/${id}`, patch); setOrder((o) => ({ ...o, ...data })); toast.success("Pesanan diperbarui"); }
    catch { toast.error("Gagal memperbarui"); }
  };
  if (!order) return <div className="text-[#8B7355]">Memuat...</div>;
  const items = order.items || [order.item];
  const phoneNum = (order.customer_phone || "").replace(/[^0-9]/g, "");
  const copySummary = () => { navigator.clipboard.writeText(order.whatsapp_message || ""); toast.success("Ringkasan disalin"); };

  return (
    <div className="max-w-4xl">
      <button onClick={() => navigate("/admin/orders")} className="mb-4 inline-flex items-center gap-1 text-sm text-[#8B5A2B]" data-testid="admin-back-orders"><ChevronLeft size={16} /> Kembali</button>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div><h1 className="font-heading text-2xl font-bold text-[#8B5A2B]">{order.order_number}</h1><p className="text-sm text-[#8B7355]">{new Date(order.created_at).toLocaleString("id-ID")}{order.updated_by_name ? ` · diperbarui oleh ${order.updated_by_name}` : ""}</p></div>
        {order.requires_admin_confirmation && <span className="rounded-full bg-amber-100 px-3 py-1 text-xs font-medium text-amber-800">Perlu Konfirmasi Admin</span>}
      </div>

      <div className="mt-6 grid gap-4 lg:grid-cols-2">
        <div className="rounded-2xl border border-[#E5DCC5] bg-white p-5 shadow-sm lg:col-span-2">
          <div className="grid gap-4 sm:grid-cols-2">
            <div><Label className="mb-1.5 block text-sm font-semibold">Status Pesanan</Label>
              <Select value={order.order_status} onValueChange={(v) => update({ order_status: v })}><SelectTrigger data-testid="select-order-status" className="h-11 bg-white"><SelectValue /></SelectTrigger><SelectContent>{Object.entries(ORDER_STATUS).map(([k, v]) => <SelectItem key={k} value={k}>{v.label}</SelectItem>)}</SelectContent></Select></div>
            <div><Label className="mb-1.5 block text-sm font-semibold">Status Pembayaran</Label>
              <Select value={order.payment_status} onValueChange={(v) => update({ payment_status: v })}><SelectTrigger data-testid="select-payment-status" className="h-11 bg-white"><SelectValue /></SelectTrigger><SelectContent>{Object.entries(PAYMENT_STATUS).map(([k, v]) => <SelectItem key={k} value={k}>{v.label}</SelectItem>)}</SelectContent></Select></div>
          </div>
          <div className="mt-4"><Label className="mb-1.5 block text-sm font-semibold">Catatan Admin</Label>
            <Textarea value={note} onChange={(e) => setNote(e.target.value)} data-testid="admin-note-input" className="min-h-[70px] bg-white" />
            <Button onClick={() => update({ admin_note: note })} data-testid="save-admin-note" className="mt-2 rounded-xl bg-[#8B5A2B] hover:bg-[#6B4423]">Simpan Catatan</Button></div>
          <div className="mt-4 flex flex-wrap gap-2">
            <a href={`https://wa.me/${phoneNum}`} target="_blank" rel="noreferrer"><Button variant="outline" className="rounded-xl border-[#25D366] text-[#25D366]"><MessageCircle size={16} className="mr-1" /> WhatsApp</Button></a>
            {order.customer_maps_url && <a href={order.customer_maps_url} target="_blank" rel="noreferrer"><Button variant="outline" className="rounded-xl border-[#E5DCC5] text-[#5C4A3D]"><MapPin size={16} className="mr-1" /> Maps</Button></a>}
            <Button variant="outline" onClick={copySummary} data-testid="admin-copy-summary" className="rounded-xl border-[#E5DCC5] text-[#5C4A3D]"><Copy size={16} className="mr-1" /> Salin Ringkasan</Button>
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

        <Block title="Rincian Harga">
          <Row k="Subtotal Produk" v={`${fmtLE(order.subtotal_le)} LE`} />
          {order.discount_le > 0 && <Row k={`Diskon${order.discount_code ? ` (${order.discount_code})` : ""}`} v={`-${fmtLE(order.discount_le)} LE`} />}
          <Row k="Ongkir" v={`${fmtLE(order.delivery_fee_le)} LE`} />
          <div className="my-1 border-t border-dashed border-[#E5DCC5]" />
          <Row k="Total LE" v={<span className="font-bold text-[#8B5A2B]">{fmtLE(order.total_le)} LE</span>} />
          <Row k="Rate" v={`Rp${fmtLE(order.exchange_rate_idr_per_le)}/LE`} />
          <Row k="Estimasi IDR" v={fmtIDR(order.estimated_total_idr)} />
        </Block>

        <Block title="Pembayaran & Pengiriman">
          <Row k="Metode Bayar" v={order.payment_method === "transfer" ? "Transfer" : "Cash"} />
          <Row k="Status Bayar" v={PAYMENT_STATUS[order.payment_status]?.label} />
          <Row k="Pengiriman" v={order.delivery_method === "delivery" ? "Delivery" : "Ambil di Toko"} />
          {order.delivery_zone_name && <Row k="Zona" v={order.delivery_zone_name} />}
        </Block>
      </div>
    </div>
  );
}

const Block = ({ title, children }) => (
  <div className="rounded-2xl border border-[#E5DCC5] bg-white p-5 shadow-sm"><div className="mb-2 font-heading text-sm font-bold uppercase tracking-wide text-[#8B5A2B]">{title}</div><div className="space-y-1">{children}</div></div>
);
const Row = ({ k, v }) => (<div className="flex justify-between gap-4 text-sm"><span className="shrink-0 text-[#8B7355]">{k}</span><span className="break-all text-right font-medium text-[#2C1E16]">{v}</span></div>);
