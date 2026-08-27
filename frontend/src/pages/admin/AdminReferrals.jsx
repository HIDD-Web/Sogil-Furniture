import React, { useEffect, useState } from "react";
import api from "../../lib/api";
import { fmtLE } from "../../lib/format";
import { Input } from "../../components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../../components/ui/select";
import { toast } from "sonner";

export default function AdminReferrals() {
  const [list, setList] = useState([]);
  const [enabled, setEnabled] = useState(true);
  const load = () => api.get("/admin/referrals").then((r) => setList(r.data));
  useEffect(() => { load(); api.get("/store-info").then((r) => setEnabled(r.data.referral_program_enabled)); }, []);

  const upd = async (r, patch) => { await api.put(`/admin/referrals/${r.id}`, patch); load(); };
  const toggleProgram = async (v) => { await api.put("/admin/settings", { referral_program_enabled: v }); setEnabled(v); toast.success("Pengaturan disimpan"); };

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="font-heading text-2xl font-bold text-[#2C1E16]">Referral</h1>
        <label className="flex items-center gap-2 rounded-xl border border-[#E5DCC5] bg-white px-3 py-2 text-sm">
          Program Referral
          <Select value={enabled ? "on" : "off"} onValueChange={(v) => toggleProgram(v === "on")}><SelectTrigger data-testid="referral-toggle" className="h-8 w-24 bg-white"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="on">Aktif</SelectItem><SelectItem value="off">Nonaktif</SelectItem></SelectContent></Select>
        </label>
      </div>
      <p className="mt-1 text-sm text-[#8B7355]">Kode referral dibuat otomatis untuk setiap pelanggan. Atur diskon, poin, dan batas di sini.</p>

      {list.length === 0 ? <div className="mt-6 rounded-2xl border border-dashed border-[#E5DCC5] bg-white p-10 text-center text-[#8B7355]">Belum ada pelanggan/kode referral.</div> : (
        <div className="mt-6 overflow-x-auto rounded-2xl border border-[#E5DCC5] bg-white shadow-sm">
          <table className="w-full text-sm">
            <thead className="bg-[#F1EBE0] text-left text-xs uppercase text-[#8B7355]"><tr><th className="px-3 py-3">Kode</th><th className="px-3 py-3">Pemilik</th><th className="px-3 py-3">Diskon %</th><th className="px-3 py-3">Maks LE</th><th className="px-3 py-3">Poin/Order</th><th className="px-3 py-3">Klaim</th><th className="px-3 py-3">Poin</th><th className="px-3 py-3">Berakhir</th><th className="px-3 py-3">Status</th></tr></thead>
            <tbody>
              {list.map((r) => (
                <tr key={r.id} className="border-t border-[#F1EBE0]" data-testid={`referral-row-${r.code}`}>
                  <td className="px-3 py-2 font-mono font-medium text-[#8B5A2B]">{r.code}</td>
                  <td className="px-3 py-2 text-[#2C1E16]">{r.owner_name}</td>
                  <td className="px-3 py-2"><Input type="number" defaultValue={r.discount_percentage} onBlur={(e) => Number(e.target.value) !== r.discount_percentage && upd(r, { discount_percentage: Number(e.target.value) })} className="h-9 w-20 bg-white" /></td>
                  <td className="px-3 py-2"><Input type="number" defaultValue={r.max_discount_le} onBlur={(e) => Number(e.target.value) !== r.max_discount_le && upd(r, { max_discount_le: Number(e.target.value) })} className="h-9 w-24 bg-white" /></td>
                  <td className="px-3 py-2"><Input type="number" defaultValue={r.points_per_order} onBlur={(e) => Number(e.target.value) !== r.points_per_order && upd(r, { points_per_order: Number(e.target.value) })} className="h-9 w-20 bg-white" /></td>
                  <td className="px-3 py-2 text-[#5C4A3D]">{r.claims || 0}</td>
                  <td className="px-3 py-2 text-[#5C4A3D]">{fmtLE(r.points_awarded || 0)}</td>
                  <td className="px-3 py-2"><Input type="date" defaultValue={r.end_date || ""} onBlur={(e) => e.target.value !== (r.end_date || "") && upd(r, { end_date: e.target.value })} className="h-9 w-36 bg-white" /></td>
                  <td className="px-3 py-2"><Select value={r.status} onValueChange={(v) => upd(r, { status: v })}><SelectTrigger className="h-9 w-28 bg-white" data-testid={`ref-status-${r.code}`}><SelectValue /></SelectTrigger><SelectContent><SelectItem value="active">Aktif</SelectItem><SelectItem value="inactive">Nonaktif</SelectItem><SelectItem value="expired">Kedaluwarsa</SelectItem></SelectContent></Select></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
