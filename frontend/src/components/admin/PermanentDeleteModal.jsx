import React, { useState, useEffect } from "react";
import { AlertTriangle, Trash2, X } from "lucide-react";
import { Button } from "../ui/button";
import { Input } from "../ui/input";
import { Label } from "../ui/label";

export default function PermanentDeleteModal({
  open,
  onClose,
  onConfirm,
  title = "Hapus Permanen",
  entityType = "Record",
  entityIdentifier = "",
  warningMessages = [],
  loading = false,
}) {
  const [confirmPhrase, setConfirmPhrase] = useState("");
  const [reason, setReason] = useState("");

  useEffect(() => {
    if (open) {
      setConfirmPhrase("");
      setReason("");
    }
  }, [open]);

  if (!open) return null;

  const isPhraseValid = confirmPhrase.trim() === "HAPUS PERMANEN";

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!isPhraseValid || loading) return;
    onConfirm(reason.trim() || undefined);
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-xs"
      data-testid="permanent-delete-modal-overlay"
    >
      <div
        className="w-full max-w-lg rounded-2xl border border-red-200 bg-white p-6 shadow-2xl animate-in fade-in zoom-in-95 duration-150"
        data-testid="permanent-delete-modal"
      >
        {/* Header */}
        <div className="flex items-start justify-between gap-3 border-b border-red-100 pb-4">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-red-100 text-red-600">
              <AlertTriangle size={22} />
            </div>
            <div>
              <h3 className="font-heading text-lg font-bold text-red-950">
                {title}
              </h3>
              <p className="text-xs text-red-700">
                Tindakan destruktif ini tidak dapat dibatalkan melalui sistem
              </p>
            </div>
          </div>
          <button
            type="button"
            disabled={loading}
            onClick={onClose}
            className="rounded-lg p-1 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-600 disabled:opacity-50"
          >
            <X size={18} />
          </button>
        </div>

        {/* Content */}
        <form onSubmit={handleSubmit} className="mt-4 space-y-4">
          <div className="rounded-xl border border-red-100 bg-red-50/60 p-4 text-xs text-red-900 space-y-2">
            <div>
              Anda akan menghapus <strong className="font-semibold">{entityType}</strong>:
              <div className="mt-1 font-mono text-base font-bold text-red-700">
                {entityIdentifier}
              </div>
            </div>

            <p className="font-medium text-red-800">
              ⚠️ Record ini akan dihapus secara <strong>permanen</strong> dari database.
              Entity terkait lainnya (Finance, Order/Invoice, Customer) <strong>TIDAK</strong> akan ikut dihapus.
            </p>

            {warningMessages.length > 0 && (
              <ul className="list-disc pl-4 space-y-1 text-red-700 pt-1 border-t border-red-200/60">
                {warningMessages.map((msg, idx) => (
                  <li key={idx}>{msg}</li>
                ))}
              </ul>
            )}
          </div>

          <div>
            <Label className="text-xs font-semibold text-zinc-700">
              Alasan Penghapusan (Opsional)
            </Label>
            <Input
              type="text"
              placeholder="Contoh: Pembersihan data test operasional"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              disabled={loading}
              className="mt-1 h-10 text-xs bg-zinc-50/60 border-zinc-200"
              data-testid="permanent-delete-reason-input"
            />
          </div>

          <div>
            <Label className="text-xs font-semibold text-red-900 block">
              Untuk melanjutkan, ketik persis: <span className="font-mono font-bold text-red-600 select-all">HAPUS PERMANEN</span>
            </Label>
            <Input
              type="text"
              autoFocus
              placeholder="HAPUS PERMANEN"
              value={confirmPhrase}
              onChange={(e) => setConfirmPhrase(e.target.value)}
              disabled={loading}
              className="mt-1 h-11 font-mono font-semibold tracking-wide border-red-300 focus-visible:ring-red-400"
              data-testid="permanent-delete-confirm-input"
            />
          </div>

          {/* Action buttons */}
          <div className="flex items-center justify-end gap-2.5 pt-3 border-t border-zinc-100">
            <Button
              type="button"
              variant="outline"
              onClick={onClose}
              disabled={loading}
              className="h-10 rounded-xl border-zinc-200 text-xs font-semibold text-zinc-700 hover:bg-zinc-50"
              data-testid="permanent-delete-cancel-btn"
            >
              Batal
            </Button>
            <Button
              type="submit"
              disabled={!isPhraseValid || loading}
              className="h-10 rounded-xl bg-red-600 hover:bg-red-700 text-xs font-bold text-white shadow-xs disabled:opacity-40 disabled:cursor-not-allowed"
              data-testid="permanent-delete-submit-btn"
            >
              <Trash2 size={14} className="mr-1.5" />
              {loading ? "Menghapus..." : "Hapus Permanen"}
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}
