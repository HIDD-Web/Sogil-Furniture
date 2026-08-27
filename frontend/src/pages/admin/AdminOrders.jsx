import React, { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import api from "../../lib/api";
import { fmtLE } from "../../lib/format";
import { ORDER_STATUS, PAYMENT_STATUS } from "../../lib/constants";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { useAuth } from "../../context/AuthContext";
import { Trash2, Search } from "lucide-react";
import { toast } from "sonner";

export default function AdminOrders() {
  const { user } = useAuth();
  const canDelete = user?.role === "owner" || user?.permissions?.delete_data;
  const [orders, setOrders] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [appliedQ, setAppliedQ] = useState("");
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const status = params.get("status");
  const payment = params.get("payment_status");

  useEffect(() => {
    setLoading(true);
    const q = {};
    if (status) q.status = status;
    if (payment) q.payment_status = payment;
    if (appliedQ) q.q = appliedQ;
    api.get("/admin/orders", { params: q }).then((r) => setOrders(r.data)).finally(() => setLoading(false));
  }, [status, payment, appliedQ]);

  const activeFilter = status ? ORDER_STATUS[status]?.label : payment ? PAYMENT_STATUS[payment]?.label : null;

  const del = async (e, o) => {
    e.stopPropagation();
    const paid = o.payment_status === "lunas";
    const msg = paid ? `Pesanan ${o.order_number} sudah LUNAS. Menghapus akan membalik pendapatan otomatis terkait. Lanjutkan?` : `Hapus pesanan ${o.order_number}? Tindakan ini tidak dapat dibatalkan.`;
    if (!window.confirm(msg)) return;
    try { await api.delete(`/admin/orders/${o.id}`); toast.success("Pesanan dihapus"); setOrders((prev) => prev.filter((x) => x.id !== o.id)); }
    catch (err) { toast.error(err.response?.data?.detail || "Gagal menghapus"); }
  };

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h1 className="font-heading text-2xl font-bold text-[#2C1E16]">Pesanan</h1>
          <p className="mt-1 text-sm text-[#8B7355]">{orders.length} pesanan{activeFilter ? ` · Filter: ${activeFilter}` : ""}</p>
        </div>
        {activeFilter && <Button variant="outline" onClick={() => setParams({})} data-testid="clear-filter" className="rounded-xl border-[#8B5A2B] text-[#8B5A2B]">Hapus Filter</Button>}
      </div>

      <div className="mt-4 flex max-w-md gap-2">
        <div className="relative flex-1">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#8B7355]" />
          <Input value={search} onChange={(e) => setSearch(e.target.value)} onKeyDown={(e) => e.key === "Enter" && setAppliedQ(search.trim())}
            placeholder="Cari No. Pesanan, nama, HP, produk, username, kode referral..." data-testid="order-search" className="bg-white pl-9" />
        </div>
        <Button onClick={() => setAppliedQ(search.trim())} data-testid="order-search-btn" className="rounded-xl bg-[#8B5A2B] hover:bg-[#6B4423]">Cari</Button>
        {appliedQ && <Button variant="outline" onClick={() => { setSearch(""); setAppliedQ(""); }} data-testid="order-search-clear" className="rounded-xl border-[#E5DCC5] text-[#5C4A3D]">Reset</Button>}
      </div>

      {loading ? <div className="mt-8 text-[#8B7355]">Memuat...</div> : orders.length === 0 ? (
        <div className="mt-8 rounded-2xl border border-dashed border-[#E5DCC5] bg-white p-10 text-center text-[#8B7355]">Belum ada pesanan.</div>
      ) : (
        <div className="mt-6 overflow-hidden rounded-2xl border border-[#E5DCC5] bg-white shadow-sm">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-[#F1EBE0] text-left text-xs uppercase tracking-wide text-[#8B7355]">
                <tr><th className="px-4 py-3">No. Pesanan</th><th className="px-4 py-3">Tanggal</th><th className="px-4 py-3">Customer</th><th className="px-4 py-3">Produk</th><th className="px-4 py-3">Kirim</th><th className="px-4 py-3">Total</th><th className="px-4 py-3">Bayar</th><th className="px-4 py-3">Status</th>{canDelete && <th className="px-4 py-3"></th>}</tr>
              </thead>
              <tbody>
                {orders.map((o) => (
                  <tr key={o.id} onClick={() => navigate(`/admin/orders/${o.id}`)} data-testid={`order-row-${o.order_number}`} className="cursor-pointer border-t border-[#F1EBE0] hover:bg-[#FBF9F4]">
                    <td className="px-4 py-3 font-medium text-[#8B5A2B]">{o.order_number}</td>
                    <td className="px-4 py-3 text-[#5C4A3D]">{new Date(o.created_at).toLocaleDateString("id-ID")}</td>
                    <td className="px-4 py-3 text-[#2C1E16]">{o.customer_name}</td>
                    <td className="px-4 py-3 text-[#5C4A3D]">{(o.items || [o.item]).map((it) => it?.product_name_snapshot).join(", ")}</td>
                    <td className="px-4 py-3 text-[#5C4A3D]">{o.delivery_method === "delivery" ? (o.delivery_zone_name || "Delivery") : "Ambil"}</td>
                    <td className="px-4 py-3 font-medium text-[#2C1E16]">{fmtLE(o.total_le)} LE</td>
                    <td className="px-4 py-3"><Badge variant="outline" className={PAYMENT_STATUS[o.payment_status]?.color}>{PAYMENT_STATUS[o.payment_status]?.label}</Badge></td>
                    <td className="px-4 py-3"><Badge variant="outline" className={ORDER_STATUS[o.order_status]?.color}>{ORDER_STATUS[o.order_status]?.label}</Badge></td>
                    {canDelete && <td className="px-4 py-3"><button onClick={(e) => del(e, o)} data-testid={`delete-order-${o.order_number}`} className="p-1 text-red-500 hover:text-red-700"><Trash2 size={16} /></button></td>}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
