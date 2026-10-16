import React, { useEffect, useState, useMemo } from "react";
import api from "../../lib/api";
import { formatApiError } from "../../lib/format";
import { useAuth } from "../../context/AuthContext";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Textarea } from "../../components/ui/textarea";
import {
  CircleDollarSign,
  ShieldCheck,
  ShieldAlert,
  Save,
  RotateCcw,
  Calculator,
  History,
  AlertTriangle,
  Info,
  CheckCircle2,
  Users,
  Coins,
  ArrowRight,
  X
} from "lucide-react";
import { toast } from "sonner";

export default function AdminDeliveryWageSettings() {
  const { user } = useAuth();
  const isOwner = user?.role === "owner";
  const hasFinance = user?.permissions?.access_finance || isOwner;

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [policy, setPolicy] = useState({
    base_wage_per_order_le: 50.0,
    unusual_amount_threshold_le: 100.0,
    max_helper_wage_per_order_le: 500.0,
    currency: "EGP",
    rounding_policy: "piastre_round_half_up"
  });
  const [history, setHistory] = useState([]);

  // Simulator states
  const [simAmount, setSimAmount] = useState(50.0);
  const [simHelperCount, setSimHelperCount] = useState(3);
  const [testModalOpen, setTestModalOpen] = useState(false);
  const [testOverrideReason, setTestOverrideReason] = useState("");
  const [testConfirmed, setTestConfirmed] = useState(false);

  const loadPolicy = async () => {
    try {
      setLoading(true);
      const res = await api.get("/admin/delivery-wage-policy");
      if (res.data) {
        setPolicy({
          base_wage_per_order_le: Number(res.data.base_wage_per_order_le) || 50.0,
          unusual_amount_threshold_le: Number(res.data.unusual_amount_threshold_le) || 100.0,
          max_helper_wage_per_order_le: Number(res.data.max_helper_wage_per_order_le) || 500.0,
          currency: res.data.currency || "EGP",
          rounding_policy: res.data.rounding_policy || "piastre_round_half_up",
          updated_at: res.data.updated_at,
          updated_by_name: res.data.updated_by_name
        });
        setSimAmount(Number(res.data.base_wage_per_order_le) || 50.0);
      }
    } catch (err) {
      toast.error("Gagal memuat kebijakan upah: " + formatApiError(err.response?.data?.detail));
    } finally {
      setLoading(false);
    }
  };

  const loadHistory = async () => {
    try {
      const res = await api.get("/admin/delivery-wage-policy/history");
      setHistory(Array.isArray(res.data) ? res.data : []);
    } catch {
      // Non-critical history loading failure
    }
  };

  useEffect(() => {
    if (hasFinance) {
      loadPolicy();
      loadHistory();
    }
  }, [hasFinance]);

  // Client-side exact piastre simulation calculation
  const simAllocations = useMemo(() => {
    const n = Math.max(1, parseInt(simHelperCount, 10) || 1);
    const totalPiastres = Math.round((Number(simAmount) || 0) * 100);
    if (totalPiastres < 0) return [];

    const quotient = Math.floor(totalPiastres / n);
    const remainder = totalPiastres % n;

    const list = [];
    for (let i = 0; i < n; i++) {
      const p = i < remainder ? quotient + 1 : quotient;
      list.push({
        index: i + 1,
        piastres: p,
        amount_le: (p / 100).toFixed(2),
        pct: totalPiastres > 0 ? ((p / totalPiastres) * 100).toFixed(1) : 0
      });
    }
    return list;
  }, [simAmount, simHelperCount]);

  const isSimOverHardCap = Number(simAmount) > Number(policy.max_helper_wage_per_order_le);
  const isSimOverThreshold = Number(simAmount) > Number(policy.unusual_amount_threshold_le) && !isSimOverHardCap;
  const isSimNormal = Number(simAmount) <= Number(policy.unusual_amount_threshold_le);

  const handleSavePolicy = async () => {
    if (!isOwner) {
      toast.error("Hanya Owner/CEO yang memiliki hak untuk mengubah kebijakan upah.");
      return;
    }
    const baseWage = Number(policy.base_wage_per_order_le);
    const threshold = Number(policy.unusual_amount_threshold_le);
    const hardCap = Number(policy.max_helper_wage_per_order_le);

    if (isNaN(baseWage) || baseWage < 0) {
      toast.error("Tarif dasar upah harus berupa angka valid dan tidak boleh negatif.");
      return;
    }
    if (isNaN(threshold) || threshold <= 0) {
      toast.error("Batas konfirmasi nominal tidak wajar harus lebih besar dari 0.");
      return;
    }
    if (isNaN(hardCap) || hardCap <= 0) {
      toast.error("Batas maksimum keras upah (hard cap) harus lebih besar dari 0.");
      return;
    }
    if (baseWage > threshold) {
      toast.error(`Tarif dasar (${baseWage} LE) tidak boleh melebihi batas konfirmasi (${threshold} LE).`);
      return;
    }
    if (threshold >= hardCap) {
      toast.error(`Batas konfirmasi (${threshold} LE) harus lebih kecil dari batas maksimum keras (${hardCap} LE). Hubungan yang diwajibkan: dasar <= batas konfirmasi < batas maksimum keras.`);
      return;
    }

    try {
      setSaving(true);
      const payload = {
        base_wage_per_order_le: baseWage,
        unusual_amount_threshold_le: threshold,
        max_helper_wage_per_order_le: hardCap,
        currency: policy.currency || "EGP",
        rounding_policy: "piastre_round_half_up"
      };
      await api.put("/admin/delivery-wage-policy", payload);
      toast.success("Kebijakan upah bertingkat berhasil disimpan!");
      await loadPolicy();
      await loadHistory();
    } catch (err) {
      toast.error("Gagal menyimpan: " + formatApiError(err.response?.data?.detail));
    } finally {
      setSaving(false);
    }
  };

  if (!hasFinance) {
    return (
      <div className="rounded-2xl border border-red-200 bg-red-50 p-6 text-center text-red-700">
        <ShieldAlert size={40} className="mx-auto mb-2 text-red-500" />
        <h2 className="text-lg font-bold">Akses Terbatas</h2>
        <p className="text-sm">Halaman ini hanya dapat diakses oleh Owner atau Administrator Keuangan.</p>
      </div>
    );
  }

  return (
    <div className="max-w-4xl space-y-6">
      {/* Page Header */}
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between border-b border-[#E5DCC5] pb-4">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="font-heading text-2xl font-bold text-[#2C1E16]">Pengaturan Upah Pengiriman</h1>
            {isOwner ? (
              <span className="inline-flex items-center gap-1 rounded-full bg-emerald-100 px-2.5 py-0.5 text-xs font-semibold text-emerald-800">
                <ShieldCheck size={12} /> Owner
              </span>
            ) : (
              <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2.5 py-0.5 text-xs font-semibold text-amber-800">
                <Info size={12} /> Keuangan (Mode Baca)
              </span>
            )}
          </div>
          <p className="mt-1 text-xs sm:text-sm text-[#8B7355]">
            Konfigurasi tarif upah helper pengantaran, batas konfirmasi nominal tidak wajar, dan pembagian presisi piastre.
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={() => { loadPolicy(); loadHistory(); }}
          className="rounded-xl border-[#E5DCC5] text-[#5C4A3D] hover:bg-[#EFE6D5]"
        >
          <RotateCcw size={14} className="mr-1" /> Muat Ulang
        </Button>
      </div>

      {/* Role Alert / Notice */}
      {!isOwner && (
        <div className="rounded-xl border border-amber-200 bg-amber-50 p-3.5 text-xs sm:text-sm text-amber-900 flex items-start gap-2.5">
          <Info size={18} className="text-amber-600 shrink-0 mt-0.5" />
          <div>
            <span className="font-semibold">Mode Baca Saja (Tim Keuangan):</span> Anda dapat melihat kebijakan aktif, mensimulasikan alokasi upah, dan memverifikasi batas konfirmasi. Perubahan kebijakan dasar hanya dapat disimpan oleh Owner/CEO.
          </div>
        </div>
      )}

      {/* Main Settings Card */}
      <div className="rounded-2xl border border-[#E5DCC5] bg-white p-5 sm:p-6 shadow-sm space-y-5">
        <div className="flex items-center gap-2 font-heading text-sm font-bold uppercase tracking-wider text-[#8B5A2B]">
          <CircleDollarSign size={18} /> Kebijakan Upah Helper Bertingkat
        </div>

        {loading ? (
          <div className="py-8 text-center text-sm text-[#8B7355]">Memuat kebijakan...</div>
        ) : (
          <div className="grid gap-5 sm:grid-cols-3">
            <div>
              <Label className="block text-sm font-semibold text-[#2C1E16] mb-1">
                Tarif Dasar Upah per Pesanan (EGP)
              </Label>
              <div className="relative">
                <Input
                  type="number"
                  min="0"
                  step="1"
                  disabled={!isOwner || saving}
                  value={policy.base_wage_per_order_le}
                  onChange={(e) => setPolicy({ ...policy, base_wage_per_order_le: e.target.value })}
                  className="bg-white pr-12 font-medium"
                />
                <span className="absolute right-3 top-2.5 text-xs font-bold text-[#8B7355]">EGP</span>
              </div>
              <p className="mt-1 text-xs text-[#8B7355]">
                Tarif standar per pesanan sukses yang dibagi rata kepada seluruh helper internal trip.
              </p>
            </div>

            <div>
              <Label className="block text-sm font-semibold text-[#2C1E16] mb-1">
                Batas Konfirmasi Nominal (EGP)
              </Label>
              <div className="relative">
                <Input
                  type="number"
                  min="1"
                  step="10"
                  disabled={!isOwner || saving}
                  value={policy.unusual_amount_threshold_le}
                  onChange={(e) => setPolicy({ ...policy, unusual_amount_threshold_le: e.target.value })}
                  className="bg-white pr-12 font-medium"
                />
                <span className="absolute right-3 top-2.5 text-xs font-bold text-[#8B7355]">EGP</span>
              </div>
              <p className="mt-1 text-xs text-[#8B7355]">
                Ambang peringatan. Di atas batas ini butuh konfirmasi dan alasan tertulis (Default: 100 EGP).
              </p>
            </div>

            <div>
              <Label className="block text-sm font-semibold text-[#2C1E16] mb-1">
                Batas Maksimum Keras (EGP)
              </Label>
              <div className="relative">
                <Input
                  type="number"
                  min="1"
                  step="10"
                  disabled={!isOwner || saving}
                  value={policy.max_helper_wage_per_order_le}
                  onChange={(e) => setPolicy({ ...policy, max_helper_wage_per_order_le: e.target.value })}
                  className="bg-white pr-12 font-medium text-rose-700"
                />
                <span className="absolute right-3 top-2.5 text-xs font-bold text-rose-600">EGP</span>
              </div>
              <p className="mt-1 text-xs text-[#8B7355]">
                Plafon liabilitas mutlak. Di atas batas ini otomatis ditolak oleh backend (Default: 500 EGP).
              </p>
            </div>

            <div className="sm:col-span-3 rounded-xl border border-[#F1EBE0] bg-[#FAF8F5] p-3.5 space-y-1">
              <div className="text-xs font-semibold text-[#5C4A3D] flex items-center gap-1.5">
                <Coins size={14} className="text-[#8B5A2B]" /> Aturan Kebijakan Bertingkat: Dasar &le; Batas Konfirmasi &lt; Batas Maksimum Keras
              </div>
              <p className="text-xs text-[#8B7355]">
                Sistem menggunakan aritmatika integer piastre eksak (1 piastre = 0.01 EGP). Seluruh alokasi helper selalu berjumlah persis 100% dari total upah tanpa ada selisih uang mengambang.
              </p>
            </div>
          </div>
        )}

        {isOwner && (
          <div className="pt-2 flex justify-end">
            <Button
              onClick={handleSavePolicy}
              disabled={saving || loading}
              className="rounded-xl bg-[#8B5A2B] hover:bg-[#6B4423] text-white px-5"
            >
              <Save size={16} className="mr-1.5" />
              {saving ? "Menyimpan..." : "Simpan Pengaturan Upah"}
            </Button>
          </div>
        )}
      </div>

      {/* Live Allocation Preview & Threshold Simulator */}
      <div className="rounded-2xl border border-[#E5DCC5] bg-white p-5 sm:p-6 shadow-sm space-y-5">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 font-heading text-sm font-bold uppercase tracking-wider text-[#8B5A2B]">
            <Calculator size={18} /> Simulator Distribusi Upah & Uji Ambang Batas
          </div>
          <span className="text-xs text-[#8B7355]">Alat Bantu Estimasi</span>
        </div>

        <p className="text-xs sm:text-sm text-[#8B7355]">
          Simulasikan bagaimana nominal upah dibagi rata di antara helper dan verifikasi bagaimana kebijakan bertingkat memperlakukan nominal tersebut.
        </p>

        <div className="grid gap-4 sm:grid-cols-2 bg-[#F9F6F0] p-4 rounded-xl border border-[#E5DCC5]/60">
          <div>
            <Label className="text-xs font-semibold text-[#5C4A3D]">Nominal Simulasi (EGP)</Label>
            <div className="relative mt-1">
              <Input
                type="number"
                min="0"
                step="5"
                value={simAmount}
                onChange={(e) => setSimAmount(e.target.value)}
                className="bg-white pr-12 text-sm font-bold text-[#2C1E16]"
              />
              <span className="absolute right-3 top-2.5 text-xs font-bold text-[#8B7355]">EGP</span>
            </div>
          </div>

          <div>
            <Label className="text-xs font-semibold text-[#5C4A3D]">Jumlah Helper Ditugaskan</Label>
            <div className="flex items-center gap-2 mt-1">
              {[1, 2, 3, 4, 5].map((count) => (
                <button
                  key={count}
                  type="button"
                  onClick={() => setSimHelperCount(count)}
                  className={`flex-1 py-2 text-xs font-bold rounded-lg border transition-colors ${
                    simHelperCount === count
                      ? "bg-[#8B5A2B] text-white border-[#8B5A2B]"
                      : "bg-white text-[#5C4A3D] border-[#E5DCC5] hover:bg-[#EFE6D5]"
                  }`}
                >
                  {count} Helper
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Tier Status Badges */}
        {isSimOverHardCap && (
          <div className="rounded-xl border border-rose-300 bg-rose-50 p-4 text-xs sm:text-sm text-rose-950 flex items-start gap-2.5">
            <ShieldAlert size={20} className="text-rose-600 shrink-0 mt-0.5" />
            <div>
              <span className="font-bold">Nominal Melebihi Batas Maksimum Keras ({policy.max_helper_wage_per_order_le} EGP):</span>
              <p className="mt-0.5 text-xs text-rose-800">
                Sistem backend akan <strong>MENOLAK OTOMATIS</strong> pengajuan ini dengan HTTP 422. Konfirmasi petugas dan alasan tidak dapat melewati batas ini.
              </p>
            </div>
          </div>
        )}

        {isSimOverThreshold && (
          <div className="rounded-xl border border-amber-300 bg-amber-50 p-4 text-xs sm:text-sm text-amber-950 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
            <div className="flex items-start gap-2.5">
              <AlertTriangle size={20} className="text-amber-600 shrink-0 mt-0.5" />
              <div>
                <span className="font-bold">Nominal Memerlukan Konfirmasi Petugas ({policy.unusual_amount_threshold_le} - {policy.max_helper_wage_per_order_le} EGP):</span>
                <p className="mt-0.5 text-xs text-amber-800">
                  Pada alur serah terima, sistem mewajibkan checkbox konfirmasi kebenaran nominal dan alasan tertulis minimal 5 karakter.
                </p>
              </div>
            </div>
            <Button
              size="sm"
              variant="outline"
              onClick={() => { setTestOverrideReason(""); setTestConfirmed(false); setTestModalOpen(true); }}
              className="shrink-0 rounded-xl border-amber-400 bg-white text-amber-900 hover:bg-amber-100 text-xs font-semibold"
            >
              Uji Coba Dialog Konfirmasi
            </Button>
          </div>
        )}

        {isSimNormal && (
          <div className="rounded-xl border border-emerald-300 bg-emerald-50 p-3 text-xs sm:text-sm text-emerald-950 flex items-center gap-2.5">
            <CheckCircle2 size={18} className="text-emerald-600 shrink-0" />
            <div>
              <span className="font-bold">Nominal Standar (&le; {policy.unusual_amount_threshold_le} EGP):</span>
              <span className="ml-1 text-xs text-emerald-800">Diproses secara normal tanpa memerlukan dialog konfirmasi khusus.</span>
            </div>
          </div>
        )}

        {/* Breakdown Table */}
        <div className="overflow-x-auto rounded-xl border border-[#E5DCC5]">
          <table className="w-full text-left text-xs sm:text-sm">
            <thead className="bg-[#FAF8F5] text-xs font-bold uppercase tracking-wider text-[#8B7355] border-b border-[#E5DCC5]">
              <tr>
                <th className="py-2.5 px-3">Helper</th>
                <th className="py-2.5 px-3">Alokasi (EGP)</th>
                <th className="py-2.5 px-3">Satuan Piastre</th>
                <th className="py-2.5 px-3">Proporsi</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#F1EBE0]">
              {simAllocations.map((a) => (
                <tr key={a.index} className="hover:bg-[#FAF8F5]/60">
                  <td className="py-2.5 px-3 font-medium text-[#2C1E16]">Helper {a.index}</td>
                  <td className="py-2.5 px-3 font-mono font-bold text-[#8B5A2B]">{a.amount_le} EGP</td>
                  <td className="py-2.5 px-3 text-[#5C4A3D] font-mono">{a.piastres} piastre</td>
                  <td className="py-2.5 px-3 text-[#8B7355]">{a.pct}%</td>
                </tr>
              ))}
            </tbody>
            <tfoot className="bg-[#FAF8F5] border-t border-[#E5DCC5] font-bold text-xs sm:text-sm">
              <tr>
                <td className="py-2.5 px-3 text-[#2C1E16]">Total Alokasi Terdistribusi</td>
                <td className="py-2.5 px-3 font-mono text-[#8B5A2B]">
                  {(Number(simAmount) || 0).toFixed(2)} EGP
                </td>
                <td className="py-2.5 px-3 font-mono text-[#5C4A3D]">
                  {Math.round((Number(simAmount) || 0) * 100)} piastre
                </td>
                <td className="py-2.5 px-3 text-emerald-700 flex items-center gap-1">
                  <CheckCircle2 size={13} /> 100% Eksak
                </td>
              </tr>
            </tfoot>
          </table>
        </div>
      </div>

      {/* Change History Card */}
      <div className="rounded-2xl border border-[#E5DCC5] bg-white p-5 sm:p-6 shadow-sm space-y-4">
        <div className="flex items-center gap-2 font-heading text-sm font-bold uppercase tracking-wider text-[#8B5A2B]">
          <History size={18} /> Riwayat Kebijakan &amp; Audit Upah
        </div>

        {history.length === 0 ? (
          <div className="py-6 text-center text-xs text-[#8B7355]">
            Belum ada riwayat perubahan terekam. Kebijakan saat ini menggunakan nilai standar awal.
          </div>
        ) : (
          <div className="overflow-x-auto rounded-xl border border-[#E5DCC5]">
            <table className="w-full text-left text-xs">
              <thead className="bg-[#FAF8F5] text-xs font-bold text-[#8B7355] border-b border-[#E5DCC5]">
                <tr>
                  <th className="py-2.5 px-3">Waktu</th>
                  <th className="py-2.5 px-3">Jenis Kegiatan</th>
                  <th className="py-2.5 px-3">Petugas</th>
                  <th className="py-2.5 px-3">Detail &amp; Nilai</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#F1EBE0]">
                {history.map((h, idx) => (
                  <tr key={idx} className="hover:bg-[#FAF8F5]/60">
                    <td className="py-2 px-3 text-[#5C4A3D]">
                      {h.timestamp ? new Date(h.timestamp).toLocaleString("id-ID") : "-"}
                    </td>
                    <td className="py-2 px-3">
                      {h.action === "update_delivery_wage_policy" && (
                        <span className="inline-flex rounded-md bg-blue-100 px-2 py-0.5 text-[11px] font-semibold text-blue-800">
                          Kebijakan
                        </span>
                      )}
                      {h.action === "delivery_wage_threshold_override" && (
                        <span className="inline-flex rounded-md bg-amber-100 px-2 py-0.5 text-[11px] font-semibold text-amber-800">
                          Konfirmasi Override
                        </span>
                      )}
                      {h.action === "delivery_wage_hard_cap_rejection" && (
                        <span className="inline-flex rounded-md bg-rose-100 px-2 py-0.5 text-[11px] font-semibold text-rose-800">
                          Ditolak Hard Cap
                        </span>
                      )}
                      {!["update_delivery_wage_policy", "delivery_wage_threshold_override", "delivery_wage_hard_cap_rejection"].includes(h.action) && (
                        <span className="inline-flex rounded-md bg-stone-100 px-2 py-0.5 text-[11px] font-semibold text-stone-700">
                          {h.action || "Log"}
                        </span>
                      )}
                    </td>
                    <td className="py-2 px-3 font-medium text-[#2C1E16]">{h.performed_by_name || "Petugas"}</td>
                    <td className="py-2 px-3 text-[#5C4A3D]">
                      {h.action === "update_delivery_wage_policy" && h.metadata?.new && (
                        <span>
                          Dasar: {h.metadata.new.base_wage_per_order_le} LE | Ambang: {h.metadata.new.unusual_amount_threshold_le} LE | Cap: {h.metadata.new.max_helper_wage_per_order_le} LE
                        </span>
                      )}
                      {h.action === "delivery_wage_threshold_override" && (
                        <span>
                          Pesanan: <span className="font-mono font-medium">{h.entity_identifier || h.metadata?.order_number}</span> | Upah: <strong>{h.metadata?.recorded_amount_le} LE</strong> | Alasan: <em>{h.metadata?.override_reason}</em>
                        </span>
                      )}
                      {h.action === "delivery_wage_hard_cap_rejection" && (
                        <span className="text-rose-700">
                          Pesanan: <span className="font-mono">{h.entity_identifier || h.metadata?.order_number}</span> | Dicoba: <strong>{h.metadata?.attempted_amount_le} LE</strong> (Batas Keras: {h.metadata?.hard_cap_le} LE) — Ditolak
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Threshold Override Interactive Confirmation Modal */}
      {testModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div className="w-full max-w-md rounded-2xl border border-[#E5DCC5] bg-white p-6 shadow-xl space-y-4 animate-in fade-in zoom-in-95">
            <div className="flex items-center justify-between border-b border-[#F1EBE0] pb-3">
              <div className="flex items-center gap-2 font-heading text-base font-bold text-amber-900">
                <AlertTriangle size={20} className="text-amber-600" />
                Konfirmasi Nominal Tidak Wajar
              </div>
              <button onClick={() => setTestModalOpen(false)} className="text-[#8B7355] hover:text-[#2C1E16]">
                <X size={18} />
              </button>
            </div>

            <div className="space-y-3 text-xs sm:text-sm text-[#5C4A3D]">
              <div className="rounded-xl bg-amber-50 p-3 border border-amber-200">
                <p>
                  Nominal upah yang dimasukkan: <span className="font-bold font-mono text-amber-950">{simAmount} EGP</span>.
                </p>
                <p className="mt-1 text-xs text-amber-800">
                  Batas konfirmasi nominal tidak wajar saat ini adalah <span className="font-bold">{policy.unusual_amount_threshold_le} EGP</span>.
                </p>
              </div>

              <p className="text-xs text-[#8B7355]">
                Apakah Anda yakin nominal ini sudah benar dan bukan kesalahan ketik (typo)?
              </p>

              <div>
                <Label className="block text-xs font-semibold text-[#2C1E16] mb-1">
                  Alasan Override Upah <span className="text-red-500">* (minimal 5 karakter)</span>
                </Label>
                <Textarea
                  rows={3}
                  value={testOverrideReason}
                  onChange={(e) => setTestOverrideReason(e.target.value)}
                  placeholder="Contoh: Pengantaran tangga manual ke lantai 5 tanpa lift untuk lemari 3 pintu jati"
                  className="bg-white text-xs"
                />
              </div>
            </div>

            <div className="flex items-center justify-end gap-2 border-t border-[#F1EBE0] pt-3">
              <Button
                variant="outline"
                size="sm"
                onClick={() => setTestModalOpen(false)}
                className="rounded-xl border-[#E5DCC5] text-[#5C4A3D]"
              >
                Batal
              </Button>
              <Button
                size="sm"
                onClick={() => {
                  if (!testOverrideReason || testOverrideReason.trim().length < 5) {
                    toast.error("Alasan override wajib diisi minimal 5 karakter.");
                    return;
                  }
                  toast.success("Konfirmasi valid! Nominal override diizinkan.");
                  setTestModalOpen(false);
                }}
                className="rounded-xl bg-amber-600 hover:bg-amber-700 text-white"
              >
                Konfirmasi & Lanjutkan
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
