import React, { useEffect, useState } from "react";
import api from "../../lib/api";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../../components/ui/select";
import { Input } from "../../components/ui/input";
import { X, ChevronRight } from "lucide-react";

const money = (v, cur) => (cur === "IDR" ? "Rp" : "") + Math.round(Number(v) || 0).toLocaleString("de-DE") + (cur === "EGP" ? " LE" : "");
const PERIODS = [["this_month", "Bulan Ini"], ["last_month", "Bulan Lalu"], ["last_3_months", "3 Bulan Terakhir"], ["this_year", "Tahun Ini"], ["last_year", "Tahun Lalu"], ["custom", "Kustom"]];

export default function AdminFinanceStats() {
  const [period, setPeriod] = useState("this_month");
  const [range, setRange] = useState({ start: "", end: "" });
  const [currency, setCurrency] = useState("EGP");
  const [data, setData] = useState(null);
  const [selectedMember, setSelectedMember] = useState(null);

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

      {/* Keuangan Tim */}
      <div className="rounded-2xl border border-[#E5DCC5] bg-white p-5 shadow-sm" data-testid="team-wages-card">
        <div className="mb-2 flex items-center justify-between">
          <div className="font-heading font-bold text-[#2C1E16] text-base sm:text-lg">
            Keuangan Tim
          </div>
          <span className="text-xs text-[#8B7355]">
            Urutan: Total Terbesar ↓ Terkecil
          </span>
        </div>
        <p className="text-xs text-[#8B7355] mb-4">
          Total upah riil yang diterima setiap akun tim berdasarkan transaksi keuangan pada periode ini. Klik akun untuk melihat rincian riwayat transaksinya.
        </p>

        {(!data?.team_wages || data.team_wages.length === 0) ? (
          <div className="py-4 text-center text-sm text-[#8B7355]">
            Belum ada data upah tim yang dicatat pada periode ini.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-xs uppercase text-[#8B7355]">
                <tr>
                  <th className="py-2 w-12">#</th>
                  <th>Nama Akun Tim</th>
                  <th>Peran</th>
                  <th className="text-center">Transaksi</th>
                  <th className="text-right">Total Upah Diterima</th>
                  <th className="text-center w-24">Aksi</th>
                </tr>
              </thead>
              <tbody>
                {data.team_wages.map((w, i) => (
                  <tr
                    key={w.id || i}
                    onClick={() => setSelectedMember(w)}
                    className="border-t border-[#F1EBE0] cursor-pointer hover:bg-[#FBF9F4] transition-colors"
                    data-testid={`team-wage-row-${w.id || i}`}
                  >
                    <td className="py-2.5 font-semibold text-[#8B7355]">{i + 1}</td>
                    <td className="font-medium text-[#2C1E16]">{w.name}</td>
                    <td>
                      <span className="rounded-full bg-[#EFE6D5] px-2 py-0.5 text-xs text-[#8B5A2B] font-medium capitalize">
                        {w.role || "Employee"}
                      </span>
                    </td>
                    <td className="text-center text-[#5C4A3D]">{w.count}x</td>
                    <td className="text-right font-bold text-[#8B5A2B]">{money(w.total, currency)}</td>
                    <td className="text-center">
                      <span className="inline-flex items-center gap-1 text-xs text-[#8B5A2B] font-medium underline">
                        Rincian <ChevronRight size={13} />
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Drilldown Modal: Riwayat Transaksi Upah Akun */}
      {selectedMember && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-xs"
          onClick={() => setSelectedMember(null)}
          data-testid="wage-drilldown-modal"
        >
          <div
            className="relative w-full max-w-2xl max-h-[90vh] flex flex-col rounded-2xl border border-[#E5DCC5] bg-white p-5 sm:p-6 shadow-xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-start justify-between border-b border-[#F1EBE0] pb-4">
              <div>
                <div className="flex items-center gap-2">
                  <h3 className="font-heading text-lg sm:text-xl font-bold text-[#2C1E16]">{selectedMember.name}</h3>
                  <span className="rounded-full bg-[#EFE6D5] px-2.5 py-0.5 text-xs font-semibold text-[#8B5A2B] uppercase">
                    {selectedMember.role || "Akun Tim"}
                  </span>
                </div>
                <p className="mt-1 text-xs sm:text-sm text-[#8B7355]">
                  Total Upah Periode Ini: <span className="font-bold text-[#8B5A2B]">{money(selectedMember.total, currency)}</span> ({selectedMember.count} transaksi)
                </p>
              </div>
              <button
                onClick={() => setSelectedMember(null)}
                className="rounded-lg p-1.5 text-[#8B7355] hover:bg-[#F1EBE0] hover:text-[#2C1E16]"
                aria-label="Tutup"
                data-testid="close-drilldown-modal"
              >
                <X size={20} />
              </button>
            </div>

            <div className="mt-4 flex-1 overflow-y-auto space-y-2.5 pr-1">
              <div className="text-xs font-semibold uppercase tracking-wider text-[#8B7355]">
                Riwayat Transaksi Upah
              </div>
              {selectedMember.transactions && selectedMember.transactions.length > 0 ? (
                <div className="divide-y divide-[#F1EBE0] rounded-xl border border-[#F1EBE0]">
                  {selectedMember.transactions.map((t, idx) => (
                    <div key={t.id || idx} className="p-3 text-xs sm:text-sm flex flex-col sm:flex-row sm:items-center justify-between gap-2" data-testid={`drilldown-row-${idx}`}>
                      <div className="space-y-0.5">
                        <div className="flex items-center gap-2">
                          <span className="font-semibold text-[#2C1E16]">{t.category || "Pekerja"}</span>
                          <span className="text-[11px] text-[#8B7355]">· {(t.date || "").slice(0, 10)}</span>
                        </div>
                        {t.description ? (
                          <p className="text-[#5C4A3D] text-xs">{t.description}</p>
                        ) : (
                          <p className="text-[#8B7355] text-xs italic">Tanpa keterangan</p>
                        )}
                        <div className="text-[11px] text-[#8B7355]">Dicatat oleh: {t.recorded_by_name || "-"}</div>
                      </div>
                      <div className="text-left sm:text-right font-bold text-[#8B5A2B] text-sm shrink-0">
                        {money(t.amount, currency)}
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="py-6 text-center text-xs text-[#8B7355]">Tidak ada riwayat transaksi pada periode ini.</div>
              )}
            </div>

            <div className="mt-4 border-t border-[#F1EBE0] pt-3 flex justify-end">
              <button
                onClick={() => setSelectedMember(null)}
                className="rounded-xl bg-[#8B5A2B] px-4 py-2 text-xs sm:text-sm font-medium text-white hover:bg-[#6B4423]"
                data-testid="drilldown-modal-close-btn"
              >
                Tutup
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
