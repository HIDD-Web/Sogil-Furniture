import React, { useEffect, useRef, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import api, { imgUrl } from "../../lib/api";
import { formatApiError } from "../../lib/format";
import { CATEGORY_LABELS } from "../../lib/constants";
import { config_summary_client } from "../../lib/summary";
import { ProductImage } from "../../components/ProductImage";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Textarea } from "../../components/ui/textarea";
import { Label } from "../../components/ui/label";
import { Switch } from "../../components/ui/switch";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../../components/ui/select";
import { ChevronLeft, Upload, Trash2, Plus, Star, ArrowUp, ArrowDown, ArrowLeft, ArrowRight } from "lucide-react";
import { toast } from "sonner";
import VariantPhotoManager from "../../components/admin/VariantPhotoManager";

const PHOTO_ATTRS = {
  rak: [["length", "lengths"], ["level", "levels"], ["type", "types"], ["finishing", "finishings"]],
  meja: [["size", "sizes"], ["height", "heights"], ["finishing", "finishings"]],
  meja_rak: [["variant", "variants"], ["type", "types"], ["finishing", "finishings"]],
};

const LEGACY_LABELS = { length: "Panjang", level: "Jumlah Tingkat", type: "Tipe", finishing: "Finishing", size: "Ukuran Meja", height: "Tinggi Meja", variant: "Varian/Tingkat" };

// Derive selectable photo-config options from the product's CURRENT config schema:
// prefer additive `pricing.groups` (size/levels/height/finishing, mount, pilihan, desain, ...),
// fall back to the legacy category-based flat arrays for Rak/Meja backward compatibility.
function getOptionDefs(prod) {
  const pr = prod?.pricing || {};
  if (Array.isArray(pr.groups)) {
    return pr.groups.map((g) => ({
      key: g.key,
      options: (g.options || []).filter((o) => (g.key === "type" ? o !== "A+" && o !== "B+" : true)),
      label: g.label || g.key,
    }));
  }
  return (PHOTO_ATTRS[prod?.category] || []).map(([key, arr]) => {
    let opts = pr[arr] || [];
    if (key === "type") {
      opts = opts.filter((o) => o !== "A+" && o !== "B+");
    }
    return { key, options: opts, label: LEGACY_LABELS[key] || key };
  });
}

