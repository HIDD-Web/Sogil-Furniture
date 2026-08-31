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
  const [priority, setPriority] = useState([]);
  const [notes, setNotes] = useState({});
  const [coverPreview, setCoverPreview] = useState(null);
  const fileRef = useRef();
  const coverRef = useRef();
  const photoRefs = useRef({});

  useEffect(() => {
    api.get("/products?admin_view=true").then((r) => {
      const prod = r.data.find((x) => x.id === id);
      if (prod) {
        prod.photos = prod.photos || []; setP(prod); setPricingText(JSON.stringify(prod.pricing || {}, null, 2));
        const defs = PHOTO_ATTRS[prod.category] || [];
        const w = prod.photo_weights || {};
        const ordered = Object.keys(w).length ? [...defs.map((d) => d[0])].sort((a, b) => (w[b] || 0) - (w[a] || 0)) : defs.map((d) => d[0]);
        setPriority(ordered); setNotes(prod.option_notes || {});
      }
    });
  }, [id]);

  useEffect(() => {
    if (p?.cover_mode === "auto") api.get(`/admin/products/${id}/cover-preview`).then((r) => setCoverPreview(r.data)).catch(() => setCoverPreview(null));
    else setCoverPreview(null);
  }, [p?.cover_mode, id]);

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
    const photo_weights = {}; priority.forEach((k, i) => { photo_weights[k] = denom ? Math.round((n - i) / denom * 100) / 100 : 0; });
    const option_notes = Object.fromEntries(Object.entries(notes).filter(([, v]) => (v || "").trim()));
    try {
      await api.put(`/admin/products/${id}`, { name: p.name, category: p.category, description: p.description, image_url: p.image_url,
        active: p.active, configurable: p.configurable, starting_price_le: p.starting_price_le, pricing,
        photos: p.photos, representative_photo_id: p.representative_photo_id, photo_weights, option_notes,
        category_cover_image: p.category_cover_image || "", cover_mode: p.cover_mode || "manual" });
      toast.success("Produk disimpan"); navigate("/admin/products");
    } catch { toast.error("Gagal menyimpan"); }
  };
  const KEY_LABELS = { length: "Panjang", level: "Jumlah Tingkat", type: "Tipe", finishing: "Finishing", size: "Ukuran Meja", height: "Tinggi Meja", variant: "Varian/Tingkat" };
  const movePriority = (i, dir) => setPriority((prev) => { const a = [...prev]; const j = i + dir; if (j < 0 || j >= a.length) return prev; [a[i], a[j]] = [a[j], a[i]]; return a; });
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

        <div className="border-t border-[#F1EBE0] pt-4">
          <Label className="font-heading text-sm font-semibold">Gambar Cover Kategori</Label>
          <p className="mt-1 text-xs text-[#8B7355]">Gambar untuk halaman katalog. Terpisah dari foto konfigurasi — tidak dipakai sebagai foto tiap konfigurasi.</p>
          <div className="mt-2 flex items-center gap-3">
            <div className="h-20 w-20 overflow-hidden rounded-xl border border-[#E5DCC5] bg-white">
              {p.category_cover_image ? <img src={imgUrl(p.category_cover_image)} alt="" className="h-full w-full object-cover" /> : <div className="flex h-full items-center justify-center text-[10px] text-[#8B7355]">Cover</div>}
            </div>
            <input ref={coverRef} type="file" accept="image/*" hidden onChange={(e) => e.target.files[0] && uploadTo(e.target.files[0], (u) => setField("category_cover_image", u))} data-testid="cover-input" />
            <Button variant="outline" onClick={() => coverRef.current?.click()} data-testid="cover-upload" className="rounded-xl border-[#8B5A2B] text-xs text-[#8B5A2B]"><Upload size={14} className="mr-1" /> Unggah Cover</Button>
            {p.category_cover_image && <Button variant="ghost" onClick={() => setField("category_cover_image", "")} className="text-xs text-red-500">Hapus</Button>}
          </div>
          <div className="mt-3">
            <Label className="mb-1 block text-xs text-[#8B7355]">Mode Cover</Label>
            <Select value={p.cover_mode || "manual"} onValueChange={(v) => setField("cover_mode", v)}>
              <SelectTrigger className="w-56 bg-white" data-testid="cover-mode"><SelectValue /></SelectTrigger>
              <SelectContent><SelectItem value="manual">Manual (gambar di atas)</SelectItem><SelectItem value="auto">Otomatis (konfigurasi terlaris)</SelectItem></SelectContent>
            </Select>
          </div>
          {p.cover_mode === "auto" && (
            <div className="mt-3 rounded-xl border border-[#E5DCC5] bg-[#FBF9F4] p-3" data-testid="cover-auto-preview">
              <div className="text-xs font-semibold text-[#8B5A2B]">Pratinjau Cover Otomatis</div>
              {coverPreview?.selected ? (
                <div className="mt-2 flex items-center gap-3">
                  <div className="h-16 w-16 shrink-0 overflow-hidden rounded-lg border border-[#E5DCC5] bg-white">
                    {coverPreview.selected.image ? <img src={imgUrl(coverPreview.selected.image)} alt="" className="h-full w-full object-cover" /> : <div className="flex h-full items-center justify-center text-[10px] text-[#8B7355]">Tanpa foto</div>}
                  </div>
                  <div className="text-xs text-[#5C4A3D]">
                    <div className="font-medium text-[#2C1E16]">{p.name} — {config_summary_client(p.category, coverPreview.selected.config) || "Konfigurasi"}</div>
                    <div className="mt-0.5 text-[#8B7355]">Berdasarkan {coverPreview.selected.count} unit dipesan (konfigurasi terlaris)</div>
                    {!coverPreview.selected.image && <div className="mt-0.5 text-amber-600">Belum ada foto konfigurasi yang cocok — cover katalog akan kosong sampai foto ditambahkan.</div>}
                  </div>
                </div>
              ) : (
                <div className="mt-2 text-xs text-[#8B7355]">Belum ada pesanan untuk kategori ini, jadi belum ada konfigurasi terlaris yang bisa dipilih.</div>
              )}
            </div>
          )}
        </div>

        {/* Photo manager */}
        <div className="border-t border-[#F1EBE0] pt-4">
          <div className="flex items-center justify-between">
            <Label className="font-heading text-sm font-semibold">Foto Konfigurasi</Label>
            <Button variant="outline" onClick={addPhoto} data-testid="add-photo" className="rounded-xl border-[#8B5A2B] text-xs text-[#8B5A2B]"><Plus size={14} className="mr-1" /> Tambah Foto</Button>
          </div>
          <p className="mt-1 text-xs text-[#8B7355]">Tentukan atribut & foto per konfigurasi. Gunakan panah untuk mengatur urutan konfigurasi (↑↓) dan urutan foto di dalamnya (←→). Foto 1 = foto utama.</p>
          <div className="mt-3 max-h-[460px] space-y-3 overflow-y-auto rounded-xl border border-[#F1EBE0] p-2">
            {(p.photos || []).map((ph, idx) => (
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
                    <button onClick={() => movePhotoSet(idx, -1)} disabled={idx === 0} data-testid={`config-up-${ph.id}`} className="rounded border border-[#E5DCC5] p-1 text-[#8B5A2B] disabled:opacity-30"><ArrowUp size={14} /></button>
                    <button onClick={() => movePhotoSet(idx, 1)} disabled={idx === (p.photos.length - 1)} data-testid={`config-down-${ph.id}`} className="rounded border border-[#E5DCC5] p-1 text-[#8B5A2B] disabled:opacity-30"><ArrowDown size={14} /></button>
                    <button onClick={() => delPhoto(ph.id)} className="p-1.5 text-red-500"><Trash2 size={16} /></button>
                  </div>
                </div>
                <div className="mt-2 grid grid-cols-3 gap-2">
                  {["main_url", "front_url", "side_url"].map((slot, si) => (
                    <div key={slot} data-testid={`photo-slot-${ph.id}-${si}`}>
                      <div className="aspect-square overflow-hidden rounded-lg border border-[#E5DCC5] bg-white">
                        {ph[slot] ? <img src={imgUrl(ph[slot])} alt="" className="h-full w-full object-cover" /> : <div className="flex h-full items-center justify-center text-[10px] text-[#8B7355]">{si === 0 ? "Foto 1 (Utama)" : `Foto ${si + 1}`}</div>}
                      </div>
                      <input type="file" accept="image/*" hidden ref={(el) => (photoRefs.current[ph.id + slot] = el)} onChange={(e) => e.target.files[0] && uploadTo(e.target.files[0], (u) => updPhoto(ph.id, { [slot]: u }))} />
                      <div className="mt-1 flex items-center gap-1">
                        <button onClick={() => photoRefs.current[ph.id + slot]?.click()} data-testid={`photo-upload-${ph.id}-${slot}`} className="flex-1 rounded-lg border border-[#8B5A2B] py-1 text-[10px] text-[#8B5A2B]">Unggah</button>
                        <button onClick={() => moveSlot(ph.id, si, -1)} disabled={si === 0} data-testid={`photo-slot-left-${ph.id}-${si}`} className="rounded border border-[#E5DCC5] px-1 py-1 text-[#8B5A2B] disabled:opacity-30"><ArrowLeft size={12} /></button>
                        <button onClick={() => moveSlot(ph.id, si, 1)} disabled={si === 2} data-testid={`photo-slot-right-${ph.id}-${si}`} className="rounded border border-[#E5DCC5] px-1 py-1 text-[#8B5A2B] disabled:opacity-30"><ArrowRight size={12} /></button>
                      </div>
                    </div>
                  ))}
                </div>
                <div className="mt-2">
                  <div className="mb-1 text-[10px] font-medium text-[#8B7355]">Foto tambahan (boleh lebih dari 3)</div>
                  <div className="flex flex-wrap gap-2">
                    {(ph.images || []).map((u, ii) => (
                      <div key={ii} className="relative">
                        <div className="h-14 w-14 overflow-hidden rounded-lg border border-[#E5DCC5] bg-white"><img src={imgUrl(u)} alt="" className="h-full w-full object-cover" /></div>
                        <button onClick={() => updPhoto(ph.id, { images: (ph.images || []).filter((_, x) => x !== ii) })} data-testid={`img-del-${ph.id}-${ii}`} className="absolute -right-1 -top-1 flex h-4 w-4 items-center justify-center rounded-full bg-red-500 text-[10px] leading-none text-white">×</button>
                      </div>
                    ))}
                    <input type="file" accept="image/*" hidden ref={(el) => (photoRefs.current[ph.id + "add"] = el)} onChange={(e) => e.target.files[0] && uploadTo(e.target.files[0], (u) => updPhoto(ph.id, { images: [...(ph.images || []), u] }))} />
                    <button onClick={() => photoRefs.current[ph.id + "add"]?.click()} data-testid={`add-photo-${ph.id}`} className="flex h-14 w-14 items-center justify-center rounded-lg border-2 border-dashed border-[#8B5A2B] text-[#8B5A2B]"><Plus size={16} /></button>
                  </div>
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
            <Label className="mb-1 block font-heading text-sm font-semibold">Prioritas Pencocokan Foto</Label>
            <p className="mb-2 text-xs text-[#8B7355]">Urutan ini khusus produk ini. Menentukan opsi mana yang paling diprioritaskan saat memilih foto terdekat (bila tidak ada foto sama persis).</p>
            <div className="space-y-1.5">
              {priority.map((k, i) => (
                <div key={k} className="flex items-center justify-between rounded-xl border border-[#E5DCC5] bg-[#FBF9F4] px-3 py-2" data-testid={`priority-${k}`}>
                  <span className="text-sm text-[#2C1E16]"><b className="mr-1 text-[#8B5A2B]">{i + 1}.</b> {KEY_LABELS[k] || k}</span>
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

        {p.configurable && attrDefs.length > 0 && (
          <div className="border-t border-[#F1EBE0] pt-4">
            <Label className="mb-1 block font-heading text-sm font-semibold">Catatan Opsi (Notes)</Label>
            <p className="mb-2 text-xs text-[#8B7355]">Catatan opsional per grup opsi (mis. "Jarak per tingkat ± 28 cm"). Kosongkan bila tidak perlu — tidak akan tampil.</p>
            <div className="space-y-2">
              {attrDefs.map(([key]) => (
                <div key={key}>
                  <Label className="mb-0.5 block text-xs text-[#8B7355]">{KEY_LABELS[key] || key}</Label>
                  <Input value={notes[key] || ""} onChange={(e) => setNotes((prev) => ({ ...prev, [key]: e.target.value }))} data-testid={`note-${key}`} placeholder="Catatan (opsional)" className="bg-white" />
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
