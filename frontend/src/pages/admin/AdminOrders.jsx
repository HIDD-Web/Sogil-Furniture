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
    <div className="space-y-4 sm:space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h1 className="font-heading text-xl sm:text-2xl font-bold text-[#2C1E16]">Pesanan</h1>
          <p className="mt-0.5 text-xs sm:text-sm text-[#8B7355]">{orders.length} pesanan{activeFilter ? ` · Filter: ${activeFilter}` : ""}</p>
        </div>
        {activeFilter && <Button variant="outline" onClick={() => setParams({})} data-testid="clear-filter" className="rounded-xl border-[#8B5A2B] text-xs sm:text-sm text-[#8B5A2B]">Hapus Filter</Button>}
      </div>

      <div className="flex flex-wrap sm:flex-nowrap max-w-md gap-2">
        <div className="relative flex-1 min-w-[200px]">
          <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#8B7355]" />
          <Input value={search} onChange={(e) => setSearch(e.target.value)} onKeyDown={(e) => e.key === "Enter" && setAppliedQ(search.trim())}
            placeholder="Cari no. pesanan, customer..." data-testid="order-search" className="bg-white pl-8 text-xs sm:text-sm" />
        </div>
        <div className="flex gap-2">
          <Button onClick={() => setAppliedQ(search.trim())} data-testid="order-search-btn" className="rounded-xl bg-[#8B5A2B] text-xs sm:text-sm hover:bg-[#6B4423]">Cari</Button>
          {appliedQ && <Button variant="outline" onClick={() => { setSearch(""); setAppliedQ(""); }} data-testid="order-search-clear" className="rounded-xl border-[#E5DCC5] text-xs sm:text-sm text-[#5C4A3D]">Reset</Button>}
        </div>
      </div>

      {loading ? <div className="mt-6 text-sm text-[#8B7355]">Memuat...</div> : orders.length === 0 ? (
        <div className="mt-6 rounded-2xl border border-dashed border-[#E5DCC5] bg-white p-8 text-center text-sm text-[#8B7355]">Belum ada pesanan.</div>
      ) : (
        <>
          {/* Mobile View: Order Cards */}
          <div className="space-y-2.5 md:hidden">
            {orders.map((o) => (
              <div
                key={o.id}
                onClick={() => navigate(`/admin/orders/${o.id}`)}
                data-testid={`order-card-${o.order_number}`}
                className="cursor-pointer rounded-xl border border-[#E5DCC5] bg-white p-3.5 shadow-xs transition-shadow hover:shadow-sm"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="font-heading font-bold text-xs text-[#8B5A2B]">{o.order_number}</span>
                  <span className="text-[11px] text-[#8B7355]">{new Date(o.created_at).toLocaleDateString("id-ID")}</span>
                </div>

                <div className="mt-1.5 flex items-center justify-between gap-2">
                  <span className="font-medium text-sm text-[#2C1E16]">{o.customer_name}</span>
                  <span className="text-xs font-bold text-[#8B5A2B]">{fmtLE(o.total_le)} LE</span>
                </div>

                <p className="mt-1 text-xs text-[#5C4A3D] line-clamp-1">
                  {(o.items || [o.item]).map((it) => it?.product_name_snapshot).join(", ")}
                </p>

                <div className="mt-2.5 flex items-center justify-between border-t border-[#F1EBE0] pt-2">
                  <div className="flex flex-wrap gap-1.5">
                    <Badge variant="outline" className={`px-1.5 py-0 text-[10px] ${PAYMENT_STATUS[o.payment_status]?.color}`}>
                      {PAYMENT_STATUS[o.payment_status]?.label}
                    </Badge>
                    <Badge variant="outline" className={`px-1.5 py-0 text-[10px] ${ORDER_STATUS[o.order_status]?.color}`}>
                      {ORDER_STATUS[o.order_status]?.label}
                    </Badge>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-[11px] text-[#8B7355]">
                      {o.delivery_method === "delivery" ? (o.delivery_zone_name || "Delivery") : "Ambil"}
                    </span>
                    {canDelete && (
                      <button onClick={(e) => del(e, o)} data-testid={`delete-order-mobile-${o.order_number}`} className="p-0.5 text-red-500 hover:text-red-700">
                        <Trash2 size={14} />
                      </button>
                    )}
                  </div>
                </div>
              </div>
            ))}
          </div>

          {/* Desktop View: Full Table */}
          <div className="hidden md:block overflow-hidden rounded-2xl border border-[#E5DCC5] bg-white shadow-xs">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-[#F1EBE0] text-left text-xs uppercase tracking-wide text-[#8B7355]">
                  <tr>
                    <th className="px-4 py-3">No. Pesanan</th>
                    <th className="px-4 py-3">Tanggal</th>
                    <th className="px-4 py-3">Customer</th>
                    <th className="px-4 py-3">Produk</th>
                    <th className="px-4 py-3">Kirim</th>
                    <th className="px-4 py-3">Total</th>
                    <th className="px-4 py-3">Bayar</th>
                    <th className="px-4 py-3">Status</th>
                    {canDelete && <th className="px-4 py-3"></th>}
                  </tr>
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
        </>
      )}
    </div>
  );
}
