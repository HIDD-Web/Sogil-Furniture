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
  Scissors,
  Boxes,
  Trash2,
  Split,
  Shapes,
  FileText,
  ChevronDown,
  ChevronUp,
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

const INITIAL_TRANSFORMATION_OUTPUT = {
  form_source: "new", // "new" | "existing"
  existing_form_id: "",
  form_type: "standard",
  label: "",
  width: "",
  length: "",
  thickness: "",
  dimension_unit: "cm",
  quantity: "",
  stock_unit: "",
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
  enable_precut: false,
  processed_quantity: "",
  precut_outputs: [{ ...INITIAL_TRANSFORMATION_OUTPUT }],
};

const INITIAL_ADJUSTMENT_FORM = {
  material_id: "",
  stock_form_id: "",
  adjustment_type: "adjustment_in",
  quantity: "",
  movement_date: new Date().toISOString().slice(0, 10),
  reason: "",
  notes: "",
};

const INITIAL_STOCK_FORM = {
  form_type: "standard",
  width: "",
  length: "",
  thickness: "",
  dimension_unit: "cm",
  stock_unit: "",
  label: "",
  notes: "",
};

const INITIAL_TRANSFORMATION_FORM = {
  material_id: "",
  transformation_date: new Date().toISOString().slice(0, 10),
  source_stock_form_id: "",
  source_quantity: "",
  outputs: [{ ...INITIAL_TRANSFORMATION_OUTPUT }],
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

  // Phase 5: Transformations list & filters
  const [transformations, setTransformations] = useState([]);
  const [transformationSearch, setTransformationSearch] = useState("");
  const [transformationMaterialFilter, setTransformationMaterialFilter] = useState("all");
  const [transformationStartDate, setTransformationStartDate] = useState("");
  const [transformationEndDate, setTransformationEndDate] = useState("");

  // Phase 5: Stock Forms Modal states
  const [stockFormsModalOpen, setStockFormsModalOpen] = useState(false);
  const [selectedStockFormMaterial, setSelectedStockFormMaterial] = useState(null);
  const [stockFormsList, setStockFormsList] = useState([]);
  const [loadingStockForms, setLoadingStockForms] = useState(false);
  const [newStockFormOpen, setNewStockFormOpen] = useState(false);
  const [newStockForm, setNewStockForm] = useState(INITIAL_STOCK_FORM);
  const [submittingStockForm, setSubmittingStockForm] = useState(false);

  // Phase 5: Stock Transformation Modal states
  const [transformationModalOpen, setTransformationModalOpen] = useState(false);
  const [transformationForm, setTransformationForm] = useState(INITIAL_TRANSFORMATION_FORM);
  const [submittingTransformation, setSubmittingTransformation] = useState(false);
  const [availableSourceForms, setAvailableSourceForms] = useState([]);
  const [loadingSourceForms, setLoadingSourceForms] = useState(false);

  // Phase 5: Transformation Detail Modal state
  const [transformationDetailModalOpen, setTransformationDetailModalOpen] = useState(false);
  const [selectedTransformationDetail, setSelectedTransformationDetail] = useState(null);
  const [loadingTransformationDetail, setLoadingTransformationDetail] = useState(false);

  // Phase 5: Stock Forms for Adjustment Modal
  const [adjustmentStockForms, setAdjustmentStockForms] = useState([]);
  const [loadingAdjustmentStockForms, setLoadingAdjustmentStockForms] = useState(false);

  // Expanded stock forms per material in main tables: { [materialId]: boolean }
  const [expandedStockForms, setExpandedStockForms] = useState({});

  const loadMaterials = async () => {
    try {
      setLoading(true);
      const res = await api.get("/admin/materials");
      setMaterials(Array.isArray(res.data) ? res.data : []);
    } catch (err) {
      if (err?.name === "CanceledError" || err?.code === "ERR_CANCELED") return;
      console.error("Error loading materials:", err);
      toast.error(formatApiError(err?.response?.data?.detail) || "Gagal memuat data bahan");
    } finally {
      setLoading(false);
    }
  };

  const loadPurchases = async () => {
    try {
      const res = await api.get("/admin/materials/purchases");
      setPurchases(Array.isArray(res.data) ? res.data : []);
    } catch (err) {
      if (err?.name === "CanceledError" || err?.code === "ERR_CANCELED") return;
      console.error("Error loading purchases:", err);
      toast.error(formatApiError(err?.response?.data?.detail) || "Gagal memuat riwayat pembelian");
    }
  };

  const loadStockSummary = async () => {
    try {
      const res = await api.get("/admin/materials/stock");
      setStockSummary(Array.isArray(res.data) ? res.data : []);
    } catch (err) {
      if (err?.name === "CanceledError" || err?.code === "ERR_CANCELED") return;
      console.error("Error loading stock summary:", err);
      toast.error(formatApiError(err?.response?.data?.detail) || "Gagal memuat ringkasan stok");
    }
  };

  const loadTransformations = async () => {
    try {
      const res = await api.get("/admin/materials/stock-transformations");
      setTransformations(Array.isArray(res.data) ? res.data : []);
    } catch (err) {
      if (err?.name === "CanceledError" || err?.code === "ERR_CANCELED") return;
      console.error("Error loading stock transformations:", err);
      toast.error(formatApiError(err?.response?.data?.detail) || "Gagal memuat riwayat transformasi stok");
    }
  };

  useEffect(() => {
    loadMaterials();
    loadPurchases();
    loadStockSummary();
    loadTransformations();
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
      enable_precut: false,
      processed_quantity: "",
      precut_outputs: [{ ...INITIAL_TRANSFORMATION_OUTPUT, stock_unit: presetMaterial?.unit || "pcs" }],
    });
    setPurchaseModalOpen(true);
  };

  const handlePurchaseSubmit = async (e) => {
    e.preventDefault();
    if (!purchaseForm.material_id) return toast.error("Pilih bahan yang dibeli");
    if (!purchaseForm.purchase_date) return toast.error("Tanggal pembelian wajib diisi");
    if (!purchaseForm.quantity || Number(purchaseForm.quantity) <= 0) return toast.error("Jumlah (quantity) harus lebih besar dari 0");
    if (purchaseForm.unit_price === "" || Number(purchaseForm.unit_price) < 0) return toast.error("Harga satuan tidak valid");

    if (purchaseForm.enable_precut) {
      const procQ = Number(purchaseForm.processed_quantity || 0);
      if (procQ <= 0) {
        return toast.error("Jumlah bahan yang dipotong langsung (pre-cut) harus lebih besar dari 0");
      }
      if (procQ > Number(purchaseForm.quantity)) {
        return toast.error("Jumlah dipotong langsung tidak boleh melebihi jumlah pembelian");
      }
      const validOuts = (purchaseForm.precut_outputs || []).filter(o => Number(o.quantity) > 0);
      if (validOuts.length === 0) {
        return toast.error("Tambahkan minimal 1 bentuk hasil potong dengan jumlah > 0");
      }
    }

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

      if (purchaseForm.enable_precut && Number(purchaseForm.processed_quantity) > 0) {
        payload.stock_processing = {
          mode: "pre_cut",
          processed_quantity: Number(purchaseForm.processed_quantity),
          outputs: purchaseForm.precut_outputs.filter(o => Number(o.quantity) > 0).map(o => ({
            form_type: o.form_type || "standard",
            label: (o.label || "").trim(),
            width: o.width ? Number(o.width) : undefined,
            length: o.length ? Number(o.length) : undefined,
            thickness: o.thickness ? Number(o.thickness) : undefined,
            dimension_unit: o.dimension_unit || "cm",
            quantity: Number(o.quantity),
            stock_unit: o.stock_unit || selectedPurchaseMaterial?.unit || "pcs",
            notes: (o.notes || "").trim(),
          })),
        };
      }

      await api.post("/admin/materials/purchases", payload);
      toast.success("Pembelian bahan berhasil dicatat (Stok bertambah & Pengeluaran tercatat di Keuangan)");
      setPurchaseModalOpen(false);
      loadMaterials();
      loadPurchases();
      loadStockSummary();
      loadTransformations();
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
      loadTransformations();
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail) || "Gagal membatalkan pembelian");
    }
  };

  // Stock Adjustment Handlers
  const openAdjustmentModal = async (presetMaterial = null, presetStockForm = null) => {
    const matId = presetMaterial ? presetMaterial.id : "";
    const sfId = presetStockForm ? presetStockForm.id : "";
    setAdjustmentForm({
      material_id: matId,
      stock_form_id: sfId,
      adjustment_type: "adjustment_in",
      quantity: "",
      movement_date: new Date().toISOString().slice(0, 10),
      reason: presetStockForm ? "Stok Awal Fisik" : "",
      notes: "",
      _lockedStockForm: !!presetStockForm,
      _lockedStockFormDoc: presetStockForm || null,
    });
    setAdjustmentModalOpen(true);
    if (matId) {
      loadAdjustmentForms(matId);
    } else {
      setAdjustmentStockForms([]);
    }
  };

  const loadAdjustmentForms = async (matId) => {
    try {
      setLoadingAdjustmentStockForms(true);
      const res = await api.get(`/admin/materials/${matId}/stock-forms`);
      setAdjustmentStockForms(res.data || []);
    } catch {
      setAdjustmentStockForms([]);
    } finally {
      setLoadingAdjustmentStockForms(false);
    }
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
        stock_form_id: adjustmentForm.stock_form_id || undefined,
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

  // Phase 5: Stock Forms Handlers
  const openStockFormsModal = async (material) => {
    setSelectedStockFormMaterial(material);
    setNewStockFormOpen(false);
    setNewStockForm({
      ...INITIAL_STOCK_FORM,
      stock_unit: material.unit || "pcs",
    });
    setStockFormsModalOpen(true);
    await loadStockForms(material.id);
  };

  const loadStockForms = async (matId) => {
    try {
      setLoadingStockForms(true);
      const res = await api.get(`/admin/materials/${matId}/stock-forms`);
      setStockFormsList(res.data || []);
    } catch {
      toast.error("Gagal memuat data bentuk stok bahan");
    } finally {
      setLoadingStockForms(false);
    }
  };

  const handleCreateStockForm = async (e) => {
    e.preventDefault();
    if (!selectedStockFormMaterial) return;
    try {
      setSubmittingStockForm(true);
      const payload = {
        form_type: newStockForm.form_type || "standard",
        width: newStockForm.width ? Number(newStockForm.width) : undefined,
        length: newStockForm.length ? Number(newStockForm.length) : undefined,
        thickness: newStockForm.thickness ? Number(newStockForm.thickness) : undefined,
        dimension_unit: newStockForm.dimension_unit || "cm",
        stock_unit: newStockForm.stock_unit || selectedStockFormMaterial.unit || "pcs",
        label: newStockForm.label.trim(),
        notes: newStockForm.notes.trim(),
      };
      await api.post(`/admin/materials/${selectedStockFormMaterial.id}/stock-forms`, payload);
      toast.success("Bentuk stok berhasil ditambahkan");
      setNewStockForm({
        ...INITIAL_STOCK_FORM,
        stock_unit: selectedStockFormMaterial.unit || "pcs",
      });
      setNewStockFormOpen(false);
      loadStockForms(selectedStockFormMaterial.id);
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail) || "Gagal menambahkan bentuk stok");
    } finally {
      setSubmittingStockForm(false);
    }
  };

  // Phase 5: Stock Transformations Handlers
  const openTransformationModal = async (presetMaterial = null) => {
    const matId = presetMaterial ? presetMaterial.id : "";
    setTransformationForm({
      material_id: matId,
      transformation_date: new Date().toISOString().slice(0, 10),
      source_stock_form_id: matId ? "raw" : "",
      source_quantity: "",
      outputs: [{ ...INITIAL_TRANSFORMATION_OUTPUT, stock_unit: presetMaterial?.unit || "pcs" }],
      notes: "",
    });
    setTransformationModalOpen(true);
    if (matId) {
      await loadSourceForms(matId);
    } else {
      setAvailableSourceForms([]);
    }
  };

  const loadSourceForms = async (matId) => {
    try {
      setLoadingSourceForms(true);
      const res = await api.get(`/admin/materials/${matId}/stock-forms`);
      setAvailableSourceForms(res.data || []);
    } catch {
      setAvailableSourceForms([]);
    } finally {
      setLoadingSourceForms(false);
    }
  };

  const handleTransformationSubmit = async (e) => {
    e.preventDefault();
    if (!transformationForm.material_id) return toast.error("Pilih bahan yang dipotong/ditransformasi");
    if (!transformationForm.source_stock_form_id) return toast.error("Pilih bentuk stok asal");
    if (!transformationForm.source_quantity || Number(transformationForm.source_quantity) <= 0) {
      return toast.error("Jumlah asal yang dipotong harus lebih besar dari 0");
    }
    const validOutputs = (transformationForm.outputs || []).filter(o => Number(o.quantity) > 0);
    if (validOutputs.length === 0) {
      return toast.error("Tambahkan minimal 1 bentuk hasil potong dengan jumlah > 0");
    }

    try {
      setSubmittingTransformation(true);
      const payload = {
        material_id: transformationForm.material_id,
        transformation_date: transformationForm.transformation_date,
        source_stock_form_id: transformationForm.source_stock_form_id,
        source_quantity: Number(transformationForm.source_quantity),
        outputs: validOutputs.map(o => ({
          stock_form_id: o.existing_form_id || undefined,
          form_type: o.form_type || "standard",
          label: (o.label || "").trim(),
          width: o.width ? Number(o.width) : undefined,
          length: o.length ? Number(o.length) : undefined,
          thickness: o.thickness ? Number(o.thickness) : undefined,
          dimension_unit: o.dimension_unit || "cm",
          quantity: Number(o.quantity),
          stock_unit: o.stock_unit || "pcs",
          notes: (o.notes || "").trim(),
        })),
        notes: (transformationForm.notes || "").trim(),
      };
      const res = await api.post("/admin/materials/stock-transformations", payload);
      toast.success(`Transformasi berhasil dicatat (${res.data?.transformation?.transformation_number || "Sukses"})`);
      setTransformationModalOpen(false);
      loadMaterials();
      loadStockSummary();
      loadTransformations();
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail) || "Gagal mencatat transformasi");
    } finally {
      setSubmittingTransformation(false);
    }
  };

  const openTransformationDetail = async (tr) => {
    try {
      setLoadingTransformationDetail(true);
      setTransformationDetailModalOpen(true);
      const res = await api.get(`/admin/materials/stock-transformations/${tr.id || tr.transformation_number}`);
      setSelectedTransformationDetail(res.data);
    } catch {
      toast.error("Gagal memuat detail transformasi");
      setSelectedTransformationDetail(tr);
    } finally {
      setLoadingTransformationDetail(false);
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

  const filteredTransformations = useMemo(() => {
    return transformations.filter((t) => {
      if (transformationMaterialFilter !== "all" && t.material_id !== transformationMaterialFilter) {
        return false;
      }
      if (transformationStartDate && t.transformation_date < transformationStartDate) {
        return false;
      }
      if (transformationEndDate && t.transformation_date > transformationEndDate) {
        return false;
      }
      if (transformationSearch.trim()) {
        const q = transformationSearch.toLowerCase();
        const num = (t.transformation_number || "").toLowerCase();
        const mat = (t.material_name_snapshot || "").toLowerCase();
        const reason = (t.reason || "").toLowerCase();
        const pb = (t.related_purchase_number || "").toLowerCase();
        if (!num.includes(q) && !mat.includes(q) && !reason.includes(q) && !pb.includes(q)) {
          return false;
        }
      }
      return true;
    });
  }, [transformations, transformationMaterialFilter, transformationStartDate, transformationEndDate, transformationSearch]);

  const selectedPurchaseMaterial = useMemo(() => {
    return materials.find((m) => m.id === purchaseForm.material_id);
  }, [materials, purchaseForm.material_id]);

  const selectedAdjustmentMaterial = useMemo(() => {
    return materials.find((m) => m.id === adjustmentForm.material_id);
  }, [materials, adjustmentForm.material_id]);

  const selectedTransformationMaterial = useMemo(() => {
    return materials.find((m) => m.id === transformationForm.material_id);
  }, [materials, transformationForm.material_id]);

  const selectedSourceStockForm = useMemo(() => {
    if (transformationForm.source_stock_form_id === "raw") {
      return {
        id: "raw",
        form_type: "raw",
        label: "Stok Mentah Utuh",
        current_quantity: selectedTransformationMaterial?.current_stock || 0,
        stock_unit: selectedTransformationMaterial?.unit || "lembar",
      };
    }
    return availableSourceForms.find((sf) => sf.id === transformationForm.source_stock_form_id);
  }, [availableSourceForms, transformationForm.source_stock_form_id, selectedTransformationMaterial]);

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
            onClick={() => openTransformationModal()}
            data-testid="stock-transformation-btn"
            variant="outline"
            className="rounded-xl border-[#E5DCC5] bg-white text-[#5C4A3D] hover:bg-[#EFE6D5] flex items-center gap-1.5"
          >
            <Scissors size={17} /> Transformasi Stok
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
        <button
          type="button"
          onClick={() => setActiveTab("transformations")}
          className={`flex items-center gap-2 px-5 py-3 text-sm font-semibold border-b-2 transition whitespace-nowrap ${
            activeTab === "transformations"
              ? "border-[#8B5A2B] text-[#8B5A2B] bg-white rounded-t-xl"
              : "border-transparent text-[#8B7355] hover:text-[#2C1E16]"
          }`}
          data-testid="tab-transformations"
        >
          <Scissors size={17} />
          Transformasi Stok ({transformations.length})
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
                            <div>
                              <span className={`font-bold ${stockVal > 0 ? "text-emerald-700" : "text-amber-800"}`}>
                                {stockVal} {m.unit}
                              </span>
                              {m.stock_forms && m.stock_forms.filter((sf) => sf.form_type !== "raw").length > 0 && (
                                <div className="mt-1">
                                  <button
                                    type="button"
                                    onClick={() => setExpandedStockForms((prev) => ({ ...prev, [m.id]: !prev[m.id] }))}
                                    className="inline-flex items-center gap-1 text-[11px] font-medium text-[#8B5A2B] hover:text-[#5C4A3D] bg-amber-50 hover:bg-amber-100 border border-amber-200 rounded px-1.5 py-0.5 transition"
                                  >
                                    <Scissors size={10} />
                                    <span>
                                      {m.stock_forms.filter((sf) => sf.form_type !== "raw").length} potong
                                    </span>
                                    {expandedStockForms[m.id] ? <ChevronUp size={10} /> : <ChevronDown size={10} />}
                                  </button>
                                  {expandedStockForms[m.id] && (
                                    <div className="mt-1.5 space-y-1 pl-1 border-l-2 border-amber-300">
                                      {m.stock_forms
                                        .filter((sf) => sf.form_type !== "raw")
                                        .map((sf) => (
                                          <div key={sf.id} className="text-[10px] text-[#5C4A3D] flex items-center justify-between gap-2 py-0.5">
                                            <span className="truncate max-w-[140px]" title={sf.label || sf.form_type}>
                                              • {sf.label || (sf.width && sf.length ? `${sf.length}×${sf.width} ${sf.dimension_unit}` : sf.form_type)}:
                                            </span>
                                            <span className={`font-semibold shrink-0 ${Number(sf.current_quantity || 0) > 0 ? "text-emerald-700" : "text-gray-400"}`}>
                                              {sf.current_quantity || 0} {sf.stock_unit}
                                            </span>
                                          </div>
                                        ))}
                                    </div>
                                  )}
                                </div>
                              )}
                            </div>
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
                                <>
                                  <button
                                    type="button"
                                    onClick={() => openRecordPurchaseModal(m)}
                                    className="rounded-lg p-1.5 text-[#8B5A2B] hover:bg-[#EFE6D5] transition"
                                    title="Catat Pembelian Bahan Ini"
                                    data-testid={`buy-material-${m.id}`}
                                  >
                                    <ShoppingCart size={15} />
                                  </button>
                                  <button
                                    type="button"
                                    onClick={() => openStockFormsModal(m)}
                                    className="rounded-lg p-1.5 text-purple-700 hover:bg-purple-50 transition"
                                    title="Kelola Bentuk Stok (Stock Forms)"
                                    data-testid={`stock-forms-material-${m.id}`}
                                  >
                                    <Boxes size={15} />
                                  </button>
                                  <button
                                    type="button"
                                    onClick={() => openTransformationModal(m)}
                                    className="rounded-lg p-1.5 text-amber-700 hover:bg-amber-50 transition"
                                    title="Transformasi / Potong Bahan Ini"
                                    data-testid={`transform-material-${m.id}`}
                                  >
                                    <Scissors size={15} />
                                  </button>
                                </>
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
                            <div>
                              <span className={`font-bold px-2 py-0.5 rounded-md inline-block ${
                                stockVal > 0
                                  ? "bg-emerald-50 text-emerald-700 border border-emerald-200"
                                  : "bg-gray-100 text-gray-700 border border-gray-200"
                              }`}>
                                {stockVal} {m.unit}
                              </span>
                              {m.stock_forms && m.stock_forms.filter((sf) => sf.form_type !== "raw").length > 0 && (
                                <div className="mt-1 font-sans">
                                  <button
                                    type="button"
                                    onClick={() => setExpandedStockForms((prev) => ({ ...prev, [m.id]: !prev[m.id] }))}
                                    className="inline-flex items-center gap-1 text-[11px] font-medium text-[#8B5A2B] hover:text-[#5C4A3D] bg-amber-50 hover:bg-amber-100 border border-amber-200 rounded px-1.5 py-0.5 transition"
                                  >
                                    <Scissors size={10} />
                                    <span>
                                      {m.stock_forms.filter((sf) => sf.form_type !== "raw").length} potong
                                    </span>
                                    {expandedStockForms[m.id] ? <ChevronUp size={10} /> : <ChevronDown size={10} />}
                                  </button>
                                  {expandedStockForms[m.id] && (
                                    <div className="mt-1.5 space-y-1 pl-1 border-l-2 border-amber-300">
                                      {m.stock_forms
                                        .filter((sf) => sf.form_type !== "raw")
                                        .map((sf) => (
                                          <div key={sf.id} className="text-[10px] text-[#5C4A3D] flex items-center justify-between gap-2 py-0.5">
                                            <span className="truncate max-w-[140px]" title={sf.label || sf.form_type}>
                                              • {sf.label || (sf.width && sf.length ? `${sf.length}×${sf.width} ${sf.dimension_unit}` : sf.form_type)}:
                                            </span>
                                            <span className={`font-semibold shrink-0 ${Number(sf.current_quantity || 0) > 0 ? "text-emerald-700" : "text-gray-400"}`}>
                                              {sf.current_quantity || 0} {sf.stock_unit}
                                            </span>
                                          </div>
                                        ))}
                                    </div>
                                  )}
                                </div>
                              )}
                            </div>
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
                                <>
                                  <button
                                    type="button"
                                    onClick={() => openStockFormsModal(m)}
                                    className="rounded-lg p-1.5 text-purple-700 hover:bg-purple-50 transition"
                                    title="Kelola Bentuk Stok"
                                    data-testid={`stock-forms-tab-stock-${m.id}`}
                                  >
                                    <Boxes size={15} />
                                  </button>
                                  <button
                                    type="button"
                                    onClick={() => openTransformationModal(m)}
                                    className="rounded-lg p-1.5 text-amber-700 hover:bg-amber-50 transition"
                                    title="Transformasi / Potong Bahan"
                                    data-testid={`transform-tab-stock-${m.id}`}
                                  >
                                    <Scissors size={15} />
                                  </button>
                                  <button
                                    type="button"
                                    onClick={() => openAdjustmentModal(m)}
                                    className="rounded-lg p-1.5 text-[#8B5A2B] hover:bg-[#EFE6D5] transition"
                                    title="Penyesuaian Stok"
                                    data-testid={`adjust-stock-${m.id}`}
                                  >
                                    <SlidersHorizontal size={15} />
                                  </button>
                                </>
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

      {/* TAB 4: TRANSFORMASI STOK (Phase 5) */}
      {activeTab === "transformations" && (
        <>
          {/* Transformation Filters */}
          <div className="rounded-2xl border border-[#E5DCC5] bg-white p-4 shadow-sm space-y-3">
            <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
              <div className="relative flex-1">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-[#8B7355]" size={16} />
                <Input
                  type="text"
                  placeholder="Cari nomor transformasi (TR-...), nama bahan, alasan, atau nomor pembelian..."
                  value={transformationSearch}
                  onChange={(e) => setTransformationSearch(e.target.value)}
                  className="pl-9 bg-[#F9F6F0] border-[#E5DCC5] text-sm"
                  data-testid="search-transformation-input"
                />
              </div>

              <div className="flex flex-wrap items-center gap-2">
                <Select
                  value={transformationMaterialFilter}
                  onValueChange={setTransformationMaterialFilter}
                >
                  <SelectTrigger className="w-[180px] bg-[#F9F6F0] border-[#E5DCC5] text-xs">
                    <SelectValue placeholder="Filter Bahan" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">Semua Bahan</SelectItem>
                    {materials.map((m) => (
                      <SelectItem key={m.id} value={m.id}>
                        {m.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>

                <div className="flex items-center gap-1.5">
                  <Input
                    type="date"
                    value={transformationStartDate}
                    onChange={(e) => setTransformationStartDate(e.target.value)}
                    className="w-[130px] bg-[#F9F6F0] border-[#E5DCC5] text-xs"
                    title="Tanggal Mulai"
                  />
                  <span className="text-xs text-[#8B7355]">s/d</span>
                  <Input
                    type="date"
                    value={transformationEndDate}
                    onChange={(e) => setTransformationEndDate(e.target.value)}
                    className="w-[130px] bg-[#F9F6F0] border-[#E5DCC5] text-xs"
                    title="Tanggal Akhir"
                  />
                </div>

                {(transformationSearch || transformationMaterialFilter !== "all" || transformationStartDate || transformationEndDate) && (
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={() => {
                      setTransformationSearch("");
                      setTransformationMaterialFilter("all");
                      setTransformationStartDate("");
                      setTransformationEndDate("");
                    }}
                    className="text-xs text-[#8B5A2B] hover:bg-[#FAF7F2]"
                  >
                    Reset
                  </Button>
                )}
              </div>
            </div>
          </div>

          {/* Transformation Table */}
          <div className="rounded-2xl border border-[#E5DCC5] bg-white overflow-hidden shadow-sm">
            <div className="px-5 py-4 border-b border-[#E5DCC5] flex items-center justify-between">
              <div>
                <h3 className="font-heading font-bold text-[#2C1E16]">
                  Riwayat Transformasi & Pemotongan Bahan
                </h3>
                <p className="text-xs text-[#8B7355] mt-0.5">
                  Daftar seluruh perubahan bentuk fisik bahan (pemotongan, pembuatan komponen, sisa potongan).
                </p>
              </div>
              <Button
                type="button"
                onClick={() => openTransformationModal()}
                data-testid="create-transformation-btn"
                className="rounded-xl bg-[#8B5A2B] hover:bg-[#6B4423] text-white text-xs h-9 px-3 flex items-center gap-1.5"
              >
                <Scissors size={14} /> Catat Transformasi
              </Button>
            </div>

            {filteredTransformations.length === 0 ? (
              <div className="p-8 text-center text-[#8B7355] space-y-2">
                <Scissors className="mx-auto text-[#C8B89E]" size={36} />
                <p className="font-medium text-sm">Belum ada riwayat transformasi stok</p>
                <p className="text-xs max-w-sm mx-auto">
                  Transformasi stok terjadi saat pemotongan lembaran/batang menjadi ukuran komponen tertentu atau saat pre-cut pembelian.
                </p>
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm" data-testid="transformations-table">
                  <thead className="bg-[#F9F6F0] text-xs font-semibold text-[#8B7355] uppercase border-b border-[#E5DCC5]">
                    <tr>
                      <th className="px-4 py-3">No. Transformasi</th>
                      <th className="px-4 py-3">Tanggal</th>
                      <th className="px-4 py-3">Bahan</th>
                      <th className="px-4 py-3">Bentuk Asal (Dipotong)</th>
                      <th className="px-4 py-3">Hasil Bentuk Output</th>
                      <th className="px-4 py-3">Alasan / Referensi</th>
                      <th className="px-4 py-3">Operator</th>
                      <th className="px-4 py-3 text-right">Aksi</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#E5DCC5]">
                    {filteredTransformations.map((tr) => (
                      <tr key={tr.id} className="hover:bg-[#FAF8F5] transition" data-testid={`transformation-row-${tr.id}`}>
                        <td className="px-4 py-3 font-mono font-semibold text-xs text-[#8B5A2B]">
                          {tr.transformation_number}
                        </td>
                        <td className="px-4 py-3 text-xs text-[#5C4A3D]">
                          {tr.transformation_date}
                        </td>
                        <td className="px-4 py-3">
                          <div className="font-medium text-[#2C1E16] text-xs">{tr.material_name_snapshot}</div>
                          <div className="text-[10px] text-[#8B7355] font-mono">{tr.material_specs_snapshot}</div>
                        </td>
                        <td className="px-4 py-3 text-xs">
                          <span className="font-bold text-red-700">
                            -{tr.source_quantity} {tr.source_stock_unit || ""}
                          </span>
                          <span className="block text-[10px] text-[#8B7355]">
                            {tr.source_stock_form_id ? "Dari stok form" : "Bentuk asal"}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-xs">
                          <div className="flex flex-wrap gap-1 max-w-xs">
                            {(tr.output_stock_forms || []).map((out, idx) => (
                              <Badge
                                key={idx}
                                variant="outline"
                                className={`text-[10px] ${
                                  out.form_type === "custom"
                                    ? "bg-purple-50 text-purple-800 border-purple-200"
                                    : "bg-emerald-50 text-emerald-800 border-emerald-200"
                                }`}
                              >
                                +{out.quantity} {out.stock_unit || "pcs"} ({out.label || `${out.dimensions?.length || ""}x${out.dimensions?.width || ""}`})
                              </Badge>
                            ))}
                          </div>
                        </td>
                        <td className="px-4 py-3 text-xs text-[#5C4A3D]">
                          {tr.related_purchase_number ? (
                            <div>
                              <Badge variant="outline" className="bg-blue-50 text-blue-700 border-blue-200 text-[10px]">
                                Pre-cut {tr.related_purchase_number}
                              </Badge>
                              <span className="block text-[10px] text-[#8B7355] mt-0.5">{tr.reason}</span>
                            </div>
                          ) : (
                            <span>{tr.reason || "-"}</span>
                          )}
                        </td>
                        <td className="px-4 py-3 text-xs text-[#8B7355]">
                          {tr.created_by_name || "Admin"}
                        </td>
                        <td className="px-4 py-3 text-right">
                          <button
                            type="button"
                            onClick={() => openTransformationDetail(tr)}
                            className="rounded-lg p-1.5 text-blue-700 hover:bg-blue-50 transition"
                            title="Lihat Detail Transformasi"
                            data-testid={`view-transformation-${tr.id}`}
                          >
                            <FileText size={15} />
                          </button>
                        </td>
                      </tr>
                    ))}
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
          <div className="w-full max-w-2xl max-h-[90vh] overflow-y-auto rounded-2xl border border-[#E5DCC5] bg-white p-6 shadow-xl">
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

              {/* PRE-CUT / STOCK PROCESSING (Phase 5) */}
              <div className="rounded-xl border border-[#E5DCC5] bg-[#FAF8F5] p-3 space-y-3">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <input
                      type="checkbox"
                      id="enable-precut"
                      checked={purchaseForm.enable_precut || false}
                      onChange={(e) => {
                        const checked = e.target.checked;
                        setPurchaseForm({
                          ...purchaseForm,
                          enable_precut: checked,
                          processed_quantity: checked ? (purchaseForm.processed_quantity || purchaseForm.quantity || "") : "",
                        });
                      }}
                      className="rounded border-[#C8B89E] text-[#8B5A2B] focus:ring-[#8B5A2B] h-4 w-4"
                      data-testid="purchase-enable-precut"
                    />
                    <label htmlFor="enable-precut" className="text-xs font-bold text-[#2C1E16] cursor-pointer flex items-center gap-1.5">
                      <Scissors size={14} className="text-[#8B5A2B]" />
                      Potong Langsung / Pre-cut Saat Pembelian
                    </label>
                  </div>
                  {purchaseForm.enable_precut && (
                    <Badge variant="outline" className="bg-amber-100 text-amber-800 text-[10px]">
                      Pre-cut Aktif
                    </Badge>
                  )}
                </div>

                {purchaseForm.enable_precut && (
                  <div className="space-y-3 pt-2 border-t border-[#E5DCC5]">
                    <div>
                      <Label className="mb-1 block text-xs font-semibold text-[#5C4A3D]">
                        Jumlah Bahan yang Dipotong Langsung <span className="text-red-500">*</span>
                      </Label>
                      <Input
                        type="number"
                        step="any"
                        min="0.0001"
                        max={purchaseForm.quantity || undefined}
                        placeholder={selectedPurchaseMaterial ? `Maksimal ${purchaseForm.quantity || 0} ${selectedPurchaseMaterial.unit}` : "0"}
                        value={purchaseForm.processed_quantity || ""}
                        onChange={(e) => setPurchaseForm({ ...purchaseForm, processed_quantity: e.target.value })}
                        data-testid="purchase-processed-qty"
                        className="bg-white"
                        required={purchaseForm.enable_precut}
                      />
                      <span className="mt-1 block text-[10px] text-[#8B7355]">
                        Sisa raw: <strong className="text-emerald-700">{Math.max(0, Number(purchaseForm.quantity || 0) - Number(purchaseForm.processed_quantity || 0))} {selectedPurchaseMaterial?.unit || ""}</strong> tetap disimpan sebagai lembaran/batang utuh.
                      </span>
                    </div>

                    <div className="space-y-2">
                      <div className="flex items-center justify-between">
                        <span className="text-xs font-semibold text-[#5C4A3D]">Hasil Potongan (Output Forms):</span>
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          onClick={() => {
                            setPurchaseForm({
                              ...purchaseForm,
                              precut_outputs: [
                                ...(purchaseForm.precut_outputs || []),
                                { ...INITIAL_TRANSFORMATION_OUTPUT, stock_unit: selectedPurchaseMaterial?.unit || "pcs" }
                              ]
                            });
                          }}
                          className="h-7 text-xs px-2 text-[#8B5A2B] border-[#8B5A2B]"
                        >
                          <Plus size={12} className="mr-1" /> Tambah Ukuran Hasil
                        </Button>
                      </div>

                      {(purchaseForm.precut_outputs || []).map((out, idx) => (
                        <div key={idx} className="rounded-lg border border-[#E5DCC5] bg-white p-2.5 space-y-2 text-xs">
                          <div className="flex items-center justify-between gap-2">
                            <span className="font-semibold text-[#2C1E16]">Bentuk #{idx + 1}</span>
                            <div className="flex items-center gap-2">
                              <select
                                value={out.form_type || "standard"}
                                onChange={(e) => {
                                  const updated = [...purchaseForm.precut_outputs];
                                  updated[idx].form_type = e.target.value;
                                  setPurchaseForm({ ...purchaseForm, precut_outputs: updated });
                                }}
                                className="text-[11px] rounded border border-[#E5DCC5] bg-white px-2 py-0.5"
                              >
                                <option value="standard">Standard (Komponen)</option>
                                <option value="custom">Custom (Sisa Potong / Remnant)</option>
                              </select>
                              {purchaseForm.precut_outputs.length > 1 && (
                                <button
                                  type="button"
                                  onClick={() => {
                                    const updated = purchaseForm.precut_outputs.filter((_, i) => i !== idx);
                                    setPurchaseForm({ ...purchaseForm, precut_outputs: updated });
                                  }}
                                  className="text-red-500 hover:text-red-700"
                                >
                                  <Trash2 size={13} />
                                </button>
                              )}
                            </div>
                          </div>
                          <div className="grid grid-cols-2 gap-2">
                            <Input
                              placeholder="Label (contoh: Rak 80x30)"
                              value={out.label || ""}
                              onChange={(e) => {
                                const updated = [...purchaseForm.precut_outputs];
                                updated[idx].label = e.target.value;
                                setPurchaseForm({ ...purchaseForm, precut_outputs: updated });
                              }}
                              className="h-8 text-xs bg-white"
                            />
                            <div className="flex items-center gap-1">
                              <Input
                                type="number"
                                step="any"
                                min="0.0001"
                                placeholder="Qty"
                                value={out.quantity || ""}
                                onChange={(e) => {
                                  const updated = [...purchaseForm.precut_outputs];
                                  updated[idx].quantity = e.target.value;
                                  setPurchaseForm({ ...purchaseForm, precut_outputs: updated });
                                }}
                                className="h-8 text-xs bg-white w-20"
                                required={purchaseForm.enable_precut}
                              />
                              <Input
                                placeholder="Satuan"
                                value={out.stock_unit || selectedPurchaseMaterial?.unit || "pcs"}
                                onChange={(e) => {
                                  const updated = [...purchaseForm.precut_outputs];
                                  updated[idx].stock_unit = e.target.value;
                                  setPurchaseForm({ ...purchaseForm, precut_outputs: updated });
                                }}
                                className="h-8 text-xs bg-white"
                              />
                            </div>
                          </div>
                          <div className="grid grid-cols-4 gap-1">
                            <Input
                              type="number"
                              step="any"
                              placeholder="P (Panjang)"
                              value={out.length || ""}
                              onChange={(e) => {
                                const updated = [...purchaseForm.precut_outputs];
                                updated[idx].length = e.target.value;
                                setPurchaseForm({ ...purchaseForm, precut_outputs: updated });
                              }}
                              className="h-7 text-[11px] bg-white"
                            />
                            <Input
                              type="number"
                              step="any"
                              placeholder="L (Lebar)"
                              value={out.width || ""}
                              onChange={(e) => {
                                const updated = [...purchaseForm.precut_outputs];
                                updated[idx].width = e.target.value;
                                setPurchaseForm({ ...purchaseForm, precut_outputs: updated });
                              }}
                              className="h-7 text-[11px] bg-white"
                            />
                            <Input
                              type="number"
                              step="any"
                              placeholder="T (Tebal)"
                              value={out.thickness || ""}
                              onChange={(e) => {
                                const updated = [...purchaseForm.precut_outputs];
                                updated[idx].thickness = e.target.value;
                                setPurchaseForm({ ...purchaseForm, precut_outputs: updated });
                              }}
                              className="h-7 text-[11px] bg-white"
                            />
                            <select
                              value={out.dimension_unit || "cm"}
                              onChange={(e) => {
                                const updated = [...purchaseForm.precut_outputs];
                                updated[idx].dimension_unit = e.target.value;
                                setPurchaseForm({ ...purchaseForm, precut_outputs: updated });
                              }}
                              className="h-7 text-[11px] rounded border border-[#E5DCC5] bg-white px-1"
                            >
                              <option value="cm">cm</option>
                              <option value="mm">mm</option>
                              <option value="m">m</option>
                            </select>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
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
                  onValueChange={(val) => {
                    setAdjustmentForm({ ...adjustmentForm, material_id: val, stock_form_id: "" });
                    if (val) loadAdjustmentForms(val);
                  }}
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

              {selectedAdjustmentMaterial && (
                <div>
                  <Label className="mb-1 block text-xs font-semibold text-[#5C4A3D]">
                    Bentuk Stok Fisik {adjustmentForm._lockedStockForm ? "(Terkunci)" : "(Opsional)"}
                  </Label>
                  {adjustmentForm._lockedStockForm ? (
                    <div className="rounded-lg border border-purple-200 bg-purple-50 p-2.5 text-xs text-[#2C1E16]">
                      <div className="flex items-center justify-between">
                        <span className="font-semibold text-purple-900">
                          {adjustmentForm._lockedStockFormDoc?.label || "Bentuk Fisik Khusus"}
                        </span>
                        <Badge variant="outline" className="text-[10px] bg-white text-purple-800 border-purple-300">
                          {adjustmentForm._lockedStockFormDoc?.form_type === "custom" ? "Custom/Sisa" : "Standard"}
                        </Badge>
                      </div>
                      <div className="mt-1 flex items-center gap-2 text-[11px] text-[#5C4A3D]">
                        <span>
                          Dimensi: {adjustmentForm._lockedStockFormDoc?.length || "-"} × {adjustmentForm._lockedStockFormDoc?.width || "-"} {adjustmentForm._lockedStockFormDoc?.dimension_unit || "cm"}
                        </span>
                        <span>·</span>
                        <span>
                          Stok saat ini: <strong className="text-emerald-700">{adjustmentForm._lockedStockFormDoc?.current_quantity || 0} {adjustmentForm._lockedStockFormDoc?.stock_unit || selectedAdjustmentMaterial.unit}</strong>
                        </span>
                      </div>
                    </div>
                  ) : (
                    <>
                      <Select
                        value={adjustmentForm.stock_form_id || "all"}
                        onValueChange={(val) => setAdjustmentForm({ ...adjustmentForm, stock_form_id: val === "all" ? "" : val })}
                      >
                        <SelectTrigger className="bg-white" data-testid="adjustment-form-stock-form">
                          <SelectValue placeholder="-- Semua / Stok Agregat Bahan --" />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="all">-- Semua / Stok Agregat Bahan --</SelectItem>
                          {adjustmentStockForms.map((sf) => (
                            <SelectItem key={sf.id} value={sf.id}>
                              [{sf.form_type === "raw" ? "Raw" : sf.form_type === "custom" ? "Custom/Sisa" : "Standard"}] {sf.label || (sf.width && sf.length ? `${sf.length}×${sf.width} ${sf.dimension_unit}` : "Bentuk Stok")} — Tersisa: {sf.current_quantity || 0} {sf.stock_unit || selectedAdjustmentMaterial.unit}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      <span className="mt-1 block text-[10px] text-[#8B7355]">
                        Pilih bentuk stok tertentu jika penyesuaian opname dilakukan pada bentuk fisik spesifik.
                      </span>
                    </>
                  )}
                </div>
              )}

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
                  <div className="flex items-center gap-1.5">
                    <Input
                      type="number"
                      step="any"
                      min="0.0001"
                      placeholder="0"
                      value={adjustmentForm.quantity}
                      onChange={(e) => setAdjustmentForm({ ...adjustmentForm, quantity: e.target.value })}
                      required
                      data-testid="adjustment-form-qty"
                      className="bg-white flex-1"
                    />
                    <span className="text-xs font-semibold px-2.5 py-2 bg-[#F9F6F0] rounded-md border border-[#E5DCC5] text-[#5C4A3D]">
                      {adjustmentForm._lockedStockFormDoc?.stock_unit ||
                        adjustmentStockForms.find(sf => sf.id === adjustmentForm.stock_form_id)?.stock_unit ||
                        selectedAdjustmentMaterial?.unit ||
                        "pcs"}
                    </span>
                  </div>
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
      {/* MODAL: STOCK FORMS (Phase 5) */}
      {stockFormsModalOpen && selectedStockFormMaterial && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-2xl max-h-[90vh] overflow-y-auto rounded-2xl border border-[#E5DCC5] bg-white p-6 shadow-xl">
            <div className="mb-4 flex items-center justify-between border-b border-[#E5DCC5] pb-3">
              <div>
                <h2 className="font-heading text-lg font-bold text-[#2C1E16] flex items-center gap-2">
                  <Boxes className="text-purple-700" size={20} />
                  Bentuk Stok Fisik: {selectedStockFormMaterial.name}
                </h2>
                <div className="mt-1 flex items-center gap-2 text-xs text-[#8B7355]">
                  <span className="font-mono">{selectedStockFormMaterial.specs}</span>
                  <span>·</span>
                  <span>Total Agregat: <strong className="text-emerald-700">{selectedStockFormMaterial.current_stock || 0} {selectedStockFormMaterial.unit}</strong></span>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setStockFormsModalOpen(false)}
                className="text-[#8B7355] hover:text-[#2C1E16]"
              >
                <X size={20} />
              </button>
            </div>

            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => setNewStockFormOpen(!newStockFormOpen)}
                  className="text-xs text-[#8B5A2B] border-[#8B5A2B]"
                  data-testid="toggle-add-stock-form-btn"
                >
                  <Plus size={14} className="mr-1" />
                  {newStockFormOpen ? "Batal Tambah Bentuk" : "Tambah Bentuk Stok Baru"}
                </Button>

                <Button
                  type="button"
                  size="sm"
                  onClick={() => {
                    setStockFormsModalOpen(false);
                    openTransformationModal(selectedStockFormMaterial);
                  }}
                  className="text-xs bg-[#8B5A2B] hover:bg-[#6B4423] text-white flex items-center gap-1.5"
                  data-testid="transform-from-stock-forms-btn"
                >
                  <Scissors size={13} />
                  Transformasi Bahan Ini
                </Button>
              </div>

              {/* Inline Form to Add Stock Form */}
              {newStockFormOpen && (
                <form onSubmit={handleCreateStockForm} className="rounded-xl border border-[#E5DCC5] bg-[#FAF8F5] p-4 space-y-3">
                  <h4 className="font-semibold text-xs text-[#2C1E16]">Tambah Ukuran / Bentuk Stok Baru</h4>
                  <div className="grid grid-cols-2 gap-2">
                    <div>
                      <Label className="mb-1 block text-[11px] font-semibold text-[#5C4A3D]">Tipe Bentuk</Label>
                      <select
                        value={newStockForm.form_type}
                        onChange={(e) => setNewStockForm({ ...newStockForm, form_type: e.target.value })}
                        className="w-full text-xs rounded border border-[#E5DCC5] bg-white px-2 py-1.5"
                      >
                        <option value="standard">Standard (Ukuran Standar Komponen)</option>
                        <option value="custom">Custom (Sisa Potong / Remnant)</option>
                      </select>
                    </div>
                    <div>
                      <Label className="mb-1 block text-[11px] font-semibold text-[#5C4A3D]">Label / Nama Ukuran</Label>
                      <Input
                        placeholder="Contoh: Rak 80x30, Sisa 42x244"
                        value={newStockForm.label}
                        onChange={(e) => setNewStockForm({ ...newStockForm, label: e.target.value })}
                        className="h-8 text-xs bg-white"
                      />
                    </div>
                  </div>

                  <div className="grid grid-cols-4 gap-2">
                    <div>
                      <Label className="mb-1 block text-[11px] font-semibold text-[#5C4A3D]">Panjang</Label>
                      <Input
                        type="number"
                        step="any"
                        placeholder="P"
                        value={newStockForm.length}
                        onChange={(e) => setNewStockForm({ ...newStockForm, length: e.target.value })}
                        className="h-8 text-xs bg-white"
                      />
                    </div>
                    <div>
                      <Label className="mb-1 block text-[11px] font-semibold text-[#5C4A3D]">Lebar</Label>
                      <Input
                        type="number"
                        step="any"
                        placeholder="L"
                        value={newStockForm.width}
                        onChange={(e) => setNewStockForm({ ...newStockForm, width: e.target.value })}
                        className="h-8 text-xs bg-white"
                      />
                    </div>
                    <div>
                      <Label className="mb-1 block text-[11px] font-semibold text-[#5C4A3D]">Tebal</Label>
                      <Input
                        type="number"
                        step="any"
                        placeholder="T"
                        value={newStockForm.thickness}
                        onChange={(e) => setNewStockForm({ ...newStockForm, thickness: e.target.value })}
                        className="h-8 text-xs bg-white"
                      />
                    </div>
                    <div>
                      <Label className="mb-1 block text-[11px] font-semibold text-[#5C4A3D]">Satuan Ukuran</Label>
                      <select
                        value={newStockForm.dimension_unit}
                        onChange={(e) => setNewStockForm({ ...newStockForm, dimension_unit: e.target.value })}
                        className="w-full h-8 text-xs rounded border border-[#E5DCC5] bg-white px-2"
                      >
                        <option value="cm">cm</option>
                        <option value="mm">mm</option>
                        <option value="m">m</option>
                      </select>
                    </div>
                  </div>

                  <div className="flex items-center justify-end gap-2 pt-2">
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={() => setNewStockFormOpen(false)}
                      className="text-xs"
                    >
                      Batal
                    </Button>
                    <Button
                      type="submit"
                      disabled={submittingStockForm}
                      size="sm"
                      className="text-xs bg-[#8B5A2B] hover:bg-[#6B4423] text-white"
                    >
                      {submittingStockForm ? "Menyimpan..." : "Simpan Bentuk Stok"}
                    </Button>
                  </div>
                </form>
              )}

              {/* Stock Forms Table */}
              {loadingStockForms ? (
                <div className="py-6 text-center text-xs text-[#8B7355]">Memuat bentuk stok...</div>
              ) : stockFormsList.length === 0 ? (
                <div className="rounded-xl border border-dashed border-[#E5DCC5] p-6 text-center text-xs text-[#8B7355]">
                  Belum ada catatan bentuk fisik untuk bahan ini. Bentuk stok akan otomatis tercatat saat pembelian atau transformasi.
                </div>
              ) : (
                <div className="rounded-xl border border-[#E5DCC5] overflow-hidden">
                  <table className="w-full text-left text-xs">
                    <thead className="bg-[#F9F6F0] font-semibold text-[#8B7355] border-b border-[#E5DCC5]">
                      <tr>
                        <th className="px-3 py-2">Tipe</th>
                        <th className="px-3 py-2">Label</th>
                        <th className="px-3 py-2">Dimensi (P × L × T)</th>
                        <th className="px-3 py-2 text-right">Stok Fisik Tersedia</th>
                        <th className="px-3 py-2">Catatan</th>
                        <th className="px-3 py-2 text-center">Aksi</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-[#E5DCC5]">
                      {stockFormsList.map((sf) => (
                        <tr key={sf.id} className="hover:bg-[#FAF8F5]">
                          <td className="px-3 py-2.5">
                            <Badge
                              variant="outline"
                              className={`text-[10px] ${
                                sf.form_type === "raw"
                                  ? "bg-blue-50 text-blue-800 border-blue-200"
                                  : sf.form_type === "custom"
                                  ? "bg-purple-50 text-purple-800 border-purple-200"
                                  : "bg-emerald-50 text-emerald-800 border-emerald-200"
                              }`}
                            >
                              {sf.form_type === "raw" ? "Raw / Utuh" : sf.form_type === "custom" ? "Custom (Sisa)" : "Standard"}
                            </Badge>
                          </td>
                          <td className="px-3 py-2.5 font-medium text-[#2C1E16]">
                            {sf.label || "-"}
                          </td>
                          <td className="px-3 py-2.5 font-mono text-[#5C4A3D]">
                            {sf.length || sf.width ? (
                              <span>
                                {sf.length || "-"} × {sf.width || "-"}
                                {sf.thickness ? ` × ${sf.thickness}` : ""} {sf.dimension_unit || "cm"}
                              </span>
                            ) : (
                              <span className="text-gray-400 italic">Bentuk standar asal</span>
                            )}
                          </td>
                          <td className="px-3 py-2.5 text-right font-bold text-emerald-800">
                            {sf.current_quantity || 0} {sf.stock_unit || selectedStockFormMaterial.unit}
                          </td>
                          <td className="px-3 py-2.5 text-[#8B7355]">
                            {sf.notes || "-"}
                          </td>
                          <td className="px-3 py-2.5 text-center">
                            {sf.form_type !== "raw" ? (
                              <Button
                                type="button"
                                variant="outline"
                                size="sm"
                                onClick={() => {
                                  setStockFormsModalOpen(false);
                                  openAdjustmentModal(selectedStockFormMaterial, sf);
                                }}
                                className="h-6 text-[10px] px-2 text-[#8B5A2B] border-[#8B5A2B] hover:bg-[#FAF8F5]"
                                title="Sesuaikan stok fisik atau masukkan stok awal bentuk ini"
                                data-testid={`adjust-stock-form-${sf.id}`}
                              >
                                Sesuaikan / Stok Awal
                              </Button>
                            ) : (
                              <span className="text-[10px] text-gray-400 italic">Stok Bahan Utama</span>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>

            <div className="mt-5 flex justify-end border-t border-[#E5DCC5] pt-3">
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => setStockFormsModalOpen(false)}
                className="rounded-xl border-[#E5DCC5]"
              >
                Tutup
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* MODAL: CREATE TRANSFORMATION (Phase 5) */}
      {transformationModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-2xl max-h-[90vh] overflow-y-auto rounded-2xl border border-[#E5DCC5] bg-white p-6 shadow-xl">
            <div className="mb-4 flex items-center justify-between border-b border-[#E5DCC5] pb-3">
              <div>
                <h2 className="font-heading text-lg font-bold text-[#2C1E16] flex items-center gap-2">
                  <Scissors className="text-[#8B5A2B]" size={20} />
                  Catat Transformasi / Pemotongan Stok
                </h2>
                <p className="text-xs text-[#8B7355] mt-0.5">
                  Potong stok bentuk asal (lembaran/batang) menjadi ukuran komponen baru atau sisa potongan.
                </p>
              </div>
              <button
                type="button"
                onClick={() => setTransformationModalOpen(false)}
                disabled={submittingTransformation}
                className="text-[#8B7355] hover:text-[#2C1E16]"
              >
                <X size={20} />
              </button>
            </div>

            <form onSubmit={handleTransformationSubmit} className="space-y-4">
              {/* Material Selection */}
              <div>
                <Label className="mb-1 block text-xs font-semibold text-[#5C4A3D]">
                  Pilih Bahan <span className="text-red-500">*</span>
                </Label>
                <Select
                  value={transformationForm.material_id}
                  onValueChange={(val) => {
                    setTransformationForm({
                      ...transformationForm,
                      material_id: val,
                      source_stock_form_id: "raw",
                      outputs: [{ ...INITIAL_TRANSFORMATION_OUTPUT, stock_unit: materials.find(m => m.id === val)?.unit || "pcs" }]
                    });
                    if (val) loadSourceForms(val);
                  }}
                  required
                >
                  <SelectTrigger className="bg-white" data-testid="transformation-form-material">
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
                {selectedTransformationMaterial && (
                  <div className="mt-1 text-xs text-[#8B7355]">
                    Total Stok Bahan: <strong className="text-emerald-700">{selectedTransformationMaterial.current_stock || 0} {selectedTransformationMaterial.unit}</strong>
                  </div>
                )}
              </div>

              {/* Source Stock Form & Quantity */}
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <Label className="mb-1 block text-xs font-semibold text-[#5C4A3D]">
                    Bentuk Stok Asal yang Dipotong <span className="text-red-500">*</span>
                  </Label>
                  {loadingSourceForms ? (
                    <div className="text-xs text-[#8B7355] py-2">Memuat bentuk stok...</div>
                  ) : (
                    <Select
                      value={transformationForm.source_stock_form_id}
                      onValueChange={(val) => setTransformationForm({ ...transformationForm, source_stock_form_id: val })}
                      required
                    >
                      <SelectTrigger className="bg-white" data-testid="transformation-source-sf">
                        <SelectValue placeholder="-- Pilih Bentuk Asal --" />
                      </SelectTrigger>
                      <SelectContent>
                        {selectedTransformationMaterial && (
                          <SelectItem value="raw">
                            [Raw/Utuh] Stok Mentah Utuh ({selectedTransformationMaterial.specs || selectedTransformationMaterial.name}) (Stok: {selectedTransformationMaterial.current_stock || 0} {selectedTransformationMaterial.unit || "lembar"})
                          </SelectItem>
                        )}
                        {availableSourceForms
                          .filter((sf) => sf.form_type !== "raw")
                          .map((sf) => (
                            <SelectItem key={sf.id} value={sf.id}>
                              [{sf.form_type === "custom" ? "Custom" : "Standard"}] {sf.label || (sf.width && sf.length ? `${sf.length}×${sf.width} ${sf.dimension_unit}` : "Bentuk Stok")} (Stok: {sf.current_quantity || 0} {sf.stock_unit})
                            </SelectItem>
                          ))}
                      </SelectContent>
                    </Select>
                  )}
                  {selectedSourceStockForm && (
                    <span className="mt-1 block text-[10px] text-[#8B7355]">
                      Stok bentuk ini: <strong className="text-emerald-700">{selectedSourceStockForm.current_quantity || 0} {selectedSourceStockForm.stock_unit}</strong>
                    </span>
                  )}
                </div>

                <div>
                  <Label className="mb-1 block text-xs font-semibold text-[#5C4A3D]">
                    Jumlah Asal yang Dipotong <span className="text-red-500">*</span>
                  </Label>
                  <Input
                    type="number"
                    step="any"
                    min="0.0001"
                    placeholder="Contoh: 1, 2, 5"
                    value={transformationForm.source_quantity}
                    onChange={(e) => setTransformationForm({ ...transformationForm, source_quantity: e.target.value })}
                    required
                    data-testid="transformation-source-qty"
                    className="bg-white"
                  />
                  {selectedSourceStockForm && transformationForm.source_quantity && (
                    <span className="mt-1 block text-[10px] text-[#8B7355]">
                      Sisa setelah potong: <strong>{Math.max(0, Number(selectedSourceStockForm.current_quantity || 0) - Number(transformationForm.source_quantity || 0))} {selectedSourceStockForm.stock_unit}</strong>
                    </span>
                  )}
                </div>
              </div>

              {/* Transformation Date */}
              <div>
                <Label className="mb-1 block text-xs font-semibold text-[#5C4A3D]">
                  Tanggal Transformasi / Pemotongan <span className="text-red-500">*</span>
                </Label>
                <Input
                  type="date"
                  value={transformationForm.transformation_date}
                  onChange={(e) => setTransformationForm({ ...transformationForm, transformation_date: e.target.value })}
                  required
                  data-testid="transformation-date"
                  className="bg-white"
                />
              </div>

              {/* Output Stock Forms Builder */}
              <div className="rounded-xl border border-[#E5DCC5] bg-[#FAF8F5] p-3 space-y-3">
                <div className="flex items-center justify-between">
                  <div>
                    <h4 className="font-semibold text-xs text-[#2C1E16]">Bentuk Hasil Potongan (Outputs)</h4>
                    <span className="text-[10px] text-[#8B7355]">Tentukan satu atau lebih ukuran hasil potong (termasuk sisa jika ada).</span>
                  </div>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => {
                      setTransformationForm({
                        ...transformationForm,
                        outputs: [
                          ...(transformationForm.outputs || []),
                          { ...INITIAL_TRANSFORMATION_OUTPUT, stock_unit: selectedTransformationMaterial?.unit || "pcs" }
                        ]
                      });
                    }}
                    className="h-7 text-xs px-2 text-[#8B5A2B] border-[#8B5A2B]"
                  >
                    <Plus size={12} className="mr-1" /> Tambah Ukuran Hasil
                  </Button>
                </div>

                <div className="space-y-2">
                  {(transformationForm.outputs || []).map((out, idx) => {
                    const existingFormsList = availableSourceForms.filter((sf) => sf.form_type !== "raw");
                    const isExistingMode = out.form_source === "existing";

                    return (
                      <div key={idx} className="rounded-lg border border-[#E5DCC5] bg-white p-2.5 space-y-2.5 text-xs">
                        <div className="flex items-center justify-between gap-2 flex-wrap">
                          <div className="flex items-center gap-2">
                            <span className="font-semibold text-[#2C1E16]">Bentuk Hasil #{idx + 1}</span>
                            {/* Toggle Mode: Ukuran Baru vs Ukuran Yang Ada */}
                            {existingFormsList.length > 0 && (
                              <div className="inline-flex rounded-md border border-[#E5DCC5] bg-[#FAF8F5] p-0.5 text-[10px]">
                                <button
                                  type="button"
                                  onClick={() => {
                                    const updated = [...transformationForm.outputs];
                                    updated[idx].form_source = "existing";
                                    setTransformationForm({ ...transformationForm, outputs: updated });
                                  }}
                                  className={`px-2 py-0.5 rounded transition ${
                                    isExistingMode
                                      ? "bg-[#8B5A2B] text-white font-medium shadow-xs"
                                      : "text-[#5C4A3D] hover:text-[#2C1E16]"
                                  }`}
                                >
                                  Pilih Ukuran Yang Ada
                                </button>
                                <button
                                  type="button"
                                  onClick={() => {
                                    const updated = [...transformationForm.outputs];
                                    updated[idx].form_source = "new";
                                    setTransformationForm({ ...transformationForm, outputs: updated });
                                  }}
                                  className={`px-2 py-0.5 rounded transition ${
                                    !isExistingMode
                                      ? "bg-[#8B5A2B] text-white font-medium shadow-xs"
                                      : "text-[#5C4A3D] hover:text-[#2C1E16]"
                                  }`}
                                >
                                  Ukuran Baru
                                </button>
                              </div>
                            )}
                          </div>

                          <div className="flex items-center gap-2">
                            {!isExistingMode && (
                              <select
                                value={out.form_type || "standard"}
                                onChange={(e) => {
                                  const updated = [...transformationForm.outputs];
                                  updated[idx].form_type = e.target.value;
                                  setTransformationForm({ ...transformationForm, outputs: updated });
                                }}
                                className="text-[11px] rounded border border-[#E5DCC5] bg-white px-2 py-0.5"
                              >
                                <option value="standard">Standard (Komponen)</option>
                                <option value="custom">Custom (Sisa Potong / Remnant)</option>
                              </select>
                            )}
                            {transformationForm.outputs.length > 1 && (
                              <button
                                type="button"
                                onClick={() => {
                                  const updated = transformationForm.outputs.filter((_, i) => i !== idx);
                                  setTransformationForm({ ...transformationForm, outputs: updated });
                                }}
                                className="text-red-500 hover:text-red-700"
                              >
                                <Trash2 size={13} />
                              </button>
                            )}
                          </div>
                        </div>

                        {/* MODE A: PILIH UKURAN YANG ADA */}
                        {isExistingMode ? (
                          <div className="space-y-2 bg-[#FAF8F5] p-2 rounded border border-[#E5DCC5]">
                            <div>
                              <Label className="mb-1 block text-[11px] font-medium text-[#5C4A3D]">
                                Pilih Ukuran / Bentuk yang Sudah Ada
                              </Label>
                              <select
                                value={out.existing_form_id || ""}
                                onChange={(e) => {
                                  const selId = e.target.value;
                                  const chosen = existingFormsList.find((sf) => sf.id === selId);
                                  const updated = [...transformationForm.outputs];
                                  if (chosen) {
                                    updated[idx] = {
                                      ...updated[idx],
                                      existing_form_id: chosen.id,
                                      form_type: chosen.form_type || "standard",
                                      label: chosen.label || "",
                                      width: chosen.width ?? "",
                                      length: chosen.length ?? "",
                                      thickness: chosen.thickness ?? "",
                                      dimension_unit: chosen.dimension_unit || "cm",
                                      stock_unit: chosen.stock_unit || selectedTransformationMaterial?.unit || "pcs",
                                    };
                                  } else {
                                    updated[idx].existing_form_id = "";
                                  }
                                  setTransformationForm({ ...transformationForm, outputs: updated });
                                }}
                                className="w-full text-xs rounded border border-[#E5DCC5] bg-white px-2 py-1.5"
                              >
                                <option value="">-- Pilih Ukuran Terdaftar --</option>
                                {existingFormsList.map((sf) => (
                                  <option key={sf.id} value={sf.id}>
                                    [{sf.form_type === "custom" ? "Custom" : "Standard"}] {sf.label || (sf.width && sf.length ? `${sf.length}×${sf.width} ${sf.dimension_unit}` : "Bentuk Stok")} (Stok saat ini: {sf.current_quantity || 0} {sf.stock_unit})
                                  </option>
                                ))}
                              </select>
                            </div>

                            <div className="grid grid-cols-2 gap-2">
                              <div>
                                <Label className="mb-1 block text-[11px] font-medium text-[#5C4A3D]">
                                  Jumlah Tambahan Hasil Potong (Qty) <span className="text-red-500">*</span>
                                </Label>
                                <div className="flex items-center gap-1">
                                  <Input
                                    type="number"
                                    step="any"
                                    min="0.0001"
                                    placeholder="Qty"
                                    value={out.quantity || ""}
                                    onChange={(e) => {
                                      const updated = [...transformationForm.outputs];
                                      updated[idx].quantity = e.target.value;
                                      setTransformationForm({ ...transformationForm, outputs: updated });
                                    }}
                                    className="h-8 text-xs bg-white w-24"
                                    required
                                  />
                                  <span className="text-xs text-[#5C4A3D] font-medium px-2 py-1 bg-white rounded border border-[#E5DCC5]">
                                    {out.stock_unit || selectedTransformationMaterial?.unit || "pcs"}
                                  </span>
                                </div>
                              </div>

                              {out.existing_form_id && (
                                <div className="text-[11px] text-[#5C4A3D] self-end pb-1">
                                  <span>Dimensi: </span>
                                  <strong>
                                    {out.length && out.width ? `${out.length} × ${out.width}` : "-"}{out.thickness ? ` × ${out.thickness}` : ""} {out.dimension_unit}
                                  </strong>
                                </div>
                              )}
                            </div>
                          </div>
                        ) : (
                          /* MODE B: UKURAN / KOMPONEN BARU */
                          <div className="space-y-2">
                            <div className="grid grid-cols-2 gap-2">
                              <Input
                                placeholder="Label (contoh: Rak 80x30, Sisa 42x244)"
                                value={out.label || ""}
                                onChange={(e) => {
                                  const updated = [...transformationForm.outputs];
                                  updated[idx].label = e.target.value;
                                  setTransformationForm({ ...transformationForm, outputs: updated });
                                }}
                                className="h-8 text-xs bg-white"
                              />
                              <div className="flex items-center gap-1">
                                <Input
                                  type="number"
                                  step="any"
                                  min="0.0001"
                                  placeholder="Qty"
                                  value={out.quantity || ""}
                                  onChange={(e) => {
                                    const updated = [...transformationForm.outputs];
                                    updated[idx].quantity = e.target.value;
                                    setTransformationForm({ ...transformationForm, outputs: updated });
                                  }}
                                  className="h-8 text-xs bg-white w-20"
                                  required
                                />
                                <Input
                                  placeholder="Satuan"
                                  value={out.stock_unit || selectedTransformationMaterial?.unit || "pcs"}
                                  onChange={(e) => {
                                    const updated = [...transformationForm.outputs];
                                    updated[idx].stock_unit = e.target.value;
                                    setTransformationForm({ ...transformationForm, outputs: updated });
                                  }}
                                  className="h-8 text-xs bg-white"
                                />
                              </div>
                            </div>

                            <div className="grid grid-cols-4 gap-1">
                              <Input
                                type="number"
                                step="any"
                                placeholder="P (Panjang)"
                                value={out.length || ""}
                                onChange={(e) => {
                                  const updated = [...transformationForm.outputs];
                                  updated[idx].length = e.target.value;
                                  setTransformationForm({ ...transformationForm, outputs: updated });
                                }}
                                className="h-7 text-[11px] bg-white"
                              />
                              <Input
                                type="number"
                                step="any"
                                placeholder="L (Lebar)"
                                value={out.width || ""}
                                onChange={(e) => {
                                  const updated = [...transformationForm.outputs];
                                  updated[idx].width = e.target.value;
                                  setTransformationForm({ ...transformationForm, outputs: updated });
                                }}
                                className="h-7 text-[11px] bg-white"
                              />
                              <Input
                                type="number"
                                step="any"
                                placeholder="T (Tebal)"
                                value={out.thickness || ""}
                                onChange={(e) => {
                                  const updated = [...transformationForm.outputs];
                                  updated[idx].thickness = e.target.value;
                                  setTransformationForm({ ...transformationForm, outputs: updated });
                                }}
                                className="h-7 text-[11px] bg-white"
                              />
                              <select
                                value={out.dimension_unit || "cm"}
                                onChange={(e) => {
                                  const updated = [...transformationForm.outputs];
                                  updated[idx].dimension_unit = e.target.value;
                                  setTransformationForm({ ...transformationForm, outputs: updated });
                                }}
                                className="h-7 text-[11px] rounded border border-[#E5DCC5] bg-white px-1"
                              >
                                <option value="cm">cm</option>
                                <option value="mm">mm</option>
                                <option value="m">m</option>
                              </select>
                            </div>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>

              {/* Notes */}
              <div>
                <Label className="mb-1 block text-xs font-semibold text-[#5C4A3D]">
                  Alasan / Catatan Pemotongan
                </Label>
                <Textarea
                  placeholder="Contoh: Pemotongan untuk pesanan lemari #ORD-..., persiapan komponen rak..."
                  value={transformationForm.notes}
                  onChange={(e) => setTransformationForm({ ...transformationForm, notes: e.target.value })}
                  rows={2}
                  className="bg-white text-xs"
                />
              </div>

              <div className="mt-6 flex items-center justify-end gap-2 border-t border-[#E5DCC5] pt-4">
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => setTransformationModalOpen(false)}
                  disabled={submittingTransformation}
                  className="rounded-xl border-[#E5DCC5]"
                >
                  Batal
                </Button>
                <Button
                  type="submit"
                  disabled={submittingTransformation}
                  data-testid="submit-transformation-btn"
                  className="rounded-xl bg-[#8B5A2B] hover:bg-[#6B4423] text-white"
                >
                  {submittingTransformation ? "Menyimpan..." : "Simpan Transformasi Stok"}
                </Button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* MODAL: TRANSFORMATION DETAIL (Phase 5) */}
      {transformationDetailModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
          <div className="w-full max-w-lg rounded-2xl border border-[#E5DCC5] bg-white p-6 shadow-xl">
            <div className="mb-4 flex items-center justify-between border-b border-[#E5DCC5] pb-3">
              <div>
                <div className="flex items-center gap-2">
                  <Badge variant="outline" className="bg-amber-100 text-amber-800 font-mono text-xs">
                    {selectedTransformationDetail?.transformation_number}
                  </Badge>
                  <span className="text-xs text-[#8B7355]">
                    {selectedTransformationDetail?.transformation_date}
                  </span>
                </div>
                <h3 className="font-heading text-base font-bold text-[#2C1E16] mt-1">
                  Detail Transformasi / Pemotongan Bahan
                </h3>
              </div>
              <button
                type="button"
                onClick={() => setTransformationDetailModalOpen(false)}
                className="text-[#8B7355] hover:text-[#2C1E16]"
              >
                <X size={20} />
              </button>
            </div>

            {loadingTransformationDetail ? (
              <div className="py-6 text-center text-xs text-[#8B7355]">Memuat detail transformasi...</div>
            ) : selectedTransformationDetail ? (
              <div className="space-y-4 text-xs">
                {/* Material Info */}
                <div className="rounded-xl border border-[#E5DCC5] bg-[#FAF8F5] p-3 space-y-1.5">
                  <div className="text-[11px] text-[#8B7355] uppercase font-semibold">Bahan yang Ditransformasi</div>
                  <div className="font-bold text-sm text-[#2C1E16]">
                    {selectedTransformationDetail.material_name_snapshot}
                  </div>
                  <div className="font-mono text-[11px] text-[#5C4A3D]">
                    {selectedTransformationDetail.material_specs_snapshot}
                  </div>
                  {selectedTransformationDetail.related_purchase_number && (
                    <div className="pt-1">
                      <Badge variant="outline" className="bg-blue-50 text-blue-700 border-blue-200 text-[10px]">
                        Pre-cut Pembelian: {selectedTransformationDetail.related_purchase_number}
                      </Badge>
                    </div>
                  )}
                </div>

                {/* Source Form Deduction */}
                <div className="rounded-xl border border-red-200 bg-red-50/50 p-3 flex items-center justify-between">
                  <div>
                    <span className="block text-[11px] font-semibold text-red-800">Bahan Asal yang Terpotong / Keluar</span>
                    <span className="text-[11px] text-red-600">Dikurangkan dari bentuk stok asal</span>
                  </div>
                  <span className="font-bold text-base text-red-700 font-mono">
                    -{selectedTransformationDetail.source_quantity} {selectedTransformationDetail.source_stock_unit || ""}
                  </span>
                </div>

                {/* Output Forms */}
                <div>
                  <span className="block text-xs font-semibold text-[#5C4A3D] mb-1.5">
                    Hasil Bentuk Output yang Dihasilkan:
                  </span>
                  <div className="space-y-1.5">
                    {(selectedTransformationDetail.output_stock_forms || []).map((out, idx) => (
                      <div key={idx} className="rounded-lg border border-[#E5DCC5] p-2.5 flex items-center justify-between bg-white">
                        <div>
                          <div className="flex items-center gap-1.5">
                            <Badge
                              variant="outline"
                              className={`text-[9px] ${
                                out.form_type === "custom"
                                  ? "bg-purple-50 text-purple-800 border-purple-200"
                                  : "bg-emerald-50 text-emerald-800 border-emerald-200"
                              }`}
                            >
                              {out.form_type === "custom" ? "Custom (Sisa)" : "Standard"}
                            </Badge>
                            <span className="font-semibold text-xs text-[#2C1E16]">
                              {out.label || "Komponen"}
                            </span>
                          </div>
                          {out.dimensions && (out.dimensions.width || out.dimensions.length) && (
                            <span className="text-[10px] text-[#8B7355] font-mono mt-0.5 block">
                              Dimensi: {out.dimensions.length || "-"} × {out.dimensions.width || "-"}
                              {out.dimensions.thickness ? ` × ${out.dimensions.thickness}` : ""} {out.dimensions.unit || "cm"}
                            </span>
                          )}
                        </div>
                        <span className="font-bold text-sm text-emerald-700 font-mono">
                          +{out.quantity} {out.stock_unit || "pcs"}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Reason & Operator */}
                <div className="rounded-xl border border-[#E5DCC5] bg-white p-3 space-y-1">
                  <div className="text-[11px] text-[#8B7355]">Alasan / Catatan:</div>
                  <div className="font-medium text-[#2C1E16]">{selectedTransformationDetail.reason || "-"}</div>
                  {selectedTransformationDetail.notes && (
                    <div className="text-[11px] text-[#8B7355] italic pt-1">{selectedTransformationDetail.notes}</div>
                  )}
                  <div className="text-[10px] text-[#8B7355] pt-1 border-t border-[#E5DCC5] mt-2">
                    Dibuat oleh: {selectedTransformationDetail.created_by_name || "Admin"} · {selectedTransformationDetail.created_at?.slice(0, 19).replace("T", " ")}
                  </div>
                </div>
              </div>
            ) : null}

            <div className="mt-5 flex justify-end border-t border-[#E5DCC5] pt-3">
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => setTransformationDetailModalOpen(false)}
                className="rounded-xl border-[#E5DCC5]"
              >
                Tutup
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
