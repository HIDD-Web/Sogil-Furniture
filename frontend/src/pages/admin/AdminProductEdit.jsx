import React, { useEffect, useRef, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import api, { imgUrl } from "../../lib/api";
import { formatApiError } from "../../lib/format";
import { CATEGORY_LABELS } from "../../lib/constants";
import { ProductImage } from "../../components/ProductImage";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Textarea } from "../../components/ui/textarea";
import { Label } from "../../components/ui/label";
import { Switch } from "../../components/ui/switch";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../../components/ui/select";
import { ChevronLeft, Upload, Trash2, Plus, Star } from "lucide-react";
import { toast } from "sonner";

const PHOTO_ATTRS = {
  rak: [["length", "lengths"], ["level", "levels"], ["type", "types"], ["finishing", "finishings"]],
  meja: [["size", "sizes"], ["height", "heights"], ["finishing", "finishings"]],
  meja_rak: [["variant", "variants"], ["type", "types"], ["finishing", "finishings"]],
};

export default function AdminProductEdit() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [p, setP] = useState(null);
  const [pricingText, setPricingText] = useState("{}");
  const fileRef = useRef();
  const photoRefs = useRef({});

  useEffect(() => {
    api.get("/products?admin_view=true").then((r) => {
      const prod = r.data.find((x) => x.id === id);
      if (prod) { prod.photos = prod.photos || []; setP(prod); setPricingText(JSON.stringify(prod.pricing || {}, null, 2)); }
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

  const save = async () => {
    let pricing = p.pricing;
    try { pricing = JSON.parse(pricingText); } catch { toast.error("Format JSON pricing tidak valid"); return; }
    try {
      await api.put(`/admin/products/${id}`, { name: p.name, category: p.category, description: p.description, image_url: p.image_url,
        active: p.active, configurable: p.configurable, starting_price_le: p.starting_price_le, pricing,
        photos: p.photos, representative_photo_id: p.representative_photo_id });
      toast.success("Produk disimpan"); navigate("/admin/products");
    } catch { toast.error("Gagal menyimpan"); }
  };
  const remove = async () => { if (!window.confirm("Hapus produk ini?")) return; await api.delete(`/admin/products/${id}`); navigate("/admin/products"); };

  if (!p) return <div className="text-[#8B7355]">Memuat...</div>;
  const basePrices = p.pricing?.base_prices || {};
  const attrDefs = PHOTO_ATTRS[p.category] || [];

  return (
    <div className="max-w-3xl">
      <button onClick={() => navigate("/admin/products")} className="mb-4 inline-flex items-center gap-1 text-sm text-[#8B5A2B]"><ChevronLeft size={16} /> Kembali</button>
      <h1 className="font-heading text-2xl font-bold text-[#2C1E16]">Kelola Produk</h1>
      {p.updated_by_name && <p className="mt-1 text-xs text-[#8B7355]">Terakhir diperbarui oleh {p.updated_by_name}</p>}

      <div className="mt-4 space-y-5 rounded-2xl border border-[#E5DCC5] bg-white p-5 shadow-sm">
        <div className="flex flex-col gap-4 sm:flex-row">
          <div className="w-40 shrink-0">
            <div className="overflow-hidden rounded-xl border border-[#E5DCC5]"><ProductImage url={p.image_url} ratio="aspect-square" /></div>
            <input ref={fileRef} type="file" accept="image/*" hidden onChange={(e) => e.target.files[0] && uploadTo(e.target.files[0], (u) => setField("image_url", u))} data-testid="product-image-input" />
            <Button variant="outline" onClick={() => fileRef.current?.click()} data-testid="product-image-upload" className="mt-2 w-full rounded-xl border-[#8B5A2B] text-xs text-[#8B5A2B]"><Upload size={14} className="mr-1" /> Gambar Utama</Button>
          </div>
          <div className="flex-1 space-y-3">
            <div><Label className="mb-1 block text-sm">Nama</Label><Input value={p.name} onChange={(e) => setField("name", e.target.value)} data-testid="product-name" className="bg-white" /></div>
            <div><Label className="mb-1 block text-sm">Kategori</Label>
              <Select value={p.category} onValueChange={(v) => setField("category", v)}><SelectTrigger data-testid="product-category" className="bg-white"><SelectValue /></SelectTrigger><SelectContent>{Object.entries(CATEGORY_LABELS).map(([k, v]) => <SelectItem key={k} value={k}>{v}</SelectItem>)}</SelectContent></Select>
            </div>
            <div><Label className="mb-1 block text-sm">Deskripsi</Label><Textarea value={p.description} onChange={(e) => setField("description", e.target.value)} data-testid="product-desc" className="bg-white" /></div>
            <div><Label className="mb-1 block text-sm">Harga Mulai (LE)</Label><Input type="number" value={p.starting_price_le} onChange={(e) => setField("starting_price_le", e.target.value)} className="bg-white" /></div>
          </div>
        </div>
        <div className="flex flex-wrap gap-6">
          <label className="flex items-center gap-2 text-sm"><Switch checked={p.active} onCheckedChange={(v) => setField("active", v)} data-testid="product-active" /> Aktif</label>
          <label className="flex items-center gap-2 text-sm"><Switch checked={p.configurable} onCheckedChange={(v) => setField("configurable", v)} data-testid="product-configurable" /> Bisa dikonfigurasi</label>
        </div>

        {/* Photo manager */}
        <div className="border-t border-[#F1EBE0] pt-4">
          <div className="flex items-center justify-between">
            <Label className="font-heading text-sm font-semibold">Foto Konfigurasi</Label>
            <Button variant="outline" onClick={addPhoto} data-testid="add-photo" className="rounded-xl border-[#8B5A2B] text-xs text-[#8B5A2B]"><Plus size={14} className="mr-1" /> Tambah Foto</Button>
          </div>
          <p className="mt-1 text-xs text-[#8B7355]">Tentukan atribut & 3 foto (utama, depan, samping). Sistem otomatis memilih foto terdekat untuk konfigurasi customer.</p>
          <div className="mt-3 space-y-3">
            {(p.photos || []).map((ph) => (
              <div key={ph.id} className="rounded-xl border border-[#E5DCC5] bg-[#FBF9F4] p-3" data-testid={`photo-set-${ph.id}`}>
                <div className="flex items-center justify-between">
                  <div className="flex flex-wrap gap-2">
                    {attrDefs.map(([key, arr]) => (
                      <Select key={key} value={ph.attributes[key] || ""} onValueChange={(v) => updPhotoAttr(ph.id, key, v)}>
                        <SelectTrigger className="h-9 w-28 bg-white text-xs" data-testid={`photo-attr-${ph.id}-${key}`}><SelectValue placeholder={key} /></SelectTrigger>
                        <SelectContent>{(p.pricing?.[arr] || []).map((o) => <SelectItem key={o} value={String(o)}>{o}</SelectItem>)}</SelectContent>
                      </Select>
                    ))}
                  </div>
                  <div className="flex items-center gap-1">
                    <button onClick={() => setField("representative_photo_id", ph.id)} data-testid={`set-rep-${ph.id}`} title="Jadikan gambar kategori"
                      className={`p-1.5 ${p.representative_photo_id === ph.id ? "text-amber-500" : "text-[#8B7355]"}`}><Star size={16} fill={p.representative_photo_id === ph.id ? "currentColor" : "none"} /></button>
                    <button onClick={() => delPhoto(ph.id)} className="p-1.5 text-red-500"><Trash2 size={16} /></button>
                  </div>
                </div>
                <div className="mt-2 grid grid-cols-3 gap-2">
                  {["main_url", "front_url", "side_url"].map((slot) => (
                    <div key={slot}>
                      <div className="aspect-square overflow-hidden rounded-lg border border-[#E5DCC5] bg-white">
                        {ph[slot] ? <img src={imgUrl(ph[slot])} alt="" className="h-full w-full object-cover" /> : <div className="flex h-full items-center justify-center text-[10px] text-[#8B7355]">{slot === "main_url" ? "Utama" : slot === "front_url" ? "Depan" : "Samping"}</div>}
                      </div>
                      <input type="file" accept="image/*" hidden ref={(el) => (photoRefs.current[ph.id + slot] = el)} onChange={(e) => e.target.files[0] && uploadTo(e.target.files[0], (u) => updPhoto(ph.id, { [slot]: u }))} />
                      <button onClick={() => photoRefs.current[ph.id + slot]?.click()} data-testid={`photo-upload-${ph.id}-${slot}`} className="mt-1 w-full rounded-lg border border-[#8B5A2B] py-1 text-[10px] text-[#8B5A2B]">Unggah</button>
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
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
            <Label className="mb-1 block font-heading text-sm font-semibold">Konfigurasi Lanjutan (JSON)</Label>
            <p className="mb-2 text-xs text-[#8B7355]">Tipe, penyesuaian tipe, dan harga finishing.</p>
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
