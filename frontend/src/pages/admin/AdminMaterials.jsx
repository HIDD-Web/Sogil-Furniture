import React, { useEffect, useState, useMemo } from "react";
import api from "../../lib/api";
import { formatApiError } from "../../lib/format";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Textarea } from "../../components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../../components/ui/select";
import { Badge } from "../../components/ui/badge";
import {
  Layers,
  Plus,
  Pencil,
  Archive,
  RotateCcw,
  Search,
  X,
  Filter,
} from "lucide-react";
import { toast } from "sonner";

const CATEGORIES = ["Material", "Parts"];
const UNITS = ["pcs", "batang", "lembar", "meter", "kg", "box"];

const INITIAL_FORM = {
  name: "",
  category: "Material",
  specs: "",
  sku: "",
  unit: "pcs",
  notes: "",
};

export default function AdminMaterials() {
  const [materials, setMaterials] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [categoryFilter, setCategoryFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("active");

  // Modal states
  const [modalOpen, setModalOpen] = useState(false);
  const [editingItem, setEditingItem] = useState(null);
  const [form, setForm] = useState(INITIAL_FORM);
  const [submitting, setSubmitting] = useState(false);

  const loadMaterials = async () => {
    try {
      setLoading(true);
      const res = await api.get("/admin/materials");
      setMaterials(res.data || []);
    } catch {
      toast.error("Gagal memuat data bahan");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadMaterials();
  }, []);

  const openAddModal = () => {
    setEditingItem(null);
    setForm(INITIAL_FORM);
    setModalOpen(true);
  };

  const openEditModal = (item) => {
    setEditingItem(item);
    setForm({
      name: item.name || "",
      category: item.category || "Material",
      specs: item.specs || "",
      sku: item.sku || "",
      unit: item.unit || "pcs",
      notes: item.notes || "",
    });
    setModalOpen(true);
  };

  const closeModal = () => {
    if (submitting) return;
    setModalOpen(false);
    setEditingItem(null);
    setForm(INITIAL_FORM);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!form.name.trim()) return toast.error("Nama bahan wajib diisi");
    if (!form.specs.trim()) return toast.error("Spesifikasi/Ukuran wajib diisi");
    if (!form.category) return toast.error("Kategori wajib dipilih");
    if (!form.unit) return toast.error("Satuan wajib dipilih");

    try {
      setSubmitting(true);
      const payload = {
        name: form.name.trim(),
        category: form.category,
        specs: form.specs.trim(),
        sku: form.sku.trim() || null,
        unit: form.unit,
        notes: form.notes.trim() || "",
      };

      if (editingItem) {
        await api.put(`/admin/materials/${editingItem.id}`, payload);
        toast.success("Bahan berhasil diperbarui");
      } else {
        await api.post("/admin/materials", payload);
        toast.success("Bahan baru berhasil ditambahkan");
      }
      closeModal();
      loadMaterials();
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail) || "Gagal menyimpan bahan");
    } finally {
      setSubmitting(false);
    }
  };

  const handleArchive = async (item) => {
    const isArchived = item.status === "archived";
    const confirmMsg = isArchived
      ? `Aktifkan kembali bahan "${item.name} (${item.specs})"?`
      : `Arsipkan bahan "${item.name} (${item.specs})"?`;

    if (!window.confirm(confirmMsg)) return;

    try {
      if (isArchived) {
        await api.put(`/admin/materials/${item.id}`, { status: "active" });
        toast.success("Bahan berhasil diaktifkan kembali");
      } else {
        await api.delete(`/admin/materials/${item.id}`);
        toast.success("Bahan berhasil diarsipkan");
      }
      loadMaterials();
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail) || "Gagal mengubah status bahan");
    }
  };

  const filteredMaterials = useMemo(() => {
    return materials.filter((m) => {
      // Category filter
      if (categoryFilter !== "all" && m.category !== categoryFilter) {
        return false;
      }
      // Status filter
      if (statusFilter !== "all" && m.status !== statusFilter) {
        return false;
      }
      // Search filter (name, specs, sku)
      if (search.trim()) {
        const q = search.toLowerCase();
        const matchName = (m.name || "").toLowerCase().includes(q);
        const matchSpecs = (m.specs || "").toLowerCase().includes(q);
        const matchSku = (m.sku || "").toLowerCase().includes(q);
        if (!matchName && !matchSpecs && !matchSku) return false;
      }
      return true;
    });
  }, [materials, categoryFilter, statusFilter, search]);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="font-heading text-2xl font-bold text-[#2C1E16] flex items-center gap-2">
            <Layers className="text-[#8B5A2B]" size={26} />
            Data Bahan
          </h1>
          <p className="mt-1 text-sm text-[#8B7355]">
            Kelola master data bahan baku dan komponen perabot Sogil Furniture.
          </p>
        </div>
        <Button
          onClick={openAddModal}
          data-testid="add-material-btn"
          className="rounded-xl bg-[#8B5A2B] hover:bg-[#6B4423] text-white shadow-sm flex items-center gap-1.5 self-start sm:self-auto"
        >
          <Plus size={18} /> Tambah Bahan
        </Button>
      </div>

      {/* Filter & Search Bar */}
      <div className="rounded-2xl border border-[#E5DCC5] bg-white p-4 shadow-sm space-y-3">
        <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          {/* Search box */}
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-[#8B7355]" size={16} />
            <Input
              type="text"
              placeholder="Cari nama bahan, spesifikasi, atau SKU..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-9 bg-[#F9F6F0] border-[#E5DCC5] text-sm"
              data-testid="search-material-input"
            />
            {search && (
              <button
                onClick={() => setSearch("")}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
              >
                <X size={14} />
              </button>
            )}
          </div>

          {/* Filters */}
          <div className="flex flex-wrap items-center gap-2">
            <div className="flex items-center gap-1.5 text-xs text-[#8B7355]">
              <Filter size={14} />
              <span>Kategori:</span>
            </div>
            <div className="flex rounded-lg border border-[#E5DCC5] bg-[#F9F6F0] p-0.5 text-xs">
              <button
                type="button"
                onClick={() => setCategoryFilter("all")}
                className={`rounded-md px-3 py-1 font-medium transition ${
                  categoryFilter === "all" ? "bg-white text-[#8B5A2B] shadow-xs" : "text-[#5C4A3D] hover:text-[#2C1E16]"
                }`}
                data-testid="filter-cat-all"
              >
                Semua
              </button>
              <button
                type="button"
                onClick={() => setCategoryFilter("Material")}
                className={`rounded-md px-3 py-1 font-medium transition ${
                  categoryFilter === "Material" ? "bg-white text-[#8B5A2B] shadow-xs" : "text-[#5C4A3D] hover:text-[#2C1E16]"
                }`}
                data-testid="filter-cat-material"
              >
                Material
              </button>
              <button
                type="button"
                onClick={() => setCategoryFilter("Parts")}
                className={`rounded-md px-3 py-1 font-medium transition ${
                  categoryFilter === "Parts" ? "bg-white text-[#8B5A2B] shadow-xs" : "text-[#5C4A3D] hover:text-[#2C1E16]"
                }`}
                data-testid="filter-cat-parts"
              >
                Parts
              </button>
            </div>

            <div className="ml-2 flex items-center gap-1.5 text-xs text-[#8B7355]">
              <span>Status:</span>
            </div>
            <Select value={statusFilter} onValueChange={setStatusFilter}>
              <SelectTrigger className="h-8 w-28 text-xs bg-white border-[#E5DCC5]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">Semua Status</SelectItem>
                <SelectItem value="active">Aktif</SelectItem>
                <SelectItem value="archived">Diarsipkan</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>
      </div>

      {/* Materials Table */}
      <div className="overflow-hidden rounded-2xl border border-[#E5DCC5] bg-white shadow-sm">
        {loading ? (
          <div className="p-12 text-center text-[#8B7355]">Memuat data bahan...</div>
        ) : filteredMaterials.length === 0 ? (
          <div className="p-12 text-center text-[#8B7355]">
            <Layers className="mx-auto mb-2 opacity-30" size={36} />
            <p className="font-medium text-[#5C4A3D]">Tidak ada bahan yang ditemukan</p>
            <p className="mt-1 text-xs">
              {search || categoryFilter !== "all" || statusFilter !== "all"
                ? "Coba sesuaikan kata kunci pencarian atau filter status."
                : "Klik tombol '+ Tambah Bahan' untuk mulai mendaftarkan bahan."}
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm" data-testid="materials-table">
              <thead className="border-b border-[#E5DCC5] bg-[#F1EBE0] text-xs uppercase text-[#8B7355]">
                <tr>
                  <th className="px-4 py-3 font-semibold">Nama Bahan</th>
                  <th className="px-4 py-3 font-semibold">Spesifikasi / Ukuran</th>
                  <th className="px-4 py-3 font-semibold">Kategori</th>
                  <th className="px-4 py-3 font-semibold">Satuan</th>
                  <th className="px-4 py-3 font-semibold">SKU / Kode</th>
                  <th className="px-4 py-3 font-semibold">Catatan</th>
                  <th className="px-4 py-3 font-semibold">Status</th>
                  <th className="px-4 py-3 text-right font-semibold">Aksi</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#F1EBE0]">
                {filteredMaterials.map((m) => {
                  const isArchived = m.status === "archived";
                  return (
                    <tr
                      key={m.id}
                      className={`hover:bg-[#FAF8F5] transition ${isArchived ? "bg-[#FAF7F2] opacity-75" : ""}`}
                      data-testid={`material-row-${m.id}`}
                    >
                      <td className="px-4 py-3 font-medium text-[#2C1E16]">
                        {m.name}
                      </td>
                      <td className="px-4 py-3 text-[#5C4A3D] font-mono text-xs">
                        {m.specs}
                      </td>
                      <td className="px-4 py-3">
                        <Badge
                          variant="outline"
                          className={
                            m.category === "Material"
                              ? "bg-amber-50 text-amber-800 border-amber-200"
                              : "bg-blue-50 text-blue-800 border-blue-200"
                          }
                        >
                          {m.category}
                        </Badge>
                      </td>
                      <td className="px-4 py-3 font-medium text-[#5C4A3D]">
                        {m.unit}
                      </td>
                      <td className="px-4 py-3 text-xs text-[#8B7355] font-mono">
                        {m.sku || "-"}
                      </td>
                      <td className="px-4 py-3 text-xs text-[#8B7355] max-w-xs truncate" title={m.notes || ""}>
                        {m.notes || "-"}
                      </td>
                      <td className="px-4 py-3">
                        <Badge
                          variant="outline"
                          className={
                            isArchived
                              ? "bg-gray-100 text-gray-600 border-gray-200"
                              : "bg-green-100 text-green-800 border-green-200"
                          }
                        >
                          {isArchived ? "Diarsipkan" : "Aktif"}
                        </Badge>
                      </td>
                      <td className="px-4 py-3 text-right">
                        <div className="flex items-center justify-end gap-1.5">
                          <button
                            type="button"
                            onClick={() => openEditModal(m)}
                            className="rounded-lg p-1.5 text-[#8B5A2B] hover:bg-[#EFE6D5] transition"
                            title="Edit Bahan"
                            data-testid={`edit-material-${m.id}`}
                          >
                            <Pencil size={15} />
                          </button>
                          <button
                            type="button"
                            onClick={() => handleArchive(m)}
                            className={`rounded-lg p-1.5 transition ${
                              isArchived
                                ? "text-green-700 hover:bg-green-100"
                                : "text-gray-500 hover:text-red-600 hover:bg-red-50"
                            }`}
                            title={isArchived ? "Aktifkan kembali" : "Arsipkan bahan"}
                            data-testid={`archive-material-${m.id}`}
                          >
                            {isArchived ? <RotateCcw size={15} /> : <Archive size={15} />}
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Add / Edit Modal */}
      {modalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-md rounded-2xl border border-[#E5DCC5] bg-white p-6 shadow-xl">
            <div className="mb-4 flex items-center justify-between border-b border-[#E5DCC5] pb-3">
              <h2 className="font-heading text-lg font-bold text-[#2C1E16]">
                {editingItem ? "Edit Data Bahan" : "Tambah Bahan Baru"}
              </h2>
              <button
                type="button"
                onClick={closeModal}
                disabled={submitting}
                className="text-[#8B7355] hover:text-[#2C1E16]"
              >
                <X size={20} />
              </button>
            </div>

            <form onSubmit={handleSubmit} className="space-y-4">
              <div>
                <Label className="mb-1 block text-xs font-semibold text-[#5C4A3D]">
                  Nama Bahan <span className="text-red-500">*</span>
                </Label>
                <Input
                  type="text"
                  placeholder="Contoh: Balok Kayu, Baut Mur, Blockboard"
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                  required
                  data-testid="material-form-name"
                  className="bg-white"
                />
              </div>

              <div>
                <Label className="mb-1 block text-xs font-semibold text-[#5C4A3D]">
                  Spesifikasi / Ukuran <span className="text-red-500">*</span>
                </Label>
                <Input
                  type="text"
                  placeholder="Contoh: 5x5 x 300 cm, M6 x 20 mm, 18 mm"
                  value={form.specs}
                  onChange={(e) => setForm({ ...form, specs: e.target.value })}
                  required
                  data-testid="material-form-specs"
                  className="bg-white"
                />
                <p className="mt-1 text-[11px] text-[#8B7355]">
                  Bahan dengan nama sama tetapi spesifikasi berbeda diperlakukan sebagai item berbeda.
                </p>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <Label className="mb-1 block text-xs font-semibold text-[#5C4A3D]">
                    Kategori <span className="text-red-500">*</span>
                  </Label>
                  <Select
                    value={form.category}
                    onValueChange={(val) => setForm({ ...form, category: val })}
                  >
                    <SelectTrigger className="bg-white" data-testid="material-form-category">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {CATEGORIES.map((cat) => (
                        <SelectItem key={cat} value={cat}>
                          {cat}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>

                <div>
                  <Label className="mb-1 block text-xs font-semibold text-[#5C4A3D]">
                    Satuan <span className="text-red-500">*</span>
                  </Label>
                  <Select
                    value={form.unit}
                    onValueChange={(val) => setForm({ ...form, unit: val })}
                  >
                    <SelectTrigger className="bg-white" data-testid="material-form-unit">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {UNITS.map((u) => (
                        <SelectItem key={u} value={u}>
                          {u}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              </div>

              <div>
                <Label className="mb-1 block text-xs font-semibold text-[#5C4A3D]">
                  SKU / Kode Bahan (Opsional)
                </Label>
                <Input
                  type="text"
                  placeholder="Contoh: MAT-KY-5X5-300"
                  value={form.sku}
                  onChange={(e) => setForm({ ...form, sku: e.target.value })}
                  data-testid="material-form-sku"
                  className="bg-white font-mono text-xs"
                />
              </div>

              <div>
                <Label className="mb-1 block text-xs font-semibold text-[#5C4A3D]">
                  Catatan (Opsional)
                </Label>
                <Textarea
                  placeholder="Catatan tambahan mengenai pemasok, kualitas, atau penyimpanan..."
                  value={form.notes}
                  onChange={(e) => setForm({ ...form, notes: e.target.value })}
                  rows={2}
                  data-testid="material-form-notes"
                  className="bg-white text-xs"
                />
              </div>

              <div className="mt-6 flex items-center justify-end gap-2 border-t border-[#E5DCC5] pt-4">
                <Button
                  type="button"
                  variant="outline"
                  onClick={closeModal}
                  disabled={submitting}
                  className="rounded-xl border-[#E5DCC5]"
                >
                  Batal
                </Button>
                <Button
                  type="submit"
                  disabled={submitting}
                  data-testid="material-submit-btn"
                  className="rounded-xl bg-[#8B5A2B] hover:bg-[#6B4423] text-white"
                >
                  {submitting ? "Menyimpan..." : editingItem ? "Simpan Perubahan" : "Tambah Bahan"}
                </Button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
