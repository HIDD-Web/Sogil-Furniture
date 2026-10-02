import React, { useEffect, useState, useMemo } from "react";
import api from "../../lib/api";
import { formatApiError, fmtLE } from "../../lib/format";
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
  ShoppingCart,
  History,
  Ban,
  Package,
  ArrowDownRight,
  ArrowUpRight,
  SlidersHorizontal,
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

const INITIAL_PURCHASE_FORM = {
  material_id: "",
  purchase_date: new Date().toISOString().slice(0, 10),
  unit_price: "",
  quantity: "",
  currency: "EGP",
  exchange_rate: "",
  supplier_name: "",
  notes: "",
};

const INITIAL_ADJUSTMENT_FORM = {
  material_id: "",
  adjustment_type: "adjustment_in",
  quantity: "",
  movement_date: new Date().toISOString().slice(0, 10),
  reason: "",
  notes: "",
};

export default function AdminMaterials() {
  const [activeTab, setActiveTab] = useState("materials"); // "materials" | "purchases" | "stock"
  const [materials, setMaterials] = useState([]);
  const [purchases, setPurchases] = useState([]);
  const [stockSummary, setStockSummary] = useState([]);
  const [loading, setLoading] = useState(true);

  // Materials filter & search
  const [search, setSearch] = useState("");
  const [categoryFilter, setCategoryFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("active");

  // Purchases filter & search
  const [purchaseSearch, setPurchaseSearch] = useState("");
  const [purchaseMaterialFilter, setPurchaseMaterialFilter] = useState("all");
  const [purchaseStatusFilter, setPurchaseStatusFilter] = useState("all"); // "all", "valid", "void"
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");

  // Stock filter & search
  const [stockSearch, setStockSearch] = useState("");
  const [stockCategoryFilter, setStockCategoryFilter] = useState("all");

  // Material Modal states
  const [modalOpen, setModalOpen] = useState(false);
  const [editingItem, setEditingItem] = useState(null);
  const [form, setForm] = useState(INITIAL_FORM);
  const [submitting, setSubmitting] = useState(false);

  // Purchase Modal states
  const [purchaseModalOpen, setPurchaseModalOpen] = useState(false);
  const [purchaseForm, setPurchaseForm] = useState(INITIAL_PURCHASE_FORM);
  const [submittingPurchase, setSubmittingPurchase] = useState(false);

  // Stock Adjustment Modal states
  const [adjustmentModalOpen, setAdjustmentModalOpen] = useState(false);
  const [adjustmentForm, setAdjustmentForm] = useState(INITIAL_ADJUSTMENT_FORM);
  const [submittingAdjustment, setSubmittingAdjustment] = useState(false);

  // Price History Modal state
  const [historyModalOpen, setHistoryModalOpen] = useState(false);
  const [historyData, setHistoryData] = useState(null);
  const [loadingHistory, setLoadingHistory] = useState(false);

  // Stock Movements Modal state
  const [movementsModalOpen, setMovementsModalOpen] = useState(false);
  const [movementsData, setMovementsData] = useState(null);
  const [loadingMovements, setLoadingMovements] = useState(false);

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

  const loadPurchases = async () => {
    try {
      const res = await api.get("/admin/materials/purchases");
      setPurchases(res.data || []);
    } catch {
      toast.error("Gagal memuat riwayat pembelian");
    }
  };

  const loadStockSummary = async () => {
    try {
      const res = await api.get("/admin/materials/stock");
      setStockSummary(res.data || []);
    } catch {
      toast.error("Gagal memuat ringkasan stok");
    }
  };

  useEffect(() => {
    loadMaterials();
    loadPurchases();
    loadStockSummary();
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
      loadStockSummary();
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
      loadStockSummary();
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail) || "Gagal mengubah status bahan");
    }
  };

  // Purchase Handlers
  const openRecordPurchaseModal = async (presetMaterial = null) => {
    let defaultRate = "357";
    try {
      const res = await api.get("/admin/settings");
      if (res.data?.exchange_rate_idr_per_le) {
        defaultRate = String(res.data.exchange_rate_idr_per_le);
      }
    } catch {
      // Keep default 357
    }
    setPurchaseForm({
      material_id: presetMaterial ? presetMaterial.id : "",
      purchase_date: new Date().toISOString().slice(0, 10),
      unit_price: "",
      quantity: "",
      currency: "EGP",
      exchange_rate: defaultRate,
      supplier_name: "",
      notes: "",
    });
    setPurchaseModalOpen(true);
  };

  const handlePurchaseSubmit = async (e) => {
    e.preventDefault();
    if (!purchaseForm.material_id) return toast.error("Pilih bahan yang dibeli");
    if (!purchaseForm.purchase_date) return toast.error("Tanggal pembelian wajib diisi");
    if (!purchaseForm.quantity || Number(purchaseForm.quantity) <= 0) return toast.error("Jumlah (quantity) harus lebih besar dari 0");
    if (purchaseForm.unit_price === "" || Number(purchaseForm.unit_price) < 0) return toast.error("Harga satuan tidak valid");

    try {
      setSubmittingPurchase(true);
      const payload = {
        material_id: purchaseForm.material_id,
        purchase_date: purchaseForm.purchase_date,
        quantity: Number(purchaseForm.quantity),
        unit_price: Number(purchaseForm.unit_price),
        currency: purchaseForm.currency || "EGP",
        exchange_rate: purchaseForm.exchange_rate ? Number(purchaseForm.exchange_rate) : undefined,
        supplier_name: purchaseForm.supplier_name.trim(),
        notes: purchaseForm.notes.trim(),
      };
      await api.post("/admin/materials/purchases", payload);
      toast.success("Pembelian bahan berhasil dicatat (Stok bertambah & Pengeluaran tercatat di Keuangan)");
      setPurchaseModalOpen(false);
      loadMaterials();
      loadPurchases();
      loadStockSummary();
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail) || "Gagal mencatat pembelian");
    } finally {
      setSubmittingPurchase(false);
    }
  };

  const handleVoidPurchase = async (purchase) => {
    const reason = window.prompt(`Masukkan alasan pembatalan (void) untuk pembelian ${purchase.purchase_number}:`);
    if (reason === null) return;

    try {
      await api.post(`/admin/materials/purchases/${purchase.id}/void`, {
        void_reason: reason.trim() || "Dibatalkan oleh admin",
      });
      toast.success("Pembelian berhasil di-void dan stok dikoreksi");
      loadPurchases();
      loadMaterials();
      loadStockSummary();
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail) || "Gagal membatalkan pembelian");
    }
  };

  // Stock Adjustment Handlers
  const openAdjustmentModal = (presetMaterial = null) => {
    setAdjustmentForm({
      material_id: presetMaterial ? presetMaterial.id : "",
      adjustment_type: "adjustment_in",
      quantity: "",
      movement_date: new Date().toISOString().slice(0, 10),
      reason: "",
      notes: "",
    });
    setAdjustmentModalOpen(true);
  };

  const handleAdjustmentSubmit = async (e) => {
    e.preventDefault();
    if (!adjustmentForm.material_id) return toast.error("Pilih bahan yang disesuaikan");
    if (!adjustmentForm.quantity || Number(adjustmentForm.quantity) <= 0) return toast.error("Jumlah penyesuaian harus lebih besar dari 0");
    if (!adjustmentForm.reason.trim()) return toast.error("Alasan penyesuaian stok wajib diisi");

    try {
      setSubmittingAdjustment(true);
      const payload = {
        adjustment_type: adjustmentForm.adjustment_type,
        quantity: Number(adjustmentForm.quantity),
        movement_date: adjustmentForm.movement_date,
        reason: adjustmentForm.reason.trim(),
        notes: adjustmentForm.notes.trim(),
      };
      await api.post(`/admin/materials/${adjustmentForm.material_id}/stock-adjustment`, payload);
      toast.success("Penyesuaian stok berhasil disimpan");
      setAdjustmentModalOpen(false);
      loadMaterials();
      loadStockSummary();
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail) || "Gagal menyesuaikan stok");
    } finally {
      setSubmittingAdjustment(false);
    }
  };

  const openPriceHistoryModal = async (material) => {
    try {
      setLoadingHistory(true);
      setHistoryModalOpen(true);
      const res = await api.get(`/admin/materials/${material.id}/price-history`);
      setHistoryData(res.data);
    } catch {
      toast.error("Gagal memuat riwayat harga");
      setHistoryModalOpen(false);
    } finally {
      setLoadingHistory(false);
    }
  };

  const openMovementsModal = async (material) => {
    try {
      setLoadingMovements(true);
      setMovementsModalOpen(true);
      const res = await api.get(`/admin/materials/${material.id}/stock-movements`);
      setMovementsData(res.data);
    } catch {
      toast.error("Gagal memuat riwayat pergerakan stok");
      setMovementsModalOpen(false);
    } finally {
      setLoadingMovements(false);
    }
  };

  const filteredMaterials = useMemo(() => {
    return materials.filter((m) => {
      if (categoryFilter !== "all" && m.category !== categoryFilter) return false;
      if (statusFilter !== "all" && m.status !== statusFilter) return false;
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

  const filteredPurchases = useMemo(() => {
    return purchases.filter((p) => {
      if (purchaseMaterialFilter !== "all" && p.material_id !== purchaseMaterialFilter) return false;
      if (purchaseStatusFilter === "valid" && p.is_void) return false;
      if (purchaseStatusFilter === "void" && !p.is_void) return false;
      if (startDate && p.purchase_date < startDate) return false;
      if (endDate && p.purchase_date > endDate) return false;
      if (purchaseSearch.trim()) {
        const q = purchaseSearch.toLowerCase();
        const matchNo = (p.purchase_number || "").toLowerCase().includes(q);
        const matchName = (p.material_name_snapshot || "").toLowerCase().includes(q);
        const matchSpecs = (p.material_specs_snapshot || "").toLowerCase().includes(q);
        const matchSupplier = (p.supplier_name || "").toLowerCase().includes(q);
        if (!matchNo && !matchName && !matchSpecs && !matchSupplier) return false;
      }
      return true;
    });
  }, [purchases, purchaseMaterialFilter, purchaseStatusFilter, startDate, endDate, purchaseSearch]);

  const filteredStock = useMemo(() => {
    return stockSummary.filter((m) => {
      if (stockCategoryFilter !== "all" && m.category !== stockCategoryFilter) return false;
      if (stockSearch.trim()) {
        const q = stockSearch.toLowerCase();
        const matchName = (m.name || "").toLowerCase().includes(q);
        const matchSpecs = (m.specs || "").toLowerCase().includes(q);
        const matchSku = (m.sku || "").toLowerCase().includes(q);
        if (!matchName && !matchSpecs && !matchSku) return false;
      }
      return true;
    });
  }, [stockSummary, stockCategoryFilter, stockSearch]);

  const selectedPurchaseMaterial = useMemo(() => {
    return materials.find((m) => m.id === purchaseForm.material_id);
  }, [materials, purchaseForm.material_id]);

  const selectedAdjustmentMaterial = useMemo(() => {
    return materials.find((m) => m.id === adjustmentForm.material_id);
  }, [materials, adjustmentForm.material_id]);

  const purchaseEstimatedTotal = useMemo(() => {
    const q = Number(purchaseForm.quantity) || 0;
    const p = Number(purchaseForm.unit_price) || 0;
    return Math.round(q * p * 100) / 100;
  }, [purchaseForm.quantity, purchaseForm.unit_price]);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="font-heading text-2xl font-bold text-[#2C1E16] flex items-center gap-2">
            <Layers className="text-[#8B5A2B]" size={26} />
            Data Bahan & Stok
          </h1>
          <p className="mt-1 text-sm text-[#8B7355]">
            Kelola master data bahan baku, catat pembelian, pantau riwayat harga, dan kendalikan stok bahan Sogil Furniture.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button
            onClick={() => openRecordPurchaseModal()}
            data-testid="record-purchase-btn"
            className="rounded-xl bg-[#8B5A2B] hover:bg-[#6B4423] text-white shadow-sm flex items-center gap-1.5"
          >
            <ShoppingCart size={17} /> Catat Pembelian
          </Button>
          <Button
            onClick={() => openAdjustmentModal()}
            data-testid="stock-adjustment-btn"
            variant="outline"
            className="rounded-xl border-[#E5DCC5] bg-white text-[#5C4A3D] hover:bg-[#EFE6D5] flex items-center gap-1.5"
          >
            <SlidersHorizontal size={17} /> Penyesuaian Stok
          </Button>
          <Button
            onClick={openAddModal}
            data-testid="add-material-btn"
            variant="outline"
            className="rounded-xl border-[#E5DCC5] text-[#5C4A3D] hover:bg-[#EFE6D5] flex items-center gap-1.5"
          >
            <Plus size={17} /> Tambah Bahan
          </Button>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex border-b border-[#E5DCC5] overflow-x-auto">
        <button
          type="button"
          onClick={() => setActiveTab("materials")}
          className={`flex items-center gap-2 px-5 py-3 text-sm font-semibold border-b-2 transition whitespace-nowrap ${
            activeTab === "materials"
              ? "border-[#8B5A2B] text-[#8B5A2B] bg-white rounded-t-xl"
              : "border-transparent text-[#8B7355] hover:text-[#2C1E16]"
          }`}
          data-testid="tab-materials"
        >
          <Layers size={17} />
          Master Data Bahan ({materials.length})
        </button>
        <button
          type="button"
          onClick={() => setActiveTab("stock")}
          className={`flex items-center gap-2 px-5 py-3 text-sm font-semibold border-b-2 transition whitespace-nowrap ${
            activeTab === "stock"
              ? "border-[#8B5A2B] text-[#8B5A2B] bg-white rounded-t-xl"
              : "border-transparent text-[#8B7355] hover:text-[#2C1E16]"
          }`}
          data-testid="tab-stock"
        >
          <Package size={17} />
          Stok Bahan ({stockSummary.length})
        </button>
        <button
          type="button"
          onClick={() => setActiveTab("purchases")}
          className={`flex items-center gap-2 px-5 py-3 text-sm font-semibold border-b-2 transition whitespace-nowrap ${
            activeTab === "purchases"
              ? "border-[#8B5A2B] text-[#8B5A2B] bg-white rounded-t-xl"
              : "border-transparent text-[#8B7355] hover:text-[#2C1E16]"
          }`}
          data-testid="tab-purchases"
        >
          <ShoppingCart size={17} />
          Riwayat Pembelian ({purchases.length})
        </button>
      </div>

      {/* TAB 1: MASTER DATA BAHAN */}
      {activeTab === "materials" && (
        <>
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
                      <th className="px-4 py-3 font-semibold">Stok Saat Ini</th>
                      <th className="px-4 py-3 font-semibold">Harga Terakhir</th>
                      <th className="px-4 py-3 font-semibold">SKU / Kode</th>
                      <th className="px-4 py-3 font-semibold">Status</th>
                      <th className="px-4 py-3 text-right font-semibold">Aksi</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#F1EBE0]">
                    {filteredMaterials.map((m) => {
                      const isArchived = m.status === "archived";
                      const stockVal = m.current_stock !== undefined && m.current_stock !== null ? Number(m.current_stock) : 0;
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
                          <td className="px-4 py-3 text-xs">
                            <span className={`font-bold ${stockVal > 0 ? "text-emerald-700" : "text-amber-800"}`}>
                              {stockVal} {m.unit}
                            </span>
                          </td>
                          <td className="px-4 py-3 text-xs">
                            {m.latest_price !== undefined && m.latest_price !== null ? (
                              <div>
                                <span className="font-semibold text-[#2C1E16]">
                                  {m.latest_price} {m.latest_currency || "EGP"}
                                </span>
                                <span className="text-[#8B7355] block text-[10px]">
                                  {m.latest_purchase_date}
                                </span>
                              </div>
                            ) : (
                              <span className="text-gray-400 italic">Belum ada</span>
                            )}
                          </td>
                          <td className="px-4 py-3 text-xs text-[#8B7355] font-mono">
                            {m.sku || "-"}
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
                              {!isArchived && (
                                <button
                                  type="button"
                                  onClick={() => openRecordPurchaseModal(m)}
                                  className="rounded-lg p-1.5 text-[#8B5A2B] hover:bg-[#EFE6D5] transition"
                                  title="Catat Pembelian Bahan Ini"
                                  data-testid={`buy-material-${m.id}`}
                                >
                                  <ShoppingCart size={15} />
                                </button>
                              )}
                              <button
                                type="button"
                                onClick={() => openPriceHistoryModal(m)}
                                className="rounded-lg p-1.5 text-blue-700 hover:bg-blue-50 transition"
                                title="Lihat Riwayat Harga"
                                data-testid={`history-material-${m.id}`}
                              >
                                <History size={15} />
                              </button>
                              <button
                                type="button"
                                onClick={() => openMovementsModal(m)}
                                className="rounded-lg p-1.5 text-emerald-700 hover:bg-emerald-50 transition"
                                title="Lihat Pergerakan Stok"
                                data-testid={`stock-movements-material-${m.id}`}
                              >
                                <Package size={15} />
                              </button>
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
        </>
      )}

      {/* TAB 2: STOK BAHAN (Phase 3) */}
      {activeTab === "stock" && (
        <>
          {/* Stock Filter & Search Bar */}
          <div className="rounded-2xl border border-[#E5DCC5] bg-white p-4 shadow-sm space-y-3">
            <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
              <div className="relative flex-1">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-[#8B7355]" size={16} />
                <Input
                  type="text"
                  placeholder="Cari nama bahan, spesifikasi, atau SKU..."
                  value={stockSearch}
                  onChange={(e) => setStockSearch(e.target.value)}
                  className="pl-9 bg-[#F9F6F0] border-[#E5DCC5] text-sm"
                  data-testid="search-stock-input"
                />
                {stockSearch && (
                  <button
                    onClick={() => setStockSearch("")}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
                  >
                    <X size={14} />
                  </button>
                )}
              </div>

              <div className="flex items-center gap-2">
                <div className="flex items-center gap-1.5 text-xs text-[#8B7355]">
                  <Filter size={14} />
                  <span>Kategori:</span>
                </div>
                <Select value={stockCategoryFilter} onValueChange={setStockCategoryFilter}>
                  <SelectTrigger className="h-8 w-32 text-xs bg-white border-[#E5DCC5]">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">Semua Kategori</SelectItem>
                    <SelectItem value="Material">Material</SelectItem>
                    <SelectItem value="Parts">Parts</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
          </div>

          {/* Stock Table */}
          <div className="overflow-hidden rounded-2xl border border-[#E5DCC5] bg-white shadow-sm">
            {filteredStock.length === 0 ? (
              <div className="p-12 text-center text-[#8B7355]">
                <Package className="mx-auto mb-2 opacity-30" size={36} />
                <p className="font-medium text-[#5C4A3D]">Tidak ada data stok bahan</p>
                <p className="mt-1 text-xs">Pastikan master bahan sudah terdaftar.</p>
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm" data-testid="stock-table">
                  <thead className="border-b border-[#E5DCC5] bg-[#F1EBE0] text-xs uppercase text-[#8B7355]">
                    <tr>
                      <th className="px-4 py-3 font-semibold">Nama Bahan</th>
                      <th className="px-4 py-3 font-semibold">Spesifikasi / Ukuran</th>
                      <th className="px-4 py-3 font-semibold">Kategori</th>
                      <th className="px-4 py-3 font-semibold">Stok Saat Ini</th>
                      <th className="px-4 py-3 font-semibold">Satuan</th>
                      <th className="px-4 py-3 font-semibold">Pergerakan Terakhir</th>
                      <th className="px-4 py-3 font-semibold">Status</th>
                      <th className="px-4 py-3 text-right font-semibold">Aksi</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#F1EBE0]">
                    {filteredStock.map((m) => {
                      const isArchived = m.status === "archived";
                      const stockVal = Number(m.current_stock || 0);
                      const lastMov = m.last_movement;
                      return (
                        <tr
                          key={m.id}
                          className={`hover:bg-[#FAF8F5] transition ${isArchived ? "bg-[#FAF7F2] opacity-75" : ""}`}
                          data-testid={`stock-row-${m.id}`}
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
                          <td className="px-4 py-3 font-mono text-sm">
                            <span className={`font-bold px-2 py-0.5 rounded-md ${
                              stockVal > 0
                                ? "bg-emerald-50 text-emerald-700 border border-emerald-200"
                                : "bg-gray-100 text-gray-700 border border-gray-200"
                            }`}>
                              {stockVal} {m.unit}
                            </span>
                          </td>
                          <td className="px-4 py-3 text-[#5C4A3D]">
                            {m.unit}
                          </td>
                          <td className="px-4 py-3 text-xs">
                            {lastMov ? (
                              <div>
                                <span className={`font-semibold ${lastMov.quantity_delta > 0 ? "text-emerald-700" : "text-red-700"}`}>
                                  {lastMov.quantity_delta > 0 ? `+${lastMov.quantity_delta}` : lastMov.quantity_delta} {m.unit}
                                </span>
                                <span className="text-[#8B7355] block text-[10px]">
                                  {lastMov.movement_date} · {lastMov.reason}
                                </span>
                              </div>
                            ) : (
                              <span className="text-gray-400 italic">Belum ada pergerakan</span>
                            )}
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
                              {!isArchived && (
                                <button
                                  type="button"
                                  onClick={() => openAdjustmentModal(m)}
                                  className="rounded-lg p-1.5 text-[#8B5A2B] hover:bg-[#EFE6D5] transition"
                                  title="Penyesuaian Stok"
                                  data-testid={`adjust-stock-${m.id}`}
                                >
                                  <SlidersHorizontal size={15} />
                                </button>
                              )}
                              <button
                                type="button"
                                onClick={() => openMovementsModal(m)}
                                className="rounded-lg p-1.5 text-emerald-700 hover:bg-emerald-50 transition"
                                title="Lihat Riwayat Pergerakan"
                                data-testid={`history-stock-${m.id}`}
                              >
                                <Package size={15} />
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
        </>
      )}

      {/* TAB 3: RIWAYAT PEMBELIAN */}
      {activeTab === "purchases" && (
        <>
          {/* Purchase Filters */}
          <div className="rounded-2xl border border-[#E5DCC5] bg-white p-4 shadow-sm space-y-3">
            <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
              <div className="relative flex-1">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-[#8B7355]" size={16} />
                <Input
                  type="text"
                  placeholder="Cari nomor pembelian, nama bahan, spesifikasi, atau supplier..."
                  value={purchaseSearch}
                  onChange={(e) => setPurchaseSearch(e.target.value)}
                  className="pl-9 bg-[#F9F6F0] border-[#E5DCC5] text-sm"
                  data-testid="search-purchase-input"
                />
                {purchaseSearch && (
                  <button
                    onClick={() => setPurchaseSearch("")}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
                  >
                    <X size={14} />
                  </button>
                )}
              </div>

              <div className="flex flex-wrap items-center gap-2">
                <Select value={purchaseMaterialFilter} onValueChange={setPurchaseMaterialFilter}>
                  <SelectTrigger className="h-8 w-44 text-xs bg-white border-[#E5DCC5]">
                    <SelectValue placeholder="Semua Bahan" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">Semua Bahan</SelectItem>
                    {materials.map((m) => (
                      <SelectItem key={m.id} value={m.id}>
                        {m.name} ({m.specs})
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>

                <Select value={purchaseStatusFilter} onValueChange={setPurchaseStatusFilter}>
                  <SelectTrigger className="h-8 w-28 text-xs bg-white border-[#E5DCC5]">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">Semua Status</SelectItem>
                    <SelectItem value="valid">Aktif (Valid)</SelectItem>
                    <SelectItem value="void">Void</SelectItem>
                  </SelectContent>
                </Select>

                <div className="flex items-center gap-1.5 text-xs text-[#8B7355]">
                  <Input
                    type="date"
                    value={startDate}
                    onChange={(e) => setStartDate(e.target.value)}
                    className="h-8 w-32 bg-white text-xs"
                    title="Dari Tanggal"
                  />
                  <span>-</span>
                  <Input
                    type="date"
                    value={endDate}
                    onChange={(e) => setEndDate(e.target.value)}
                    className="h-8 w-32 bg-white text-xs"
                    title="Sampai Tanggal"
                  />
                </div>
              </div>
            </div>
          </div>

          {/* Purchases Table */}
          <div className="overflow-hidden rounded-2xl border border-[#E5DCC5] bg-white shadow-sm">
            {filteredPurchases.length === 0 ? (
              <div className="p-12 text-center text-[#8B7355]">
                <ShoppingCart className="mx-auto mb-2 opacity-30" size={36} />
                <p className="font-medium text-[#5C4A3D]">Tidak ada data pembelian yang ditemukan</p>
                <p className="mt-1 text-xs">
                  Klik tombol 'Catat Pembelian' untuk mulai mencatat transaksi pembelian bahan.
                </p>
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm" data-testid="purchases-table">
                  <thead className="border-b border-[#E5DCC5] bg-[#F1EBE0] text-xs uppercase text-[#8B7355]">
                    <tr>
                      <th className="px-4 py-3 font-semibold">No. Pembelian</th>
                      <th className="px-4 py-3 font-semibold">Tanggal</th>
                      <th className="px-4 py-3 font-semibold">Bahan</th>
                      <th className="px-4 py-3 font-semibold">Harga Satuan</th>
                      <th className="px-4 py-3 font-semibold">Qty</th>
                      <th className="px-4 py-3 font-semibold">Total</th>
                      <th className="px-4 py-3 font-semibold">Supplier</th>
                      <th className="px-4 py-3 font-semibold">Status</th>
                      <th className="px-4 py-3 text-right font-semibold">Aksi</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#F1EBE0]">
                    {filteredPurchases.map((p) => {
                      return (
                        <tr
                          key={p.id}
                          className={`hover:bg-[#FAF8F5] transition ${p.is_void ? "bg-[#FAF7F2] opacity-60 line-through" : ""}`}
                          data-testid={`purchase-row-${p.id}`}
                        >
                          <td className="px-4 py-3 font-mono text-xs font-semibold text-[#8B5A2B]">
                            {p.purchase_number}
                          </td>
                          <td className="px-4 py-3 text-xs text-[#5C4A3D]">
                            {p.purchase_date}
                          </td>
                          <td className="px-4 py-3">
                            <div className="font-medium text-[#2C1E16]">
                              {p.material_name_snapshot}
                            </div>
                            <div className="text-xs text-[#8B7355] font-mono">
                              {p.material_specs_snapshot}
                            </div>
                          </td>
                          <td className="px-4 py-3 text-xs font-semibold text-[#2C1E16]">
                            {p.unit_price} {p.currency}
                          </td>
                          <td className="px-4 py-3 text-xs text-[#5C4A3D]">
                            {p.quantity} {p.unit}
                          </td>
                          <td className="px-4 py-3 text-xs font-bold text-[#8B5A2B]">
                            {p.total_amount} {p.currency}
                          </td>
                          <td className="px-4 py-3 text-xs text-[#5C4A3D]">
                            {p.supplier_name || "-"}
                          </td>
                          <td className="px-4 py-3">
                            <Badge
                              variant="outline"
                              className={
                                p.is_void
                                  ? "bg-red-50 text-red-700 border-red-200"
                                  : "bg-green-50 text-green-700 border-green-200"
                              }
                            >
                              {p.is_void ? "Void" : "Valid"}
                            </Badge>
                          </td>
                          <td className="px-4 py-3 text-right">
                            {!p.is_void ? (
                              <button
                                type="button"
                                onClick={() => handleVoidPurchase(p)}
                                className="rounded-lg p-1.5 text-red-600 hover:bg-red-50 transition"
                                title="Void / Batalkan Pembelian"
                                data-testid={`void-purchase-${p.id}`}
                              >
                                <Ban size={15} />
                              </button>
                            ) : (
                              <span className="text-[11px] text-[#8B7355] italic" title={p.void_reason || ""}>
                                Dibatalkan
                              </span>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      )}

      {/* MODAL: RECORD PURCHASE */}
      {purchaseModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-lg rounded-2xl border border-[#E5DCC5] bg-white p-6 shadow-xl">
            <div className="mb-4 flex items-center justify-between border-b border-[#E5DCC5] pb-3">
              <h2 className="font-heading text-lg font-bold text-[#2C1E16] flex items-center gap-2">
                <ShoppingCart className="text-[#8B5A2B]" size={20} />
                Catat Pembelian Bahan
              </h2>
              <button
                type="button"
                onClick={() => setPurchaseModalOpen(false)}
                disabled={submittingPurchase}
                className="text-[#8B7355] hover:text-[#2C1E16]"
              >
                <X size={20} />
              </button>
            </div>

            <form onSubmit={handlePurchaseSubmit} className="space-y-4">
              <div>
                <Label className="mb-1 block text-xs font-semibold text-[#5C4A3D]">
                  Pilih Bahan <span className="text-red-500">*</span>
                </Label>
                <Select
                  value={purchaseForm.material_id}
                  onValueChange={(val) => setPurchaseForm({ ...purchaseForm, material_id: val })}
                  required
                >
                  <SelectTrigger className="bg-white" data-testid="purchase-form-material">
                    <SelectValue placeholder="-- Pilih Bahan dari Master Data --" />
                  </SelectTrigger>
                  <SelectContent>
                    {materials
                      .filter((m) => m.status !== "archived")
                      .map((m) => (
                        <SelectItem key={m.id} value={m.id}>
                          {m.name} — {m.specs} ({m.unit})
                        </SelectItem>
                      ))}
                  </SelectContent>
                </Select>
                {selectedPurchaseMaterial && (
                  <div className="mt-1.5 flex items-center gap-2 text-xs text-[#8B7355]">
                    <Badge variant="outline" className="text-[10px] bg-[#F9F6F0]">
                      {selectedPurchaseMaterial.category}
                    </Badge>
                    <span>Satuan: <strong className="text-[#2C1E16]">{selectedPurchaseMaterial.unit}</strong></span>
                    {selectedPurchaseMaterial.latest_price !== undefined && selectedPurchaseMaterial.latest_price !== null && (
                      <span className="text-amber-700">
                        (Harga terakhir: {selectedPurchaseMaterial.latest_price} {selectedPurchaseMaterial.latest_currency})
                      </span>
                    )}
                  </div>
                )}
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <Label className="mb-1 block text-xs font-semibold text-[#5C4A3D]">
                    Tanggal Pembelian <span className="text-red-500">*</span>
                  </Label>
                  <Input
                    type="date"
                    value={purchaseForm.purchase_date}
                    onChange={(e) => setPurchaseForm({ ...purchaseForm, purchase_date: e.target.value })}
                    required
                    data-testid="purchase-form-date"
                    className="bg-white"
                  />
                </div>
                <div>
                  <Label className="mb-1 block text-xs font-semibold text-[#5C4A3D]">
                    Mata Uang
                  </Label>
                  <Select
                    value={purchaseForm.currency}
                    onValueChange={(val) => setPurchaseForm({ ...purchaseForm, currency: val })}
                  >
                    <SelectTrigger className="bg-white" data-testid="purchase-form-currency">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="EGP">EGP (Egyptian Pound)</SelectItem>
                      <SelectItem value="IDR">IDR (Rupiah)</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              </div>

              <div>
                <Label className="mb-1 block text-xs font-semibold text-[#5C4A3D]">
                  Kurs Nilai Tukar (1 EGP ke IDR)
                </Label>
                <Input
                  type="number"
                  step="any"
                  min="1"
                  placeholder="357"
                  value={purchaseForm.exchange_rate}
                  onChange={(e) => setPurchaseForm({ ...purchaseForm, exchange_rate: e.target.value })}
                  data-testid="purchase-form-rate"
                  className="bg-white"
                />
                <span className="mt-1 block text-[10px] text-[#8B7355]">
                  Default dari Pengaturan Toko. Dapat disesuaikan jika transaksi menggunakan kurs berbeda.
                </span>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <Label className="mb-1 block text-xs font-semibold text-[#5C4A3D]">
                    Jumlah (Quantity) <span className="text-red-500">*</span>
                  </Label>
                  <Input
                    type="number"
                    step="any"
                    min="0.0001"
                    placeholder={selectedPurchaseMaterial ? `Dalam ${selectedPurchaseMaterial.unit}` : "0"}
                    value={purchaseForm.quantity}
                    onChange={(e) => setPurchaseForm({ ...purchaseForm, quantity: e.target.value })}
                    required
                    data-testid="purchase-form-qty"
                    className="bg-white"
                  />
                </div>
                <div>
                  <Label className="mb-1 block text-xs font-semibold text-[#5C4A3D]">
                    Harga Satuan ({purchaseForm.currency}) <span className="text-red-500">*</span>
                  </Label>
                  <Input
                    type="number"
                    step="any"
                    min="0"
                    placeholder="0"
                    value={purchaseForm.unit_price}
                    onChange={(e) => setPurchaseForm({ ...purchaseForm, unit_price: e.target.value })}
                    required
                    data-testid="purchase-form-unit-price"
                    className="bg-white"
                  />
                </div>
              </div>

              {/* Total Calculation Preview */}
              <div className="rounded-xl border border-[#E5DCC5] bg-[#FAF8F5] p-3 flex items-center justify-between">
                <span className="text-xs text-[#8B7355] font-medium">Estimasi Total Pembelian:</span>
                <span className="text-base font-bold text-[#8B5A2B]">
                  {purchaseEstimatedTotal} {purchaseForm.currency}
                </span>
              </div>

              <div>
                <Label className="mb-1 block text-xs font-semibold text-[#5C4A3D]">
                  Nama Toko / Supplier (Opsional)
                </Label>
                <Input
                  type="text"
                  placeholder="Contoh: Toko Kayu Barokah, Al-Nasr Baut"
                  value={purchaseForm.supplier_name}
                  onChange={(e) => setPurchaseForm({ ...purchaseForm, supplier_name: e.target.value })}
                  data-testid="purchase-form-supplier"
                  className="bg-white text-xs"
                />
              </div>

              <div>
                <Label className="mb-1 block text-xs font-semibold text-[#5C4A3D]">
                  Catatan (Opsional)
                </Label>
                <Textarea
                  placeholder="Catatan pembelian, nomor nota fisik, grade bahan, dll..."
                  value={purchaseForm.notes}
                  onChange={(e) => setPurchaseForm({ ...purchaseForm, notes: e.target.value })}
                  rows={2}
                  data-testid="purchase-form-notes"
                  className="bg-white text-xs"
                />
              </div>

              <div className="mt-6 flex items-center justify-end gap-2 border-t border-[#E5DCC5] pt-4">
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => setPurchaseModalOpen(false)}
                  disabled={submittingPurchase}
                  className="rounded-xl border-[#E5DCC5]"
                >
                  Batal
                </Button>
                <Button
                  type="submit"
                  disabled={submittingPurchase}
                  data-testid="submit-purchase-btn"
                  className="rounded-xl bg-[#8B5A2B] hover:bg-[#6B4423] text-white"
                >
                  {submittingPurchase ? "Menyimpan..." : "Simpan Pembelian"}
                </Button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* MODAL: STOCK ADJUSTMENT (Phase 3) */}
      {adjustmentModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-lg rounded-2xl border border-[#E5DCC5] bg-white p-6 shadow-xl">
            <div className="mb-4 flex items-center justify-between border-b border-[#E5DCC5] pb-3">
              <h2 className="font-heading text-lg font-bold text-[#2C1E16] flex items-center gap-2">
                <SlidersHorizontal className="text-[#8B5A2B]" size={20} />
                Penyesuaian Stok Bahan
              </h2>
              <button
                type="button"
                onClick={() => setAdjustmentModalOpen(false)}
                disabled={submittingAdjustment}
                className="text-[#8B7355] hover:text-[#2C1E16]"
              >
                <X size={20} />
              </button>
            </div>

            <form onSubmit={handleAdjustmentSubmit} className="space-y-4">
              <div>
                <Label className="mb-1 block text-xs font-semibold text-[#5C4A3D]">
                  Pilih Bahan <span className="text-red-500">*</span>
                </Label>
                <Select
                  value={adjustmentForm.material_id}
                  onValueChange={(val) => setAdjustmentForm({ ...adjustmentForm, material_id: val })}
                  required
                >
                  <SelectTrigger className="bg-white" data-testid="adjustment-form-material">
                    <SelectValue placeholder="-- Pilih Bahan --" />
                  </SelectTrigger>
                  <SelectContent>
                    {materials
                      .filter((m) => m.status !== "archived")
                      .map((m) => (
                        <SelectItem key={m.id} value={m.id}>
                          {m.name} — {m.specs} ({m.unit})
                        </SelectItem>
                      ))}
                  </SelectContent>
                </Select>
                {selectedAdjustmentMaterial && (
                  <div className="mt-1.5 text-xs text-[#8B7355]">
                    Stok sistem saat ini: <strong className="text-emerald-700">{selectedAdjustmentMaterial.current_stock || 0} {selectedAdjustmentMaterial.unit}</strong>
                  </div>
                )}
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <Label className="mb-1 block text-xs font-semibold text-[#5C4A3D]">
                    Tipe Penyesuaian <span className="text-red-500">*</span>
                  </Label>
                  <Select
                    value={adjustmentForm.adjustment_type}
                    onValueChange={(val) => setAdjustmentForm({ ...adjustmentForm, adjustment_type: val })}
                  >
                    <SelectTrigger className="bg-white" data-testid="adjustment-form-type">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="adjustment_in">Penyesuaian Masuk (+)</SelectItem>
                      <SelectItem value="adjustment_out">Penyesuaian Keluar (-)</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div>
                  <Label className="mb-1 block text-xs font-semibold text-[#5C4A3D]">
                    Jumlah (Qty) <span className="text-red-500">*</span>
                  </Label>
                  <Input
                    type="number"
                    step="any"
                    min="0.0001"
                    placeholder="0"
                    value={adjustmentForm.quantity}
                    onChange={(e) => setAdjustmentForm({ ...adjustmentForm, quantity: e.target.value })}
                    required
                    data-testid="adjustment-form-qty"
                    className="bg-white"
                  />
                </div>
              </div>

              <div>
                <Label className="mb-1 block text-xs font-semibold text-[#5C4A3D]">
                  Tanggal Penyesuaian <span className="text-red-500">*</span>
                </Label>
                <Input
                  type="date"
                  value={adjustmentForm.movement_date}
                  onChange={(e) => setAdjustmentForm({ ...adjustmentForm, movement_date: e.target.value })}
                  required
                  data-testid="adjustment-form-date"
                  className="bg-white"
                />
              </div>

              <div>
                <Label className="mb-1 block text-xs font-semibold text-[#5C4A3D]">
                  Alasan Penyesuaian <span className="text-red-500">*</span>
                </Label>
                <Input
                  type="text"
                  placeholder="Contoh: Selisih opname fisik, Rusak/Afkir, Sisa proyek"
                  value={adjustmentForm.reason}
                  onChange={(e) => setAdjustmentForm({ ...adjustmentForm, reason: e.target.value })}
                  required
                  data-testid="adjustment-form-reason"
                  className="bg-white text-xs"
                />
              </div>

              <div>
                <Label className="mb-1 block text-xs font-semibold text-[#5C4A3D]">
                  Catatan Tambahan (Opsional)
                </Label>
                <Textarea
                  placeholder="Keterangan lebih lanjut mengenai penyesuaian stok ini..."
                  value={adjustmentForm.notes}
                  onChange={(e) => setAdjustmentForm({ ...adjustmentForm, notes: e.target.value })}
                  rows={2}
                  data-testid="adjustment-form-notes"
                  className="bg-white text-xs"
                />
              </div>

              <div className="mt-6 flex items-center justify-end gap-2 border-t border-[#E5DCC5] pt-4">
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => setAdjustmentModalOpen(false)}
                  disabled={submittingAdjustment}
                  className="rounded-xl border-[#E5DCC5]"
                >
                  Batal
                </Button>
                <Button
                  type="submit"
                  disabled={submittingAdjustment}
                  data-testid="submit-adjustment-btn"
                  className="rounded-xl bg-[#8B5A2B] hover:bg-[#6B4423] text-white"
                >
                  {submittingAdjustment ? "Menyimpan..." : "Simpan Penyesuaian"}
                </Button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* MODAL: STOCK MOVEMENTS (Phase 3) */}
      {movementsModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-2xl rounded-2xl border border-[#E5DCC5] bg-white p-6 shadow-xl">
            <div className="mb-4 flex items-center justify-between border-b border-[#E5DCC5] pb-3">
              <div>
                <h2 className="font-heading text-lg font-bold text-[#2C1E16] flex items-center gap-2">
                  <Package className="text-[#8B5A2B]" size={20} />
                  Riwayat Pergerakan Stok
                </h2>
                {movementsData?.material && (
                  <p className="text-xs text-[#8B7355] mt-0.5">
                    {movementsData.material.name} — {movementsData.material.specs} (Stok Saat Ini: <strong>{movementsData.material.current_stock || 0} {movementsData.material.unit}</strong>)
                  </p>
                )}
              </div>
              <button
                type="button"
                onClick={() => setMovementsModalOpen(false)}
                className="text-[#8B7355] hover:text-[#2C1E16]"
              >
                <X size={20} />
              </button>
            </div>

            {loadingMovements ? (
              <div className="p-8 text-center text-[#8B7355]">Memuat riwayat pergerakan...</div>
            ) : !movementsData?.movements || movementsData.movements.length === 0 ? (
              <div className="p-8 text-center text-[#8B7355]">
                <Package className="mx-auto mb-2 opacity-30" size={32} />
                <p className="font-medium text-[#5C4A3D]">Belum ada pergerakan stok untuk bahan ini</p>
                <p className="mt-1 text-xs">Pergerakan stok dicatat otomatis saat ada pembelian atau penyesuaian manual.</p>
              </div>
            ) : (
              <div className="max-h-96 overflow-y-auto">
                <table className="w-full text-left text-sm" data-testid="stock-movements-table">
                  <thead className="border-b border-[#E5DCC5] bg-[#F1EBE0] text-xs uppercase text-[#8B7355] sticky top-0">
                    <tr>
                      <th className="px-3 py-2">Tanggal</th>
                      <th className="px-3 py-2">Tipe</th>
                      <th className="px-3 py-2">Perubahan</th>
                      <th className="px-3 py-2">Sebelum</th>
                      <th className="px-3 py-2">Sesudah</th>
                      <th className="px-3 py-2">Keterangan</th>
                      <th className="px-3 py-2">No. Pergerakan</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#F1EBE0]">
                    {movementsData.movements.map((m) => {
                      const isPositive = m.quantity_delta > 0;
                      return (
                        <tr key={m.id} className="hover:bg-[#FAF8F5] text-xs">
                          <td className="px-3 py-2 font-medium text-[#2C1E16]">
                            {m.movement_date}
                          </td>
                          <td className="px-3 py-2">
                            <Badge
                              variant="outline"
                              className={`text-[10px] ${
                                m.movement_type === "purchase_in"
                                  ? "bg-blue-50 text-blue-700 border-blue-200"
                                  : isPositive
                                  ? "bg-emerald-50 text-emerald-700 border-emerald-200"
                                  : "bg-red-50 text-red-700 border-red-200"
                              }`}
                            >
                              {m.movement_type === "purchase_in"
                                ? "Pembelian"
                                : isPositive
                                ? "Penyesuaian (+)"
                                : "Penyesuaian (-)"}
                            </Badge>
                          </td>
                          <td className="px-3 py-2 font-bold font-mono">
                            <span className={isPositive ? "text-emerald-700" : "text-red-700"}>
                              {isPositive ? `+${m.quantity_delta}` : m.quantity_delta} {m.unit}
                            </span>
                          </td>
                          <td className="px-3 py-2 text-[#5C4A3D] font-mono">
                            {m.previous_stock}
                          </td>
                          <td className="px-3 py-2 font-semibold text-[#2C1E16] font-mono">
                            {m.new_stock}
                          </td>
                          <td className="px-3 py-2 text-[#5C4A3D] max-w-xs truncate" title={m.reason}>
                            {m.reason}
                          </td>
                          <td className="px-3 py-2 font-mono text-[11px] text-[#8B7355]">
                            {m.movement_number}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}

            <div className="mt-6 flex items-center justify-end border-t border-[#E5DCC5] pt-4">
              <Button
                type="button"
                onClick={() => setMovementsModalOpen(false)}
                className="rounded-xl bg-[#8B5A2B] hover:bg-[#6B4423] text-white"
              >
                Tutup
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* MODAL: PRICE HISTORY */}
      {historyModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-2xl rounded-2xl border border-[#E5DCC5] bg-white p-6 shadow-xl">
            <div className="mb-4 flex items-center justify-between border-b border-[#E5DCC5] pb-3">
              <div>
                <h2 className="font-heading text-lg font-bold text-[#2C1E16] flex items-center gap-2">
                  <History className="text-[#8B5A2B]" size={20} />
                  Riwayat Harga Pembelian
                </h2>
                {historyData?.material && (
                  <p className="text-xs text-[#8B7355] mt-0.5">
                    {historyData.material.name} — {historyData.material.specs} ({historyData.material.unit})
                  </p>
                )}
              </div>
              <button
                type="button"
                onClick={() => setHistoryModalOpen(false)}
                className="text-[#8B7355] hover:text-[#2C1E16]"
              >
                <X size={20} />
              </button>
            </div>

            {loadingHistory ? (
              <div className="p-8 text-center text-[#8B7355]">Memuat riwayat...</div>
            ) : !historyData?.history || historyData.history.length === 0 ? (
              <div className="p-8 text-center text-[#8B7355]">
                <History className="mx-auto mb-2 opacity-30" size={32} />
                <p className="font-medium text-[#5C4A3D]">Belum ada riwayat pembelian untuk bahan ini</p>
                <p className="mt-1 text-xs">Klik 'Catat Pembelian' untuk mencatat transaksi pertama.</p>
              </div>
            ) : (
              <div className="max-h-96 overflow-y-auto">
                <table className="w-full text-left text-sm" data-testid="price-history-table">
                  <thead className="border-b border-[#E5DCC5] bg-[#F1EBE0] text-xs uppercase text-[#8B7355] sticky top-0">
                    <tr>
                      <th className="px-3 py-2">Tanggal</th>
                      <th className="px-3 py-2">Harga Satuan</th>
                      <th className="px-3 py-2">Qty</th>
                      <th className="px-3 py-2">Total</th>
                      <th className="px-3 py-2">Supplier</th>
                      <th className="px-3 py-2">No. Pembelian</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#F1EBE0]">
                    {historyData.history.map((h, idx) => (
                      <tr key={h.id} className="hover:bg-[#FAF8F5] text-xs">
                        <td className="px-3 py-2 font-medium text-[#2C1E16]">
                          {h.purchase_date}
                          {idx === 0 && (
                            <Badge variant="outline" className="ml-2 text-[9px] bg-green-50 text-green-700 border-green-200">
                              Terbaru
                            </Badge>
                          )}
                        </td>
                        <td className="px-3 py-2 font-bold text-[#8B5A2B]">
                          {h.unit_price} {h.currency}
                        </td>
                        <td className="px-3 py-2 text-[#5C4A3D]">
                          {h.quantity} {h.unit}
                        </td>
                        <td className="px-3 py-2 font-semibold text-[#2C1E16]">
                          {h.total_amount} {h.currency}
                        </td>
                        <td className="px-3 py-2 text-[#5C4A3D]">
                          {h.supplier_name || "-"}
                        </td>
                        <td className="px-3 py-2 font-mono text-[11px] text-[#8B7355]">
                          {h.purchase_number}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            <div className="mt-6 flex items-center justify-end border-t border-[#E5DCC5] pt-4">
              <Button
                type="button"
                onClick={() => setHistoryModalOpen(false)}
                className="rounded-xl bg-[#8B5A2B] hover:bg-[#6B4423] text-white"
              >
                Tutup
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* MODAL: ADD / EDIT MATERIAL MASTER */}
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
