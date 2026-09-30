import React, { useEffect, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import api from "../../lib/api";
import { fmtLE, formatApiError } from "../../lib/format";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Textarea } from "../../components/ui/textarea";
import { Label } from "../../components/ui/label";
import {
  Plus,
  Trash2,
  Copy,
  ChevronLeft,
  Save,
  Send,
  Search,
  UserCheck,
  UserPlus,
  Layers,
  Sparkles,
  Info,
  Lock,
} from "lucide-react";
import { toast } from "sonner";

const emptyItem = (type = "custom") => ({
  item_id: `item_${Math.random().toString(36).substring(2, 9)}`,
  item_type: type,
  product_id: null,
  product_slug: null,
  name: "",
  description: "",
  quantity: 1,
  dimensions: {
    length: "",
    width: "",
    height: "",
    notes: "",
  },
  material: "",
  finishing: "",
  unit_price: 0,
  notes: "",
});

export default function AdminInvoiceForm() {
  const { id } = useParams();
  const [searchParams] = useSearchParams();
  const customRequestId = searchParams.get("custom_request_id");
  const isEdit = Boolean(id);
  const navigate = useNavigate();

  const [loading, setLoading] = useState(isEdit);
  const [submitting, setSubmitting] = useState(false);
  const [catalogProducts, setCatalogProducts] = useState([]);

  // Customer search state
  const [customerMode, setCustomerMode] = useState("manual"); // "search" | "manual"
  const [customerSearchQ, setCustomerSearchQ] = useState("");
  const [customerSearchResults, setCustomerSearchResults] = useState([]);
  const [searchingCustomer, setSearchingCustomer] = useState(false);

  // Form State
  const [status, setStatus] = useState("DRAFT");
  const [customer, setCustomer] = useState({
    customer_id: null,
    name: "",
    whatsapp: "",
    egypt_phone: "",
    address: "",
  });
  const [source, setSource] = useState(null);
  const [items, setItems] = useState([emptyItem("custom")]);
  const [discountAmount, setDiscountAmount] = useState(0);
  const [deliveryFee, setDeliveryFee] = useState(0);
  const [additionalFee, setAdditionalFee] = useState(0);
  const [customerNote, setCustomerNote] = useState("");
  const [internalNote, setInternalNote] = useState("");

  // Load catalog products for catalog item selection
  useEffect(() => {
    api.get("/products")
      .then((r) => setCatalogProducts(Array.isArray(r.data) ? r.data : []))
      .catch(() => {});
  }, []);

  // If in edit mode, fetch existing invoice
  useEffect(() => {
    if (!isEdit) return;
    setLoading(true);
    api.get(`/admin/invoices/${id}`)
      .then((r) => {
        const inv = r.data;
        if (inv.status === "CONVERTED" || inv.status === "CANCELLED") {
          toast.error("Invoice dengan status ini tidak dapat diubah.");
          navigate(`/admin/invoices/${id}`);
          return;
        }
        setStatus(inv.status || "DRAFT");
        setCustomer({
          customer_id: inv.customer?.customer_id || null,
          name: inv.customer?.name || "",
          whatsapp: inv.customer?.whatsapp || "",
          egypt_phone: inv.customer?.egypt_phone || "",
          address: inv.customer?.address || "",
        });
        setCustomerMode(inv.customer?.customer_id ? "search" : "manual");
        setSource(inv.source || null);
        setItems(
          (inv.items || []).map((it) => ({
            item_id: it.item_id || `item_${Math.random().toString(36).substring(2, 9)}`,
            item_type: it.item_type || "custom",
            product_id: it.product_id || null,
            product_slug: it.product_slug || null,
            name: it.name || "",
            description: it.description || "",
            quantity: Number(it.quantity) || 1,
            dimensions: {
              length: it.dimensions?.length || "",
              width: it.dimensions?.width || "",
              height: it.dimensions?.height || "",
              notes: it.dimensions?.notes || "",
            },
            material: it.material || "",
            finishing: it.finishing || "",
            unit_price: Number(it.unit_price) || 0,
            notes: it.notes || "",
          }))
        );
        setDiscountAmount(inv.discount_amount || 0);
        setDeliveryFee(inv.delivery_fee || 0);
        setAdditionalFee(inv.additional_fee || 0);
        setCustomerNote(inv.customer_note || "");
        setInternalNote(inv.internal_note || "");
      })
      .catch((err) => {
        toast.error(err.response?.data?.detail || "Gagal memuat detail invoice");
        navigate("/admin/invoices");
      })
      .finally(() => setLoading(false));
  }, [id, isEdit, navigate]);

  // If new invoice and custom_request_id provided, prefill
  useEffect(() => {
    if (isEdit || !customRequestId) return;
    api.get("/admin/custom-requests")
      .then((r) => {
        const list = Array.isArray(r.data) ? r.data : [];
        const req = list.find((x) => (x.id || x._id) === customRequestId);
        if (req) {
          setCustomer((prev) => ({
            ...prev,
            name: req.customer_name || prev.name,
            whatsapp: req.customer_phone || prev.whatsapp,
            egypt_phone: req.phone_number || prev.egypt_phone,
            address: req.customer_address || prev.address,
          }));
          setSource({ custom_request_id: customRequestId });
          const dims = req.dimensions || {};
          setItems([
            {
              item_id: `item_cr_${customRequestId.substring(0, 6)}`,
              item_type: "custom",
              product_id: null,
              product_slug: null,
              name: req.furniture_type ? `Custom ${req.furniture_type}` : "Pesanan Custom",
              description: req.notes || "",
              quantity: 1,
              dimensions: {
                length: dims.length || "",
                width: dims.width || "",
                height: dims.height || "",
                notes: dims.notes || "",
              },
              material: req.material || "",
              finishing: req.finishing || "",
              unit_price: Number(req.budget_estimation_le) || 0,
              notes: `Tiket Request: ${req.ticket_number || customRequestId}`,
            },
          ]);
          setInternalNote(`Dibuat dari Request Custom #${req.ticket_number || customRequestId}`);
          toast.info(`Data otomatis terisi dari Request Custom #${req.ticket_number || customRequestId}`);
        }
      })
      .catch(() => {});
  }, [customRequestId, isEdit]);

  // Customer search debounce
  useEffect(() => {
    if (!customerSearchQ || customerSearchQ.trim().length < 2) {
      setCustomerSearchResults([]);
      return;
    }
    const timer = setTimeout(() => {
      setSearchingCustomer(true);
      api.get("/admin/customers", { params: { q: customerSearchQ.trim() } })
        .then((r) => setCustomerSearchResults(Array.isArray(r.data) ? r.data : []))
        .catch(() => {})
        .finally(() => setSearchingCustomer(false));
    }, 300);
    return () => clearTimeout(timer);
  }, [customerSearchQ]);

  const selectCustomer = (c) => {
    setCustomer({
      customer_id: c.id || c._id,
      name: c.username || c.name || "",
      whatsapp: c.phone || "",
      egypt_phone: c.egypt_phone || "",
      address: c.address || "",
    });
    setCustomerSearchResults([]);
    setCustomerSearchQ("");
    toast.success(`Customer "${c.username || c.name}" dipilih`);
  };

  // Item helpers
  const handleItemChange = (index, field, value) => {
    setItems((prev) => {
      const next = [...prev];
      next[index] = { ...next[index], [field]: value };
      return next;
    });
  };

  const handleDimensionChange = (index, dimField, value) => {
    setItems((prev) => {
      const next = [...prev];
      next[index] = {
        ...next[index],
        dimensions: { ...next[index].dimensions, [dimField]: value },
      };
      return next;
    });
  };

  const handleProductSelect = (index, productId) => {
    const prod = catalogProducts.find((p) => (p.id || p._id) === productId);
    if (!prod) return;
    setItems((prev) => {
      const next = [...prev];
      next[index] = {
        ...next[index],
        product_id: prod.id || prod._id,
        product_slug: prod.slug || null,
        name: prod.name || next[index].name,
        unit_price: Number(prod.starting_price_le) || 0,
        description: prod.description || next[index].description,
      };
      return next;
    });
  };

  const addItem = (type = "custom") => {
    setItems((prev) => [...prev, emptyItem(type)]);
  };

  const duplicateItem = (index) => {
    setItems((prev) => {
      const target = prev[index];
      const cloned = {
        ...target,
        item_id: `item_${Math.random().toString(36).substring(2, 9)}`,
        name: `${target.name} (Salinan)`,
      };
      const next = [...prev];
      next.splice(index + 1, 0, cloned);
      return next;
    });
    toast.info("Item berhasil diduplikasi");
  };

  const removeItem = (index) => {
    if (items.length <= 1) {
      toast.error("Invoice minimal harus memiliki 1 item.");
      return;
    }
    setItems((prev) => prev.filter((_, i) => i !== index));
  };

  // Calculations
  const subtotal = items.reduce((acc, it) => {
    const q = Math.max(1, parseInt(it.quantity, 10) || 1);
    const p = Math.max(0, parseFloat(it.unit_price) || 0);
    return acc + q * p;
  }, 0);

  const discNum = Math.max(0, parseFloat(discountAmount) || 0);
  const delivNum = Math.max(0, parseFloat(deliveryFee) || 0);
  const addFeeNum = Math.max(0, parseFloat(additionalFee) || 0);
  const total = Math.max(0, subtotal - discNum + delivNum + addFeeNum);

  const handleSubmit = async (targetStatus) => {
    // Basic client validation
    if (!customer.name.trim()) {
      toast.error("Nama customer wajib diisi.");
      return;
    }
    const wa = customer.whatsapp.trim();
    if (!wa || !wa.startsWith("+")) {
      toast.error("No WhatsApp harus diawali kode negara dengan tanda + (contoh: +62812... atau +201...)");
      return;
    }

    if (items.length === 0) {
      toast.error("Invoice minimal harus memiliki 1 item.");
      return;
    }

    for (let i = 0; i < items.length; i++) {
      const it = items[i];
      if (!it.name.trim()) {
        toast.error(`Nama item ke-${i + 1} wajib diisi.`);
        return;
      }
      if (parseInt(it.quantity, 10) < 1) {
        toast.error(`Jumlah item ke-${i + 1} minimal 1.`);
        return;
      }
      if (parseFloat(it.unit_price) < 0) {
        toast.error(`Harga item ke-${i + 1} tidak boleh negatif.`);
        return;
      }
    }

    const payload = {
      status: targetStatus,
      customer: {
        customer_id: customer.customer_id || null,
        name: customer.name.trim(),
        whatsapp: customer.whatsapp.trim(),
        egypt_phone: customer.egypt_phone?.trim() || null,
        address: customer.address?.trim() || null,
      },
      source: source || null,
      items: items.map((it) => ({
        item_id: it.item_id,
        item_type: it.item_type || "custom",
        product_id: it.product_id || null,
        product_slug: it.product_slug || null,
        name: it.name.trim(),
        description: it.description?.trim() || "",
        quantity: parseInt(it.quantity, 10) || 1,
        dimensions: {
          length: it.dimensions?.length?.trim() || null,
          width: it.dimensions?.width?.trim() || null,
          height: it.dimensions?.height?.trim() || null,
          notes: it.dimensions?.notes?.trim() || null,
        },
        material: it.material?.trim() || "",
        finishing: it.finishing?.trim() || "",
        unit_price: parseFloat(it.unit_price) || 0,
        notes: it.notes?.trim() || "",
      })),
      discount_amount: discNum,
      delivery_fee: delivNum,
      additional_fee: addFeeNum,
      customer_note: customerNote.trim(),
      internal_note: internalNote.trim(),
    };

    setSubmitting(true);
    try {
      if (isEdit) {
        const { data } = await api.put(`/admin/invoices/${id}`, payload);
        if (targetStatus === "SENT" && status === "DRAFT") {
          try {
            await api.post(`/admin/invoices/${id}/send`);
            setStatus("SENT");
            toast.success("Invoice berhasil diperbarui dan ditandai Menunggu Konfirmasi");
          } catch (sendErr) {
            toast.error(
              "Data invoice berhasil disimpan, namun gagal menandai Siap Kirim: " +
              (formatApiError(sendErr.response?.data?.detail) || "Silakan coba kembali.")
            );
            return;
          }
        } else {
          toast.success("Invoice berhasil diperbarui");
        }
        navigate(`/admin/invoices/${data.id || data._id || id}`);
      } else {
        const { data } = await api.post("/admin/invoices", payload);
        toast.success(`Invoice ${data.invoice_number} berhasil dibuat!`);
        navigate(`/admin/invoices/${data.id || data._id}`);
      }
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail) || "Gagal menyimpan invoice");
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) {
    return <div className="py-16 text-center text-sm text-[#8B7355]">Memuat invoice...</div>;
  }

  return (
    <div className="max-w-4xl mx-auto space-y-6 pb-12">
      {/* Top Navigation */}
      <div className="flex items-center justify-between border-b border-[#E5DCC5] pb-4">
        <div className="flex items-center gap-3">
          <Button
            variant="outline"
            size="sm"
            onClick={() => navigate(isEdit ? `/admin/invoices/${id}` : "/admin/invoices")}
            className="h-8 rounded-lg border-[#E5DCC5] text-xs text-[#5C4A3D]"
          >
            <ChevronLeft size={15} className="mr-1" /> Kembali
          </Button>
          <h1 className="font-heading text-lg sm:text-xl font-bold text-[#2C1E16]">
            {isEdit ? "Edit Invoice" : "Buat Invoice Baru"}
          </h1>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            disabled={submitting}
            onClick={() => handleSubmit("DRAFT")}
            className="rounded-xl border-[#E5DCC5] text-xs font-semibold text-[#5C4A3D] hover:bg-[#FBF9F4]"
          >
            <Save size={14} className="mr-1.5" /> Simpan Draft
          </Button>
          <Button
            disabled={submitting}
            onClick={() => handleSubmit("SENT")}
            className="rounded-xl bg-[#8B5A2B] text-xs font-semibold text-white hover:bg-[#6B4423]"
          >
            <Send size={14} className="mr-1.5" /> Simpan & Siap Kirim
          </Button>
        </div>
      </div>

      {/* SECTION A: Customer */}
      <div className="rounded-2xl border border-[#E5DCC5] bg-white p-5 sm:p-6 shadow-xs space-y-4">
        <div className="flex items-center justify-between border-b border-[#F1EBE0] pb-3">
          <div>
            <h2 className="font-heading text-base font-bold text-[#2C1E16]">
              A. Informasi Pelanggan
            </h2>
            <p className="text-xs text-[#8B7355]">
              Snapshot data pemesan yang akan tertera pada invoice resmi
            </p>
          </div>
          <div className="flex items-center rounded-xl bg-[#FAF5EE] p-1 border border-[#E5DCC5]">
            <button
              type="button"
              onClick={() => setCustomerMode("search")}
              className={`rounded-lg px-2.5 py-1 text-xs font-medium transition-colors ${
                customerMode === "search"
                  ? "bg-[#8B5A2B] text-white shadow-xs"
                  : "text-[#5C4A3D] hover:text-[#2C1E16]"
              }`}
            >
              <UserCheck size={12} className="inline mr-1" /> Cari Pelanggan
            </button>
            <button
              type="button"
              onClick={() => {
                setCustomerMode("manual");
                setCustomer((prev) => ({ ...prev, customer_id: null }));
              }}
              className={`rounded-lg px-2.5 py-1 text-xs font-medium transition-colors ${
                customerMode === "manual"
                  ? "bg-[#8B5A2B] text-white shadow-xs"
                  : "text-[#5C4A3D] hover:text-[#2C1E16]"
              }`}
            >
              <UserPlus size={12} className="inline mr-1" /> Manual
            </button>
          </div>
        </div>

        {customerMode === "search" && (
          <div className="relative rounded-xl bg-[#FAF5EE] p-3 border border-[#E5DCC5]">
            <Label className="text-xs font-semibold text-[#5C4A3D]">
              Cari Pelanggan Terdaftar
            </Label>
            <div className="relative mt-1">
              <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#8B7355]" />
              <Input
                value={customerSearchQ}
                onChange={(e) => setCustomerSearchQ(e.target.value)}
                placeholder="Ketik nama atau nomor WhatsApp customer..."
                className="pl-8 text-xs bg-white h-9"
              />
            </div>
            {searchingCustomer && (
              <p className="mt-1 text-[11px] text-[#8B7355]">Mencari customer...</p>
            )}
            {customerSearchResults.length > 0 && (
              <div className="absolute left-3 right-3 top-full z-20 mt-1 max-h-48 overflow-y-auto rounded-xl border border-[#E5DCC5] bg-white shadow-lg">
                {customerSearchResults.map((c) => (
                  <button
                    key={c.id || c._id}
                    type="button"
                    onClick={() => selectCustomer(c)}
                    className="w-full text-left px-3 py-2 text-xs hover:bg-[#FAF5EE] border-b border-[#F1EBE0] last:border-0"
                  >
                    <div className="font-semibold text-[#2C1E16]">{c.username || c.name}</div>
                    <div className="text-[11px] text-[#8B7355]">{c.phone || c.email || "-"}</div>
                  </button>
                ))}
              </div>
            )}
            {customer.customer_id && (
              <div className="mt-2 text-xs text-emerald-700 font-medium">
                ✓ Terhubung dengan akun member: <strong>{customer.name}</strong>
              </div>
            )}
          </div>
        )}

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div>
            <Label className="text-xs font-semibold text-[#5C4A3D]">
              Nama Customer <span className="text-red-500">*</span>
            </Label>
            <Input
              value={customer.name}
              onChange={(e) => setCustomer({ ...customer, name: e.target.value })}
              placeholder="Contoh: Ahmad Fauzan"
              className="mt-1 text-xs"
            />
          </div>

          <div>
            <Label className="text-xs font-semibold text-[#5C4A3D]">
              No. WhatsApp (dengan kode negara) <span className="text-red-500">*</span>
            </Label>
            <Input
              value={customer.whatsapp}
              onChange={(e) => setCustomer({ ...customer, whatsapp: e.target.value })}
              placeholder="Contoh: +628123456789 atau +201551685018"
              className="mt-1 text-xs font-mono"
            />
            <p className="text-[10px] text-[#8B7355] mt-0.5">Wajib diawali tanda +</p>
          </div>

          <div>
            <Label className="text-xs font-semibold text-[#5C4A3D]">No. Telepon Mesir (Opsional)</Label>
            <Input
              value={customer.egypt_phone}
              onChange={(e) => setCustomer({ ...customer, egypt_phone: e.target.value })}
              placeholder="Contoh: 01551685018"
              className="mt-1 text-xs font-mono"
            />
          </div>

          <div>
            <Label className="text-xs font-semibold text-[#5C4A3D]">Alamat Pengiriman</Label>
            <Input
              value={customer.address}
              onChange={(e) => setCustomer({ ...customer, address: e.target.value })}
              placeholder="Contoh: Madinat Nasr, Hay Asyir, Kairo"
              className="mt-1 text-xs"
            />
          </div>
        </div>

        <div className="rounded-xl bg-[#FAF8F5] p-2.5 text-[11px] text-[#8B7355] flex items-center gap-1.5 border border-[#F1EBE0]">
          <Info size={13} className="shrink-0 text-[#8B5A2B]" />
          <span>
            Data di atas disimpan sebagai <strong>snapshot historis</strong> untuk invoice ini. Mengubah data di sini tidak akan mengubah profil utama pelanggan.
          </span>
        </div>
      </div>

      {/* SECTION B: Items */}
      <div className="rounded-2xl border border-[#E5DCC5] bg-white p-5 sm:p-6 shadow-xs space-y-4">
        <div className="flex items-center justify-between border-b border-[#F1EBE0] pb-3">
          <div>
            <h2 className="font-heading text-base font-bold text-[#2C1E16]">
              B. Daftar Item Pesanan
            </h2>
            <p className="text-xs text-[#8B7355]">
              Mendukung multi-item, produk katalog maupun pesanan custom penuh
            </p>
          </div>
          <div className="flex gap-2">
            <Button
              type="button"
              size="sm"
              onClick={() => addItem("custom")}
              className="rounded-xl bg-[#8B5A2B] text-xs text-white hover:bg-[#6B4423]"
            >
              <Plus size={14} className="mr-1" /> + Item Custom
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => addItem("catalog")}
              className="rounded-xl border-[#8B5A2B]/40 text-[#8B5A2B] text-xs hover:bg-[#FAF5EE]"
            >
              <Plus size={14} className="mr-1" /> + Item Katalog
            </Button>
          </div>
        </div>

        <div className="space-y-4">
          {items.map((it, idx) => {
            const lineTotal = Math.max(0, (parseInt(it.quantity, 10) || 1) * (parseFloat(it.unit_price) || 0));
            return (
              <div
                key={it.item_id || idx}
                className="rounded-2xl border border-[#E5DCC5] bg-[#FAF8F5] p-4 sm:p-5 space-y-3.5 relative"
              >
                {/* Item Card Header */}
                <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[#E5DCC5]/60 pb-2.5">
                  <div className="flex items-center gap-2">
                    <span className="flex h-6 w-6 items-center justify-center rounded-full bg-[#8B5A2B] text-[11px] font-bold text-white">
                      {idx + 1}
                    </span>
                    <span className="font-heading text-xs font-bold text-[#2C1E16]">
                      {it.name || `Item #${idx + 1}`}
                    </span>
                    <span
                      className={`rounded-full px-2 py-0.5 text-[10px] font-semibold border ${
                        it.item_type === "catalog"
                          ? "bg-purple-100 text-purple-800 border-purple-200"
                          : "bg-amber-100 text-amber-800 border-amber-200"
                      }`}
                    >
                      {it.item_type === "catalog" ? "Produk Katalog" : "Custom Order"}
                    </span>
                  </div>

                  <div className="flex items-center gap-1">
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={() => duplicateItem(idx)}
                      className="h-7 text-xs text-[#5C4A3D] hover:bg-[#EFE6D5]"
                      title="Duplikasi Item"
                    >
                      <Copy size={13} className="mr-1" /> Duplikasi
                    </Button>
                    {items.length > 1 && (
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        onClick={() => removeItem(idx)}
                        className="h-7 text-xs text-red-600 hover:bg-red-50"
                        title="Hapus Item"
                      >
                        <Trash2 size={13} className="mr-1" /> Hapus
                      </Button>
                    )}
                  </div>
                </div>

                {/* If Catalog: Product Picker */}
                {it.item_type === "catalog" && (
                  <div className="rounded-xl bg-white p-3 border border-[#E5DCC5]">
                    <Label className="text-xs font-semibold text-[#5C4A3D]">
                      Pilih dari Katalog Produk
                    </Label>
                    <select
                      value={it.product_id || ""}
                      onChange={(e) => handleProductSelect(idx, e.target.value)}
                      className="mt-1 w-full rounded-xl border border-[#E5DCC5] bg-white px-3 py-2 text-xs text-[#2C1E16] focus:outline-none focus:ring-1 focus:ring-[#8B5A2B]"
                    >
                      <option value="">-- Pilih Produk Sogil --</option>
                      {catalogProducts.map((p) => (
                        <option key={p.id || p._id} value={p.id || p._id}>
                          {p.name} ({fmtLE(p.starting_price_le)} LE)
                        </option>
                      ))}
                    </select>
                  </div>
                )}

                {/* Item Core Fields */}
                <div className="grid grid-cols-1 sm:grid-cols-12 gap-3">
                  <div className="sm:col-span-6">
                    <Label className="text-xs font-semibold text-[#5C4A3D]">
                      Nama Item <span className="text-red-500">*</span>
                    </Label>
                    <Input
                      value={it.name}
                      onChange={(e) => handleItemChange(idx, "name", e.target.value)}
                      placeholder="Contoh: Meja Belajar Minimalis"
                      className="mt-1 text-xs bg-white"
                    />
                  </div>

                  <div className="sm:col-span-2">
                    <Label className="text-xs font-semibold text-[#5C4A3D]">
                      Jumlah (Qty) <span className="text-red-500">*</span>
                    </Label>
                    <Input
                      type="number"
                      min="1"
                      value={it.quantity}
                      onChange={(e) =>
                        handleItemChange(idx, "quantity", Math.max(1, parseInt(e.target.value, 10) || 1))
                      }
                      className="mt-1 text-xs bg-white text-center font-bold"
                    />
                  </div>

                  <div className="sm:col-span-4">
                    <Label className="text-xs font-semibold text-[#5C4A3D]">
                      Harga Satuan (LE) <span className="text-red-500">*</span>
                    </Label>
                    <Input
                      type="number"
                      min="0"
                      value={it.unit_price}
                      onChange={(e) => handleItemChange(idx, "unit_price", e.target.value)}
                      className="mt-1 text-xs bg-white font-semibold"
                    />
                  </div>
                </div>

                {/* Dimensions (Length, Width, Height, Notes) */}
                <div className="rounded-xl bg-white p-3 border border-[#E5DCC5] space-y-2">
                  <Label className="text-xs font-semibold text-[#8B5A2B]">
                    Spesifikasi Ukuran / Dimensi
                  </Label>
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                    <div>
                      <span className="text-[10px] text-[#8B7355]">Panjang (cm)</span>
                      <Input
                        value={it.dimensions?.length || ""}
                        onChange={(e) => handleDimensionChange(idx, "length", e.target.value)}
                        placeholder="Pjg"
                        className="mt-0.5 text-xs h-8"
                      />
                    </div>
                    <div>
                      <span className="text-[10px] text-[#8B7355]">Lebar (cm)</span>
                      <Input
                        value={it.dimensions?.width || ""}
                        onChange={(e) => handleDimensionChange(idx, "width", e.target.value)}
                        placeholder="Lbr"
                        className="mt-0.5 text-xs h-8"
                      />
                    </div>
                    <div>
                      <span className="text-[10px] text-[#8B7355]">Tinggi (cm)</span>
                      <Input
                        value={it.dimensions?.height || ""}
                        onChange={(e) => handleDimensionChange(idx, "height", e.target.value)}
                        placeholder="Tgi"
                        className="mt-0.5 text-xs h-8"
                      />
                    </div>
                    <div>
                      <span className="text-[10px] text-[#8B7355]">Catatan Ukuran</span>
                      <Input
                        value={it.dimensions?.notes || ""}
                        onChange={(e) => handleDimensionChange(idx, "notes", e.target.value)}
                        placeholder="Contoh: Meja L"
                        className="mt-0.5 text-xs h-8"
                      />
                    </div>
                  </div>
                </div>

                {/* Material & Finishing */}
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <div>
                    <Label className="text-xs font-semibold text-[#5C4A3D]">Material</Label>
                    <Input
                      value={it.material}
                      onChange={(e) => handleItemChange(idx, "material", e.target.value)}
                      placeholder="Contoh: Blockboard 18mm, Kayu Pinus"
                      className="mt-1 text-xs bg-white"
                    />
                  </div>
                  <div>
                    <Label className="text-xs font-semibold text-[#5C4A3D]">Finishing</Label>
                    <Input
                      value={it.finishing}
                      onChange={(e) => handleItemChange(idx, "finishing", e.target.value)}
                      placeholder="Contoh: HPL Putih Glossy, Cat Duco"
                      className="mt-1 text-xs bg-white"
                    />
                  </div>
                </div>

                {/* Deskripsi & Catatan Khusus Item */}
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <div>
                    <Label className="text-xs font-semibold text-[#5C4A3D]">Deskripsi Tambahan</Label>
                    <Input
                      value={it.description}
                      onChange={(e) => handleItemChange(idx, "description", e.target.value)}
                      placeholder="Penjelasan bentuk atau model"
                      className="mt-1 text-xs bg-white"
                    />
                  </div>
                  <div>
                    <Label className="text-xs font-semibold text-[#5C4A3D]">Catatan Item</Label>
                    <Input
                      value={it.notes}
                      onChange={(e) => handleItemChange(idx, "notes", e.target.value)}
                      placeholder="Catatan pengerjaan item"
                      className="mt-1 text-xs bg-white"
                    />
                  </div>
                </div>

                {/* Live Item Total Display */}
                <div className="flex items-center justify-between border-t border-[#E5DCC5]/60 pt-2 text-xs">
                  <span className="text-[#8B7355]">
                    {it.quantity} × {fmtLE(it.unit_price)} LE
                  </span>
                  <div className="text-right">
                    <span className="text-[11px] text-[#8B7355] mr-1">Subtotal Item:</span>
                    <span className="font-heading font-bold text-sm text-[#8B5A2B]">
                      {fmtLE(lineTotal)} LE
                    </span>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* SECTION C: Price Summary */}
      <div className="rounded-2xl border border-[#E5DCC5] bg-white p-5 sm:p-6 shadow-xs space-y-4">
        <h2 className="font-heading text-base font-bold text-[#2C1E16] border-b border-[#F1EBE0] pb-3">
          C. Rincian & Kalkulasi Harga
        </h2>

        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          <div>
            <Label className="text-xs font-semibold text-[#5C4A3D]">Potongan / Diskon (LE)</Label>
            <Input
              type="number"
              min="0"
              value={discountAmount}
              onChange={(e) => setDiscountAmount(e.target.value)}
              placeholder="0"
              className="mt-1 text-xs"
            />
          </div>

          <div>
            <Label className="text-xs font-semibold text-[#5C4A3D]">Biaya Ongkir (LE)</Label>
            <Input
              type="number"
              min="0"
              value={deliveryFee}
              onChange={(e) => setDeliveryFee(e.target.value)}
              placeholder="0"
              className="mt-1 text-xs"
            />
          </div>

          <div>
            <Label className="text-xs font-semibold text-[#5C4A3D]">Biaya Tambahan / Perakitan (LE)</Label>
            <Input
              type="number"
              min="0"
              value={additionalFee}
              onChange={(e) => setAdditionalFee(e.target.value)}
              placeholder="0"
              className="mt-1 text-xs"
            />
          </div>
        </div>

        {/* Live Calculated Box */}
        <div className="rounded-2xl bg-[#FAF5EE] border border-[#E5DCC5] p-4 space-y-2 text-xs">
          <div className="flex justify-between text-[#5C4A3D]">
            <span>Subtotal ({items.length} item)</span>
            <span className="font-semibold">{fmtLE(subtotal)} LE</span>
          </div>
          {discNum > 0 && (
            <div className="flex justify-between text-red-600">
              <span>Diskon</span>
              <span>-{fmtLE(discNum)} LE</span>
            </div>
          )}
          {delivNum > 0 && (
            <div className="flex justify-between text-[#5C4A3D]">
              <span>Ongkos Kirim</span>
              <span>+{fmtLE(delivNum)} LE</span>
            </div>
          )}
          {addFeeNum > 0 && (
            <div className="flex justify-between text-[#5C4A3D]">
              <span>Biaya Tambahan</span>
              <span>+{fmtLE(addFeeNum)} LE</span>
            </div>
          )}
          <div className="border-t border-[#E5DCC5] pt-2 flex justify-between items-baseline">
            <span className="font-heading font-bold text-sm text-[#2C1E16]">TOTAL AKHIR</span>
            <span className="font-heading font-bold text-lg text-[#8B5A2B]">{fmtLE(total)} LE</span>
          </div>
        </div>
      </div>

      {/* SECTION D: Notes */}
      <div className="rounded-2xl border border-[#E5DCC5] bg-white p-5 sm:p-6 shadow-xs space-y-4">
        <h2 className="font-heading text-base font-bold text-[#2C1E16] border-b border-[#F1EBE0] pb-3">
          D. Catatan Invoice
        </h2>

        <div>
          <Label className="text-xs font-semibold text-[#5C4A3D] flex items-center gap-1.5">
            <span>Catatan untuk Customer</span>
            <span className="text-[10px] text-[#8B7355] font-normal">
              (Akan tampil di cetakan invoice/PDF resmi)
            </span>
          </Label>
          <Textarea
            value={customerNote}
            onChange={(e) => setCustomerNote(e.target.value)}
            rows={2}
            placeholder="Contoh: Estimasi pengerjaan 10-14 hari kerja. Finishing natural doff."
            className="mt-1 text-xs"
          />
        </div>

        <div>
          <Label className="text-xs font-semibold text-[#5C4A3D] flex items-center gap-1.5">
            <Lock size={12} className="text-[#8B5A2B]" />
            <span>Catatan Internal</span>
            <span className="text-[10px] text-amber-700 font-normal">
              (Khusus admin — TIDAK akan tampil di cetakan invoice customer)
            </span>
          </Label>
          <Textarea
            value={internalNote}
            onChange={(e) => setInternalNote(e.target.value)}
            rows={2}
            placeholder="Contoh: Customer kenalan Mas Fauzi, prioritaskan produksi setelah transfer DP."
            className="mt-1 text-xs bg-amber-50/40 border-amber-200"
          />
        </div>
      </div>

      {/* Bottom Sticky Action Bar */}
      <div className="flex items-center justify-between border-t border-[#E5DCC5] pt-4">
        <Button
          type="button"
          variant="outline"
          onClick={() => navigate(isEdit ? `/admin/invoices/${id}` : "/admin/invoices")}
          className="rounded-xl border-[#E5DCC5] text-xs text-[#5C4A3D]"
        >
          Batal
        </Button>
        <div className="flex items-center gap-2">
          <Button
            type="button"
            variant="outline"
            disabled={submitting}
            onClick={() => handleSubmit("DRAFT")}
            className="rounded-xl border-[#8B5A2B] text-xs font-semibold text-[#8B5A2B] hover:bg-[#FAF5EE]"
          >
            <Save size={14} className="mr-1.5" /> Simpan Draft
          </Button>
          <Button
            type="button"
            disabled={submitting}
            onClick={() => handleSubmit("SENT")}
            className="rounded-xl bg-[#8B5A2B] text-xs font-semibold text-white hover:bg-[#6B4423]"
          >
            <Send size={14} className="mr-1.5" /> Simpan & Siap Kirim
          </Button>
        </div>
      </div>
    </div>
  );
}
