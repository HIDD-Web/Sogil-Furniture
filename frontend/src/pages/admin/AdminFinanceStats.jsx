import React, { useEffect, useState } from "react";
import api from "../../lib/api";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../../components/ui/select";
import { Input } from "../../components/ui/input";

const money = (v, cur) => (cur === "IDR" ? "Rp" : "") + Math.round(Number(v) || 0).toLocaleString("de-DE") + (cur === "EGP" ? " LE" : "");
const PERIODS = [["this_month", "Bulan Ini"], ["last_month", "Bulan Lalu"], ["last_3_months", "3 Bulan Terakhir"], ["this_year", "Tahun Ini"], ["last_year", "Tahun Lalu"], ["custom", "Kustom"]];

export default function AdminFinanceStats() {
  const [period, setPeriod] = useState("this_month");
  const [range, setRange] = useState({ start: "", end: "" });
  const [currency, setCurrency] = useState("EGP");
  const [data, setData] = useState(null);

  useEffect(() => {
    const p = { period, currency };
    if (period === "custom") { p.start = range.start; p.end = range.end; }
    api.get("/admin/finance/statistics", { params: p }).then((r) => setData(r.data)).catch(() => setData(null));
  }, [period, currency, range.start, range.end]);

  const Table = ({ title, rows, cur }) => (
    <div className="rounded-2xl border border-[#E5DCC5] bg-white p-5 shadow-sm">
      <div className="mb-3 font-heading font-bold text-[#2C1E16]">{title}</div>
      {(!rows || rows.length === 0) ? <div className="text-sm text-[#8B7355]">Belum ada data pada periode ini.</div> : (
        <table className="w-full text-sm">
          <thead className="text-left text-xs uppercase text-[#8B7355]"><tr><th className="py-1">#</th><th>Kategori</th><th>Klasifikasi</th><th className="text-right">Total</th><th className="text-right">Transaksi</th><th className="text-right">%</th></tr></thead>
          <tbody>
            {rows.map((g, i) => (
              <tr key={i} className="border-t border-[#F1EBE0]" data-testid={`stat-row-${g.type}-${i}`}>
                <td className="py-1.5 text-[#8B7355]">{i + 1}</td>
                <td className="text-[#2C1E16]">{g.category}</td>
                <td><span className={`rounded-full px-2 py-0.5 text-xs ${g.classification === "transfer" ? "bg-amber-100 text-amber-700" : "bg-[#EFE6D5] text-[#8B5A2B]"}`}>{g.classification === "transfer" ? "Transfer" : g.classification === "revenue" ? "Revenue" : "Cost"}</span></td>
                <td className="text-right font-medium text-[#2C1E16]">{money(g.total, cur)}</td>
                <td className="text-right text-[#5C4A3D]">{g.count}</td>
                <td className="text-right text-[#8B7355]">{g.pct}%</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );

  const t = data?.totals || {};

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="font-heading text-2xl font-bold text-[#2C1E16]">Statistik Keuangan</h1>
        <div className="flex flex-wrap gap-2">
          <Select value={currency} onValueChange={setCurrency}><SelectTrigger data-testid="stat-currency" className="w-24 bg-white"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="EGP">EGP</SelectItem><SelectItem value="IDR">IDR</SelectItem></SelectContent></Select>
          <Select value={period} onValueChange={setPeriod}><SelectTrigger data-testid="stat-period" className="w-44 bg-white"><SelectValue /></SelectTrigger>
            <SelectContent>{PERIODS.map(([v, l]) => <SelectItem key={v} value={v}>{l}</SelectItem>)}</SelectContent></Select>
          {period === "custom" && (<>
            <Input type="date" value={range.start} onChange={(e) => setRange({ ...range, start: e.target.value })} className="w-40 bg-white" data-testid="stat-start" />
            <Input type="date" value={range.end} onChange={(e) => setRange({ ...range, end: e.target.value })} className="w-40 bg-white" data-testid="stat-end" />
          </>)}
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5" data-testid="stat-totals">
        {[["Revenue", t.revenue], ["Transfer Masuk", t.transfer_income], ["Cost", t.cost], ["Transfer Keluar", t.transfer_expense], ["Laba Operasi", t.operating_profit]].map(([l, v]) => (
          <div key={l} className="rounded-2xl border border-[#E5DCC5] bg-white p-4 shadow-sm">
            <div className="text-xs text-[#8B7355]">{l}</div>
            <div className="mt-1 font-heading text-lg font-bold text-[#8B5A2B]">{money(v || 0, currency)}</div>
          </div>
        ))}
      </div>

      <Table title="Pemasukan per Kategori" rows={data?.income} cur={currency} />
      <Table title="Pengeluaran per Kategori" rows={data?.expense} cur={currency} />
    </div>
  );
}
