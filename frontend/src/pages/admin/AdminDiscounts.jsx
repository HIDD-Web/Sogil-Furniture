import React, { useEffect, useState } from "react";
import api from "../../lib/api";
import { formatApiError } from "../../lib/format";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../../components/ui/select";
import { Badge } from "../../components/ui/badge";
import { Plus, Trash2, Ticket } from "lucide-react";
import { toast } from "sonner";

const STATUS = { active: "bg-green-100 text-green-800 border-green-200", disabled: "bg-gray-100 text-gray-700 border-gray-200", expired: "bg-red-100 text-red-700 border-red-200" };

export default function AdminDiscounts() {
  const [list, setList] = useState([]);
  const [f, setF] = useState({ code: "", name: "", percentage: "", max_amount: "", max_claims: "", start_date: "", end_date: "", status: "active" });

  const load = () => api.get("/admin/discounts").then((r) => setList(r.data));
  useEffect(() => { load(); }, []);

  const create = async () => {
    if (!f.code || !f.percentage) return toast.error("Isi kode & persentase");
    try { await api.post("/admin/discounts", f); toast.success("Diskon dibuat"); setF({ code: "", name: "", percentage: "", max_amount: "", max_claims: "", start_date: "", end_date: "", status: "active" }); load(); }
    catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };
  const upd = async (d, patch) => { await api.put(`/admin/discounts/${d.id}`, patch); load(); };
  const del = async (d) => { if (!window.confirm(`Hapus diskon ${d.code}?`)) return; await api.delete(`/admin/discounts/${d.id}`); load(); };

  return (
    <div className="space-y-6">
      <h1 className="font-heading text-2xl font-bold text-[#2C1E16]">Kode Diskon</h1>

      <div className="rounded-2xl border border-[#E5DCC5] bg-white p-5 shadow-sm">
        <div className="mb-3 flex items-center gap-2 font-heading font-bold text-[#2C1E16]"><Ticket size={18} /> Buat Diskon</div>
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          <div><Label className="mb-1 block text-xs">Kode</Label><Input value={f.code} onChange={(e) => setF({ ...f, code: e.target.value })} data-testid="disc-code" className="bg-white" /></div>
          <div><Label className="mb-1 block text-xs">Nama/Deskripsi</Label><Input value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} data-testid="disc-name" className="bg-white" /></div>
          <div><Label className="mb-1 block text-xs">Persentase (%)</Label><Input type="number" value={f.percentage} onChange={(e) => setF({ ...f, percentage: e.target.value })} data-testid="disc-pct" className="bg-white" /></div>
          <div><Label className="mb-1 block text-xs">Maks Potongan (LE)</Label><Input type="number" value={f.max_amount} onChange={(e) => setF({ ...f, max_amount: e.target.value })} data-testid="disc-max" className="bg-white" /></div>
          <div><Label className="mb-1 block text-xs">Maks Klaim</Label><Input type="number" value={f.max_claims} onChange={(e) => setF({ ...f, max_claims: e.target.value })} data-testid="disc-claims" className="bg-white" /></div>
          <div><Label className="mb-1 block text-xs">Status</Label><Select value={f.status} onValueChange={(v) => setF({ ...f, status: v })}><SelectTrigger className="bg-white"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="active">Aktif</SelectItem><SelectItem value="disabled">Nonaktif</SelectItem></SelectContent></Select></div>
          <div><Label className="mb-1 block text-xs">Mulai</Label><Input type="date" value={f.start_date} onChange={(e) => setF({ ...f, start_date: e.target.value })} className="bg-white" /></div>
          <div><Label className="mb-1 block text-xs">Berakhir</Label><Input type="date" value={f.end_date} onChange={(e) => setF({ ...f, end_date: e.target.value })} className="bg-white" /></div>
        </div>
        <Button onClick={create} data-testid="create-discount" className="mt-3 rounded-xl bg-[#8B5A2B] hover:bg-[#6B4423]"><Plus size={16} className="mr-1" /> Buat Diskon</Button>
      </div>

      {list.length === 0 ? <div className="rounded-2xl border border-dashed border-[#E5DCC5] bg-white p-10 text-center text-[#8B7355]">Belum ada kode diskon.</div> : (
        <div className="overflow-hidden rounded-2xl border border-[#E5DCC5] bg-white shadow-sm">
          <table className="w-full text-sm">
            <thead className="bg-[#F1EBE0] text-left text-xs uppercase text-[#8B7355]"><tr><th className="px-4 py-3">Kode</th><th className="px-4 py-3">%</th><th className="px-4 py-3">Maks</th><th className="px-4 py-3">Klaim</th><th className="px-4 py-3">Berlaku</th><th className="px-4 py-3">Status</th><th className="px-4 py-3"></th></tr></thead>
            <tbody>
              {list.map((d) => (
                <tr key={d.id} className="border-t border-[#F1EBE0]" data-testid={`discount-row-${d.code}`}>
                  <td className="px-4 py-3 font-medium text-[#8B5A2B]">{d.code}<div className="text-xs font-normal text-[#8B7355]">{d.name}</div></td>
                  <td className="px-4 py-3">{d.percentage}%</td>
                  <td className="px-4 py-3">{d.max_amount ? `${d.max_amount} LE` : "-"}</td>
                  <td className="px-4 py-3">{d.claims || 0}{d.max_claims ? `/${d.max_claims}` : ""}</td>
                  <td className="px-4 py-3 text-xs text-[#5C4A3D]">{d.start_date || "-"} → {d.end_date || "-"}</td>
                  <td className="px-4 py-3">
                    <Select value={d.status} onValueChange={(v) => upd(d, { status: v })}><SelectTrigger className="h-8 w-28 bg-white" data-testid={`disc-status-${d.code}`}><SelectValue /></SelectTrigger><SelectContent><SelectItem value="active">Aktif</SelectItem><SelectItem value="disabled">Nonaktif</SelectItem><SelectItem value="expired">Kedaluwarsa</SelectItem></SelectContent></Select>
                  </td>
                  <td className="px-4 py-3"><button onClick={() => del(d)} data-testid={`del-discount-${d.code}`} className="p-1 text-red-500"><Trash2 size={16} /></button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
