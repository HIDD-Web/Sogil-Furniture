import React, { useEffect, useState, useMemo } from "react";
import { useSearchParams } from "react-router-dom";
import api, { imgUrl } from "../../lib/api";
import { fmtLE } from "../../lib/format";
import { buildCategoryPreviews } from "../../lib/catalog";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Textarea } from "../../components/ui/textarea";
import { Label } from "../../components/ui/label";
import { Badge } from "../../components/ui/badge";
import { Switch } from "../../components/ui/switch";
import {
  Plus,
  Pencil,
  Trash2,
  ArrowUp,
  ArrowDown,
  ArrowLeft,
  ArrowRight,
  Layers,
  X,
  Sparkles,
  Check,
  RotateCcw,
  Search,
  Eye,
} from "lucide-react";
import { toast } from "sonner";

export default function AdminCategories() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [categories, setCategories] = useState([]);
  const [products, setProducts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [modalOpen, setModalOpen] = useState(false);
  const [editingCat, setEditingCat] = useState(null);
  const [featuredModalCat, setFeaturedModalCat] = useState(null);
  const [form, setForm] = useState({ name: "", key: "", description: "", sort_order: 1, active: true });

  const loadData = async () => {
    try {
      const [catsRes, prodsRes] = await Promise.all([
        api.get("/admin/categories"),
        api.get("/products?admin_view=true").catch(() => ({ data: [] })),
      ]);
      const cats = catsRes.data || [];
      setCategories(cats);
      setProducts(prodsRes.data || []);

      // Auto-open featured modal if requested in URL query ?featured=<category_key>
      const featKey = searchParams.get("featured");
      if (featKey) {
        const found = cats.find((c) => c.key === featKey);
        if (found) setFeaturedModalCat(found);
      }
    } catch (err) {
      toast.error("Gagal memuat data kategori");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  const openCreate = () => {
    const nextOrder = categories.length ? Math.max(...categories.map((c) => c.sort_order || 0)) + 1 : 1;
    setEditingCat(null);
    setForm({ name: "", key: "", description: "", sort_order: nextOrder, active: true });
    setModalOpen(true);
  };

  const openEdit = (cat) => {
    setEditingCat(cat);
    setForm({
      name: cat.name || "",
      key: cat.key || "",
      description: cat.description || "",
      sort_order: cat.sort_order || 1,
      active: cat.active !== false,
    });
    setModalOpen(true);
  };

  const saveCategory = async (e) => {
    e.preventDefault();
    if (!form.name.trim()) return toast.error("Nama kategori wajib diisi");
    const key = (form.key || form.name).trim().toLowerCase().replace(/[^a-z0-9]+/g, "_");
    if (!key) return toast.error("Key kategori wajib diisi");

    try {
      if (editingCat) {
        await api.put(`/admin/categories/${editingCat.id}`, { ...form, key });
        toast.success("Kategori diperbarui");
      } else {
        await api.post("/admin/categories", { ...form, key });
        toast.success("Kategori baru ditambahkan");
      }
      setModalOpen(false);
      loadData();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Gagal menyimpan kategori");
    }
  };

  const moveOrder = async (index, dir) => {
    const targetIdx = index + dir;
    if (targetIdx < 0 || targetIdx >= categories.length) return;
    const current = categories[index];
    const target = categories[targetIdx];

    try {
      const currentOrder = current.sort_order || index + 1;
      const targetOrder = target.sort_order || targetIdx + 1;

      await Promise.all([
        api.put(`/admin/categories/${current.id}`, { sort_order: targetOrder }),
        api.put(`/admin/categories/${target.id}`, { sort_order: currentOrder }),
      ]);
      loadData();
    } catch {
      toast.error("Gagal mengubah urutan");
    }
  };

  const deleteCategory = async (cat) => {
    const count = products.filter((p) => p.category === cat.key).length;
    const promptMsg = count > 0
      ? `Kategori "${cat.name}" memiliki ${count} produk terkait. Menonaktifkan kategori ini akan menyembunyikannya dari customer. Lanjutkan?`
      : `Hapus kategori "${cat.name}"? Tindakan ini tidak dapat dibatalkan.`;

    if (!window.confirm(promptMsg)) return;

    try {
      const res = await api.delete(`/admin/categories/${cat.id}`);
      if (res.data?.status === "deactivated") {
        toast.success("Kategori dinonaktifkan");
      } else {
        toast.success("Kategori dihapus");
      }
      loadData();
    } catch (err) {
      toast.error(err.response?.data?.detail || "Gagal menghapus kategori");
    }
  };

  return (
    <div className="space-y-4 sm:space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h1 className="font-heading text-xl sm:text-2xl font-bold text-[#2C1E16]">Kategori Produk</h1>
          <p className="mt-0.5 text-xs sm:text-sm text-[#8B7355]">
            Kelola kategori dinamis, deskripsi, urutan tampilan, dan status aktif.
          </p>
        </div>
        <Button onClick={openCreate} data-testid="add-category-btn" className="h-9 sm:h-10 rounded-xl bg-[#8B5A2B] text-xs sm:text-sm hover:bg-[#6B4423]">
          <Plus size={15} className="mr-1" /> Tambah Kategori
        </Button>
      </div>

      {loading ? (
        <div className="mt-6 text-sm text-[#8B7355]">Memuat data kategori...</div>
      ) : categories.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-[#E5DCC5] bg-white p-8 text-center text-sm text-[#8B7355]">
          Belum ada kategori terdaftar.
        </div>
      ) : (
        <div className="grid gap-3 sm:gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {categories.map((cat, idx) => {
            const prodCount = products.filter((p) => p.category === cat.key).length;
            return (
              <div
                key={cat.id}
                className="flex flex-col justify-between rounded-2xl border border-[#E5DCC5] bg-white p-4 shadow-xs transition-shadow hover:shadow-sm"
                data-testid={`category-card-${cat.key}`}
              >
                <div>
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-mono text-xs text-[#8B7355]">slug: {cat.key}</span>
                    <div className="flex items-center gap-1.5">
                      {cat.active !== false ? (
                        <Badge variant="outline" className="border-green-300 bg-green-50 px-1.5 py-0 text-[10px] text-green-700">
                          Aktif
                        </Badge>
                      ) : (
                        <Badge variant="outline" className="border-red-300 bg-red-50 px-1.5 py-0 text-[10px] text-red-700">
                          Nonaktif
                        </Badge>
                      )}
                      <span className="text-[11px] font-semibold text-[#8B5A2B]">#{cat.sort_order}</span>
                    </div>
                  </div>

                  <h3 className="mt-2 font-heading text-base sm:text-lg font-bold text-[#2C1E16]">
                    {cat.name}
                  </h3>

                  {cat.description ? (
                    <p className="mt-1 text-xs text-[#5C4A3D] line-clamp-2">{cat.description}</p>
                  ) : (
                    <p className="mt-1 text-xs italic text-[#8B7355]">Belum ada deskripsi</p>
                  )}

                  <div className="mt-3 flex items-center justify-between border-t border-[#F1EBE0] pt-2 text-xs text-[#5C4A3D]">
                    <span className="inline-flex items-center gap-1 text-[11px] text-[#8B7355]">
                      <Layers size={13} /> {prodCount} produk
                    </span>
                    <div className="flex items-center gap-1">
                      <button
                        type="button"
                        onClick={() => moveOrder(idx, -1)}
                        disabled={idx === 0}
                        className="rounded border border-[#E5DCC5] p-1 text-[#8B5A2B] hover:bg-[#F5EFEB] disabled:opacity-30"
                        title="Geser ke atas"
                      >
                        <ArrowUp size={13} />
                      </button>
                      <button
                        type="button"
                        onClick={() => moveOrder(idx, 1)}
                        disabled={idx === categories.length - 1}
                        className="rounded border border-[#E5DCC5] p-1 text-[#8B5A2B] hover:bg-[#F5EFEB] disabled:opacity-30"
                        title="Geser ke bawah"
                      >
                        <ArrowDown size={13} />
                      </button>
                    </div>
                  </div>
                </div>

                {Array.isArray(cat.featured_preview_ids) && cat.featured_preview_ids.length > 0 && (
                  <div className="mt-2.5 flex items-center gap-1.5 rounded-lg border border-[#E5DCC5] bg-[#FAF5EE] px-2 py-1 text-[11px] font-medium text-[#8B5A2B]">
                    <Sparkles size={12} className="text-[#8B5A2B]" />
                    <span>Beranda: {cat.featured_preview_ids.length} variasi kustom diatur</span>
                  </div>
                )}

                <div className="mt-3 flex flex-col gap-2 border-t border-[#F1EBE0] pt-2.5">
                  <Button
                    variant="outline"
                    onClick={() => setFeaturedModalCat(cat)}
                    data-testid={`featured-cat-${cat.key}`}
                    className="h-8 w-full rounded-xl border-[#8B5A2B]/40 bg-[#FAF5EE] text-xs font-semibold text-[#8B5A2B] hover:bg-[#8B5A2B] hover:text-white transition-colors"
                  >
                    <Sparkles size={12} className="mr-1.5" /> Atur 3 Produk Beranda
                  </Button>

                  <div className="flex items-center gap-2">
                    <Button
                      variant="outline"
                      onClick={() => openEdit(cat)}
                      data-testid={`edit-cat-${cat.key}`}
                      className="h-8 flex-1 rounded-xl border-[#8B5A2B] text-xs font-medium text-[#8B5A2B] hover:bg-[#F5EFEB]"
                    >
                      <Pencil size={12} className="mr-1" /> Edit
                    </Button>
                    <Button
                      variant="ghost"
                      onClick={() => deleteCategory(cat)}
                      data-testid={`del-cat-${cat.key}`}
                      className="h-8 w-8 p-0 text-red-500 hover:bg-red-50 hover:text-red-700"
                      title="Hapus / Nonaktifkan"
                    >
                      <Trash2 size={14} />
                    </Button>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Modal Create/Edit Category */}
      {modalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-md rounded-2xl border border-[#E5DCC5] bg-white p-5 shadow-lg">
            <div className="flex items-center justify-between pb-3 border-b border-[#F1EBE0]">
              <h2 className="font-heading font-bold text-base text-[#2C1E16]">
                {editingCat ? "Edit Kategori" : "Tambah Kategori Baru"}
              </h2>
              <button onClick={() => setModalOpen(false)} className="p-1 text-[#8B7355] hover:text-[#2C1E16]">
                <X size={18} />
              </button>
            </div>

            <form onSubmit={saveCategory} className="mt-4 space-y-3.5">
              <div>
                <Label className="mb-1 block text-xs text-[#5C4A3D]">Nama Kategori</Label>
                <Input
                  value={form.name}
                  onChange={(e) => {
                    const name = e.target.value;
                    setForm((prev) => ({
                      ...prev,
                      name,
                      key: editingCat ? prev.key : name.toLowerCase().replace(/[^a-z0-9]+/g, "_"),
                    }));
                  }}
                  placeholder="Mis. Lemari, Rak Sudut"
                  className="bg-white text-xs sm:text-sm"
                  required
                />
              </div>

              <div>
                <Label className="mb-1 block text-xs text-[#5C4A3D]">Slug / Identifier (huruf kecil & garis bawah)</Label>
                <Input
                  value={form.key}
                  onChange={(e) => setForm((prev) => ({ ...prev, key: e.target.value.toLowerCase().replace(/[^a-z0-9_]+/g, "") }))}
                  placeholder="mis. lemari"
                  className="bg-white text-xs sm:text-sm font-mono"
                  required
                />
              </div>

              <div>
                <Label className="mb-1 block text-xs text-[#5C4A3D]">Deskripsi Singkat</Label>
                <Textarea
                  value={form.description}
                  onChange={(e) => setForm((prev) => ({ ...prev, description: e.target.value }))}
                  placeholder="Deskripsi singkat untuk customer..."
                  className="bg-white text-xs sm:text-sm min-h-[70px]"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <Label className="mb-1 block text-xs text-[#5C4A3D]">Urutan Tampil (No.)</Label>
                  <Input
                    type="number"
                    value={form.sort_order}
                    onChange={(e) => setForm((prev) => ({ ...prev, sort_order: Number(e.target.value) || 1 }))}
                    className="bg-white text-xs sm:text-sm"
                  />
                </div>
                <div className="flex flex-col justify-end">
                  <div className="flex items-center justify-between rounded-xl border border-[#E5DCC5] p-2">
                    <span className="text-xs text-[#5C4A3D]">Status Aktif</span>
                    <Switch
                      checked={form.active}
                      onCheckedChange={(c) => setForm((prev) => ({ ...prev, active: c }))}
                    />
                  </div>
                </div>
              </div>

              <div className="mt-4 flex gap-2 pt-2">
                <Button type="button" variant="outline" onClick={() => setModalOpen(false)} className="flex-1 rounded-xl text-xs sm:text-sm">
                  Batal
                </Button>
                <Button type="submit" className="flex-1 rounded-xl bg-[#8B5A2B] text-xs sm:text-sm hover:bg-[#6B4423]">
                  Simpan
                </Button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Modal Atur 3 Produk Beranda */}
      {featuredModalCat && (
        <FeaturedProductsModal
          open={Boolean(featuredModalCat)}
          onClose={() => {
            setFeaturedModalCat(null);
            if (searchParams.get("featured")) {
              setSearchParams({});
            }
          }}
          category={featuredModalCat}
          products={products}
          onSaved={loadData}
        />
      )}
    </div>
  );
}

function FeaturedProductsModal({
  open,
  onClose,
  category,
  products = [],
  onSaved,
}) {
  const [selectedSlots, setSelectedSlots] = useState([]);
  const [searchQuery, setSearchQuery] = useState("");
  const [saving, setSaving] = useState(false);

  // Get all possible previews for this category
  const categoryProducts = useMemo(() => {
    if (!category?.key) return [];
    return products.filter((p) => p.category === category.key);
  }, [category, products]);

  const allPreviews = useMemo(() => {
    if (!categoryProducts.length) return [];
    return buildCategoryPreviews(categoryProducts);
  }, [categoryProducts]);

  // Initialize selected slots from category.featured_preview_ids or fallback to first 3
  useEffect(() => {
    if (!open || !allPreviews.length) return;

    const explicitIds = category?.featured_preview_ids;
    if (Array.isArray(explicitIds) && explicitIds.length > 0) {
      const initial = [];
      explicitIds.forEach((fid) => {
        const found = allPreviews.find(
          (p) =>
            p.id === fid ||
            p.id.endsWith(`-${fid}`) ||
            p.config?.id === fid ||
            (p.config?.length &&
              `${p.config.length}_${p.config.level}_${p.config.type}` === fid)
        );
        if (found && !initial.some((x) => x.id === found.id)) {
          initial.push(found);
        }
      });
      // Pad to 3 if less than 3
      if (initial.length < 3) {
        allPreviews.forEach((p) => {
          if (initial.length < 3 && !initial.some((x) => x.id === p.id)) {
            initial.push(p);
          }
        });
      }
      setSelectedSlots(initial.slice(0, 3));
    } else {
      // Default: First 3 previews
      setSelectedSlots(allPreviews.slice(0, 3));
    }
  }, [open, category, allPreviews]);

  if (!open || !category) return null;

  // Reorder slots
  const moveSlot = (index, dir) => {
    const targetIdx = index + dir;
    if (targetIdx < 0 || targetIdx >= selectedSlots.length) return;
    const updated = [...selectedSlots];
    const temp = updated[index];
    updated[index] = updated[targetIdx];
    updated[targetIdx] = temp;
    setSelectedSlots(updated);
  };

  const removeSlot = (index) => {
    setSelectedSlots((prev) => prev.filter((_, i) => i !== index));
  };

  const toggleSelect = (preview) => {
    const existingIndex = selectedSlots.findIndex((p) => p.id === preview.id);
    if (existingIndex >= 0) {
      removeSlot(existingIndex);
    } else {
      if (selectedSlots.length < 3) {
        setSelectedSlots((prev) => [...prev, preview]);
      } else {
        // Replace slot 3
        setSelectedSlots((prev) => [prev[0], prev[1], preview]);
        toast.info("Mengganti posisi Slot 3");
      }
    }
  };

  const handleResetDefault = () => {
    setSelectedSlots(allPreviews.slice(0, 3));
    toast.info("Urutan direset ke default 3 variasi pertama");
  };

  const handleSave = async () => {
    if (selectedSlots.length === 0) {
      return toast.error("Pilih minimal 1 produk untuk ditampilkan di beranda");
    }

    setSaving(true);
    const featuredIds = selectedSlots.map((p) => p.id);

    try {
      // 1. Update in categories
      await api.put(`/admin/categories/${category.id}`, {
        featured_preview_ids: featuredIds,
      });

      // 2. Also update in product if matching product exists
      if (categoryProducts.length > 0) {
        await api.put(`/admin/products/${categoryProducts[0].id}`, {
          featured_preview_ids: featuredIds,
        });
      }

      toast.success(
        `Urutan 3 produk beranda untuk "${category.name}" berhasil disimpan!`
      );
      if (onSaved) onSaved();
      onClose();
    } catch (err) {
      toast.error(
        err.response?.data?.detail || "Gagal menyimpan urutan produk beranda"
      );
    } finally {
      setSaving(false);
    }
  };

  // Filter available previews by search
  const filteredPreviews = allPreviews.filter((p) => {
    if (!searchQuery.trim()) return true;
    const query = searchQuery.toLowerCase();
    return (
      (p.title && p.title.toLowerCase().includes(query)) ||
      (p.subtitle && p.subtitle.toLowerCase().includes(query)) ||
      (p.category && p.category.toLowerCase().includes(query))
    );
  });

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-3 sm:p-4 backdrop-blur-xs overflow-y-auto">
      <div className="my-auto w-full max-w-3xl rounded-2xl border border-[#E5DCC5] bg-white shadow-xl flex flex-col max-h-[92vh]">
        {/* Modal Header */}
        <div className="flex items-start justify-between border-b border-[#F1EBE0] p-4 sm:p-5">
          <div>
            <div className="inline-flex items-center gap-1.5 rounded-full bg-[#8B5A2B]/10 px-2.5 py-0.5 text-[11px] font-semibold text-[#8B5A2B]">
              <Sparkles size={12} /> Tampilan Beranda
            </div>
            <h2 className="mt-1 font-heading text-lg sm:text-xl font-bold text-[#2C1E16]">
              Atur 3 Produk Beranda: {category.name}
            </h2>
            <p className="mt-0.5 text-xs text-[#8B7355]">
              Tentukan 3 variasi/produk dan urutannya (Slot 1, 2, 3) yang akan
              tampil di homepage kategori ini.
            </p>
          </div>
          <button
            onClick={onClose}
            className="rounded-lg p-1 text-[#8B7355] hover:bg-[#F5EFEB] hover:text-[#2C1E16]"
          >
            <X size={20} />
          </button>
        </div>

        {/* Modal Body */}
        <div className="flex-1 overflow-y-auto p-4 sm:p-5 space-y-5">
          {/* Active 3 Slots Section */}
          <div className="rounded-2xl border border-[#E5DCC5] bg-[#FBF9F4] p-3.5 sm:p-4">
            <div className="flex items-center justify-between gap-2 mb-3">
              <span className="font-heading text-xs sm:text-sm font-bold text-[#2C1E16] flex items-center gap-1.5">
                <Eye size={15} className="text-[#8B5A2B]" /> 3 Produk Tampil di
                Beranda ({selectedSlots.length}/3 Terisi)
              </span>
              <button
                type="button"
                onClick={handleResetDefault}
                className="inline-flex items-center gap-1 text-[11px] font-medium text-[#8B5A2B] hover:underline"
              >
                <RotateCcw size={12} /> Reset ke Otomatis
              </button>
            </div>

            <div className="grid gap-2.5 sm:grid-cols-3">
              {[0, 1, 2].map((slotIdx) => {
                const item = selectedSlots[slotIdx];
                return (
                  <div
                    key={slotIdx}
                    className={`relative flex flex-col justify-between rounded-xl border p-2.5 transition-all ${
                      item
                        ? "border-[#8B5A2B]/40 bg-white shadow-xs"
                        : "border-dashed border-[#D5C7B0] bg-[#F5EFEB]/50 text-center"
                    }`}
                  >
                    {item ? (
                      <>
                        <div className="flex items-start gap-2.5">
                          <div className="relative h-14 w-12 shrink-0 overflow-hidden rounded-lg border border-[#E5DCC5] bg-stone-100">
                            <img
                              src={imgUrl(item.image)}
                              alt={item.title}
                              className="h-full w-full object-cover"
                            />
                            <div className="absolute top-0 left-0 bg-[#8B5A2B] text-white text-[10px] font-bold px-1.5 py-0.2 rounded-br">
                              #{slotIdx + 1}
                            </div>
                          </div>

                          <div className="min-w-0 flex-1">
                            <span className="inline-block text-[10px] font-bold text-[#8B5A2B]">
                              Slot {slotIdx + 1}{" "}
                              {slotIdx === 0
                                ? "(Utama)"
                                : slotIdx === 1
                                ? "(Kedua)"
                                : "(Ketiga)"}
                            </span>
                            <div className="text-xs font-semibold text-[#2C1E16] line-clamp-2 leading-tight">
                              {item.subtitle || item.title}
                            </div>
                            <div className="mt-0.5 text-xs font-bold text-[#8B5A2B]">
                              {fmtLE(item.price)} LE
                            </div>
                          </div>

                          <button
                            type="button"
                            onClick={() => removeSlot(slotIdx)}
                            className="text-stone-400 hover:text-red-600 p-0.5"
                            title="Hapus dari slot"
                          >
                            <X size={15} />
                          </button>
                        </div>

                        {/* Position controls */}
                        <div className="mt-2.5 flex items-center justify-between border-t border-[#F1EBE0] pt-1.5">
                          <span className="text-[10px] text-[#8B7355]">
                            Ganti Urutan:
                          </span>
                          <div className="flex items-center gap-1">
                            <button
                              type="button"
                              onClick={() => moveSlot(slotIdx, -1)}
                              disabled={slotIdx === 0}
                              className="rounded border border-[#E5DCC5] p-1 text-[#8B5A2B] hover:bg-[#F5EFEB] disabled:opacity-25"
                              title="Geser ke kiri / urutan sebelumnya"
                            >
                              <ArrowLeft size={13} />
                            </button>
                            <button
                              type="button"
                              onClick={() => moveSlot(slotIdx, 1)}
                              disabled={slotIdx === selectedSlots.length - 1}
                              className="rounded border border-[#E5DCC5] p-1 text-[#8B5A2B] hover:bg-[#F5EFEB] disabled:opacity-25"
                              title="Geser ke kanan / urutan selanjutnya"
                            >
                              <ArrowRight size={13} />
                            </button>
                          </div>
                        </div>
                      </>
                    ) : (
                      <div className="flex flex-col items-center justify-center py-4 text-[#8B7355]">
                        <div className="flex h-7 w-7 items-center justify-center rounded-full bg-[#E5DCC5] text-xs font-bold text-[#5C4A3D]">
                          {slotIdx + 1}
                        </div>
                        <span className="mt-1.5 text-xs font-medium">
                          Slot {slotIdx + 1} Kosong
                        </span>
                        <span className="text-[10px] text-[#8B7355]">
                          Pilih variasi dari daftar di bawah
                        </span>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>

          {/* All Available Variants Section */}
          <div className="space-y-3">
            <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
              <span className="font-heading text-xs sm:text-sm font-bold text-[#2C1E16] flex items-center gap-1.5">
                <Layers size={15} className="text-[#8B5A2B]" /> Semua Variasi
                Tersedia ({allPreviews.length})
              </span>

              <div className="relative w-full sm:w-64">
                <Search
                  size={14}
                  className="absolute left-2.5 top-1/2 -translate-y-1/2 text-stone-400"
                />
                <Input
                  type="text"
                  placeholder="Cari variasi / ukuran..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="h-8 pl-8 text-xs bg-white"
                />
              </div>
            </div>

            <div className="max-h-[300px] overflow-y-auto rounded-xl border border-[#E5DCC5] bg-white p-2 divide-y divide-[#F1EBE0]">
              {filteredPreviews.length === 0 ? (
                <div className="p-6 text-center text-xs text-[#8B7355]">
                  Tidak ada variasi yang cocok dengan pencarian "{searchQuery}".
                </div>
              ) : (
                filteredPreviews.map((preview) => {
                  const activeIdx = selectedSlots.findIndex(
                    (p) => p.id === preview.id
                  );
                  const isSelected = activeIdx >= 0;

                  return (
                    <div
                      key={preview.id}
                      className={`flex items-center justify-between gap-3 p-2 transition-colors rounded-lg ${
                        isSelected ? "bg-[#FAF5EE]" : "hover:bg-[#FBF9F4]"
                      }`}
                    >
                      <div className="flex items-center gap-3 min-w-0">
                        <div className="h-11 w-10 shrink-0 overflow-hidden rounded-md border border-[#E5DCC5] bg-stone-100">
                          <img
                            src={imgUrl(preview.image)}
                            alt=""
                            className="h-full w-full object-cover"
                          />
                        </div>

                        <div className="min-w-0">
                          <div className="text-xs font-semibold text-[#2C1E16] truncate">
                            {preview.subtitle || preview.title}
                          </div>
                          <div className="text-[11px] font-bold text-[#8B5A2B]">
                            {fmtLE(preview.price)} LE
                          </div>
                        </div>
                      </div>

                      <div>
                        {isSelected ? (
                          <Button
                            type="button"
                            size="sm"
                            variant="outline"
                            onClick={() => toggleSelect(preview)}
                            className="h-7 text-xs border-[#8B5A2B] bg-[#8B5A2B] text-white hover:bg-[#6B4423]"
                          >
                            <Check size={12} className="mr-1" /> Slot {activeIdx + 1}
                          </Button>
                        ) : (
                          <Button
                            type="button"
                            size="sm"
                            variant="outline"
                            onClick={() => toggleSelect(preview)}
                            className="h-7 text-xs border-[#D5C7B0] text-[#5C4A3D] hover:border-[#8B5A2B] hover:text-[#8B5A2B]"
                          >
                            + Pasang di Slot
                          </Button>
                        )}
                      </div>
                    </div>
                  );
                })
              )}
            </div>
          </div>
        </div>

        {/* Modal Footer */}
        <div className="flex items-center justify-between border-t border-[#F1EBE0] p-4 bg-[#FAF7F2] rounded-b-2xl">
          <Button
            type="button"
            variant="ghost"
            onClick={onClose}
            className="text-xs sm:text-sm text-[#5C4A3D] hover:bg-white"
          >
            Batal
          </Button>

          <Button
            type="button"
            onClick={handleSave}
            disabled={saving}
            className="rounded-xl bg-[#8B5A2B] px-5 text-xs sm:text-sm text-white hover:bg-[#6B4423]"
          >
            {saving ? "Menyimpan..." : "Simpan Urutan Beranda"}
          </Button>
        </div>
      </div>
    </div>
  );
}
