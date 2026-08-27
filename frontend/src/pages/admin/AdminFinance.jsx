import React, { useEffect, useState } from "react";
import api from "../../lib/api";
import { formatApiError } from "../../lib/format";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Textarea } from "../../components/ui/textarea";
import { Label } from "../../components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../../components/ui/select";
import { Trash2, ArrowRightLeft, TrendingUp, TrendingDown } from "lucide-react";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Legend } from "recharts";
import { toast } from "sonner";

const money = (v, cur) => (cur === "IDR" ? "Rp" : "") + Math.round(Number(v) || 0).toLocaleString("de-DE") + (cur === "EGP" ? " LE" : "");
const PERIODS = [["this_month", "Bulan Ini"], ["last_month", "Bulan Lalu"], ["this_year", "Tahun Ini"], ["last_year", "Tahun Lalu"], ["custom", "Kustom"]];

export default function AdminFinance() {
  const [stats, setStats] = useState(null);
  const [txns, setTxns] = useState([]);
  const [cats, setCats] = useState({ income: [], expense: [] });
  const [period, setPeriod] = useState("this_month");
  const [range, setRange] = useState({ start: "", end: "" });
  const [form, setForm] = useState({ type: "expense", category: "", amount: "", currency: "EGP", description: "", date: "" });
  const [xfer, setXfer] = useState({ from_account: "IDR", to_account: "EGP", from_amount: "", to_amount: "", exchange_rate: "", description: "", date: "" });
  const [adj, setAdj] = useState({ account: "EGP", new_balance: "", description: "" });
  const [newCat, setNewCat] = useState({ name: "", type: "expense" });
  const [chart, setChart] = useState({ currency: "EGP", year: new Date().getFullYear(), data: [] });

  const loadStats = () => {
    const p = { period };
    if (period === "custom") { p.start = range.start; p.end = range.end; }
    api.get("/admin/finance/stats", { params: p }).then((r) => setStats(r.data));
  };
  const loadTxns = () => api.get("/admin/finance/transactions").then((r) => setTxns(r.data));
  useEffect(() => { api.get("/admin/finance/categories").then((r) => setCats(r.data)); loadTxns(); }, []);
  useEffect(() => { loadStats(); }, [period, range.start, range.end]);
  useEffect(() => {
    api.get("/admin/finance/monthly", { params: { year: chart.year, currency: chart.currency } })
      .then((r) => setChart((c) => ({ ...c, data: r.data.months.map((m) => ({ name: m.label.slice(5), Revenue: Math.round(m.revenue), Profit: Math.round(m.profit) })) })));
  }, [chart.currency, chart.year]);

  const addTxn = async () => {
    if (!form.category || !form.amount) return toast.error("Lengkapi kategori & jumlah");
    try { await api.post("/admin/finance/transactions", { ...form, amount: Number(form.amount) }); toast.success("Transaksi ditambahkan"); setForm({ ...form, amount: "", description: "" }); loadTxns(); loadStats(); }
    catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };
  const addXfer = async () => {
    if (!xfer.from_amount || !xfer.to_amount) return toast.error("Lengkapi jumlah transfer");
    try { await api.post("/admin/finance/transfer", { ...xfer, from_amount: Number(xfer.from_amount), to_amount: Number(xfer.to_amount), exchange_rate: xfer.exchange_rate ? Number(xfer.exchange_rate) : null }); toast.success("Transfer dicatat"); setXfer({ ...xfer, from_amount: "", to_amount: "", exchange_rate: "" }); loadTxns(); loadStats(); }
    catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };
  const del = async (id) => { if (!window.confirm("Hapus transaksi?")) return; await api.delete(`/admin/finance/transactions/${id}`); loadTxns(); loadStats(); };
  const setBalance = async () => {
    if (adj.new_balance === "") return toast.error("Isi saldo baru");
    try { await api.post("/admin/finance/balance-adjust", { ...adj, new_balance: Number(adj.new_balance) }); toast.success("Saldo disesuaikan"); setAdj({ ...adj, new_balance: "", description: "" }); loadStats(); loadTxns(); }
    catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };
  const addCat = async () => {
    if (!newCat.name) return toast.error("Isi nama kategori");
    try { await api.post("/admin/finance/custom-categories", newCat); toast.success("Kategori ditambahkan"); setNewCat({ name: "", type: "expense" }); api.get("/admin/finance/categories").then((r) => setCats(r.data)); }
    catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };

  const Cmp = ({ v }) => v == null ? null : (
    <span className={`ml-2 inline-flex items-center text-xs font-medium ${v >= 0 ? "text-green-600" : "text-red-600"}`}>{v >= 0 ? <TrendingUp size={12} /> : <TrendingDown size={12} />} {v >= 0 ? "+" : ""}{v}%</span>
  );

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="font-heading text-2xl font-bold text-[#2C1E16]">Keuangan</h1>
        <div className="flex flex-wrap gap-2">
          <Select value={period} onValueChange={setPeriod}><SelectTrigger data-testid="finance-period" className="w-40 bg-white"><SelectValue /></SelectTrigger>
            <SelectContent>{PERIODS.map(([v, l]) => <SelectItem key={v} value={v}>{l}</SelectItem>)}</SelectContent></Select>
          {period === "custom" && (<>
            <Input type="date" value={range.start} onChange={(e) => setRange({ ...range, start: e.target.value })} className="w-40 bg-white" data-testid="finance-start" />
            <Input type="date" value={range.end} onChange={(e) => setRange({ ...range, end: e.target.value })} className="w-40 bg-white" data-testid="finance-end" />
          </>)}
        </div>
      </div>

      {/* Balances */}
      <div className="grid gap-4 sm:grid-cols-2">
        {["EGP", "IDR"].map((cur) => (
          <div key={cur} className="rounded-2xl border border-[#E5DCC5] bg-white p-5 shadow-sm" data-testid={`balance-${cur}`}>
            <div className="text-sm text-[#8B7355]">Saldo Akun {cur}</div>
            <div className="mt-1 font-heading text-3xl font-bold text-[#8B5A2B]">{money(stats?.balances?.[cur] || 0, cur)}</div>
          </div>
        ))}
      </div>

      {/* Stats per currency */}
      <div className="grid gap-4 sm:grid-cols-2">
        {["EGP", "IDR"].map((cur) => {
          const c = stats?.current?.[cur]; const cmp = stats?.comparison?.[cur];
          return (
            <div key={cur} className="rounded-2xl border border-[#E5DCC5] bg-white p-5 shadow-sm">
              <div className="font-heading font-bold text-[#2C1E16]">Statistik {cur}</div>
              <div className="mt-3 space-y-2 text-sm">
                <div className="flex justify-between"><span className="text-[#5C4A3D]">Pendapatan</span><span className="font-medium">{money(c?.revenue || 0, cur)}<Cmp v={cmp?.revenue} /></span></div>
                <div className="flex justify-between"><span className="text-[#5C4A3D]">Biaya</span><span className="font-medium">{money(c?.cost || 0, cur)}<Cmp v={cmp?.cost} /></span></div>
                <div className="flex justify-between border-t border-dashed border-[#E5DCC5] pt-2"><span className="text-[#5C4A3D]">Laba Operasi</span><span className="font-bold text-[#8B5A2B]">{money(c?.operating_profit || 0, cur)}<Cmp v={cmp?.operating_profit} /></span></div>
                <div className="flex justify-between"><span className="text-[#5C4A3D]">Arus Kas</span><span className="font-medium">{money(c?.cash_flow || 0, cur)}</span></div>
              </div>
            </div>
          );
        })}
      </div>

      {/* Add transaction + transfer */}
      <div className="grid gap-4 lg:grid-cols-2">
        <div className="rounded-2xl border border-[#E5DCC5] bg-white p-5 shadow-sm">
          <div className="mb-3 font-heading font-bold text-[#2C1E16]">Catat Transaksi</div>
          <div className="grid grid-cols-2 gap-2">
            <Select value={form.type} onValueChange={(v) => setForm({ ...form, type: v, category: "" })}><SelectTrigger data-testid="txn-type" className="bg-white"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="income">Pemasukan</SelectItem><SelectItem value="expense">Pengeluaran</SelectItem></SelectContent></Select>
            <Select value={form.currency} onValueChange={(v) => setForm({ ...form, currency: v })}><SelectTrigger data-testid="txn-currency" className="bg-white"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="EGP">EGP</SelectItem><SelectItem value="IDR">IDR</SelectItem></SelectContent></Select>
          </div>
          <Select value={form.category} onValueChange={(v) => setForm({ ...form, category: v })}><SelectTrigger data-testid="txn-category" className="mt-2 bg-white"><SelectValue placeholder="Kategori" /></SelectTrigger><SelectContent>{(cats[form.type] || []).map((c) => <SelectItem key={c} value={c}>{c}</SelectItem>)}</SelectContent></Select>
          <Input type="number" placeholder="Jumlah" value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })} data-testid="txn-amount" className="mt-2 bg-white" />
          <Textarea placeholder="Deskripsi (opsional)" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} className="mt-2 bg-white" />
          <Button onClick={addTxn} data-testid="txn-save" className="mt-2 w-full rounded-xl bg-[#8B5A2B] hover:bg-[#6B4423]">Simpan Transaksi</Button>
        </div>

        <div className="rounded-2xl border border-[#E5DCC5] bg-white p-5 shadow-sm">
          <div className="mb-3 flex items-center gap-2 font-heading font-bold text-[#2C1E16]"><ArrowRightLeft size={18} /> Transfer / Konversi</div>
          <div className="grid grid-cols-2 gap-2">
            <Select value={xfer.from_account} onValueChange={(v) => setXfer({ ...xfer, from_account: v })}><SelectTrigger data-testid="xfer-from" className="bg-white"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="IDR">Dari IDR</SelectItem><SelectItem value="EGP">Dari EGP</SelectItem></SelectContent></Select>
            <Select value={xfer.to_account} onValueChange={(v) => setXfer({ ...xfer, to_account: v })}><SelectTrigger data-testid="xfer-to" className="bg-white"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="EGP">Ke EGP</SelectItem><SelectItem value="IDR">Ke IDR</SelectItem></SelectContent></Select>
          </div>
          <Input type="number" placeholder="Jumlah keluar" value={xfer.from_amount} onChange={(e) => setXfer({ ...xfer, from_amount: e.target.value })} data-testid="xfer-from-amount" className="mt-2 bg-white" />
          <Input type="number" placeholder="Jumlah diterima" value={xfer.to_amount} onChange={(e) => setXfer({ ...xfer, to_amount: e.target.value })} data-testid="xfer-to-amount" className="mt-2 bg-white" />
          <Input type="number" placeholder="Rate (opsional)" value={xfer.exchange_rate} onChange={(e) => setXfer({ ...xfer, exchange_rate: e.target.value })} className="mt-2 bg-white" />
          <Button onClick={addXfer} data-testid="xfer-save" className="mt-2 w-full rounded-xl bg-[#8B5A2B] hover:bg-[#6B4423]">Catat Transfer</Button>
        </div>
      </div>

      {/* Monthly charts */}
      <div className="rounded-2xl border border-[#E5DCC5] bg-white p-5 shadow-sm" data-testid="finance-chart">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <div className="font-heading font-bold text-[#2C1E16]">Pendapatan & Laba Bulanan</div>
          <div className="flex gap-2">
            <Select value={chart.currency} onValueChange={(v) => setChart({ ...chart, currency: v })}><SelectTrigger data-testid="chart-currency" className="w-24 bg-white"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="EGP">EGP</SelectItem><SelectItem value="IDR">IDR</SelectItem></SelectContent></Select>
            <Select value={String(chart.year)} onValueChange={(v) => setChart({ ...chart, year: Number(v) })}><SelectTrigger data-testid="chart-year" className="w-28 bg-white"><SelectValue /></SelectTrigger><SelectContent>{[0, 1, 2].map((d) => { const y = new Date().getFullYear() - d; return <SelectItem key={y} value={String(y)}>{y}</SelectItem>; })}</SelectContent></Select>
          </div>
        </div>
        <div style={{ width: "100%", height: 260 }}>
          <ResponsiveContainer>
            <BarChart data={chart.data} margin={{ top: 8, right: 8, left: 8, bottom: 0 }}>
              <XAxis dataKey="name" tick={{ fontSize: 11, fill: "#8B7355" }} />
              <YAxis tick={{ fontSize: 11, fill: "#8B7355" }} width={48} />
              <Tooltip />
              <Legend />
              <Bar dataKey="Revenue" fill="#8B5A2B" radius={[4, 4, 0, 0]} />
              <Bar dataKey="Profit" fill="#C9A86A" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Balance adjust + custom category */}
      <div className="grid gap-4 lg:grid-cols-2">
        <div className="rounded-2xl border border-[#E5DCC5] bg-white p-5 shadow-sm">
          <div className="mb-3 font-heading font-bold text-[#2C1E16]">Set Saldo Saat Ini</div>
          <p className="mb-2 text-xs text-[#8B7355]">Tetapkan saldo awal/saat ini tanpa membuat transaksi historis palsu.</p>
          <div className="grid grid-cols-2 gap-2">
            <Select value={adj.account} onValueChange={(v) => setAdj({ ...adj, account: v })}><SelectTrigger data-testid="adj-account" className="bg-white"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="EGP">EGP</SelectItem><SelectItem value="IDR">IDR</SelectItem></SelectContent></Select>
            <Input type="number" placeholder="Saldo baru" value={adj.new_balance} onChange={(e) => setAdj({ ...adj, new_balance: e.target.value })} data-testid="adj-balance" className="bg-white" />
          </div>
          <Input placeholder="Catatan/alasan" value={adj.description} onChange={(e) => setAdj({ ...adj, description: e.target.value })} className="mt-2 bg-white" />
          <Button onClick={setBalance} data-testid="adj-save" className="mt-2 w-full rounded-xl bg-[#8B5A2B] hover:bg-[#6B4423]">Simpan Saldo</Button>
        </div>
        <div className="rounded-2xl border border-[#E5DCC5] bg-white p-5 shadow-sm">
          <div className="mb-3 font-heading font-bold text-[#2C1E16]">Kategori Transaksi Kustom</div>
          <div className="grid grid-cols-2 gap-2">
            <Input placeholder="Nama kategori" value={newCat.name} onChange={(e) => setNewCat({ ...newCat, name: e.target.value })} data-testid="cat-name" className="bg-white" />
            <Select value={newCat.type} onValueChange={(v) => setNewCat({ ...newCat, type: v })}><SelectTrigger data-testid="cat-type" className="bg-white"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="expense">Pengeluaran</SelectItem><SelectItem value="income">Pemasukan</SelectItem></SelectContent></Select>
          </div>
          <Button onClick={addCat} data-testid="cat-save" className="mt-2 w-full rounded-xl bg-[#8B5A2B] hover:bg-[#6B4423]">Tambah Kategori</Button>
        </div>
      </div>

      {/* Transactions list */}
      <div className="rounded-2xl border border-[#E5DCC5] bg-white p-5 shadow-sm">
        <div className="mb-3 font-heading font-bold text-[#2C1E16]">Riwayat Transaksi</div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-xs uppercase text-[#8B7355]"><tr><th className="py-2">Tanggal</th><th>Tipe</th><th>Kategori</th><th>Jumlah</th><th>Oleh</th><th></th></tr></thead>
            <tbody>
              {txns.map((t) => (
                <tr key={t.id} className="border-t border-[#F1EBE0]" data-testid={`txn-row-${t.id}`}>
                  <td className="py-2 text-[#5C4A3D]">{(t.date || "").slice(0, 10)}</td>
                  <td className="text-[#5C4A3D]">{t.type === "order_revenue" ? "Pendapatan Pesanan" : t.type === "transfer" ? "Transfer" : t.type === "income" ? "Pemasukan" : "Pengeluaran"}</td>
                  <td className="text-[#5C4A3D]">{t.category}</td>
                  <td className="font-medium text-[#2C1E16]">{t.type === "transfer" ? `${money(t.from_amount, t.from_account)} → ${money(t.to_amount, t.to_account)}` : money(t.amount, t.currency)}</td>
                  <td className="text-[#8B7355]">{t.created_by_name || "-"}</td>
                  <td>{t.type !== "order_revenue" && <button onClick={() => del(t.id)} className="p-1 text-red-500"><Trash2 size={15} /></button>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
