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
  const [form, setForm] = useState({ type: "expense", category: "", amount: "", currency: "EGP", description: "", date: "", recipient_employee_id: "" });
  const [xfer, setXfer] = useState({ from_account: "IDR", to_account: "EGP", from_amount: "", to_amount: "", exchange_rate: "", description: "", date: "" });
  const [adj, setAdj] = useState({ account: "EGP", new_balance: "", description: "" });
  const [newCat, setNewCat] = useState({ name: "", type: "expense", classification: "cost" });
  const [chart, setChart] = useState({ currency: "EGP", year: new Date().getFullYear(), data: [] });
  const [customCats, setCustomCats] = useState([]);
  const [employees, setEmployees] = useState([]);
  const [wages, setWages] = useState([]);
  const [txnSearch, setTxnSearch] = useState("");
  const [txnInput, setTxnInput] = useState("");

  const loadStats = () => {
    const p = { period };
    if (period === "custom") { p.start = range.start; p.end = range.end; }
    api.get("/admin/finance/stats", { params: p }).then((r) => setStats(r.data));
  };
  const loadTxns = () => api.get("/admin/finance/transactions", { params: txnSearch ? { q: txnSearch } : {} }).then((r) => setTxns(r.data));
  const loadChart = () => api.get("/admin/finance/monthly", { params: { year: chart.year, currency: chart.currency } })
    .then((r) => setChart((c) => ({ ...c, data: r.data.months.map((m) => ({ name: m.label.slice(5), Revenue: Math.round(m.revenue), Profit: Math.round(m.profit) })) })));
  const loadConfig = () => {
    api.get("/admin/finance/categories").then((r) => setCats(r.data));
    api.get("/admin/finance/custom-categories").then((r) => setCustomCats(r.data)).catch(() => {});
    api.get("/admin/employees").then((r) => setEmployees(r.data)).catch(() => {});
    api.get("/admin/employees/wages").then((r) => setWages(r.data)).catch(() => {});
  };
  useEffect(() => { loadConfig(); }, []);
  useEffect(() => { loadTxns(); }, [txnSearch]);
  useEffect(() => { loadStats(); }, [period, range.start, range.end]);
  useEffect(() => { loadChart(); }, [chart.currency, chart.year]);

  const addTxn = async () => {
    if (!form.category || !form.amount) return toast.error("Lengkapi kategori & jumlah");
    try { await api.post("/admin/finance/transactions", { ...form, amount: Number(form.amount) }); toast.success("Transaksi ditambahkan"); setForm({ ...form, amount: "", description: "", recipient_employee_id: "" }); loadTxns(); loadStats(); loadConfig(); loadChart(); }
    catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };
  const addXfer = async () => {
    if (!xfer.from_amount || !xfer.to_amount) return toast.error("Lengkapi jumlah transfer");
    try { await api.post("/admin/finance/transfer", { ...xfer, from_amount: Number(xfer.from_amount), to_amount: Number(xfer.to_amount), exchange_rate: xfer.exchange_rate ? Number(xfer.exchange_rate) : null }); toast.success("Transfer dicatat"); setXfer({ ...xfer, from_amount: "", to_amount: "", exchange_rate: "" }); loadTxns(); loadStats(); loadChart(); }
    catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };
  const del = async (id) => { if (!window.confirm("Hapus transaksi?")) return; await api.delete(`/admin/finance/transactions/${id}`); loadTxns(); loadStats(); loadConfig(); loadChart(); };
  const setBalance = async () => {
    if (adj.new_balance === "") return toast.error("Isi saldo baru");
    try { await api.post("/admin/finance/balance-adjust", { ...adj, new_balance: Number(adj.new_balance) }); toast.success("Saldo disesuaikan"); setAdj({ ...adj, new_balance: "", description: "" }); loadStats(); loadTxns(); loadChart(); }
    catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };
  const addCat = async () => {
    if (!newCat.name) return toast.error("Isi nama kategori");
    try { await api.post("/admin/finance/custom-categories", newCat); toast.success("Kategori ditambahkan"); setNewCat({ name: "", type: "expense", classification: "cost" }); loadConfig(); }
    catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };
  const delCat = async (c) => { if (!window.confirm(`Nonaktifkan kategori "${c.name}"? Transaksi lama tetap tersimpan dengan kategorinya.`)) return; await api.delete(`/admin/finance/custom-categories/${c.id}`); toast.success("Kategori dinonaktifkan"); loadConfig(); };

  const Cmp = ({ v }) => v == null ? null : (
    <span className={`ml-2 inline-flex items-center text-xs font-medium ${v >= 0 ? "text-green-600" : "text-red-600"}`}>{v >= 0 ? <TrendingUp size={12} /> : <TrendingDown size={12} />} {v >= 0 ? "+" : ""}{v}%</span>
  );

  return (
    <div className="space-y-4 sm:space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="font-heading text-xl sm:text-2xl font-bold text-[#2C1E16]">Keuangan</h1>
          <p className="mt-0.5 text-xs sm:text-sm text-[#8B7355]">Laporan arus kas, saldo, dan transaksi.</p>
        </div>
        <div className="flex flex-wrap gap-2 w-full sm:w-auto">
          <Select value={period} onValueChange={setPeriod}><SelectTrigger data-testid="finance-period" className="w-full sm:w-40 bg-white text-xs sm:text-sm"><SelectValue /></SelectTrigger>
            <SelectContent>{PERIODS.map(([v, l]) => <SelectItem key={v} value={v}>{l}</SelectItem>)}</SelectContent></Select>
          {period === "custom" && (<div className="flex gap-2 w-full sm:w-auto">
            <Input type="date" value={range.start} onChange={(e) => setRange({ ...range, start: e.target.value })} className="flex-1 sm:w-40 bg-white text-xs sm:text-sm" data-testid="finance-start" />
            <Input type="date" value={range.end} onChange={(e) => setRange({ ...range, end: e.target.value })} className="flex-1 sm:w-40 bg-white text-xs sm:text-sm" data-testid="finance-end" />
          </div>)}
        </div>
      </div>

      {/* Balances */}
      <div className="grid grid-cols-2 gap-2.5 sm:gap-4">
        {["EGP", "IDR"].map((cur) => (
          <div key={cur} className="rounded-xl sm:rounded-2xl border border-[#E5DCC5] bg-white p-3.5 sm:p-5 shadow-xs" data-testid={`balance-${cur}`}>
            <div className="text-xs sm:text-sm text-[#8B7355]">Saldo {cur}</div>
            <div className="mt-1 font-heading text-lg sm:text-3xl font-bold text-[#8B5A2B] truncate">{money(stats?.balances?.[cur] || 0, cur)}</div>
          </div>
        ))}
      </div>

      {/* Stats per currency */}
      <div className="grid gap-3 sm:gap-4 sm:grid-cols-2">
        {["EGP", "IDR"].map((cur) => {
          const c = stats?.current?.[cur]; const cmp = stats?.comparison?.[cur];
          return (
            <div key={cur} className="rounded-xl sm:rounded-2xl border border-[#E5DCC5] bg-white p-3.5 sm:p-5 shadow-xs">
              <div className="font-heading text-sm sm:text-base font-bold text-[#2C1E16]">Statistik {cur}</div>
              <div className="mt-2.5 sm:mt-3 space-y-1.5 sm:space-y-2 text-xs sm:text-sm">
                <div className="flex justify-between"><span className="text-[#5C4A3D]">Pendapatan</span><span className="font-medium">{money(c?.revenue || 0, cur)}<Cmp v={cmp?.revenue} /></span></div>
                <div className="flex justify-between"><span className="text-[#5C4A3D]">Biaya</span><span className="font-medium">{money(c?.cost || 0, cur)}<Cmp v={cmp?.cost} /></span></div>
                <div className="flex justify-between border-t border-dashed border-[#E5DCC5] pt-1.5 sm:pt-2"><span className="text-[#5C4A3D]">Laba Operasi</span><span className="font-bold text-[#8B5A2B]">{money(c?.operating_profit || 0, cur)}<Cmp v={cmp?.operating_profit} /></span></div>
                <div className="flex justify-between"><span className="text-[#5C4A3D]">Arus Kas</span><span className="font-medium">{money(c?.cash_flow || 0, cur)}</span></div>
              </div>
            </div>
          );
        })}
      </div>

      {/* Add transaction + transfer */}
      <div className="grid gap-3 sm:gap-4 lg:grid-cols-2">
        <div className="rounded-xl sm:rounded-2xl border border-[#E5DCC5] bg-white p-3.5 sm:p-5 shadow-xs">
          <div className="mb-3 font-heading text-sm sm:text-base font-bold text-[#2C1E16]">Catat Transaksi</div>
          <div className="grid grid-cols-2 gap-2">
            <Select value={form.type} onValueChange={(v) => setForm({ ...form, type: v, category: "" })}><SelectTrigger data-testid="txn-type" className="bg-white text-xs sm:text-sm"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="income">Pemasukan</SelectItem><SelectItem value="expense">Pengeluaran</SelectItem></SelectContent></Select>
            <Select value={form.currency} onValueChange={(v) => setForm({ ...form, currency: v })}><SelectTrigger data-testid="txn-currency" className="bg-white text-xs sm:text-sm"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="EGP">EGP</SelectItem><SelectItem value="IDR">IDR</SelectItem></SelectContent></Select>
          </div>
          <Select value={form.category} onValueChange={(v) => setForm({ ...form, category: v })}><SelectTrigger data-testid="txn-category" className="mt-2 bg-white text-xs sm:text-sm"><SelectValue placeholder="Kategori" /></SelectTrigger><SelectContent>{(cats[form.type] || []).map((c) => <SelectItem key={c} value={c}>{c}</SelectItem>)}</SelectContent></Select>
          {form.type === "expense" && /upah|wage/i.test(form.category) && (
            <Select value={form.recipient_employee_id} onValueChange={(v) => setForm({ ...form, recipient_employee_id: v })}><SelectTrigger data-testid="txn-recipient" className="mt-2 bg-white text-xs sm:text-sm"><SelectValue placeholder="Penerima (Karyawan) — opsional" /></SelectTrigger><SelectContent>{employees.length ? employees.map((e) => <SelectItem key={e.id} value={e.id}>{e.name}</SelectItem>) : <div className="px-2 py-1.5 text-xs text-[#8B7355]">Belum ada akun karyawan</div>}</SelectContent></Select>
          )}
          <Input type="number" placeholder="Jumlah" value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })} data-testid="txn-amount" className="mt-2 bg-white text-xs sm:text-sm" />
          <Textarea placeholder="Deskripsi (opsional)" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} className="mt-2 bg-white text-xs sm:text-sm" />
          <Button onClick={addTxn} data-testid="txn-save" className="mt-2 w-full rounded-xl bg-[#8B5A2B] text-xs sm:text-sm hover:bg-[#6B4423]">Simpan Transaksi</Button>
        </div>

        <div className="rounded-xl sm:rounded-2xl border border-[#E5DCC5] bg-white p-3.5 sm:p-5 shadow-xs">
          <div className="mb-3 flex items-center gap-2 font-heading text-sm sm:text-base font-bold text-[#2C1E16]"><ArrowRightLeft size={16} /> Transfer / Konversi</div>
          <div className="grid grid-cols-2 gap-2">
            <div><Label className="mb-1 block text-xs text-[#8B7355]">Dari</Label><Select value={xfer.from_account} onValueChange={(v) => setXfer({ ...xfer, from_account: v, to_account: v === "IDR" ? "EGP" : "IDR" })}><SelectTrigger data-testid="xfer-from" className="bg-white text-xs sm:text-sm"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="IDR">Akun IDR</SelectItem><SelectItem value="EGP">Akun EGP</SelectItem></SelectContent></Select></div>
            <div><Label className="mb-1 block text-xs text-[#8B7355]">Ke</Label><Select value={xfer.to_account} onValueChange={(v) => setXfer({ ...xfer, to_account: v, from_account: v === "IDR" ? "EGP" : "IDR" })}><SelectTrigger data-testid="xfer-to" className="bg-white text-xs sm:text-sm"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="IDR">Akun IDR</SelectItem><SelectItem value="EGP">Akun EGP</SelectItem></SelectContent></Select></div>
          </div>
          <Input type="number" placeholder="Jumlah keluar" value={xfer.from_amount} onChange={(e) => setXfer({ ...xfer, from_amount: e.target.value })} data-testid="xfer-from-amount" className="mt-2 bg-white text-xs sm:text-sm" />
          <Input type="number" placeholder="Jumlah diterima" value={xfer.to_amount} onChange={(e) => setXfer({ ...xfer, to_amount: e.target.value })} data-testid="xfer-to-amount" className="mt-2 bg-white text-xs sm:text-sm" />
          <Input type="number" placeholder="Rate (opsional)" value={xfer.exchange_rate} onChange={(e) => setXfer({ ...xfer, exchange_rate: e.target.value })} className="mt-2 bg-white text-xs sm:text-sm" />
          <Button onClick={addXfer} data-testid="xfer-save" className="mt-2 w-full rounded-xl bg-[#8B5A2B] text-xs sm:text-sm hover:bg-[#6B4423]">Catat Transfer</Button>
        </div>
      </div>

      {/* Monthly charts */}
      <div className="rounded-xl sm:rounded-2xl border border-[#E5DCC5] bg-white p-3.5 sm:p-5 shadow-xs" data-testid="finance-chart">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <div className="font-heading text-sm sm:text-base font-bold text-[#2C1E16]">Pendapatan & Laba Bulanan</div>
          <div className="flex gap-2">
            <Select value={chart.currency} onValueChange={(v) => setChart({ ...chart, currency: v })}><SelectTrigger data-testid="chart-currency" className="w-20 sm:w-24 bg-white text-xs sm:text-sm"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="EGP">EGP</SelectItem><SelectItem value="IDR">IDR</SelectItem></SelectContent></Select>
            <Select value={String(chart.year)} onValueChange={(v) => setChart({ ...chart, year: Number(v) })}><SelectTrigger data-testid="chart-year" className="w-24 sm:w-28 bg-white text-xs sm:text-sm"><SelectValue /></SelectTrigger><SelectContent>{[0, 1, 2].map((d) => { const y = new Date().getFullYear() - d; return <SelectItem key={y} value={String(y)}>{y}</SelectItem>; })}</SelectContent></Select>
          </div>
        </div>
        <div style={{ width: "100%", height: 240 }}>
          <ResponsiveContainer>
            <BarChart data={chart.data} margin={{ top: 8, right: 8, left: -10, bottom: 0 }}>
              <XAxis dataKey="name" tick={{ fontSize: 10, fill: "#8B7355" }} />
              <YAxis tick={{ fontSize: 10, fill: "#8B7355" }} width={42} />
              <Tooltip />
              <Legend wrapperStyle={{ fontSize: "12px" }} />
              <Bar dataKey="Revenue" fill="#8B5A2B" radius={[4, 4, 0, 0]} />
              <Bar dataKey="Profit" fill="#C9A86A" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Balance adjust + custom category */}
      <div className="grid gap-3 sm:gap-4 lg:grid-cols-2">
        <div className="rounded-xl sm:rounded-2xl border border-[#E5DCC5] bg-white p-3.5 sm:p-5 shadow-xs">
          <div className="mb-2 font-heading text-sm sm:text-base font-bold text-[#2C1E16]">Set Saldo Saat Ini</div>
          <p className="mb-2 text-xs text-[#8B7355]">Tetapkan saldo awal/saat ini tanpa membuat transaksi historis palsu.</p>
          <div className="grid grid-cols-2 gap-2">
            <Select value={adj.account} onValueChange={(v) => setAdj({ ...adj, account: v })}><SelectTrigger data-testid="adj-account" className="bg-white text-xs sm:text-sm"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="EGP">EGP</SelectItem><SelectItem value="IDR">IDR</SelectItem></SelectContent></Select>
            <Input type="number" placeholder="Saldo baru" value={adj.new_balance} onChange={(e) => setAdj({ ...adj, new_balance: e.target.value })} data-testid="adj-balance" className="bg-white text-xs sm:text-sm" />
          </div>
          <Input placeholder="Catatan/alasan" value={adj.description} onChange={(e) => setAdj({ ...adj, description: e.target.value })} className="mt-2 bg-white text-xs sm:text-sm" />
          <Button onClick={setBalance} data-testid="adj-save" className="mt-2 w-full rounded-xl bg-[#8B5A2B] text-xs sm:text-sm hover:bg-[#6B4423]">Simpan Saldo</Button>
        </div>
        <div className="rounded-xl sm:rounded-2xl border border-[#E5DCC5] bg-white p-3.5 sm:p-5 shadow-xs">
          <div className="mb-2 font-heading text-sm sm:text-base font-bold text-[#2C1E16]">Kategori Transaksi Kustom</div>
          <div className="grid grid-cols-2 gap-2">
            <Input placeholder="Nama kategori" value={newCat.name} onChange={(e) => setNewCat({ ...newCat, name: e.target.value })} data-testid="cat-name" className="bg-white text-xs sm:text-sm" />
            <Select value={newCat.type} onValueChange={(v) => setNewCat({ ...newCat, type: v, classification: v === "income" ? "revenue" : "cost" })}><SelectTrigger data-testid="cat-type" className="bg-white text-xs sm:text-sm"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="expense">Pengeluaran</SelectItem><SelectItem value="income">Pemasukan</SelectItem></SelectContent></Select>
          </div>
          <Select value={newCat.classification} onValueChange={(v) => setNewCat({ ...newCat, classification: v })}><SelectTrigger data-testid="cat-classification" className="mt-2 bg-white text-xs sm:text-sm"><SelectValue /></SelectTrigger><SelectContent>
            {newCat.type === "income" ? (<><SelectItem value="revenue">Revenue (masuk laba)</SelectItem><SelectItem value="transfer">Transfer / Non-Revenue (mis. modal)</SelectItem></>) : (<><SelectItem value="cost">Cost (masuk laba)</SelectItem><SelectItem value="transfer">Transfer / Non-Cost (mis. prive)</SelectItem></>)}
          </SelectContent></Select>
          <Button onClick={addCat} data-testid="cat-save" className="mt-2 w-full rounded-xl bg-[#8B5A2B] text-xs sm:text-sm hover:bg-[#6B4423]">Tambah Kategori</Button>
          {customCats.filter((c) => c.status !== "inactive").length > 0 && (
            <div className="mt-3 space-y-1.5 border-t border-[#F1EBE0] pt-3">
              {customCats.filter((c) => c.status !== "inactive").map((c) => (
                <div key={c.id} className="flex items-center justify-between text-xs sm:text-sm" data-testid={`custom-cat-${c.id}`}>
                  <span className="text-[#5C4A3D]">{c.name} <span className="text-[11px] text-[#8B7355]">· {c.type === "income" ? "Pemasukan" : "Pengeluaran"} · {c.classification === "transfer" ? "Transfer" : c.classification === "revenue" ? "Revenue" : "Cost"}</span></span>
                  <button onClick={() => delCat(c)} data-testid={`custom-cat-del-${c.id}`} className="p-1 text-red-500"><Trash2 size={14} /></button>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Employee wages */}
      {wages.length > 0 && (
        <div className="rounded-xl sm:rounded-2xl border border-[#E5DCC5] bg-white p-3.5 sm:p-5 shadow-xs" data-testid="wage-summary">
          <div className="mb-3 font-heading text-sm sm:text-base font-bold text-[#2C1E16]">Upah Karyawan</div>
          <div className="space-y-2.5">
            {wages.map((w) => (
              <div key={w.id} className="rounded-xl border border-[#F1EBE0] p-2.5 sm:p-3" data-testid={`wage-emp-${w.id}`}>
                <div className="flex items-center justify-between">
                  <div className="font-medium text-xs sm:text-sm text-[#2C1E16]">{w.name}</div>
                  <div className="text-xs sm:text-sm font-semibold text-[#8B5A2B]">{Object.entries(w.totals).map(([c, v]) => money(v, c)).join(" · ") || "—"}</div>
                </div>
                {w.history.length > 0 && (
                  <div className="mt-2 space-y-1 text-[11px] sm:text-xs text-[#8B7355]">
                    {w.history.slice(0, 5).map((h) => (
                      <div key={h.id} className="flex justify-between"><span>{(h.date || "").slice(0, 10)} · oleh {h.recorded_by_name || "-"}</span><span className="font-medium text-[#5C4A3D]">{money(h.amount, h.currency)}</span></div>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Transactions list */}
      <div className="rounded-xl sm:rounded-2xl border border-[#E5DCC5] bg-white p-3.5 sm:p-5 shadow-xs">
        <div className="mb-3 flex flex-col sm:flex-row sm:items-center justify-between gap-2">
          <span className="font-heading text-sm sm:text-base font-bold text-[#2C1E16]">Riwayat Transaksi</span>
          <div className="flex flex-wrap sm:flex-nowrap gap-2">
            <Input value={txnInput} onChange={(e) => setTxnInput(e.target.value)} onKeyDown={(e) => e.key === "Enter" && setTxnSearch(txnInput.trim())} placeholder="Cari transaksi..." data-testid="txn-search" className="flex-1 sm:w-64 bg-white text-xs sm:text-sm" />
            <Button onClick={() => setTxnSearch(txnInput.trim())} data-testid="txn-search-btn" className="rounded-xl bg-[#8B5A2B] text-xs sm:text-sm hover:bg-[#6B4423]">Cari</Button>
            {txnSearch && <Button variant="outline" onClick={() => { setTxnInput(""); setTxnSearch(""); }} data-testid="txn-search-clear" className="rounded-xl text-xs sm:text-sm">Reset</Button>}
          </div>
        </div>

        {/* Mobile View: Cards */}
        <div className="space-y-2 sm:hidden">
          {txns.map((t) => (
            <div key={t.id} className="rounded-lg border border-[#F1EBE0] p-2.5 text-xs" data-testid={`txn-card-${t.id}`}>
              <div className="flex items-center justify-between">
                <span className="font-semibold text-[#2C1E16]">{t.category}</span>
                <span className="font-bold text-[#8B5A2B]">
                  {t.type === "transfer" ? `${money(t.from_amount, t.from_account)} → ${money(t.to_amount, t.to_account)}` : money(t.amount, t.currency)}
                </span>
              </div>
              <div className="mt-1 flex items-center justify-between text-[11px] text-[#8B7355]">
                <span>{(t.date || "").slice(0, 10)} · {t.type === "order_revenue" ? "Pendapatan" : t.type === "transfer" ? "Transfer" : t.type === "income" ? "Pemasukan" : "Pengeluaran"}</span>
                <div className="flex items-center gap-1.5">
                  <span>{t.created_by_name || "-"}</span>
                  {t.type !== "order_revenue" && <button onClick={() => del(t.id)} className="p-0.5 text-red-500"><Trash2 size={13} /></button>}
                </div>
              </div>
              {t.description && <p className="mt-1 text-[11px] text-[#5C4A3D] line-clamp-1">{t.description}</p>}
            </div>
          ))}
          {txns.length === 0 && <div className="py-4 text-center text-xs text-[#8B7355]">Tidak ada transaksi</div>}
        </div>

        {/* Desktop View: Table */}
        <div className="hidden sm:block overflow-x-auto">
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
