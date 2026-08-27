import React, { useEffect, useState } from "react";
import api from "../../lib/api";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../../components/ui/select";
import { CATEGORY_LABELS } from "../../lib/constants";

export default function AdminAnalytics() {
  const [rows, setRows] = useState([]);
  const [category, setCategory] = useState("all");
  const [groupBy, setGroupBy] = useState("full");

  useEffect(() => {
    const params = { group_by: groupBy };
    if (category !== "all") params.category = category;
    api.get("/admin/analytics/top-configs", { params }).then((r) => setRows(r.data));
  }, [category, groupBy]);

  return (
    <div>
      <h1 className="font-heading text-2xl font-bold text-[#2C1E16]">Analitik Pesanan</h1>
      <p className="mt-1 text-sm text-[#8B7355]">Konfigurasi produk yang paling sering dipesan.</p>

      <div className="mt-5 flex flex-wrap gap-3">
        <Select value={category} onValueChange={setCategory}>
          <SelectTrigger data-testid="analytics-category" className="w-48 bg-white"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">Semua Kategori</SelectItem>
            {["rak", "meja", "meja_rak"].map((c) => <SelectItem key={c} value={c}>{CATEGORY_LABELS[c]}</SelectItem>)}
          </SelectContent>
        </Select>
        <Select value={groupBy} onValueChange={setGroupBy}>
          <SelectTrigger data-testid="analytics-groupby" className="w-48 bg-white"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="full">Konfigurasi Lengkap</SelectItem>
            <SelectItem value="length">Panjang</SelectItem>
            <SelectItem value="level">Jumlah Tingkat</SelectItem>
            <SelectItem value="type">Tipe</SelectItem>
            <SelectItem value="finishing">Finishing</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {rows.length === 0 ? (
        <div className="mt-8 rounded-2xl border border-dashed border-[#E5DCC5] bg-white p-10 text-center text-[#8B7355]">Belum ada data pesanan.</div>
      ) : (
        <div className="mt-6 overflow-hidden rounded-2xl border border-[#E5DCC5] bg-white shadow-sm">
          <table className="w-full text-sm">
            <thead className="bg-[#F1EBE0] text-left text-xs uppercase tracking-wide text-[#8B7355]"><tr><th className="px-4 py-3">Konfigurasi</th><th className="px-4 py-3">Pesanan</th><th className="px-4 py-3">Qty</th><th className="px-4 py-3">Share</th></tr></thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i} className="border-t border-[#F1EBE0]" data-testid={`analytics-row-${i}`}>
                  <td className="px-4 py-3 font-medium text-[#2C1E16]">{r.key}</td>
                  <td className="px-4 py-3 text-[#5C4A3D]">{r.orders}</td>
                  <td className="px-4 py-3 text-[#5C4A3D]">{r.quantity}</td>
                  <td className="px-4 py-3"><div className="flex items-center gap-2"><div className="h-2 w-24 rounded-full bg-[#EFE6D5]"><div className="h-2 rounded-full bg-[#8B5A2B]" style={{ width: `${r.share}%` }} /></div><span className="text-xs text-[#8B7355]">{r.share}%</span></div></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
