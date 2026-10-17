import React, { useEffect, useState, useId } from "react";
import api from "../../lib/api";
import { formatApiError } from "../../lib/format";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Textarea } from "../../components/ui/textarea";
import { Label } from "../../components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../../components/ui/select";
import { toast } from "sonner";
import {
  CircleDollarSign,
  Wallet,
  Clock,
  CheckCircle2,
  AlertCircle,
  Search,
  Filter,
  ArrowRight,
  Eye,
  X,
  RotateCcw,
  Users,
  Coins,
  Receipt
} from "lucide-react";

export const generateUUID = () => {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === "x" ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
};

const money = (v) => {
  const n = Number(v) || 0;
  const formatted = n % 1 !== 0
    ? n.toLocaleString("de-DE", { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    : Math.round(n).toLocaleString("de-DE");
  return formatted + " LE";
};

export default function AdminWorkerPendingWages() {
  const [activeTab, setActiveTab] = useState("workers"); // "workers" | "obligations" | "settlements"
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  // Data states
  const [summary, setSummary] = useState(null);
  const [obligations, setObligations] = useState([]);
  const [settlements, setSettlements] = useState([]);
  const [workersList, setWorkersList] = useState([]);

  // Filter states
  const [selectedWorkerFilter, setSelectedWorkerFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("pending");
  const [searchQuery, setSearchQuery] = useState("");

  // Settlement Modal state
  const [settleModalOpen, setSettleModalOpen] = useState(false);
  const [settleWorker, setSettleWorker] = useState(null);
  const [settleWorkerObligations, setSettleWorkerObligations] = useState([]);
  const [settleAmount, setSettleAmount] = useState("");
  const [settleMethod, setSettleMethod] = useState("cash");
  const [settleDate, setSettleDate] = useState(() => new Date().toISOString().slice(0, 10));
  const [settleRef, setSettleRef] = useState("");
  const [settleNotes, setSettleNotes] = useState("");
  const [settleIdempotencyKey, setSettleIdempotencyKey] = useState("");
  const [settleCurrency, setSettleCurrency] = useState("EGP");
  const [settleLockedRate, setSettleLockedRate] = useState(null);
  const [settleOrderHistoricalRate, setSettleOrderHistoricalRate] = useState(null);
  const [settleRate, setSettleRate] = useState("");
  const [settleIsOverride, setSettleIsOverride] = useState(false);
  const [settleOverrideReason, setSettleOverrideReason] = useState("");
  const [settleActualPayout, setSettleActualPayout] = useState("");
  const [settleIsCustomPayout, setSettleIsCustomPayout] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [settleError, setSettleError] = useState("");

  // Settlement Detail Modal
  const [detailModalOpen, setDetailModalOpen] = useState(false);
  const [selectedSettlement, setSelectedSettlement] = useState(null);
  const [voiding, setVoiding] = useState(false);
  const [voidReason, setVoidReason] = useState("");

  const loadData = async () => {
    setLoading(true);
    setError(null);
    try {
      const [sumRes, obRes, stRes, empRes] = await Promise.all([
        api.get("/admin/wages/pending-summary"),
        api.get("/admin/wage-obligations", {
          params: {
            worker_id: selectedWorkerFilter !== "all" ? selectedWorkerFilter : undefined,
            status: statusFilter,
            limit: 200,
          }
        }),
        api.get("/admin/wages/settlements", {
          params: {
            worker_id: selectedWorkerFilter !== "all" ? selectedWorkerFilter : undefined,
            limit: 100,
          }
        }),
        api.get("/admin/employees")
      ]);
      setSummary(sumRes.data);
      setObligations(obRes.data?.obligations || []);
      setSettlements(stRes.data?.settlements || []);
      setWorkersList(empRes.data || []);
    } catch (err) {
      console.error("Failed to load worker wage data:", err);
      setError(formatApiError(err) || "Gagal memuat data kewajiban upah");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, [selectedWorkerFilter, statusFilter]);

  const openSettleModal = async (worker) => {
    setSettleWorker(worker);
    setSettleError("");
    setSettleAmount("");
    setSettleRef("");
    setSettleNotes("");
    setSettleMethod("cash");
    setSettleCurrency("EGP");
    setSettleLockedRate(null);
    setSettleOrderHistoricalRate(null);
    setSettleRate("");
    setSettleIsOverride(false);
    setSettleOverrideReason("");
    setSettleActualPayout("");
    setSettleIsCustomPayout(false);
    setSettleDate(new Date().toISOString().slice(0, 10));
    setSettleIdempotencyKey(generateUUID());
    setSettleModalOpen(true);

    try {
      const res = await api.get(`/admin/workers/${worker.worker_id || worker.id}/pending-wages`);
      setSettleWorkerObligations(res.data?.obligations || []);
      const lRate = res.data?.default_settlement_rate || res.data?.default_locked_exchange_rate || null;
      const histRate = res.data?.order_historical_rate || null;
      setSettleLockedRate(lRate);
      setSettleOrderHistoricalRate(histRate);
      if (lRate) {
        setSettleRate(String(lRate));
      }
      // Default amount to total pending
      if (res.data?.total_pending_wages_le > 0) {
        setSettleAmount(String(res.data.total_pending_wages_le));
      }
    } catch (err) {
      setSettleError(formatApiError(err) || "Gagal mengambil rincian kewajiban pekerja");
    }
  };

  const handleSettleSubmit = async (e) => {
    if (e) e.preventDefault();
    if (submitting) return;

    const amt = parseFloat(settleAmount);
    if (isNaN(amt) || amt <= 0) {
      setSettleError("Nominal pembayaran harus lebih besar dari 0");
      return;
    }

    const workerId = settleWorker.worker_id || settleWorker.id;
    const workerPending = Number(settleWorker.total_le || settleWorker.total_pending_wages_le || 0);

    if (amt > workerPending && workerPending > 0) {
      setSettleError(`Nominal pembayaran (${amt} LE) melebihi total saldo terutang (${workerPending} LE)`);
      return;
    }

    let numRate = undefined;
    let customActualPayout = undefined;
    if (settleCurrency === "IDR") {
      numRate = parseFloat(settleRate);
      if (isNaN(numRate) || numRate <= 0) {
        setSettleError("Kurs penyelesaian IDR harus berupa angka positif yang valid");
        return;
      }
      if (settleIsOverride && (!settleOverrideReason || settleOverrideReason.trim().length < 3)) {
        setSettleError("Alasan perubahan kurs wajib diisi saat menggunakan kurs override (minimal 3 karakter)");
        return;
      }

      if (settleIsCustomPayout && settleActualPayout !== "") {
        customActualPayout = parseFloat(settleActualPayout);
        if (isNaN(customActualPayout) || customActualPayout <= 0) {
          setSettleError("Nominal pencairan IDR aktual harus berupa angka positif yang valid");
          return;
        }
        const stdIdr = Math.round(amt * numRate);
        if (Math.round(customActualPayout) !== stdIdr) {
          const reasonOrNote = (settleOverrideReason || settleNotes || "").trim();
          if (reasonOrNote.length < 3) {
            setSettleError("Alasan / catatan wajib diisi jika nominal pencairan IDR berbeda dari hasil konversi standar (minimal 3 karakter)");
            return;
          }
        }
      }
    }

    setSubmitting(true);
    setSettleError("");

    try {
      const payload = {
        worker_id: workerId,
        amount_le: amt,
        payment_method: settleMethod,
        payment_currency: settleCurrency,
        settlement_rate: settleCurrency === "IDR" ? numRate : undefined,
        is_rate_override: settleCurrency === "IDR" ? settleIsOverride : false,
        override_reason: (settleCurrency === "IDR" && settleIsOverride) ? settleOverrideReason.trim() : undefined,
        actual_payout_amount: (settleCurrency === "IDR" && settleIsCustomPayout && customActualPayout !== undefined) ? customActualPayout : undefined,
        payment_date: settleDate,
        reference: settleRef.trim() || undefined,
        notes: settleNotes.trim() || undefined,
        idempotency_key: settleIdempotencyKey,
      };

      const res = await api.post("/admin/wages/settlements", payload);
      toast.success(`Pembayaran upah berhasil dicatat (${res.data?.settlement_number || ""})`);
      setSettleModalOpen(false);
      await loadData();
    } catch (err) {
      console.error("Settlement error:", err);
      const rawDetail = err.response?.data?.detail;
      const detailStr = typeof rawDetail === "string" ? rawDetail : (rawDetail?.msg || JSON.stringify(rawDetail || ""));
      let displayMsg = formatApiError(rawDetail || err.message) || "Gagal memproses pembayaran upah";
      if (
        err.response?.status === 422 &&
        !settleIsOverride &&
        (detailStr.includes("Alasan perubahan kurs") || detailStr.includes("kurs override") || detailStr.includes("kurs transaksi"))
      ) {
        displayMsg = "Kurs transaksi di sistem telah berubah. Muat ulang rincian atau tutup modal untuk memperbarui kurs sebelum memproses pembayaran upah.";
      }
      setSettleError(displayMsg);
    } finally {
      setSubmitting(false);
    }
  };

  const handleVoidSettlement = async () => {
    if (!selectedSettlement) return;
    const reason = voidReason.trim();
    if (!reason) {
      toast.error("Alasan pembatalan wajib diisi");
      return;
    }
    const confirmMsg = `Batalkan pembayaran upah ${selectedSettlement.settlement_number}?\n\nPERINGATAN: Tindakan ini membatalkan pencatatan pengeluaran kas di buku besar keuangan dan mengembalikan saldo hutang upah pekerja.\n\nJangan gunakan tindakan ini jika uang tunai fisik sudah diserahkan kepada pekerja dan tidak dikembalikan. Lanjutkan pembatalan administratif?`;
    if (!window.confirm(confirmMsg)) {
      return;
    }

    setVoiding(true);
    try {
      await api.post(`/admin/wages/settlements/${selectedSettlement.id}/void`, { reason });
      toast.success("Pembayaran upah berhasil dibatalkan");
      setDetailModalOpen(false);
      setSelectedSettlement(null);
      await loadData();
    } catch (err) {
      toast.error(formatApiError(err) || "Gagal membatalkan pembayaran upah");
    } finally {
      setVoiding(false);
    }
  };

  // Filtered obligations for table
  const filteredObligations = obligations.filter((o) => {
    if (!searchQuery) return true;
    const q = searchQuery.toLowerCase();
    return (
      (o.worker_name || "").toLowerCase().includes(q) ||
      (o.obligation_number || "").toLowerCase().includes(q) ||
      (o.order_number || "").toLowerCase().includes(q) ||
      (o.task_category || "").toLowerCase().includes(q)
    );
  });

  return (
    <div className="space-y-4 sm:space-y-6" data-testid="worker-pending-wages-page">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="font-heading text-xl sm:text-2xl font-bold text-[#2C1E16]">
            Upah Pekerja & Kewajiban Terutang
          </h1>
          <p className="mt-0.5 text-xs sm:text-sm text-[#8B7355]">
            Rekapitulasi hak upah pekerja produksi, status pelunasan, dan pencatatan kas keluar.
          </p>
        </div>
        <Button
          variant="outline"
          onClick={loadData}
          className="rounded-xl border-[#E5DCC5] bg-white text-xs text-[#5C4A3D] hover:bg-[#FAF5EE]"
          data-testid="refresh-wages-btn"
        >
          <RotateCcw size={13} className="mr-1.5" /> Muat Ulang
        </Button>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-2 gap-2.5 sm:gap-4 lg:grid-cols-4" data-testid="wages-summary-cards">
        <div className="rounded-xl sm:rounded-2xl border border-amber-200 bg-amber-50/60 p-3.5 sm:p-5 shadow-xs">
          <div className="flex items-center justify-between">
            <span className="text-xs sm:text-sm font-medium text-amber-900">Total Upah Terutang</span>
            <Clock size={16} className="text-amber-700" />
          </div>
          <div className="mt-2 font-heading text-lg sm:text-2xl font-bold text-amber-950 truncate" data-testid="total-pending-wages">
            {money(summary?.total_pending_wages_le || 0)}
          </div>
          <div className="mt-1 text-[11px] text-amber-700">
            {summary?.pending_obligations_count || 0} kewajiban belum lunas
          </div>
        </div>

        <div className="rounded-xl sm:rounded-2xl border border-emerald-200 bg-emerald-50/60 p-3.5 sm:p-5 shadow-xs">
          <div className="flex items-center justify-between">
            <span className="text-xs sm:text-sm font-medium text-emerald-900">Total Telah Dibayar</span>
            <CheckCircle2 size={16} className="text-emerald-700" />
          </div>
          <div className="mt-2 font-heading text-lg sm:text-2xl font-bold text-emerald-950 truncate" data-testid="total-paid-wages">
            {money(summary?.total_paid_le || 0)}
          </div>
          <div className="mt-1 text-[11px] text-emerald-700">
            Kas keluar resmi tercatat
          </div>
        </div>

        <div className="rounded-xl sm:rounded-2xl border border-[#E5DCC5] bg-white p-3.5 sm:p-5 shadow-xs">
          <div className="flex items-center justify-between">
            <span className="text-xs sm:text-sm font-medium text-[#8B7355]">Total Akrual Keseluruhan</span>
            <Wallet size={16} className="text-[#8B5A2B]" />
          </div>
          <div className="mt-2 font-heading text-lg sm:text-2xl font-bold text-[#2C1E16] truncate">
            {money(summary?.total_accrued_le || 0)}
          </div>
          <div className="mt-1 text-[11px] text-[#8B7355]">
            Nilai borongan/unit disetujui
          </div>
        </div>

        <div className="rounded-xl sm:rounded-2xl border border-[#E5DCC5] bg-white p-3.5 sm:p-5 shadow-xs">
          <div className="flex items-center justify-between">
            <span className="text-xs sm:text-sm font-medium text-[#8B7355]">Pekerja Bersaldo</span>
            <Users size={16} className="text-[#8B5A2B]" />
          </div>
          <div className="mt-2 font-heading text-lg sm:text-2xl font-bold text-[#8B5A2B] truncate" data-testid="workers-with-balance-count">
            {summary?.workers_summary?.filter((w) => w.total_le > 0).length || 0} Orang
          </div>
          <div className="mt-1 text-[11px] text-[#8B7355]">
            Menunggu pembayaran
          </div>
        </div>
      </div>

      {/* Tabs Control */}
      <div className="flex border-b border-[#E5DCC5] text-xs sm:text-sm">
        <button
          onClick={() => setActiveTab("workers")}
          data-testid="tab-workers"
          className={`px-4 py-2.5 font-medium transition-colors border-b-2 -mb-px ${
            activeTab === "workers"
              ? "border-[#8B5A2B] text-[#8B5A2B] font-bold"
              : "border-transparent text-[#5C4A3D] hover:text-[#2C1E16]"
          }`}
        >
          Ringkasan per Pekerja
        </button>
        <button
          onClick={() => setActiveTab("obligations")}
          data-testid="tab-obligations"
          className={`px-4 py-2.5 font-medium transition-colors border-b-2 -mb-px ${
            activeTab === "obligations"
              ? "border-[#8B5A2B] text-[#8B5A2B] font-bold"
              : "border-transparent text-[#5C4A3D] hover:text-[#2C1E16]"
          }`}
        >
          Daftar Seluruh Kewajiban
        </button>
        <button
          onClick={() => setActiveTab("settlements")}
          data-testid="tab-settlements"
          className={`px-4 py-2.5 font-medium transition-colors border-b-2 -mb-px ${
            activeTab === "settlements"
              ? "border-[#8B5A2B] text-[#8B5A2B] font-bold"
              : "border-transparent text-[#5C4A3D] hover:text-[#2C1E16]"
          }`}
        >
          Riwayat Pelunasan (Settlement)
        </button>
      </div>

      {/* Error Banner */}
      {error && (
        <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-xs sm:text-sm text-red-800 flex items-center gap-2">
          <AlertCircle size={16} className="shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* TAB 1: WORKERS SUMMARY */}
      {activeTab === "workers" && (
        <div className="rounded-xl sm:rounded-2xl border border-[#E5DCC5] bg-white p-4 sm:p-5 shadow-xs" data-testid="workers-summary-card">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
            <div>
              <h2 className="font-heading font-bold text-[#2C1E16] text-base sm:text-lg">
                Daftar Akun Pekerja & Saldo Terutang
              </h2>
              <p className="text-xs text-[#8B7355] mt-0.5">
                Pilih pekerja untuk melihat kewajiban yang siap dilunasi.
              </p>
            </div>
          </div>

          {loading ? (
            <div className="py-8 text-center text-xs text-[#8B7355]">Memuat data pekerja...</div>
          ) : !summary?.workers_summary || summary.workers_summary.length === 0 ? (
            <div className="py-8 text-center text-xs sm:text-sm text-[#8B7355]" data-testid="empty-workers-msg">
              Tidak ada kewajiban upah aktif saat ini. Seluruh penugasan telah lunas atau belum diverifikasi.
            </div>
          ) : (
            <div className="overflow-x-auto -mx-1 sm:mx-0">
              <table className="w-full text-xs sm:text-sm min-w-[650px]">
                <thead className="text-left text-xs uppercase text-[#8B7355] border-b border-[#F1EBE0]">
                  <tr>
                    <th className="py-2.5 w-12">#</th>
                    <th>Nama Pekerja</th>
                    <th className="text-center">Kewajiban Aktif</th>
                    <th className="text-right">Total Akru</th>
                    <th className="text-right">Sudah Dibayar</th>
                    <th className="text-right">Sisa Terutang</th>
                    <th className="text-center w-32">Aksi</th>
                  </tr>
                </thead>
                <tbody>
                  {summary.workers_summary.map((w, idx) => (
                    <tr
                      key={w.worker_id || idx}
                      className="border-b border-[#F1EBE0] hover:bg-[#FBF9F4] transition-colors"
                      data-testid={`worker-summary-row-${w.worker_id || idx}`}
                    >
                      <td className="py-3 font-semibold text-[#8B7355]">{idx + 1}</td>
                      <td className="font-semibold text-[#2C1E16]">{w.worker_name}</td>
                      <td className="text-center text-[#5C4A3D]">{w.count} tugas</td>
                      <td className="text-right text-[#5C4A3D]">{money(w.total_accrued_le)}</td>
                      <td className="text-right text-emerald-700 font-medium">{money(w.total_paid_le)}</td>
                      <td className="text-right font-bold text-amber-900">{money(w.total_le)}</td>
                      <td className="text-center">
                        <Button
                          size="sm"
                          disabled={w.total_le <= 0}
                          onClick={() => openSettleModal(w)}
                          data-testid={`settle-btn-${w.worker_id || idx}`}
                          className="rounded-lg bg-[#8B5A2B] text-white hover:bg-[#6D4522] text-xs h-8 px-3"
                        >
                          <Coins size={13} className="mr-1" /> Bayar Upah
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* TAB 2: ALL OBLIGATIONS */}
      {activeTab === "obligations" && (
        <div className="rounded-xl sm:rounded-2xl border border-[#E5DCC5] bg-white p-4 sm:p-5 shadow-xs" data-testid="all-obligations-card">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <div className="flex flex-wrap items-center gap-2 w-full sm:w-auto">
              {/* Search */}
              <div className="relative flex-1 sm:w-56">
                <Search size={14} className="absolute left-3 top-2.5 text-[#8B7355]" />
                <Input
                  placeholder="Cari pekerja / pesanan..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="pl-8 text-xs bg-white border-[#E5DCC5]"
                  data-testid="search-obligations-input"
                />
              </div>

              {/* Status Filter */}
              <Select value={statusFilter} onValueChange={setStatusFilter}>
                <SelectTrigger className="w-36 text-xs bg-white border-[#E5DCC5]" data-testid="status-filter-select">
                  <SelectValue placeholder="Status" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="pending">Terutang (Aktif)</SelectItem>
                  <SelectItem value="accrued">Belum Dibayar</SelectItem>
                  <SelectItem value="partially_paid">Sebagian Lunas</SelectItem>
                  <SelectItem value="paid">Lunas</SelectItem>
                  <SelectItem value="all">Semua Status</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>

          {loading ? (
            <div className="py-8 text-center text-xs text-[#8B7355]">Memuat daftar kewajiban...</div>
          ) : filteredObligations.length === 0 ? (
            <div className="py-8 text-center text-xs sm:text-sm text-[#8B7355]" data-testid="empty-obligations-msg">
              Tidak ada data kewajiban upah yang cocok dengan filter.
            </div>
          ) : (
            <div className="overflow-x-auto -mx-1 sm:mx-0">
              <table className="w-full text-xs sm:text-sm min-w-[800px]">
                <thead className="text-left text-xs uppercase text-[#8B7355] border-b border-[#F1EBE0]">
                  <tr>
                    <th className="py-2.5">No. Kewajiban</th>
                    <th>Pekerja</th>
                    <th>Pesanan</th>
                    <th>Tugas</th>
                    <th className="text-center">Basis</th>
                    <th className="text-right">Total Akru</th>
                    <th className="text-right">Dibayar</th>
                    <th className="text-right">Sisa Saldo</th>
                    <th className="text-center">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredObligations.map((o) => (
                    <tr
                      key={o.id || o.obligation_number}
                      className="border-b border-[#F1EBE0] hover:bg-[#FBF9F4] transition-colors"
                      data-testid={`obligation-row-${o.id}`}
                    >
                      <td className="py-3 font-semibold text-[#8B5A2B]">{o.obligation_number}</td>
                      <td className="font-medium text-[#2C1E16]">{o.worker_name}</td>
                      <td>
                        <span className="font-mono text-xs">{o.order_number || "—"}</span>
                      </td>
                      <td className="capitalize text-[#5C4A3D]">{o.task_category || "—"}</td>
                      <td className="text-center text-xs text-[#8B7355]">
                        {o.pricing_basis === "lump_sum" ? "Borongan" : "Per Unit"}
                      </td>
                      <td className="text-right text-[#5C4A3D]">{money(o.total_amount_le)}</td>
                      <td className="text-right text-emerald-700">{money(o.paid_amount_le)}</td>
                      <td className="text-right font-bold text-amber-900">{money(o.remaining_amount_le)}</td>
                      <td className="text-center">
                        <span
                          className={`rounded-full px-2.5 py-0.5 text-[11px] font-semibold uppercase ${
                            o.status === "paid"
                              ? "bg-emerald-100 text-emerald-800"
                              : o.status === "partially_paid"
                              ? "bg-blue-100 text-blue-800"
                              : o.status === "voided"
                              ? "bg-gray-100 text-gray-700"
                              : "bg-amber-100 text-amber-800"
                          }`}
                        >
                          {o.status === "paid"
                            ? "Lunas"
                            : o.status === "partially_paid"
                            ? "Sebagian"
                            : o.status === "voided"
                            ? "Void"
                            : "Terutang"}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* TAB 3: SETTLEMENTS HISTORY */}
      {activeTab === "settlements" && (
        <div className="rounded-xl sm:rounded-2xl border border-[#E5DCC5] bg-white p-4 sm:p-5 shadow-xs" data-testid="settlements-history-card">
          <div className="mb-4">
            <h2 className="font-heading font-bold text-[#2C1E16] text-base sm:text-lg">
              Riwayat Pembayaran Upah Kas
            </h2>
            <p className="text-xs text-[#8B7355] mt-0.5">
              Setiap pembayaran upah terhubung langsung dengan jurnal pengeluaran kas keuangan.
            </p>
          </div>

          {loading ? (
            <div className="py-8 text-center text-xs text-[#8B7355]">Memuat riwayat pembayaran...</div>
          ) : settlements.length === 0 ? (
            <div className="py-8 text-center text-xs sm:text-sm text-[#8B7355]" data-testid="empty-settlements-msg">
              Belum ada riwayat pembayaran upah yang tercatat.
            </div>
          ) : (
            <div className="overflow-x-auto -mx-1 sm:mx-0">
              <table className="w-full text-xs sm:text-sm min-w-[700px]">
                <thead className="text-left text-xs uppercase text-[#8B7355] border-b border-[#F1EBE0]">
                  <tr>
                    <th className="py-2.5">No. Settlement</th>
                    <th>Tanggal</th>
                    <th>Nama Pekerja</th>
                    <th>Metode</th>
                    <th className="text-right">Nominal (LE)</th>
                    <th className="text-center">Status</th>
                    <th className="text-center w-24">Aksi</th>
                  </tr>
                </thead>
                <tbody>
                  {settlements.map((s) => (
                    <tr
                      key={s.id || s.settlement_number}
                      className="border-b border-[#F1EBE0] hover:bg-[#FBF9F4] transition-colors"
                      data-testid={`settlement-row-${s.id}`}
                    >
                      <td className="py-3 font-semibold text-[#8B5A2B]">{s.settlement_number}</td>
                      <td className="text-[#5C4A3D]">{s.settlement_date || s.created_at?.slice(0, 10)}</td>
                      <td className="font-medium text-[#2C1E16]">{s.worker_name}</td>
                      <td>
                        <div className="flex items-center gap-1.5">
                          <span className={`px-1.5 py-0.5 rounded text-[10px] font-semibold uppercase ${
                            (s.payout_currency || "EGP") === "IDR"
                              ? "bg-purple-100 text-purple-800"
                              : "bg-amber-100 text-amber-800"
                          }`}>
                            {s.payout_currency || "EGP"}
                          </span>
                          <span className="capitalize text-[#5C4A3D] text-xs">
                            {s.payment_method === "cash" ? "Tunai" : s.payment_method}
                          </span>
                        </div>
                      </td>
                      <td className="text-right">
                        <div className="font-bold text-emerald-800">{money(s.amount_le)}</div>
                        {(s.payout_currency === "IDR" || (s.payout_amount && s.payout_currency !== "EGP")) && (
                          <div className="text-[10px] text-[#8B7355] font-medium">
                            Rp {Number(s.payout_amount || 0).toLocaleString("id-ID")}
                          </div>
                        )}
                      </td>
                      <td className="text-center">
                        <span
                          className={`rounded-full px-2.5 py-0.5 text-[11px] font-semibold uppercase ${
                            s.status === "voided"
                              ? "bg-red-100 text-red-800"
                              : "bg-emerald-100 text-emerald-800"
                          }`}
                        >
                          {s.status === "voided" ? "Dibatalkan" : "Tercatat"}
                        </span>
                      </td>
                      <td className="text-center">
                        <button
                          onClick={() => {
                            setSelectedSettlement(s);
                            setVoidReason("");
                            setDetailModalOpen(true);
                          }}
                          className="inline-flex items-center gap-1 text-xs font-semibold text-[#8B5A2B] hover:underline"
                          data-testid={`view-settlement-btn-${s.id}`}
                        >
                          <Eye size={13} /> Rincian
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* SETTLEMENT MODAL */}
      {settleModalOpen && settleWorker && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-xs"
          onClick={() => !submitting && setSettleModalOpen(false)}
          data-testid="settle-wage-modal"
        >
          <div
            className="relative w-full max-w-xl sm:max-w-2xl max-h-[90vh] overflow-y-auto rounded-2xl border border-[#E5DCC5] bg-white p-4 sm:p-6 shadow-xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between border-b border-[#F1EBE0] pb-3">
              <div>
                <h3 className="font-heading text-lg font-bold text-[#2C1E16]">
                  Pelunasan Upah Pekerja
                </h3>
                <p className="text-xs text-[#8B7355] mt-0.5">
                  Pekerja: <span className="font-semibold text-[#2C1E16]">{settleWorker.worker_name || settleWorker.name}</span>
                </p>
              </div>
              <button
                disabled={submitting}
                onClick={() => setSettleModalOpen(false)}
                className="p-1.5 text-[#8B7355] hover:text-[#2C1E16] rounded-lg hover:bg-[#FBF9F4]"
              >
                <X size={18} />
              </button>
            </div>

            {/* Error Message */}
            {settleError && (
              <div className="mt-3 rounded-lg border border-red-200 bg-red-50 p-2.5 text-xs text-red-800 flex items-center gap-2">
                <AlertCircle size={14} className="shrink-0" />
                <span>{settleError}</span>
              </div>
            )}

            {/* Balance Overview */}
            <div className="mt-4 grid grid-cols-2 gap-2 rounded-xl bg-[#FBF9F4] p-3 border border-[#E5DCC5]">
              <div>
                <span className="text-[11px] text-[#8B7355]">Total Saldo Terutang</span>
                <div className="font-heading font-bold text-amber-950 text-base" data-testid="modal-pending-balance">
                  {money(settleWorker.total_le || settleWorker.total_pending_wages_le || 0)}
                </div>
              </div>
              <div>
                <span className="text-[11px] text-[#8B7355]">Jumlah Kewajiban</span>
                <div className="font-heading font-semibold text-[#5C4A3D] text-base">
                  {settleWorker.count || settleWorker.pending_obligations_count || settleWorkerObligations.length} Tugas
                </div>
              </div>
            </div>

            {/* Currency Selector */}
            <div className="mt-4">
              <Label className="text-xs text-[#5C4A3D] mb-1.5 block font-semibold">Mata Uang Pembayaran *</Label>
              <div className="grid grid-cols-2 gap-2">
                <button
                  type="button"
                  onClick={() => {
                    setSettleCurrency("EGP");
                    setSettleMethod("cash");
                  }}
                  data-testid="settle-currency-egp-btn"
                  className={`flex flex-col items-center justify-center p-2.5 rounded-xl border text-xs font-semibold transition-all min-h-[48px] ${
                    settleCurrency === "EGP"
                      ? "border-[#8B5A2B] bg-[#8B5A2B] text-white shadow-xs"
                      : "border-[#E5DCC5] bg-white text-[#5C4A3D] hover:bg-[#FBF9F4]"
                  }`}
                >
                  <span>Kas EGP (LE)</span>
                  <span className={`text-[10px] ${settleCurrency === "EGP" ? "text-amber-100" : "text-[#8B7355]"}`}>
                    Tunai Fisik Kairo
                  </span>
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setSettleCurrency("IDR");
                    setSettleMethod("bank_transfer");
                    if (settleLockedRate) setSettleRate(String(settleLockedRate));
                  }}
                  data-testid="settle-currency-idr-btn"
                  className={`flex flex-col items-center justify-center p-2.5 rounded-xl border text-xs font-semibold transition-all min-h-[48px] ${
                    settleCurrency === "IDR"
                      ? "border-[#8B5A2B] bg-[#8B5A2B] text-white shadow-xs"
                      : "border-[#E5DCC5] bg-white text-[#5C4A3D] hover:bg-[#FBF9F4]"
                  }`}
                >
                  <span>Bank IDR (Rupiah)</span>
                  <span className={`text-[10px] ${settleCurrency === "IDR" ? "text-amber-100" : "text-[#8B7355]"}`}>
                    Transfer Bank Indonesia
                  </span>
                </button>
              </div>
            </div>

            {/* IDR Conversion & Rate Override Card */}
            {settleCurrency === "IDR" && (() => {
              const amtNum = parseFloat(settleAmount) || 0;
              const rateNum = parseFloat(settleRate) || 0;
              const standardIdr = Math.round(amtNum * rateNum);
              const currentActualIdr = (settleIsCustomPayout && settleActualPayout !== "") ? Math.round(parseFloat(settleActualPayout) || 0) : standardIdr;
              const payoutVariance = currentActualIdr - standardIdr;

              return (
                <div className="mt-3 rounded-xl bg-amber-50/70 p-3 border border-amber-200 text-xs space-y-2.5">
                  <div className="flex justify-between items-center">
                    <span className="font-semibold text-amber-950">Kurs Terkini (Pengaturan):</span>
                    <span className="font-bold text-amber-900" data-testid="locked-rate-display">
                      {settleLockedRate ? `1 LE = Rp ${Number(settleLockedRate).toLocaleString("id-ID")}` : "Tidak tersedia (Kewajiban lama)"}
                    </span>
                  </div>
                  {settleOrderHistoricalRate && (
                    <div className="flex justify-between items-center text-[11px] text-[#8B7355] pt-0.5">
                      <span>Kurs Order Historis (Informasi):</span>
                      <span className="font-medium">1 LE = Rp {Number(settleOrderHistoricalRate).toLocaleString("id-ID")}</span>
                    </div>
                  )}
                  <div className="flex justify-between items-center pt-1 border-t border-amber-200/60">
                    <span className="text-[#5C4A3D]">Estimasi Konversi Standar IDR:</span>
                    <span className="font-bold text-base text-[#8B5A2B]" data-testid="estimated-idr-payout">
                      Rp {standardIdr.toLocaleString("id-ID")}
                    </span>
                  </div>
                  <p className="text-[11px] text-[#8B7355] leading-relaxed">
                    Kewajiban upah pekerja terutang berkurang sebesar <strong>{amtNum} LE</strong>. Rekening Bank IDR berkurang <strong>Rp {currentActualIdr.toLocaleString("id-ID")}</strong>.
                  </p>

                  {/* Custom Actual IDR Payout Control */}
                  <div className="pt-2 border-t border-amber-200/60 space-y-2">
                    <label className="flex items-center gap-2 cursor-pointer text-xs font-semibold text-amber-950 py-1">
                      <input
                        type="checkbox"
                        checked={settleIsCustomPayout}
                        onChange={(e) => {
                          setSettleIsCustomPayout(e.target.checked);
                          if (!e.target.checked) {
                            setSettleActualPayout("");
                          } else {
                            setSettleActualPayout(String(standardIdr));
                          }
                        }}
                        data-testid="custom-payout-toggle"
                        className="rounded border-amber-300 text-[#8B5A2B] focus:ring-[#8B5A2B] h-4 w-4"
                      />
                      <span>Sesuaikan nominal pencairan IDR aktual (Transfer/Tunai riil)</span>
                    </label>

                    {settleIsCustomPayout && (
                      <div className="space-y-2 pt-1">
                        <div>
                          <Label className="text-[11px] text-[#5C4A3D]">Nominal Pencairan IDR Aktual (Rp) *</Label>
                          <Input
                            type="number"
                            step="1"
                            required
                            placeholder={`Contoh: ${standardIdr}`}
                            value={settleActualPayout}
                            onChange={(e) => setSettleActualPayout(e.target.value)}
                            className="bg-white border-amber-300 text-xs font-semibold mt-1 h-10 sm:h-9"
                            data-testid="settle-actual-payout-input"
                          />
                        </div>

                        {payoutVariance !== 0 && (
                          <div
                            className="rounded-lg p-2.5 border bg-amber-100/70 border-amber-300 text-amber-950 text-xs space-y-1"
                            data-testid="payout-variance-warning"
                          >
                            <div className="flex items-center justify-between font-semibold">
                              <span>Selisih Konversi Aktual:</span>
                              <span className={payoutVariance > 0 ? "text-amber-900 font-bold" : "text-blue-900 font-bold"}>
                                {payoutVariance > 0 ? `+Rp ${payoutVariance.toLocaleString("id-ID")}` : `-Rp ${Math.abs(payoutVariance).toLocaleString("id-ID")}`}
                              </span>
                            </div>
                            <p className="text-[11px] text-amber-900 leading-tight">
                              <strong>Validasi Kewajiban:</strong> Pengurangan hutang upah pekerja tetap dihitung sebesar <strong>{amtNum} LE</strong>. Selisih pembayaran aktual ini ({payoutVariance > 0 ? "+" : ""}Rp {payoutVariance.toLocaleString("id-ID")}) dicatat dalam audit trail tanpa menghapus sisa saldo LE pekerja secara sepihak.
                            </p>
                          </div>
                        )}
                      </div>
                    )}
                  </div>

                  {/* Override rate toggle / controls */}
                  {settleLockedRate ? (
                    <div className="pt-2 border-t border-amber-200/60 space-y-2">
                      <label className="flex items-center gap-2 cursor-pointer text-xs font-semibold text-amber-950 py-1">
                        <input
                          type="checkbox"
                          checked={settleIsOverride}
                          onChange={(e) => {
                            setSettleIsOverride(e.target.checked);
                            if (!e.target.checked && settleLockedRate) {
                              setSettleRate(String(settleLockedRate));
                              setSettleOverrideReason("");
                            }
                          }}
                          data-testid="rate-override-toggle"
                          className="rounded border-amber-300 text-[#8B5A2B] focus:ring-[#8B5A2B] h-4 w-4"
                        />
                        <span>Ubah kurs penyelesaian aktual (Override Kurs)</span>
                      </label>

                      {settleIsOverride && (
                        <div className="space-y-2 pt-1">
                          <div>
                            <Label className="text-[11px] text-[#5C4A3D]">Kurs Override (Rp per LE) *</Label>
                            <Input
                              type="number"
                              step="0.01"
                              required
                              placeholder="Contoh: 360"
                              value={settleRate}
                              onChange={(e) => setSettleRate(e.target.value)}
                              className="bg-white border-amber-300 text-xs font-semibold mt-1 h-10 sm:h-9"
                              data-testid="settle-override-rate-input"
                            />
                          </div>
                          <div>
                            <Label className="text-[11px] text-[#5C4A3D]">Alasan Perubahan Kurs (Wajib dicatat untuk audit) *</Label>
                            <Input
                              placeholder="Contoh: Penyesuaian kurs transfer bank BCA riil"
                              value={settleOverrideReason}
                              onChange={(e) => setSettleOverrideReason(e.target.value)}
                              className="bg-white border-amber-300 text-xs mt-1 h-10 sm:h-9"
                              data-testid="settle-override-reason-input"
                            />
                          </div>
                        </div>
                      )}
                    </div>
                  ) : (
                    <div className="pt-2 border-t border-amber-200/60 space-y-1">
                      <Label className="text-[11px] text-[#5C4A3D]">Kurs Penyelesaian IDR (Rp per LE) *</Label>
                      <Input
                        type="number"
                        step="0.01"
                        required
                        placeholder="Masukkan kurs penyelesaian..."
                        value={settleRate}
                        onChange={(e) => setSettleRate(e.target.value)}
                        className="bg-white border-amber-300 text-xs font-semibold mt-1 h-10 sm:h-9"
                        data-testid="settle-rate-legacy-input"
                      />
                    </div>
                  )}
                </div>
              );
            })()}

            <form onSubmit={handleSettleSubmit} className="mt-4 space-y-3">
              <div>
                <div className="flex justify-between items-center mb-1">
                  <Label className="text-xs text-[#5C4A3D]">Nominal Kewajiban yang Dilunasi (EGP / LE) *</Label>
                  <button
                    type="button"
                    onClick={() => setSettleAmount(String(settleWorker.total_le || settleWorker.total_pending_wages_le || 0))}
                    className="text-xs text-[#8B5A2B] font-semibold hover:underline py-1 flex items-center"
                    data-testid="pay-full-btn"
                  >
                    Bayar Lunas Semua
                  </button>
                </div>
                <Input
                  type="number"
                  step="0.01"
                  required
                  placeholder="Contoh: 250"
                  value={settleAmount}
                  onChange={(e) => setSettleAmount(e.target.value)}
                  className="bg-white border-[#E5DCC5] font-semibold text-[#2C1E16] h-10 sm:h-9 text-sm sm:text-xs"
                  data-testid="settle-amount-input"
                />
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <Label className="text-xs text-[#5C4A3D]">Metode Pembayaran</Label>
                  <Select value={settleMethod} onValueChange={setSettleMethod}>
                    <SelectTrigger className="bg-white border-[#E5DCC5] text-xs mt-1 h-10 sm:h-9" data-testid="settle-method-select">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {settleCurrency === "EGP" ? (
                        <>
                          <SelectItem value="cash">Tunai / Kas EGP</SelectItem>
                          <SelectItem value="bank_transfer">Transfer Bank (EGP)</SelectItem>
                          <SelectItem value="other">Lainnya</SelectItem>
                        </>
                      ) : (
                        <>
                          <SelectItem value="bank_transfer">Transfer Bank (Rekening IDR)</SelectItem>
                          <SelectItem value="cash">Tunai IDR</SelectItem>
                          <SelectItem value="other">Lainnya</SelectItem>
                        </>
                      )}
                    </SelectContent>
                  </Select>
                </div>
                <div>
                  <Label className="text-xs text-[#5C4A3D]">Tanggal Transaksi</Label>
                  <Input
                    type="date"
                    required
                    value={settleDate}
                    onChange={(e) => setSettleDate(e.target.value)}
                    className="bg-white border-[#E5DCC5] text-xs mt-1 h-10 sm:h-9"
                    data-testid="settle-date-input"
                  />
                </div>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <Label className="text-xs text-[#5C4A3D]">Nomor Referensi (Opsional)</Label>
                  <Input
                    placeholder="Contoh: Kuitansi No. 12 / Bukti Transfer"
                    value={settleRef}
                    onChange={(e) => setSettleRef(e.target.value)}
                    className="bg-white border-[#E5DCC5] text-xs mt-1 h-10 sm:h-9"
                    data-testid="settle-ref-input"
                  />
                </div>
                <div>
                  <Label className="text-xs text-[#5C4A3D]">Catatan (Opsional)</Label>
                  <Textarea
                    placeholder="Keterangan tambahan..."
                    rows={2}
                    value={settleNotes}
                    onChange={(e) => setSettleNotes(e.target.value)}
                    className="bg-white border-[#E5DCC5] text-xs mt-1"
                    data-testid="settle-notes-input"
                  />
                </div>
              </div>

              {/* Allocation Preview */}
              <div className="pt-2 text-[11px] text-[#8B7355]">
                Sistem akan mengalokasikan pembayaran secara <strong>FIFO</strong> (kewajiban tugas tertua akan dilunasi terlebih dahulu).
              </div>

              <div className="pt-3 border-t border-[#F1EBE0] flex flex-col-reverse sm:flex-row justify-end gap-2">
                <Button
                  type="button"
                  variant="outline"
                  disabled={submitting}
                  onClick={() => setSettleModalOpen(false)}
                  className="rounded-xl border-[#E5DCC5] text-xs h-10 sm:h-9 w-full sm:w-auto"
                >
                  Batal
                </Button>
                <Button
                  type="submit"
                  disabled={submitting}
                  className="rounded-xl bg-[#8B5A2B] text-white hover:bg-[#6D4522] text-xs font-semibold h-10 sm:h-9 w-full sm:w-auto"
                  data-testid="submit-settle-btn"
                >
                  {submitting ? "Memproses..." : "Konfirmasi Pembayaran Upah"}
                </Button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* SETTLEMENT DETAIL MODAL */}
      {detailModalOpen && selectedSettlement && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-xs"
          onClick={() => setDetailModalOpen(false)}
          data-testid="settlement-detail-modal"
        >
          <div
            className="relative w-full max-w-xl rounded-2xl border border-[#E5DCC5] bg-white p-5 sm:p-6 shadow-xl max-h-[90vh] overflow-y-auto"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between border-b border-[#F1EBE0] pb-3">
              <div>
                <h3 className="font-heading text-lg font-bold text-[#2C1E16]">
                  Rincian Pelunasan Upah
                </h3>
                <span className="font-mono text-xs text-[#8B5A2B]">{selectedSettlement.settlement_number}</span>
              </div>
              <button onClick={() => setDetailModalOpen(false)} className="p-1 text-[#8B7355] hover:text-[#2C1E16]">
                <X size={18} />
              </button>
            </div>

            <div className="mt-4 grid grid-cols-2 gap-3 text-xs">
              <div>
                <span className="text-[#8B7355]">Pekerja:</span>
                <p className="font-semibold text-[#2C1E16]">{selectedSettlement.worker_name}</p>
              </div>
              <div>
                <span className="text-[#8B7355]">Tanggal Pelunasan:</span>
                <p className="font-semibold text-[#2C1E16]">{selectedSettlement.settlement_date}</p>
              </div>
              <div>
                <span className="text-[#8B7355]">Nominal Kewajiban LE:</span>
                <p className="font-bold text-emerald-800 text-sm">{money(selectedSettlement.amount_le)}</p>
              </div>
              <div>
                <span className="text-[#8B7355]">Mata Uang & Metode:</span>
                <div className="flex items-center gap-1.5 mt-0.5">
                  <span className={`px-1.5 py-0.5 rounded text-[10px] font-semibold uppercase ${
                    (selectedSettlement.payout_currency || "EGP") === "IDR"
                      ? "bg-purple-100 text-purple-800 border border-purple-200"
                      : "bg-amber-100 text-amber-800 border border-amber-200"
                  }`}>
                    {selectedSettlement.payout_currency || "EGP"}
                  </span>
                  <span className="font-medium text-[#2C1E16] capitalize">
                    {selectedSettlement.payment_method === "cash" ? "Tunai" : selectedSettlement.payment_method}
                  </span>
                </div>
              </div>

              {selectedSettlement.payout_currency === "IDR" && (
                <>
                  <div>
                    <span className="text-[#8B7355]">Nominal Pencairan IDR:</span>
                    <p className="font-bold text-[#8B5A2B] text-sm" data-testid="detail-payout-idr">
                      Rp {Number(selectedSettlement.payout_amount || 0).toLocaleString("id-ID")}
                    </p>
                  </div>
                  <div>
                    <span className="text-[#8B7355]">Kurs Digunakan:</span>
                    <p className="font-semibold text-[#2C1E16]">
                      1 LE = Rp {Number(selectedSettlement.settlement_rate || selectedSettlement.locked_exchange_rate || 0).toLocaleString("id-ID")}
                      {selectedSettlement.is_rate_override && (
                        <span className="ml-1 text-[10px] font-bold text-amber-700 bg-amber-50 px-1 py-0.5 rounded border border-amber-200">
                          (Override)
                        </span>
                      )}
                    </p>
                  </div>
                  {selectedSettlement.is_rate_override && selectedSettlement.override_reason && (
                    <div className="col-span-2">
                      <span className="text-[#8B7355]">Alasan Override Kurs:</span>
                      <p className="text-[#2C1E16] bg-amber-50/70 p-1.5 rounded border border-amber-200 text-[11px]">
                        {selectedSettlement.override_reason}
                      </p>
                    </div>
                  )}
                  {Number(selectedSettlement.variance_idr || 0) !== 0 && (
                    <div className="col-span-2" data-testid="detail-variance-notice">
                      <span className="text-[#8B7355]">Selisih Pencairan Aktual:</span>
                      <p className="text-[#2C1E16] bg-blue-50/70 p-1.5 rounded border border-blue-200 text-[11px]">
                        {Number(selectedSettlement.variance_idr) > 0 ? "+" : ""}Rp {Number(selectedSettlement.variance_idr).toLocaleString("id-ID")} dari konversi standar Rp {Number(selectedSettlement.standard_payout_amount || 0).toLocaleString("id-ID")}. Pengurangan kewajiban LE tetap murni sebesar {selectedSettlement.amount_le} LE.
                      </p>
                    </div>
                  )}
                </>
              )}

              {selectedSettlement.reference && (
                <div className="col-span-2">
                  <span className="text-[#8B7355]">Referensi:</span>
                  <p className="text-[#2C1E16]">{selectedSettlement.reference}</p>
                </div>
              )}
              {selectedSettlement.notes && (
                <div className="col-span-2">
                  <span className="text-[#8B7355]">Catatan:</span>
                  <p className="text-[#2C1E16]">{selectedSettlement.notes}</p>
                </div>
              )}
            </div>

            {/* Allocations Table */}
            <div className="mt-4 pt-3 border-t border-[#F1EBE0]">
              <h4 className="font-heading font-semibold text-xs text-[#5C4A3D] mb-2">
                Alokasi Pelunasan Kewajiban ({selectedSettlement.allocations?.length || 0})
              </h4>
              <div className="rounded-lg border border-[#E5DCC5] overflow-hidden">
                <table className="w-full text-[11px]">
                  <thead className="bg-[#FAF5EE] text-left uppercase text-[#8B7355] border-b border-[#E5DCC5]">
                    <tr>
                      <th className="p-2">No. Kewajiban</th>
                      <th className="p-2 text-right">Alokasi (LE)</th>
                      <th className="p-2 text-right">Saldo Baru</th>
                      <th className="p-2 text-center">Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(selectedSettlement.allocations || []).map((a, i) => (
                      <tr key={i} className="border-b border-[#F1EBE0]">
                        <td className="p-2 font-mono font-medium">{a.obligation_number}</td>
                        <td className="p-2 text-right font-semibold text-emerald-800">{money(a.amount_le)}</td>
                        <td className="p-2 text-right text-[#8B7355]">{money(a.new_paid_amount_le)} / {money(a.obligation_total_amount_le)}</td>
                        <td className="p-2 text-center">
                          <span className={`px-1.5 py-0.5 rounded text-[10px] uppercase font-semibold ${
                            a.obligation_status_after === "paid" ? "bg-emerald-100 text-emerald-800" : "bg-blue-100 text-blue-800"
                          }`}>
                            {a.obligation_status_after === "paid" ? "Lunas" : "Sebagian"}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            {/* Void Action if not already voided */}
            {selectedSettlement.status !== "voided" ? (
              <div className="mt-4 pt-4 border-t border-[#F1EBE0] space-y-2">
                <Label className="text-xs text-red-800 font-semibold">Batalkan Pembayaran Upah (Administratif)</Label>
                <div className="rounded-md bg-amber-50 border border-amber-200 p-2 text-[11px] text-amber-900 leading-relaxed">
                  <strong>Peringatan:</strong> Pembatalan ini membatalkan pencatatan pengeluaran kas di buku besar dan mengembalikan saldo kewajiban upah pekerja. Jangan batalkan jika uang fisik sudah diserahkan dan tidak dapat ditarik kembali.
                </div>
                <Input
                  placeholder="Alasan pembatalan (wajib)..."
                  value={voidReason}
                  onChange={(e) => setVoidReason(e.target.value)}
                  className="text-xs bg-white border-red-200"
                  data-testid="void-reason-input"
                />
                <Button
                  variant="destructive"
                  size="sm"
                  disabled={voiding || !voidReason.trim()}
                  onClick={handleVoidSettlement}
                  className="w-full text-xs font-semibold"
                  data-testid="confirm-void-btn"
                >
                  {voiding ? "Membatalkan..." : "Batalkan Pembayaran & Kembalikan Saldo Kewajiban"}
                </Button>
              </div>
            ) : (
              <div className="mt-4 rounded-lg bg-red-50 border border-red-200 p-3 text-xs text-red-800">
                <span className="font-semibold">Pembayaran Dibatalkan:</span> {selectedSettlement.void_reason || "Tidak ada alasan tercatat."}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
