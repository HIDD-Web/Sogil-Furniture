import React, { useState, useEffect } from "react";
import api, { imgUrl } from "../../lib/api";
import { formatApiError } from "../../lib/format";
import { Button } from "../ui/button";
import { Input } from "../ui/input";
import { Label } from "../ui/label";
import { Textarea } from "../ui/textarea";
import { Sparkles, Upload, X, Image as ImageIcon, Loader2 } from "lucide-react";
import { toast } from "sonner";

export default function PublishCustomCollectionModal({
  isOpen,
  onClose,
  initialData = {},
  onSuccess,
}) {
  const [title, setTitle] = useState("");
  const [priceLe, setPriceLe] = useState("");
  const [spesifikasi, setSpesifikasi] = useState("");
  const [photoUrls, setPhotoUrls] = useState([]);
  const [uploading, setUploading] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (isOpen) {
      setTitle(initialData.title || "");
      setPriceLe(initialData.price_le ? String(initialData.price_le) : "");
      setSpesifikasi(initialData.spesifikasi || "");
      setPhotoUrls(initialData.photo_urls || []);
    }
  }, [isOpen, initialData]);

  if (!isOpen) return null;

  const handleFileUpload = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;

    const fd = new FormData();
    fd.append("file", file);

    setUploading(true);
    try {
      const { data } = await api.post("/admin/upload", fd, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      if (data?.url) {
        setPhotoUrls((prev) => [...prev, data.url]);
        toast.success("Foto berhasil diunggah");
      }
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail) || "Gagal mengunggah foto");
    } finally {
      setUploading(false);
      e.target.value = "";
    }
  };

  const removePhoto = (idx) => {
    setPhotoUrls((prev) => prev.filter((_, i) => i !== idx));
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    const cleanTitle = title.trim();
    if (!cleanTitle) return toast.error("Nama desain harus diisi");
    if (!priceLe || Number(priceLe) <= 0) return toast.error("Harga acuan (LE) harus diisi valid");

    setSubmitting(true);
    try {
      const payload = {
        title: cleanTitle,
        price_le: Number(priceLe),
        spesifikasi: spesifikasi.trim(),
        photo_urls: photoUrls,
        order_id: initialData.order_id || null,
        request_id: initialData.request_id || null,
      };

      const { data } = await api.post("/admin/custom-collection/publish", payload);
      toast.success(`Desain "${cleanTitle}" berhasil dipublikasikan ke Koleksi Custom!`);
      if (onSuccess) onSuccess(data);
      onClose();
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail) || "Gagal mempublikasikan ke koleksi custom");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-xs animate-in fade-in">
      <div className="relative w-full max-w-lg rounded-2xl border border-[#E5DCC5] bg-white p-5 sm:p-6 shadow-xl max-h-[90vh] overflow-y-auto">
        <button
          onClick={onClose}
          className="absolute right-4 top-4 rounded-full p-1.5 text-[#8B7355] hover:bg-[#F9F6F0] hover:text-[#2C1E16]"
        >
          <X size={18} />
        </button>

        <div className="flex items-center gap-2 mb-1">
          <div className="p-2 rounded-xl bg-[#FAF5EE] text-[#8B5A2B]">
            <Sparkles size={20} />
          </div>
          <div>
            <h2 className="font-heading text-lg font-bold text-[#2C1E16]">
              Publikasikan ke Koleksi Custom
            </h2>
            <p className="text-xs text-[#8B7355]">
              Pajang hasil karya pesanan ini di halaman katalog Koleksi Custom agar dapat dilihat customer.
            </p>
          </div>
        </div>

        <form onSubmit={handleSubmit} className="mt-4 space-y-3.5">
          <div>
            <Label className="text-xs font-semibold text-[#2C1E16] mb-1 block">
              Nama Desain / Judul Karya <span className="text-red-500">*</span>
            </Label>
            <Input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Contoh: Meja Belajar & Rak Sudut Minimalis"
              className="bg-white text-xs sm:text-sm"
              required
            />
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <Label className="text-xs font-semibold text-[#2C1E16] mb-1 block">
                Estimasi Harga Acuan (LE) <span className="text-red-500">*</span>
              </Label>
              <Input
                type="number"
                value={priceLe}
                onChange={(e) => setPriceLe(e.target.value)}
                placeholder="Contoh: 2450"
                className="bg-white text-xs sm:text-sm"
                required
              />
            </div>
            <div>
              <Label className="text-xs font-semibold text-[#2C1E16] mb-1 block">
                Kategori
              </Label>
              <Input
                value="Koleksi Custom"
                disabled
                className="bg-[#FAF5EE] text-xs sm:text-sm text-[#8B7355]"
              />
            </div>
          </div>

          <div>
            <Label className="text-xs font-semibold text-[#2C1E16] mb-1 block">
              Spesifikasi / Detail Ukuran & Bahan
            </Label>
            <Textarea
              value={spesifikasi}
              onChange={(e) => setSpesifikasi(e.target.value)}
              placeholder="Contoh: Ukuran 120x60x75 cm, Multiplek 18mm lapis HPL serat kayu, Rangka besi hollow 3x3 cm hitam doff"
              className="bg-white text-xs sm:text-sm min-h-[60px]"
            />
          </div>

          <div>
            <div className="flex items-center justify-between mb-1.5">
              <Label className="text-xs font-semibold text-[#2C1E16]">
                Foto Hasil Jadi / Produk ({photoUrls.length} Foto)
              </Label>
              <label className="inline-flex items-center gap-1 text-xs font-medium text-[#8B5A2B] hover:text-[#6B4423] cursor-pointer">
                {uploading ? (
                  <span className="flex items-center gap-1 text-[#8B7355]">
                    <Loader2 size={13} className="animate-spin" /> Mengunggah...
                  </span>
                ) : (
                  <>
                    <Upload size={13} /> + Unggah Foto Baru
                  </>
                )}
                <input
                  type="file"
                  accept="image/*"
                  onChange={handleFileUpload}
                  disabled={uploading}
                  className="hidden"
                />
              </label>
            </div>

            {photoUrls.length === 0 ? (
              <div className="rounded-xl border border-dashed border-[#E5DCC5] bg-[#FAF5EE]/60 p-4 text-center">
                <ImageIcon size={24} className="mx-auto text-[#8B7355] mb-1 opacity-60" />
                <p className="text-xs text-[#8B7355]">
                  Belum ada foto yang dipilih. Silakan unggah foto hasil jadi furniture workshop.
                </p>
              </div>
            ) : (
              <div className="grid grid-cols-3 sm:grid-cols-4 gap-2 pt-1">
                {photoUrls.map((url, idx) => (
                  <div
                    key={idx}
                    className="group relative aspect-square rounded-xl overflow-hidden border border-[#E5DCC5] bg-zinc-100"
                  >
                    <img
                      src={imgUrl(url)}
                      alt={`Foto ${idx + 1}`}
                      className="h-full w-full object-cover"
                    />
                    {idx === 0 && (
                      <span className="absolute bottom-1 left-1 rounded-md bg-black/70 px-1 py-0.5 text-[9px] text-white font-medium">
                        Utama
                      </span>
                    )}
                    <button
                      type="button"
                      onClick={() => removePhoto(idx)}
                      className="absolute top-1 right-1 rounded-full bg-black/60 p-1 text-white opacity-0 group-hover:opacity-100 transition-opacity hover:bg-red-600"
                      title="Hapus Foto"
                    >
                      <X size={11} />
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="mt-5 flex justify-end gap-2 pt-3 border-t border-[#F1EBE0]">
            <Button
              type="button"
              variant="outline"
              onClick={onClose}
              className="rounded-xl text-xs sm:text-sm"
            >
              Batal
            </Button>
            <Button
              type="submit"
              disabled={submitting || uploading}
              className="rounded-xl bg-[#8B5A2B] hover:bg-[#6B4423] text-white text-xs sm:text-sm font-semibold flex items-center gap-1.5"
            >
              {submitting ? (
                <>
                  <Loader2 size={14} className="animate-spin" /> Mempublikasikan...
                </>
              ) : (
                <>
                  <Sparkles size={14} /> Publikasikan ke Katalog
                </>
              )}
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}
