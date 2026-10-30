import React, { useState, useEffect, useCallback } from "react";
import api from "../../lib/api";
import { fmtLE } from "../../lib/format";
import { Button } from "../ui/button";
import { Input } from "../ui/input";
import { Textarea } from "../ui/textarea";
import { Label } from "../ui/label";
import {
  ShieldCheck,
  AlertTriangle,
  CheckCircle2,
  RefreshCw,
  Pencil,
  X,
  Lock,
  Info,
  Users,
  AlertCircle,
  CreditCard,
} from "lucide-react";
import { toast } from "sonner";

export default function AdminWageOverrideCard({
  orderId,
  order,
  isOwner,
  workers = [],
  onUpdated,
}) {
  const [config, setConfig] = useState(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(null);

  // Modal / Form state
  const [modalOpen, setModalOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState(null);
  const [isConflict409, setIsConflict409] = useState(false);

  const [form, setForm] = useState({
    is_override: false,
    amount_le: "",
    recipient_id: "",
    override_reason: "",
  });

  const loadConfig = useCallback(async () => {
    if (!isOwner || !orderId) return;
    setLoading(true);
    setLoadError(null);
    try {
      const res = await api.get(`/admin/orders/${orderId}/admin-wage`);
      setConfig(res.data);
    } catch (err) {
      const msg =
        err.response?.data?.detail || "Gagal memuat konfigurasi upah admin";
      setLoadError(msg);
    } finally {
      setLoading(false);
    }
  }, [orderId, isOwner]);

  useEffect(() => {
    loadConfig();
  }, [loadConfig]);

  // Open modal and pre-fill form
  const handleOpenModal = () => {
    if (!config) return;
    setFormError(null);
    setIsConflict409(false);

    const saved = config.saved_override;
    const isOver = Boolean(config.is_override);

    setForm({
      is_override: isOver,
      amount_le:
        saved?.amount_le !== null && saved?.amount_le !== undefined
          ? String(saved.amount_le)
          : config.policy_context?.default_wage_per_order_le !== null &&
            config.policy_context?.default_wage_per_order_le !== undefined
          ? String(config.policy_context.default_wage_per_order_le)
          : "",
      recipient_id: saved?.recipient_id || "",
      override_reason: saved?.override_reason || "",
    });
    setModalOpen(true);
  };

  const handleCloseModal = () => {
    if (submitting) return;
    setModalOpen(false);
    setFormError(null);
    setIsConflict409(false);
  };

  const handleSubmit = async (e) => {
    if (e) e.preventDefault();
    if (submitting) return;

    setFormError(null);
    setIsConflict409(false);

    const isOver = Boolean(form.is_override);
    let amountVal = null;

    if (isOver) {
      if (form.amount_le !== "" && form.amount_le !== null) {
        const parsed = parseFloat(form.amount_le);
        if (isNaN(parsed) || parsed <= 0) {
          setFormError("Nominal upah override harus berupa angka lebih besar dari 0");
          return;
        }
        amountVal = parsed;
      }

      // If both amount and recipient are empty
      if (amountVal === null && !form.recipient_id) {
        setFormError(
          "Override upah aktif memerlukan nominal (amount_le) atau penerima (recipient_id)"
        );
        return;
      }

      // Check reason if above threshold
      const thresh = config?.policy_context?.unusual_amount_threshold_le;
      if (
        amountVal !== null &&
        thresh !== null &&
        thresh !== undefined &&
        amountVal > thresh
      ) {
        if (!form.override_reason || form.override_reason.trim().length < 3) {
          setFormError(
            `Nominal (${amountVal} LE) melebihi ambang tidak wajar (${thresh} LE). Alasan override wajib diisi minimal 3 karakter.`
          );
          return;
        }
      }
    }

    const payload = {
      is_override: isOver,
      amount_le: isOver ? amountVal : null,
      recipient_id: isOver ? form.recipient_id || null : null,
      override_reason: form.override_reason?.trim() || null,
    };

    setSubmitting(true);
    try {
      const res = await api.put(`/admin/orders/${orderId}/admin-wage`, payload);
      toast.success(res.data?.message || "Konfigurasi upah admin berhasil disimpan");
      setModalOpen(false);
      await loadConfig();
      if (onUpdated) onUpdated();
    } catch (err) {
      const status = err.response?.status;
      const detail = err.response?.data?.detail || "Gagal menyimpan override upah admin";
      setFormError(detail);

      if (status === 409) {
        setIsConflict409(true);
        toast.error("Konflik: " + detail);
      } else {
        toast.error(detail);
      }
    } finally {
      setSubmitting(false);
    }
  };

  // Only render for Owner
  if (!isOwner) {
    return null;
  }

  const effConfig = config?.effective_configuration;
  const policy = config?.policy_context;
  const wob = config?.obligation_state;
  const blocked = config?.blocked_state;
  const isEditable = config?.is_editable;
  const restrictionReason = config?.editing_restriction_reason;

  return (
    <div
      className="rounded-2xl border border-[#E5DCC5] bg-white p-5 shadow-sm lg:col-span-2"
      data-testid="admin-wage-override-card"
    >
      {/* Card Header */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[#F1EBE0] pb-3 mb-4">
        <div className="flex items-center gap-2">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-amber-50 text-[#8B5A2B] border border-amber-200">
            <ShieldCheck size={20} />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h3 className="font-heading text-base font-bold text-[#8B5A2B]">
                Upah Admin Per Pesanan
              </h3>
              <span className="inline-flex items-center gap-1 rounded-full bg-purple-50 px-2 py-0.5 text-[10px] font-semibold text-purple-700 border border-purple-200">
                <Lock size={10} /> Owner Only
              </span>
            </div>
            <p className="text-xs text-[#8B7355]">
              Pengaturan tarif dan penerima upah admin khusus untuk pesanan ini
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={loadConfig}
            disabled={loading}
            className="h-8 px-2 text-[#8B7355] hover:text-[#8B5A2B]"
            title="Muat Ulang Konfigurasi"
            data-testid="btn-reload-admin-wage"
          >
            <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
          </Button>

          {isEditable && (
            <Button
              type="button"
              onClick={handleOpenModal}
              disabled={loading}
              className="h-8 rounded-xl bg-[#8B5A2B] hover:bg-[#6B4423] text-white text-xs font-semibold px-3"
              data-testid="btn-open-admin-wage-modal"
            >
              <Pencil size={13} className="mr-1.5" />
              {config?.is_override ? "Ubah Override" : "Atur Override"}
            </Button>
          )}
        </div>
      </div>

      {/* Loading & Error States */}
      {loading && !config && (
        <div className="py-6 text-center text-xs text-[#8B7355]" data-testid="admin-wage-loading">
          <RefreshCw size={18} className="mx-auto mb-2 animate-spin text-[#8B5A2B]" />
          Memuat konfigurasi upah admin...
        </div>
      )}

      {loadError && (
        <div
          className="rounded-xl border border-red-200 bg-red-50 p-3 text-xs text-red-800 flex items-start gap-2 mb-3"
          data-testid="admin-wage-load-error"
        >
          <AlertCircle size={16} className="mt-0.5 shrink-0 text-red-600" />
          <div>
            <span className="font-semibold">Gagal memuat konfigurasi:</span> {loadError}
          </div>
        </div>
      )}

      {/* Main Content */}
      {config && (
        <div className="space-y-4">
          {/* Active Configuration Summary Grid */}
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4 rounded-xl border border-[#E5DCC5] bg-[#FBF9F4] p-4 text-xs">
            {/* Status Sumber */}
            <div>
              <span className="text-[#8B7355] block mb-1">Status Sumber Tarif:</span>
              {config.is_override ? (
                <span
                  className="inline-flex items-center gap-1 rounded-full bg-purple-100 text-purple-800 px-2.5 py-0.5 font-semibold text-[11px] border border-purple-200"
                  data-testid="badge-override-status"
                >
                  <CheckCircle2 size={12} />
                  Tarif Khusus (Override)
                </span>
              ) : (
                <span
                  className="inline-flex items-center gap-1 rounded-full bg-stone-100 text-stone-700 px-2.5 py-0.5 font-semibold text-[11px] border border-stone-300"
                  data-testid="badge-override-status"
                >
                  Kebijakan Default Global
                </span>
              )}
            </div>

            {/* Nominal Upah Efektif */}
            <div>
              <span className="text-[#8B7355] block mb-1">Nominal Upah Efektif:</span>
              <span className="font-bold text-sm text-[#2C1E16]" data-testid="effective-admin-wage-amount">
                {effConfig?.amount_le !== null && effConfig?.amount_le !== undefined
                  ? `${fmtLE(effConfig.amount_le)} LE`
                  : "-"}
              </span>
              {config.is_override && policy?.default_wage_per_order_le !== null && (
                <span className="text-[10px] text-[#8B7355] block mt-0.5">
                  (Default Kebijakan: {fmtLE(policy.default_wage_per_order_le)} LE)
                </span>
              )}
            </div>

            {/* Penerima Upah */}
            <div>
              <span className="text-[#8B7355] block mb-1">Penerima Upah:</span>
              <span className="font-semibold text-stone-900 block" data-testid="effective-admin-wage-recipient">
                {effConfig?.recipient_name || "Belum Ditentukan"}
              </span>
              <span className="text-[10px] text-[#8B7355]">
                {effConfig?.source === "override" && config.saved_override?.recipient_id
                  ? "(Penerima Khusus Pesanan)"
                  : "(Penerima Default Kebijakan)"}
              </span>
            </div>

            {/* Kebijakan Batas (Cap & Threshold) */}
            <div>
              <span className="text-[#8B7355] block mb-1">Batas Kebijakan Aktif:</span>
              <div className="text-[11px] text-stone-700 space-y-0.5">
                <div>
                  Hard Cap:{" "}
                  <span className="font-medium text-[#8B5A2B]">
                    {policy?.max_wage_per_order_le ? `${fmtLE(policy.max_wage_per_order_le)} LE` : "-"}
                  </span>
                </div>
                <div>
                  Ambang Konfirmasi:{" "}
                  <span className="font-medium">
                    {policy?.unusual_amount_threshold_le
                      ? `${fmtLE(policy.unusual_amount_threshold_le)} LE`
                      : "-"}
                  </span>
                </div>
              </div>
            </div>
          </div>

          {/* Alasan Override jika ada */}
          {config.is_override && effConfig?.override_reason && (
            <div
              className="rounded-xl border border-purple-200 bg-purple-50/50 p-3 text-xs text-purple-950 flex items-start gap-2"
              data-testid="admin-wage-override-reason-box"
            >
              <Info size={15} className="mt-0.5 shrink-0 text-purple-700" />
              <div>
                <span className="font-semibold text-purple-900">Alasan Override:</span>{" "}
                {effConfig.override_reason}
              </div>
            </div>
          )}

          {/* Conflict / Blocked Alert */}
          {blocked && (
            <div
              className="rounded-xl border border-amber-300 bg-amber-50 p-3.5 text-xs text-amber-950 space-y-1.5"
              data-testid="admin-wage-blocked-alert"
            >
              <div className="flex items-center gap-2 font-bold text-amber-900">
                <AlertTriangle size={16} className="text-amber-700" />
                Akrual Upah Terblokir (Blocked Conflict)
              </div>
              <p className="text-amber-900 leading-relaxed">
                {blocked.reason ||
                  "Nominal upah override melebihi batas maksimum hard cap saat pesanan lunas."}
              </p>
              <div className="text-[11px] text-amber-800">
                Batas maksimum aktif saat ini adalah{" "}
                <span className="font-semibold">{fmtLE(policy?.max_wage_per_order_le)} LE</span>.
                Anda dapat memperbarui override dengan nominal yang valid untuk menyelesaikan kendala
                ini.
              </div>
            </div>
          )}

          {/* Financial Obligation Status Details */}
          {wob ? (
            <div
              className="rounded-xl border border-stone-200 bg-stone-50 p-3.5 text-xs space-y-2"
              data-testid="admin-wage-obligation-box"
            >
              <div className="flex flex-wrap items-center justify-between gap-2 border-b border-stone-200 pb-2">
                <span className="font-bold text-stone-900 flex items-center gap-1.5">
                  <CreditCard size={15} className="text-[#8B5A2B]" />
                  Status Kewajiban Upah (Tercatat di Sistem)
                </span>
                <span
                  className={`inline-block px-2 py-0.5 rounded text-[11px] font-semibold uppercase ${
                    wob.status === "paid"
                      ? "bg-emerald-100 text-emerald-800"
                      : wob.status === "partially_paid"
                      ? "bg-blue-100 text-blue-800"
                      : wob.status === "voided"
                      ? "bg-red-100 text-red-700"
                      : "bg-purple-100 text-purple-800"
                  }`}
                  data-testid="badge-obligation-status"
                >
                  {wob.status}
                </span>
              </div>

              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-stone-700 text-[11px]">
                <div>
                  <span className="text-[#8B7355] block">Nomor Kewajiban:</span>
                  <span className="font-mono font-medium text-[#8B5A2B]">
                    {wob.obligation_number}
                  </span>
                </div>
                <div>
                  <span className="text-[#8B7355] block">Nominal Tercatat:</span>
                  <span className="font-bold text-stone-900">{fmtLE(wob.amount_le)} LE</span>
                </div>
                <div>
                  <span className="text-[#8B7355] block">Penerima Tercatat:</span>
                  <span className="font-medium text-stone-900">{wob.worker_name}</span>
                </div>
                <div>
                  <span className="text-[#8B7355] block">Waktu Akrual:</span>
                  <span>
                    {wob.accrued_at
                      ? new Date(wob.accrued_at).toLocaleString("id-ID")
                      : "-"}
                  </span>
                </div>
              </div>

              {/* Lifecycle Warning Notes */}
              {wob.status === "accrued" && (
                <div className="rounded-lg bg-amber-50/80 border border-amber-200 p-2.5 text-[11px] text-amber-900 flex items-start gap-2">
                  <Info size={14} className="mt-0.5 shrink-0 text-amber-700" />
                  <div>
                    <span className="font-semibold">Catatan Integritas Akrual:</span> Kewajiban
                    upah telah terbit ({wob.obligation_number}). Perubahan konfigurasi override di
                    bawah ini hanya memperbarui konfigurasi pesanan dan{" "}
                    <span className="font-semibold">
                      tidak otomatis mengubah nominal kewajiban yang sudah tercatat
                    </span>
                    .
                  </div>
                </div>
              )}
            </div>
          ) : (
            <div className="text-[11px] text-[#8B7355] bg-stone-50 border border-stone-200 rounded-xl p-3 flex items-center gap-2">
              <Info size={14} className="text-[#8B5A2B] shrink-0" />
              <span>
                {order?.payment_status === "lunas"
                  ? "Pesanan berstatus lunas namun kewajiban upah belum terbit (dapat disebabkan oleh kebijakan nonaktif atau rekonsiliasi historis)."
                  : "Kewajiban upah admin akan otomatis diterbitkan oleh sistem saat pembayaran pesanan mencapai status LUNAS."}
              </span>
            </div>
          )}

          {/* Edit Restriction Reason */}
          {!isEditable && restrictionReason && (
            <div
              className="rounded-xl border border-stone-300 bg-stone-100 p-3 text-xs text-stone-800 flex items-start gap-2"
              data-testid="admin-wage-restriction-alert"
            >
              <Lock size={15} className="mt-0.5 shrink-0 text-stone-600" />
              <div>
                <span className="font-semibold">Perubahan Konfigurasi Terkunci:</span>{" "}
                {restrictionReason}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Edit Override Modal */}
      {modalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div
            className="w-full max-w-lg rounded-2xl border border-[#E5DCC5] bg-white p-5 shadow-xl max-h-[90vh] overflow-y-auto"
            data-testid="modal-admin-wage-override"
          >
            {/* Modal Header */}
            <div className="flex items-center justify-between border-b border-[#F1EBE0] pb-3">
              <div>
                <h3 className="font-heading text-lg font-bold text-[#2C1E16]">
                  Konfigurasi Upah Admin
                </h3>
                <p className="text-xs text-[#8B7355]">
                  Atur atau nonaktifkan override upah admin khusus untuk pesanan #{order?.order_number}
                </p>
              </div>
              <button
                type="button"
                onClick={handleCloseModal}
                disabled={submitting}
                className="rounded-lg p-1 text-[#8B7355] hover:bg-[#F1EBE0]"
              >
                <X size={18} />
              </button>
            </div>

            <form onSubmit={handleSubmit} className="mt-4 space-y-4">
              {/* Form Error Alert */}
              {formError && (
                <div
                  className="rounded-xl border border-red-200 bg-red-50 p-3 text-xs text-red-900 space-y-2"
                  data-testid="form-error-alert"
                >
                  <div className="flex items-start gap-2">
                    <AlertCircle size={16} className="mt-0.5 shrink-0 text-red-600" />
                    <div className="flex-1">{formError}</div>
                  </div>
                  {isConflict409 && (
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      onClick={async () => {
                        await loadConfig();
                        handleCloseModal();
                      }}
                      className="w-full border-red-300 text-red-800 hover:bg-red-100 text-xs mt-1"
                      data-testid="btn-conflict-reload"
                    >
                      <RefreshCw size={13} className="mr-1.5" /> Muat Ulang Data Pesanan
                    </Button>
                  )}
                </div>
              )}

              {/* Mode Selection: Policy Default vs Override */}
              <div className="space-y-2">
                <Label className="text-xs font-semibold text-[#5C4A3D]">Mode Upah Admin</Label>
                <div className="grid grid-cols-2 gap-2">
                  <button
                    type="button"
                    onClick={() => setForm({ ...form, is_override: false })}
                    disabled={submitting}
                    className={`rounded-xl border p-3 text-left transition-all text-xs ${
                      !form.is_override
                        ? "border-[#8B5A2B] bg-[#FAF5EE] font-semibold text-[#8B5A2B] shadow-sm"
                        : "border-[#E5DCC5] bg-white text-stone-600 hover:bg-stone-50"
                    }`}
                    data-testid="radio-mode-default"
                  >
                    <div className="font-bold mb-1">Gunakan Kebijakan Default</div>
                    <div className="text-[11px] text-[#8B7355]">
                      Tarif default ({fmtLE(policy?.default_wage_per_order_le)} LE) & penerima default
                    </div>
                  </button>

                  <button
                    type="button"
                    onClick={() => setForm({ ...form, is_override: true })}
                    disabled={submitting}
                    className={`rounded-xl border p-3 text-left transition-all text-xs ${
                      form.is_override
                        ? "border-purple-600 bg-purple-50 font-semibold text-purple-900 shadow-sm"
                        : "border-[#E5DCC5] bg-white text-stone-600 hover:bg-stone-50"
                    }`}
                    data-testid="radio-mode-override"
                  >
                    <div className="font-bold mb-1 text-purple-900">Tarif / Penerima Khusus</div>
                    <div className="text-[11px] text-purple-700">
                      Tetapkan nominal khusus atau penerima spesifik untuk pesanan ini
                    </div>
                  </button>
                </div>
              </div>

              {/* Override Fields (Only visible when is_override is true) */}
              {form.is_override ? (
                <div className="space-y-3 rounded-xl border border-purple-200 bg-purple-50/30 p-3.5">
                  {/* Amount Input */}
                  <div>
                    <div className="flex items-center justify-between mb-1">
                      <Label className="text-xs font-semibold text-[#5C4A3D]">
                        Nominal Upah Khusus (LE)
                      </Label>
                      <span className="text-[10px] text-[#8B7355]">
                        Maksimum: {fmtLE(policy?.max_wage_per_order_le)} LE
                      </span>
                    </div>
                    <Input
                      type="number"
                      step="0.01"
                      min="0.01"
                      placeholder={`Contoh: ${policy?.default_wage_per_order_le || 150}`}
                      value={form.amount_le}
                      onChange={(e) => setForm({ ...form, amount_le: e.target.value })}
                      disabled={submitting}
                      className="bg-white"
                      data-testid="input-override-amount"
                    />
                    <p className="mt-1 text-[11px] text-[#8B7355]">
                      Kosongkan jika hanya ingin mengalihkan penerima (akan menggunakan tarif default{" "}
                      {fmtLE(policy?.default_wage_per_order_le)} LE).
                    </p>
                  </div>

                  {/* Recipient Selector */}
                  <div>
                    <Label className="text-xs font-semibold text-[#5C4A3D] block mb-1">
                      Penerima Upah Khusus
                    </Label>
                    <select
                      value={form.recipient_id}
                      onChange={(e) => setForm({ ...form, recipient_id: e.target.value })}
                      disabled={submitting}
                      className="w-full rounded-md border border-input bg-white px-3 py-2 text-xs ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
                      data-testid="select-override-recipient"
                    >
                      <option value="">
                        -- Gunakan Penerima Default ({policy?.default_recipient_name || "Kebijakan"}
                        ) --
                      </option>
                      {workers.map((w) => (
                        <option key={w.id || w._id} value={w.id || w._id}>
                          {w.name} ({w.role || "Admin"})
                        </option>
                      ))}
                    </select>
                    <p className="mt-1 text-[11px] text-[#8B7355]">
                      Pilih staf admin penerima khusus, atau biarkan default kebijakan.
                    </p>
                  </div>

                  {/* Override Reason */}
                  <div>
                    <div className="flex items-center justify-between mb-1">
                      <Label className="text-xs font-semibold text-[#5C4A3D]">
                        Alasan Override{" "}
                        {parseFloat(form.amount_le || 0) >
                          (policy?.unusual_amount_threshold_le || 0) && (
                          <span className="text-red-500 font-bold">*</span>
                        )}
                      </Label>
                      <span className="text-[10px] text-[#8B7355]">
                        {form.override_reason?.length || 0}/500 karakter
                      </span>
                    </div>
                    <Textarea
                      rows={2}
                      maxLength={500}
                      placeholder="Jelaskan alasan penetapan upah khusus untuk pesanan ini..."
                      value={form.override_reason}
                      onChange={(e) => setForm({ ...form, override_reason: e.target.value })}
                      disabled={submitting}
                      className="bg-white text-xs"
                      data-testid="textarea-override-reason"
                    />
                    {parseFloat(form.amount_le || 0) >
                      (policy?.unusual_amount_threshold_le || 0) && (
                      <p className="mt-1 text-[11px] text-amber-700 font-medium">
                        Wajib diisi minimal 3 karakter karena nominal melebihi ambang batas konfirmasi
                        ({fmtLE(policy?.unusual_amount_threshold_le)} LE).
                      </p>
                    )}
                  </div>
                </div>
              ) : (
                <div className="rounded-xl border border-stone-200 bg-stone-50 p-3.5 text-xs text-stone-700 space-y-2">
                  <div className="flex items-center gap-1.5 font-semibold text-stone-900">
                    <CheckCircle2 size={15} className="text-emerald-600" />
                    Kebijakan Default Aktif
                  </div>
                  <div className="grid grid-cols-2 gap-2 text-[11px]">
                    <div>
                      Tarif Default:{" "}
                      <span className="font-bold text-[#8B5A2B]">
                        {fmtLE(policy?.default_wage_per_order_le)} LE
                      </span>
                    </div>
                    <div>
                      Penerima Default:{" "}
                      <span className="font-semibold text-stone-900">
                        {policy?.default_recipient_name || "-"}
                      </span>
                    </div>
                  </div>
                  <div>
                    <Label className="text-xs font-semibold text-[#5C4A3D] block mb-1">
                      Catatan Pembatalan Override (Opsional)
                    </Label>
                    <Input
                      placeholder="Contoh: Mengembalikan ke tarif standar"
                      value={form.override_reason}
                      onChange={(e) => setForm({ ...form, override_reason: e.target.value })}
                      disabled={submitting}
                      className="bg-white text-xs"
                      data-testid="input-clear-reason"
                    />
                  </div>
                </div>
              )}

              {/* Important Disclaimers */}
              <div className="rounded-xl border border-amber-200 bg-amber-50/70 p-3 text-[11px] text-amber-950 space-y-1">
                <div className="font-semibold flex items-center gap-1 text-amber-900">
                  <Info size={13} className="text-amber-700" />
                  Prinsip Integritas Keuangan:
                </div>
                <p>
                  Perubahan konfigurasi berlaku untuk proses akrual berikutnya. Kewajiban upah yang
                  sudah tercatat di sistem tidak berubah secara otomatis.
                </p>
              </div>

              {/* Action Buttons */}
              <div className="flex items-center justify-end gap-2 pt-2 border-t border-[#F1EBE0]">
                <Button
                  type="button"
                  variant="outline"
                  onClick={handleCloseModal}
                  disabled={submitting}
                  className="rounded-xl border-[#E5DCC5] text-xs font-semibold"
                  data-testid="btn-cancel-admin-wage"
                >
                  Batal
                </Button>
                <Button
                  type="submit"
                  disabled={submitting}
                  className="rounded-xl bg-[#8B5A2B] hover:bg-[#6B4423] text-white text-xs font-semibold px-4"
                  data-testid="btn-submit-admin-wage"
                >
                  {submitting ? (
                    <>
                      <RefreshCw size={14} className="mr-1.5 animate-spin" /> Menyimpan...
                    </>
                  ) : form.is_override ? (
                    "Simpan Override"
                  ) : (
                    "Terapkan Default"
                  )}
                </Button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
