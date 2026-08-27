import React, { useEffect, useState } from "react";
import api from "../../lib/api";
import { fmtLE } from "../../lib/format";
import { useAuth } from "../../context/AuthContext";
import { Input } from "../../components/ui/input";
import { Button } from "../../components/ui/button";
import { toast } from "sonner";
import { Search } from "lucide-react";

export default function AdminCustomers() {
  const { user } = useAuth();
  const isOwner = user?.role === "owner";
  const [list, setList] = useState([]);
  const [q, setQ] = useState("");
  const [detail, setDetail] = useState(null);
  const [adj, setAdj] = useState({ amount: "", reason: "" });

  const load = () => api.get("/admin/customers", { params: q ? { q } : {} }).then((r) => setList(r.data));
  useEffect(() => { load(); }, []);
  const open = (c) => api.get(`/admin/customers/${c.id}`).then((r) => setDetail(r.data));
  const doAdjust = async () => {
    if (!adj.amount || !adj.reason) return toast.error("Isi jumlah & alasan");
    try { await api.post(`/admin/customers/${detail.customer.id}/adjust-points`, { amount: Number(adj.amount), reason: adj.reason }); toast.success("Poin disesuaikan"); setAdj({ amount: "", reason: "" }); open({ id: detail.customer.id }); }
    catch (e) { toast.error(e.response?.data?.detail || "Gagal"); }
  };

  return (
    <div>
      <h1 className="font-heading text-2xl font-bold text-[#2C1E16]">Pelanggan</h1>
      <div className="mt-4 flex gap-2">
        <div className="relative flex-1 max-w-sm"><Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#8B7355]" /><Input value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === "Enter" && load()} placeholder="Cari username / no HP" data-testid="customer-search" className="bg-white pl-9" /></div>
        <Button onClick={load} className="rounded-xl bg-[#8B5A2B] hover:bg-[#6B4423]">Cari</Button>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <div className="overflow-hidden rounded-2xl border border-[#E5DCC5] bg-white shadow-sm">
          {list.length === 0 ? <div className="p-8 text-center text-[#8B7355]">Belum ada pelanggan.</div> : (
            <table className="w-full text-sm"><tbody>
              {list.map((c) => (
                <tr key={c.id} onClick={() => open(c)} data-testid={`customer-row-${c.id}`} className="cursor-pointer border-t border-[#F1EBE0] first:border-0 hover:bg-[#FBF9F4]">
                  <td className="px-4 py-3"><div className="font-medium text-[#2C1E16]">{c.username}</div><div className="text-xs text-[#8B7355]">{c.phone}</div></td>
                  <td className="px-4 py-3 text-right"><div className="text-xs text-[#8B7355]">Poin</div><div className="font-semibold text-[#8B5A2B]">{fmtLE(c.points_available)}</div></td>
                </tr>
              ))}
            </tbody></table>
          )}
        </div>

        {detail && (
          <div className="rounded-2xl border border-[#E5DCC5] bg-white p-5 shadow-sm" data-testid="customer-detail">
            <div className="font-heading text-lg font-bold text-[#2C1E16]">{detail.customer.username}</div>
            <div className="text-sm text-[#8B7355]">{detail.customer.phone} · Kode: {detail.customer.referral_code}</div>
            <div className="mt-2 flex gap-4 text-sm"><span>Poin: <b className="text-[#8B5A2B]">{fmtLE(detail.customer.points_available)}</b></span><span>Order: <b>{detail.orders.length}</b></span></div>
            {isOwner && (
              <div className="mt-3 rounded-xl bg-[#FBF9F4] p-3">
                <div className="mb-2 text-xs font-semibold text-[#8B5A2B]">Sesuaikan Poin (Owner)</div>
                <div className="flex gap-2"><Input type="number" placeholder="+/- poin" value={adj.amount} onChange={(e) => setAdj({ ...adj, amount: e.target.value })} data-testid="adjust-points-amount" className="w-28 bg-white" /><Input placeholder="Alasan" value={adj.reason} onChange={(e) => setAdj({ ...adj, reason: e.target.value })} data-testid="adjust-points-reason" className="flex-1 bg-white" /><Button onClick={doAdjust} data-testid="adjust-points-save" className="rounded-xl bg-[#8B5A2B]">Simpan</Button></div>
              </div>
            )}
            <div className="mt-3 text-sm font-semibold text-[#2C1E16]">Riwayat Pesanan</div>
            <div className="mt-1 max-h-64 space-y-1 overflow-y-auto">
              {detail.orders.map((o) => <div key={o.id} className="flex justify-between text-sm"><span className="text-[#5C4A3D]">{o.order_number}</span><span className="font-medium">{fmtLE(o.total_le)} LE</span></div>)}
              {detail.orders.length === 0 && <div className="text-xs text-[#8B7355]">Belum ada pesanan.</div>}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
