import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import api from "../../lib/api";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Textarea } from "../../components/ui/textarea";
import { Label } from "../../components/ui/label";
import { Badge } from "../../components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../../components/ui/select";
import { fmtLE } from "../../lib/format";
import { useAuth } from "../../context/AuthContext";
import { Search, MessageCircle, ExternalLink, ShoppingBag, Eye, Trash2, X, ChevronRight, CheckCircle, Sparkles } from "lucide-react";
import { toast } from "sonner";

const STATUS_BADGES = {
  baru: { label: "Baru", bg: "bg-blue-100 text-blue-800 border-blue-200" },
  diskusi: { label: "Diskusi", bg: "bg-amber-100 text-amber-800 border-amber-200" },
  disetujui: { label: "Disetujui", bg: "bg-emerald-100 text-emerald-800 border-emerald-200" },
  dipesan: { label: "Dipesan", bg: "bg-purple-100 text-purple-800 border-purple-200" },
  ditolak: { label: "Ditolak", bg: "bg-zinc-100 text-zinc-800 border-zinc-200" },
};

export default function AdminCustomRequests() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const canDelete = user?.role === "owner" || user?.permissions?.delete_data;

  const [requests, setRequests] = useState([]);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState("all");
  const [searchQuery, setSearchQuery] = useState("");

  const [selectedReq, setSelectedReq] = useState(null);
  const [detailModalOpen, setDetailModalOpen] = useState(false);
  const [convertModalOpen, setConvertModalOpen] = useState(false);

  const [editStatus, setEditStatus] = useState("baru");
  const [adminNotes, setAdminNotes] = useState("");
  const [estimatedPrice, setEstimatedPrice] = useState("");

  const [convertForm, setConvertForm] = useState({
    subtotal_le: "",
    delivery_fee_le: "0",
    delivery_method: "delivery",
    payment_method: "transfer",
    notes: "",
  });
  const [converting, setConverting] = useState(false);

  const loadRequests = async () => {
    try {
      const { data } = await api.get("/admin/custom-requests", {
        params: {
          status: statusFilter,
          q: searchQuery || undefined,
        },
      });
      setRequests(data || []);
    } catch (err) {
      toast.error("Gagal memuat daftar request custom");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadRequests();
  }, [statusFilter]);

  const handleSearch = (e) => {
    e.preventDefault();
    loadRequests();
  };

  const openDetail = (req) => {
    setSelectedReq(req);
    setEditStatus(req.status || "baru");
    setAdminNotes(req.admin_notes || "");
    setEstimatedPrice(req.estimated_price_le ? String(req.estimated_price_le) : "");
    setDetailModalOpen(true);
  };

  const handleUpdateStatus = async () => {
    if (!selectedReq) return;
    try {
      const { data } = await api.patch(`/admin/custom-requests/${selectedReq.id || selectedReq._id}`, {
        status: editStatus,
        admin_notes: adminNotes,
        estimated_price_le: estimatedPrice ? Number(estimatedPrice) : null,
      });
      toast.success("Status request berhasil diperbarui");
      setRequests((prev) => prev.map((r) => ((r.id || r._id) === (data.id || data._id) ? data : r)));
      setSelectedReq(data);
      setDetailModalOpen(false);
    } catch (err) {
      toast.error("Gagal memperbarui status");
    }
  };

  const openConvertModal = (req) => {
    setSelectedReq(req);
    setConvertForm({
      subtotal_le: req.estimated_price_le || req.budget_estimation_le || "",
      delivery_fee_le: "0",
      delivery_method: "delivery",
      payment_method: "transfer",
      notes: `Pesanan custom dari ${req.ticket_number}`,
    });
    setConvertModalOpen(true);
  };

  const handleConvert = async (e) => {
    e.preventDefault();
    if (!selectedReq) return;
    if (!convertForm.subtotal_le || Number(convertForm.subtotal_le) <= 0) {
      toast.error("Subtotal pesanan (LE) wajib diisi dengan nominal yang benar");
      return;
    }

    setConverting(true);
    try {
      const reqId = selectedReq.id || selectedReq._id;
      const { data: newOrder } = await api.post(`/admin/custom-requests/${reqId}/convert-to-order`, {
        subtotal_le: Number(convertForm.subtotal_le),
        delivery_fee_le: Number(convertForm.delivery_fee_le) || 0,
        delivery_method: convertForm.delivery_method,
        payment_method: convertForm.payment_method,
        notes: convertForm.notes,
      });

      toast.success(`Berhasil dikonversi menjadi pesanan ${newOrder.order_number}!`);
      setConvertModalOpen(false);
      setDetailModalOpen(false);
      loadRequests();
      navigate(`/admin/orders/${newOrder.id || newOrder._id}`);
    } catch (err) {
      toast.error(err.response?.data?.detail || "Gagal mengonversi request ke pesanan");
    } finally {
      setConverting(false);
    }
  };

  const handleDelete = async (req) => {
    if (!window.confirm(`Yakin ingin menghapus request tiket ${req.ticket_number}? Tindakan ini tidak dapat dibatalkan.`)) {
      return;
    }
    try {
      const reqId = req.id || req._id;
      await api.delete(`/admin/custom-requests/${reqId}`);
      toast.success("Request custom berhasil dihapus");
      setRequests((prev) => prev.filter((r) => (r.id || r._id) !== reqId));
    } catch (err) {
      toast.error(err.response?.data?.detail || "Gagal menghapus request");
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="font-heading text-2xl font-bold text-[#2C1E16] sm:text-3xl">
            Request Custom Furniture
          </h1>
          <p className="mt-1 text-xs text-[#8B7355] sm:text-sm">
            Daftar pengajuan desain khusus, ukuran custom, dan foto referensi dari customer
          </p>
        </div>
      </div>

      {/* Filter & Search Bar */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        {/* Status Filter Chips */}
        <div className="flex gap-1.5 overflow-x-auto pb-1 text-xs">
          {[
            { id: "all", label: "Semua" },
            { id: "baru", label: "Baru" },
            { id: "diskusi", label: "Diskusi" },
            { id: "disetujui", label: "Disetujui" },
            { id: "dipesan", label: "Dipesan" },
            { id: "ditolak", label: "Ditolak" },
          ].map((tab) => (
            <button
              key={tab.id}
              onClick={() => setStatusFilter(tab.id)}
              className={`shrink-0 rounded-xl px-3 py-1.5 font-medium transition-colors ${
                statusFilter === tab.id
                  ? "bg-[#8B5A2B] text-white"
                  : "border border-[#E5DCC5] bg-white text-[#5C4A3D] hover:bg-[#FBF9F4]"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* Search */}
        <form onSubmit={handleSearch} className="relative w-full sm:w-64">
          <Input
            type="text"
            placeholder="Cari tiket, nama, HP..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="h-9 pr-8 text-xs bg-white"
          />
          <button type="submit" className="absolute right-2 top-2 text-[#8B7355]">
            <Search size={16} />
          </button>
        </form>
      </div>

      {/* Content */}
      {loading ? (
        <div className="py-16 text-center text-sm text-[#8B7355]">Memuat request custom...</div>
      ) : requests.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-[#E5DCC5] bg-white p-12 text-center">
          <p className="text-sm font-medium text-[#5C4A3D]">Belum ada request custom yang ditemukan</p>
          <p className="mt-1 text-xs text-[#8B7355]">Customer dapat mengajukan pesanan custom melalui website</p>
        </div>
      ) : (
        <>
          {/* Mobile Card List (md:hidden) */}
          <div className="space-y-3 md:hidden">
            {requests.map((req) => {
              const reqId = req.id || req._id;
              const cleanPhone = (req.customer_phone || "").replace(/[^0-9]/g, "");
              const badge = STATUS_BADGES[req.status] || STATUS_BADGES.baru;
              const dims = req.dimensions || {};
              const dimsStr = [
                dims.length && `P: ${dims.length}cm`,
                dims.width && `L: ${dims.width}cm`,
                dims.height && `T: ${dims.height}cm`,
              ].filter(Boolean).join(" · ");

              return (
                <div
                  key={reqId}
                  className="rounded-2xl border border-[#E5DCC5] bg-white p-4 shadow-sm"
                >
                  <div className="flex items-start justify-between gap-2 border-b border-[#F1EBE0] pb-2.5">
                    <div>
                      <span className="font-mono text-xs font-bold text-[#8B5A2B]">
                        {req.ticket_number}
                      </span>
                      <p className="text-[11px] text-[#8B7355]">
                        {new Date(req.created_at).toLocaleDateString("id-ID", {
                          day: "numeric",
                          month: "short",
                          year: "numeric",
                        })}
                      </p>
                    </div>
                    <span className={`rounded-full border px-2.5 py-0.5 text-[10px] font-semibold ${badge.bg}`}>
                      {badge.label}
                    </span>
                  </div>

                  <div className="mt-3 flex gap-3">
                    {/* Thumbnail */}
                    {req.reference_photos?.length > 0 ? (
                      <div className="relative h-16 w-16 shrink-0 overflow-hidden rounded-xl border border-[#E5DCC5] bg-[#FBF9F4]">
                        <img
                          src={req.reference_photos[0]}
                          alt=""
                          className="h-full w-full object-cover"
                        />
                        {req.reference_photos.length > 1 && (
                          <span className="absolute bottom-0.5 right-0.5 rounded bg-black/60 px-1 text-[9px] font-bold text-white">
                            +{req.reference_photos.length - 1}
                          </span>
                        )}
                      </div>
                    ) : (
                      <div className="flex h-16 w-16 shrink-0 items-center justify-center rounded-xl border border-[#E5DCC5] bg-[#FBF9F4] text-[#8B7355]">
                        <Sparkles size={20} />
                      </div>
                    )}

                    <div className="min-w-0 flex-1">
                      <p className="font-heading text-sm font-bold text-[#2C1E16] truncate">
                        {req.furniture_type}
                      </p>
                      {dimsStr && (
                        <p className="text-xs text-[#8B7355] truncate">{dimsStr}</p>
                      )}
                      <p className="mt-1 text-xs font-medium text-[#5C4A3D]">
                        {req.customer_name}
                      </p>
                    </div>
                  </div>

                  {/* Actions Mobile */}
                  <div className="mt-3.5 flex items-center justify-between border-t border-[#F1EBE0] pt-2.5">
                    <div className="flex gap-2">
                      <a
                        href={`https://wa.me/${cleanPhone}`}
                        target="_blank"
                        rel="noreferrer"
                        className="inline-flex items-center gap-1 rounded-lg border border-[#25D366] px-2.5 py-1 text-xs font-semibold text-[#25D366] hover:bg-emerald-50"
                      >
                        <MessageCircle size={14} /> WA
                      </a>
                      {req.converted_order_id ? (
                        <button
                          onClick={() => navigate(`/admin/orders/${req.converted_order_id}`)}
                          className="inline-flex items-center gap-1 rounded-lg border border-purple-200 bg-purple-50 px-2.5 py-1 text-xs font-semibold text-purple-700"
                        >
                          <ShoppingBag size={14} /> Buka Order
                        </button>
                      ) : (
                        <button
                          onClick={() => openConvertModal(req)}
                          className="inline-flex items-center gap-1 rounded-lg border border-[#8B5A2B] bg-[#8B5A2B] px-2.5 py-1 text-xs font-semibold text-white hover:bg-[#6B4423]"
                        >
                          <CheckCircle size={14} /> Buat Order
                        </button>
                      )}
                    </div>

                    <button
                      onClick={() => openDetail(req)}
                      className="inline-flex items-center text-xs font-semibold text-[#8B5A2B]"
                    >
                      Detail <ChevronRight size={14} />
                    </button>
                  </div>
                </div>
              );
            })}
          </div>

          {/* Desktop Table (hidden md:block) */}
          <div className="hidden overflow-hidden rounded-2xl border border-[#E5DCC5] bg-white shadow-sm md:block">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-[#E5DCC5] bg-[#FBF9F4] text-xs font-semibold text-[#5C4A3D]">
                <tr>
                  <th className="px-4 py-3">Tiket</th>
                  <th className="px-4 py-3">Customer</th>
                  <th className="px-4 py-3">Jenis & Ukuran</th>
                  <th className="px-4 py-3">Foto</th>
                  <th className="px-4 py-3">Budget</th>
                  <th className="px-4 py-3">Status</th>
                  <th className="px-4 py-3 text-right">Aksi</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#F1EBE0]">
                {requests.map((req) => {
                  const reqId = req.id || req._id;
                  const cleanPhone = (req.customer_phone || "").replace(/[^0-9]/g, "");
                  const badge = STATUS_BADGES[req.status] || STATUS_BADGES.baru;
                  const dims = req.dimensions || {};
                  const dimsStr = [
                    dims.length && `P: ${dims.length}cm`,
                    dims.width && `L: ${dims.width}cm`,
                    dims.height && `T: ${dims.height}cm`,
                  ].filter(Boolean).join(" · ");

                  return (
                    <tr key={reqId} className="hover:bg-[#FBF9F4]/50 transition-colors">
                      <td className="px-4 py-3 font-mono text-xs font-bold text-[#8B5A2B]">
                        {req.ticket_number}
                        <div className="text-[11px] font-normal text-[#8B7355]">
                          {new Date(req.created_at).toLocaleDateString("id-ID")}
                        </div>
                      </td>

                      <td className="px-4 py-3">
                        <div className="font-medium text-[#2C1E16]">{req.customer_name}</div>
                        <a
                          href={`https://wa.me/${cleanPhone}`}
                          target="_blank"
                          rel="noreferrer"
                          className="inline-flex items-center gap-1 text-xs text-[#25D366] hover:underline"
                        >
                          <MessageCircle size={12} /> {req.customer_phone}
                        </a>
                      </td>

                      <td className="px-4 py-3">
                        <div className="font-medium text-[#2C1E16]">{req.furniture_type}</div>
                        <div className="text-xs text-[#8B7355]">{dimsStr || dims.notes || "-"}</div>
                      </td>

                      <td className="px-4 py-3">
                        {req.reference_photos?.length > 0 ? (
                          <div className="flex gap-1">
                            {req.reference_photos.slice(0, 2).map((p, i) => (
                              <img
                                key={i}
                                src={p}
                                alt=""
                                className="h-9 w-9 rounded-lg border border-[#E5DCC5] object-cover cursor-pointer hover:scale-105 transition-transform"
                                onClick={() => openDetail(req)}
                              />
                            ))}
                            {req.reference_photos.length > 2 && (
                              <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-[#F1EBE0] text-xs font-bold text-[#8B7355]">
                                +{req.reference_photos.length - 2}
                              </span>
                            )}
                          </div>
                        ) : (
                          <span className="text-xs text-[#8B7355]">-</span>
                        )}
                      </td>

                      <td className="px-4 py-3 font-medium text-[#5C4A3D]">
                        {req.budget_estimation_le ? `${fmtLE(req.budget_estimation_le)} LE` : "-"}
                      </td>

                      <td className="px-4 py-3">
                        <span className={`rounded-full border px-2.5 py-0.5 text-xs font-semibold ${badge.bg}`}>
                          {badge.label}
                        </span>
                      </td>

                      <td className="px-4 py-3 text-right">
                        <div className="flex items-center justify-end gap-1.5">
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => openDetail(req)}
                            className="h-8 rounded-lg border-[#E5DCC5] text-xs text-[#5C4A3D]"
                          >
                            <Eye size={13} className="mr-1" /> Detail
                          </Button>

                          {req.converted_order_id ? (
                            <Button
                              variant="outline"
                              size="sm"
                              onClick={() => navigate(`/admin/orders/${req.converted_order_id}`)}
                              className="h-8 rounded-lg border-purple-300 text-xs text-purple-700 hover:bg-purple-50"
                            >
                              <ShoppingBag size={13} className="mr-1" /> Order
                            </Button>
                          ) : (
                            <Button
                              size="sm"
                              onClick={() => openConvertModal(req)}
                              className="h-8 rounded-lg bg-[#8B5A2B] text-xs hover:bg-[#6B4423]"
                            >
                              <CheckCircle size={13} className="mr-1" /> Buat Order
                            </Button>
                          )}

                          {canDelete && (
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => handleDelete(req)}
                              className="h-8 w-8 p-0 text-red-500 hover:bg-red-50"
                              title="Hapus Request"
                            >
                              <Trash2 size={14} />
                            </Button>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      )}

      {/* Detail Modal */}
      {detailModalOpen && selectedReq && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div className="max-h-[90vh] w-full max-w-2xl overflow-y-auto rounded-3xl border border-[#E5DCC5] bg-white p-5 sm:p-7 shadow-2xl">
            <div className="flex items-start justify-between border-b border-[#F1EBE0] pb-3">
              <div>
                <span className="font-mono text-xs font-bold text-[#8B5A2B]">
                  {selectedReq.ticket_number}
                </span>
                <h3 className="font-heading text-xl font-bold text-[#2C1E16]">
                  {selectedReq.furniture_type}
                </h3>
                <p className="text-xs text-[#8B7355]">
                  Dibuat {new Date(selectedReq.created_at).toLocaleString("id-ID")}
                </p>
              </div>
              <button
                onClick={() => setDetailModalOpen(false)}
                className="rounded-lg p-1 text-[#8B7355] hover:bg-[#F1EBE0]"
              >
                <X size={20} />
              </button>
            </div>

            <div className="mt-4 space-y-4 text-sm">
              {/* Customer Info */}
              <div className="rounded-2xl border border-[#E5DCC5] bg-[#FBF9F4] p-4">
                <p className="font-bold text-[#2C1E16]">Kontak Customer:</p>
                <div className="mt-1 grid gap-2 sm:grid-cols-2 text-xs">
                  <div>
                    <span className="text-[#8B7355]">Nama:</span> {selectedReq.customer_name}
                  </div>
                  <div>
                    <span className="text-[#8B7355]">No. WhatsApp:</span>{" "}
                    <a
                      href={`https://wa.me/${selectedReq.customer_phone?.replace(/[^0-9]/g, "")}`}
                      target="_blank"
                      rel="noreferrer"
                      className="font-semibold text-[#25D366] hover:underline"
                    >
                      {selectedReq.customer_phone} ↗
                    </a>
                  </div>
                  {selectedReq.customer_address && (
                    <div className="sm:col-span-2">
                      <span className="text-[#8B7355]">Alamat:</span> {selectedReq.customer_address}
                    </div>
                  )}
                </div>
              </div>

              {/* Specifications */}
              <div className="grid gap-3 sm:grid-cols-2">
                <div className="rounded-xl border border-[#E5DCC5] p-3 text-xs">
                  <span className="font-semibold text-[#8B7355]">Dimensi / Ukuran:</span>
                  <p className="mt-1 font-medium text-[#2C1E16]">
                    {[
                      selectedReq.dimensions?.length && `P: ${selectedReq.dimensions.length} cm`,
                      selectedReq.dimensions?.width && `L: ${selectedReq.dimensions.width} cm`,
                      selectedReq.dimensions?.height && `T: ${selectedReq.dimensions.height} cm`,
                    ].filter(Boolean).join(" × ") || "Tidak ditentukan"}
                  </p>
                  {selectedReq.dimensions?.notes && (
                    <p className="mt-1 text-[#5C4A3D]">{selectedReq.dimensions.notes}</p>
                  )}
                </div>

                <div className="rounded-xl border border-[#E5DCC5] p-3 text-xs">
                  <span className="font-semibold text-[#8B7355]">Pilihan Bahan / Finishing:</span>
                  <p className="mt-1 font-medium text-[#2C1E16]">
                    {selectedReq.material || "Belum ditentukan"}
                  </p>
                  {selectedReq.budget_estimation_le && (
                    <p className="mt-1 text-[#5C4A3D]">
                      Budget: <strong>{fmtLE(selectedReq.budget_estimation_le)} LE</strong>
                    </p>
                  )}
                </div>
              </div>

              {/* Customer Notes */}
              {selectedReq.notes && (
                <div className="rounded-xl border border-[#E5DCC5] bg-white p-3 text-xs">
                  <span className="font-semibold text-[#8B7355]">Catatan Kebutuhan:</span>
                  <p className="mt-1 whitespace-pre-wrap text-[#2C1E16]">{selectedReq.notes}</p>
                </div>
              )}

              {/* Reference Photos */}
              {selectedReq.reference_photos?.length > 0 && (
                <div>
                  <span className="text-xs font-semibold text-[#8B7355]">
                    Foto Referensi Customer ({selectedReq.reference_photos.length}):
                  </span>
                  <div className="mt-2 grid grid-cols-3 gap-2 sm:grid-cols-4">
                    {selectedReq.reference_photos.map((p, idx) => (
                      <a key={idx} href={p} target="_blank" rel="noreferrer" className="block group">
                        <div className="relative aspect-square overflow-hidden rounded-xl border border-[#E5DCC5] bg-[#FBF9F4]">
                          <img
                            src={p}
                            alt="Referensi"
                            className="h-full w-full object-cover group-hover:scale-105 transition-transform"
                          />
                        </div>
                      </a>
                    ))}
                  </div>
                </div>
              )}

              {/* Admin Update Controls */}
              <div className="border-t border-[#F1EBE0] pt-4 space-y-3">
                <p className="font-bold text-[#2C1E16]">Kelola Status & Catatan Internal:</p>

                <div className="grid gap-3 sm:grid-cols-2">
                  <div>
                    <Label className="text-xs text-[#5C4A3D]">Status Request</Label>
                    <Select value={editStatus} onValueChange={setEditStatus}>
                      <SelectTrigger className="mt-1 h-10 bg-white">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="baru">Baru</SelectItem>
                        <SelectItem value="diskusi">Dalam Diskusi</SelectItem>
                        <SelectItem value="disetujui">Disetujui</SelectItem>
                        <SelectItem value="dipesan">Dipesan (Dibuatkan Order)</SelectItem>
                        <SelectItem value="ditolak">Ditolak</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>

                  <div>
                    <Label className="text-xs text-[#5C4A3D]">Estimasi Harga Kesepakatan (LE)</Label>
                    <Input
                      type="number"
                      value={estimatedPrice}
                      onChange={(e) => setEstimatedPrice(e.target.value)}
                      placeholder="misal: 1400"
                      className="mt-1 h-10 bg-white"
                    />
                  </div>
                </div>

                <div>
                  <Label className="text-xs text-[#5C4A3D]">Catatan Internal Admin</Label>
                  <Textarea
                    value={adminNotes}
                    onChange={(e) => setAdminNotes(e.target.value)}
                    placeholder="Catatan tim produksi atau hasil pembicaraan via WhatsApp..."
                    className="mt-1 min-h-[60px] bg-white text-xs"
                  />
                </div>
              </div>
            </div>

            <div className="mt-6 flex flex-wrap gap-2 justify-end border-t border-[#F1EBE0] pt-4">
              <Button
                variant="outline"
                onClick={() => setDetailModalOpen(false)}
                className="rounded-xl border-[#E5DCC5]"
              >
                Tutup
              </Button>

              <Button
                onClick={handleUpdateStatus}
                className="rounded-xl bg-[#8B5A2B] hover:bg-[#6B4423]"
              >
                Simpan Perubahan
              </Button>

              {!selectedReq.converted_order_id && (
                <Button
                  onClick={() => {
                    setDetailModalOpen(false);
                    openConvertModal(selectedReq);
                  }}
                  className="rounded-xl bg-purple-700 hover:bg-purple-800 text-white"
                >
                  <CheckCircle size={15} className="mr-1" /> Jadikan Pesanan
                </Button>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Convert to Order Modal */}
      {convertModalOpen && selectedReq && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div className="w-full max-w-md rounded-3xl border border-[#E5DCC5] bg-white p-5 sm:p-7 shadow-2xl">
            <div className="flex items-start justify-between border-b border-[#F1EBE0] pb-3">
              <div>
                <h3 className="font-heading text-lg font-bold text-[#2C1E16]">
                  Jadikan Pesanan Resmi
                </h3>
                <p className="text-xs text-[#8B7355]">
                  Tiket: {selectedReq.ticket_number} · {selectedReq.furniture_type}
                </p>
              </div>
              <button
                onClick={() => setConvertModalOpen(false)}
                className="rounded-lg p-1 text-[#8B7355] hover:bg-[#F1EBE0]"
              >
                <X size={18} />
              </button>
            </div>

            <form onSubmit={handleConvert} className="mt-4 space-y-3">
              <div>
                <Label className="text-xs font-semibold text-[#5C4A3D]">
                  Harga Subtotal Kesepakatan (LE) <span className="text-red-500">*</span>
                </Label>
                <Input
                  type="number"
                  required
                  value={convertForm.subtotal_le}
                  onChange={(e) => setConvertForm({ ...convertForm, subtotal_le: e.target.value })}
                  placeholder="Contoh: 1500"
                  className="mt-1"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <Label className="text-xs font-semibold text-[#5C4A3D]">Ongkir (LE)</Label>
                  <Input
                    type="number"
                    value={convertForm.delivery_fee_le}
                    onChange={(e) => setConvertForm({ ...convertForm, delivery_fee_le: e.target.value })}
                    className="mt-1"
                  />
                </div>
                <div>
                  <Label className="text-xs font-semibold text-[#5C4A3D]">Metode Kirim</Label>
                  <Select
                    value={convertForm.delivery_method}
                    onValueChange={(v) => setConvertForm({ ...convertForm, delivery_method: v })}
                  >
                    <SelectTrigger className="mt-1 h-10 bg-white">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="delivery">Delivery</SelectItem>
                      <SelectItem value="pickup">Ambil di Toko</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              </div>

              <div>
                <Label className="text-xs font-semibold text-[#5C4A3D]">Metode Pembayaran</Label>
                <Select
                  value={convertForm.payment_method}
                  onValueChange={(v) => setConvertForm({ ...convertForm, payment_method: v })}
                >
                  <SelectTrigger className="mt-1 h-10 bg-white">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="transfer">Transfer Bank</SelectItem>
                    <SelectItem value="cash">Cash / Tunai</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <div>
                <Label className="text-xs font-semibold text-[#5C4A3D]">Catatan Pesanan</Label>
                <Input
                  value={convertForm.notes}
                  onChange={(e) => setConvertForm({ ...convertForm, notes: e.target.value })}
                  className="mt-1 text-xs"
                />
              </div>

              {/* Total preview */}
              <div className="rounded-xl border border-[#E5DCC5] bg-[#FBF9F4] p-3 text-xs">
                <div className="flex justify-between text-[#8B7355]">
                  <span>Total Pesanan (LE):</span>
                  <span className="font-bold text-[#8B5A2B] text-base">
                    {fmtLE((Number(convertForm.subtotal_le) || 0) + (Number(convertForm.delivery_fee_le) || 0))} LE
                  </span>
                </div>
                <p className="mt-1 text-[11px] text-[#8B7355]">
                  Order resmi akan langsung diterbitkan dan siap dikelola di menu Pesanan.
                </p>
              </div>

              <div className="mt-5 flex gap-2 pt-2">
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => setConvertModalOpen(false)}
                  className="flex-1 rounded-xl border-[#E5DCC5]"
                >
                  Batal
                </Button>
                <Button
                  type="submit"
                  disabled={converting}
                  className="flex-1 rounded-xl bg-[#8B5A2B] hover:bg-[#6B4423]"
                >
                  {converting ? "Menerbitkan..." : "Terbitkan Pesanan"}
                </Button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