export default function AdminProductEdit() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [p, setP] = useState(null);
  const [categories, setCategories] = useState([]);
  const [pricingText, setPricingText] = useState("{}");
  const [priority, setPriority] = useState([]);
  const [notes, setNotes] = useState({});
  const photoRefs = useRef({});

  useEffect(() => {
    api.get("/categories").then((r) => setCategories(r.data || [])).catch(() => {});
    api.get("/products?admin_view=true").then((r) => {
      const prod = r.data.find((x) => x.id === id);
      if (prod) {
        prod.photos = prod.photos || [];
        if (prod.pricing?.types) {
          prod.pricing.types = prod.pricing.types.filter((t) => t !== "A+" && t !== "B+");
        }
        setP(prod); setPricingText(JSON.stringify(prod.pricing || {}, null, 2));
        const defs = getOptionDefs(prod);
        const w = prod.photo_weights || {};
        const ordered = Object.keys(w).length ? defs.map((d) => d.key).sort((a, b) => (w[b] || 0) - (w[a] || 0)) : defs.map((d) => d.key);
        setPriority(ordered); setNotes(prod.option_notes || {});
      }
    });
  }, [id]);

  const setField = (k, v) => setP((prev) => ({ ...prev, [k]: v }));
  const setBasePrice = (key, val) => setP((prev) => ({ ...prev, pricing: { ...prev.pricing, base_prices: { ...prev.pricing.base_prices, [key]: Number(val) || 0 } } }));

  const uploadTo = async (file, cb) => {
    const fd = new FormData(); fd.append("file", file);
    try { const { data } = await api.post("/admin/upload", fd, { headers: { "Content-Type": "multipart/form-data" } }); cb(data.url); toast.success("Gambar diunggah"); }
    catch (err) { toast.error(formatApiError(err.response?.data?.detail)); }
  };

  const addPhoto = () => setP((prev) => ({ ...prev, photos: [...(prev.photos || []), { id: Date.now() + "", attributes: {}, main_url: "", front_url: "", side_url: "" }] }));
  const updPhoto = (pid, patch) => setP((prev) => ({ ...prev, photos: prev.photos.map((ph) => (ph.id === pid ? { ...ph, ...patch } : ph)) }));
  const updPhotoAttr = (pid, key, val) => setP((prev) => ({ ...prev, photos: prev.photos.map((ph) => (ph.id === pid ? { ...ph, attributes: { ...ph.attributes, [key]: val } } : ph)) }));
  const delPhoto = (pid) => setP((prev) => ({ ...prev, photos: prev.photos.filter((ph) => ph.id !== pid), representative_photo_id: prev.representative_photo_id === pid ? null : prev.representative_photo_id }));
  // Configuration-record order: swap position of a photo-set within the photos array (persists as array order on save).
  const movePhotoSet = (idx, dir) => setP((prev) => { const a = [...prev.photos]; const j = idx + dir; if (j < 0 || j >= a.length) return prev; [a[idx], a[j]] = [a[j], a[idx]]; return { ...prev, photos: a }; });
  // Photo order within a configuration: swap adjacent slot values (Foto 1 = primary). Only ordering metadata changes.
  const moveSlot = (pid, from, dir) => setP((prev) => ({ ...prev, photos: prev.photos.map((ph) => { if (ph.id !== pid) return ph; const slots = ["main_url", "front_url", "side_url"]; const to = from + dir; if (to < 0 || to >= slots.length) return ph; const c = { ...ph }; const tmp = c[slots[from]] || ""; c[slots[from]] = c[slots[to]] || ""; c[slots[to]] = tmp; return c; }) }));

  const save = async () => {
    let pricing = p.pricing;
    try { pricing = JSON.parse(pricingText); } catch { toast.error("Format JSON tidak valid — perubahan tidak disimpan"); return; }
    if (typeof pricing !== "object" || Array.isArray(pricing) || pricing === null) { toast.error("Konfigurasi JSON harus berupa objek {}"); return; }
    const n = priority.length, denom = n * (n + 1) / 2;
    if (Array.isArray(pricing.types)) {
      pricing.types = pricing.types.filter((t) => t !== "A+" && t !== "B+");
    }
    const photo_weights = {}; priority.forEach((k, i) => { photo_weights[k] = denom ? Math.round((n - i) / denom * 100) / 100 : 0; });
    const option_notes = Object.fromEntries(Object.entries(notes).filter(([, v]) => (v || "").trim()));
    try {
      const productName = CATEGORY_LABELS[p.category] || p.name || "Produk";
      await api.put(`/admin/products/${id}`, {
        name: productName,
        category: p.category,
        description: p.description || "",
        image_url: p.image_url || "",
        active: p.active,
        configurable: p.configurable,
        starting_price_le: p.starting_price_le,
        pricing,
        photos: p.photos,
        representative_photo_id: p.representative_photo_id,
        photo_weights,
        option_notes,
        category_cover_image: p.category_cover_image || "",
        cover_mode: p.cover_mode || "manual"
      });
      toast.success("Produk disimpan"); navigate("/admin/products");
    } catch { toast.error("Gagal menyimpan"); }
  };
  const KEY_LABELS = { length: "Panjang", level: "Jumlah Tingkat", type: "Tipe", finishing: "Finishing", size: "Ukuran Meja", height: "Tinggi Meja", variant: "Varian/Tingkat" };
  const movePriority = (i, dir) => setPriority((prev) => { const a = [...prev]; const j = i + dir; if (j < 0 || j >= a.length) return prev; [a[i], a[j]] = [a[j], a[i]]; return a; });
  const remove = async () => { if (!window.confirm("Hapus produk ini?")) return; await api.delete(`/admin/products/${id}`); navigate("/admin/products"); };

  if (!p) return <div className="text-[#8B7355]">Memuat...</div>;
  const basePrices = p.pricing?.base_prices || {};
  const optDefs = getOptionDefs(p);
  const labelOf = Object.fromEntries(optDefs.map((d) => [d.key, d.label]));

  return (
    <div className="max-w-3xl">
      <button onClick={() => navigate("/admin/products")} className="mb-4 inline-flex items-center gap-1 text-sm text-[#8B5A2B]"><ChevronLeft size={16} /> Kembali</button>
      <h1 className="font-heading text-2xl font-bold text-[#2C1E16]">Kelola Produk: {CATEGORY_LABELS[p.category] || p.name}</h1>
      {p.updated_by_name && <p className="mt-1 text-xs text-[#8B7355]">Terakhir diperbarui oleh {p.updated_by_name}</p>}

      <div className="mt-4 space-y-5 rounded-2xl border border-[#E5DCC5] bg-white p-4 sm:p-5 shadow-sm">
        <div className="space-y-4">
          <div>
            <Label className="mb-1 block text-sm font-medium">Kategori</Label>
            <Select value={p.category} onValueChange={(v) => setField("category", v)}>
              <SelectTrigger data-testid="product-category" className="bg-white">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {categories.length > 0
                  ? categories.map((c) => (
                      <SelectItem key={c.key} value={c.key}>{c.name}</SelectItem>
                    ))
                  : Object.entries(CATEGORY_LABELS).map(([k, v]) => (
                      <SelectItem key={k} value={k}>{v}</SelectItem>
                    ))}
              </SelectContent>
            </Select>
          </div>
          <div>
            <Label className="mb-1 block text-sm font-medium">Deskripsi</Label>
            <Textarea value={p.description} onChange={(e) => setField("description", e.target.value)} data-testid="product-desc" className="bg-white" />
          </div>
          <div>
            <Label className="mb-1 block text-sm font-medium">Harga Mulai (LE)</Label>
            <Input type="number" value={p.starting_price_le} onChange={(e) => setField("starting_price_le", e.target.value)} className="bg-white" />
          </div>
        </div>

        <div className="flex flex-wrap gap-6 pt-1">
          <label className="flex items-center gap-2 text-sm"><Switch checked={p.active} onCheckedChange={(v) => setField("active", v)} data-testid="product-active" /> Aktif</label>
          <label className="flex items-center gap-2 text-sm"><Switch checked={p.configurable} onCheckedChange={(v) => setField("configurable", v)} data-testid="product-configurable" /> Bisa dikonfigurasi</label>
        </div>

        {/* Photo manager per predefined combinations */}
        <div className="border-t border-[#F1EBE0] pt-4">
          <VariantPhotoManager
            product={p}
            photos={p.photos || []}
            onUpdatePhotos={(nextPhotos) => setP((prev) => ({ ...prev, photos: nextPhotos }))}
            uploadTo={uploadTo}
            pricing={p.pricing}
            onUpdatePricing={(nextPricing) => {
              setP((prev) => ({ ...prev, pricing: nextPricing }));
              setPricingText(JSON.stringify(nextPricing, null, 2));
            }}
          />
        </div>

        {Object.keys(basePrices).length > 0 && (
          <div className="border-t border-[#F1EBE0] pt-4">
            <Label className="mb-2 block font-heading text-sm font-semibold">Harga Dasar (LE) — Tipe B</Label>
            <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {Object.entries(basePrices).map(([k, v]) => (
                <div key={k}><Label className="mb-0.5 block text-xs text-[#8B7355]">{k}</Label><Input type="number" value={v} onChange={(e) => setBasePrice(k, e.target.value)} data-testid={`base-price-${k}`} className="h-10 bg-white" /></div>
              ))}
            </div>
          </div>
        )}

        {p.configurable && (
          <div className="border-t border-[#F1EBE0] pt-4">
            <Label className="mb-1 block font-heading text-sm font-semibold">Prioritas Pencocokan Foto</Label>
            <p className="mb-2 text-xs text-[#8B7355]">Urutan ini khusus produk ini. Menentukan opsi mana yang paling diprioritaskan saat memilih foto terdekat (bila tidak ada foto sama persis).</p>
            <div className="space-y-1.5">
              {priority.map((k, i) => (
                <div key={k} className="flex items-center justify-between rounded-xl border border-[#E5DCC5] bg-[#FBF9F4] px-3 py-2" data-testid={`priority-${k}`}>
                  <span className="text-sm text-[#2C1E16]"><b className="mr-1 text-[#8B5A2B]">{i + 1}.</b> {labelOf[k] || KEY_LABELS[k] || k}</span>
                  <div className="flex gap-1">
                    <button onClick={() => movePriority(i, -1)} disabled={i === 0} data-testid={`priority-up-${k}`} className="rounded border border-[#E5DCC5] p-1 text-[#8B5A2B] disabled:opacity-30"><ArrowUp size={14} /></button>
                    <button onClick={() => movePriority(i, 1)} disabled={i === priority.length - 1} data-testid={`priority-down-${k}`} className="rounded border border-[#E5DCC5] p-1 text-[#8B5A2B] disabled:opacity-30"><ArrowDown size={14} /></button>
                  </div>
                </div>
              ))}
              {priority.length === 0 && <p className="text-xs text-[#8B7355]">Kategori ini belum punya grup opsi untuk pencocokan foto.</p>}
            </div>
          </div>
        )}

        {p.configurable && optDefs.length > 0 && (
          <div className="border-t border-[#F1EBE0] pt-4">
            <Label className="mb-1 block font-heading text-sm font-semibold">Catatan Opsi (Notes)</Label>
            <p className="mb-2 text-xs text-[#8B7355]">Catatan opsional per grup opsi (mis. "Jarak per tingkat ± 28 cm"). Kosongkan bila tidak perlu — tidak akan tampil.</p>
            <div className="space-y-2">
              {optDefs.map((d) => (
                <div key={d.key}>
                  <Label className="mb-0.5 block text-xs text-[#8B7355]">{d.label}</Label>
                  <Input value={notes[d.key] || ""} onChange={(e) => setNotes((prev) => ({ ...prev, [d.key]: e.target.value }))} data-testid={`note-${d.key}`} placeholder="Catatan (opsional)" className="bg-white" />
                </div>
              ))}
            </div>
          </div>
        )}

        {p.configurable && (
          <div className="border-t border-[#F1EBE0] pt-4">
            <Label className="mb-1 block font-heading text-sm font-semibold">Konfigurasi Lanjutan (JSON)</Label>
            <p className="mb-2 text-xs text-[#8B7355]">Grup opsi, nilai, harga & finishing produk ini. JSON divalidasi sebelum disimpan.</p>
            <Textarea value={pricingText} onChange={(e) => setPricingText(e.target.value)} data-testid="product-pricing-json" className="min-h-[200px] bg-[#FBF9F4] font-mono text-xs" />
          </div>
        )}

        <div className="flex justify-between pt-2">
          <Button variant="outline" onClick={remove} data-testid="product-delete" className="rounded-xl border-red-300 text-red-600"><Trash2 size={16} className="mr-1" /> Hapus</Button>
          <Button onClick={save} data-testid="product-save" className="rounded-xl bg-[#8B5A2B] px-8 hover:bg-[#6B4423]">Simpan</Button>
        </div>
      </div>
    </div>
  );
}
