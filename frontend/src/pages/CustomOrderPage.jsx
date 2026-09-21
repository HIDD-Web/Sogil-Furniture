import React, { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { ChevronLeft, Upload, X, MessageCircle, Sparkles, CheckCircle2, Image as ImageIcon } from "lucide-react";
import api from "../lib/api";
import { normalizeEgyptPhone, validEgyptPhone } from "../lib/photoMatch";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Textarea } from "../components/ui/textarea";
import { Label } from "../components/ui/label";
import { useCustomer } from "../context/CustomerContext";
import { toast } from "sonner";

const FURNITURE_TYPES = [
  "Meja Belajar",
  "Rak Buku",
  "Meja Rak",
  "Rak Gantung",
  "Lainnya",
];

const BAHAN_CHOICES = [
  "Blockboard",
  "Fiber Lapis HPL",
];

const FINISHING_CHOICES = [
  "Natural Halus",
  "Pernis Mengkilap",
];

export default function CustomOrderPage() {
  const navigate = useNavigate();
  const { customer } = useCustomer();

  const [form, setForm] = useState({
    customer_name: "",
    customer_phone: "",
    phone_number: "",
    customer_address: "",
    furniture_type: "",
    custom_type: "",
    length: "",
    width: "",
    height: "",
    dimension_notes: "",
    material: "",
    budget_estimation_le: "",
    notes: "",
  });

  const [photos, setPhotos] = useState([]);
  const [uploading, setUploading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [successData, setSuccessData] = useState(null);
  const [selectedBahan, setSelectedBahan] = useState("");
  const [selectedFinishing, setSelectedFinishing] = useState("");
  const [isUnsure, setIsUnsure] = useState(false);

  const handleSelectBahan = (bahan) => {
    const nextBahan = selectedBahan === bahan ? "" : bahan;
    setSelectedBahan(nextBahan);
    setIsUnsure(false);
    const parts = [nextBahan, selectedFinishing].filter(Boolean);
    setForm((f) => ({ ...f, material: parts.join(" · ") }));
  };

  const handleSelectFinishing = (finishing) => {
    const nextFinishing = selectedFinishing === finishing ? "" : finishing;
    setSelectedFinishing(nextFinishing);
    setIsUnsure(false);
    const parts = [selectedBahan, nextFinishing].filter(Boolean);
    setForm((f) => ({ ...f, material: parts.join(" · ") }));
  };

  const handleSelectUnsure = () => {
    if (isUnsure) {
      setIsUnsure(false);
      setForm((f) => ({ ...f, material: "" }));
    } else {
      setIsUnsure(true);
      setSelectedBahan("");
      setSelectedFinishing("");
      setForm((f) => ({ ...f, material: "Belum Yakin (Konsultasikan)" }));
    }
  };

  useEffect(() => {
    if (customer) {
      setForm((f) => ({
        ...f,
        customer_name: f.customer_name || customer.name || "",
        customer_phone: f.customer_phone || customer.phone || "",
      }));
    }
  }, [customer]);

  const handlePhotoUpload = async (e) => {
    const files = Array.from(e.target.files || []);
    if (!files.length) return;

    if (photos.length + files.length > 5) {
      toast.error("Maksimal 5 foto referensi");
      return;
    }

    setUploading(true);
    let successCount = 0;

    for (const file of files) {
      if (file.size > 10 * 1024 * 1024) {
        toast.error(`Ukuran file "${file.name}" melebihi batas 10MB`);
        continue;
      }
      try {
        const formData = new FormData();
        formData.append("file", file);
        const { data } = await api.post("/upload-reference", formData, {
          headers: { "Content-Type": "multipart/form-data" },
        });
        if (data.url) {
          setPhotos((prev) => [...prev, data.url]);
          successCount++;
        }
      } catch (err) {
        toast.error(`Gagal mengunggah foto "${file.name}"`);
      }
    }

    setUploading(false);
    if (successCount > 0) {
      toast.success(`${successCount} foto berhasil diunggah`);
    }
  };

  const removePhoto = (idx) => {
    setPhotos((prev) => prev.filter((_, i) => i !== idx));
  };

  const handleSubmit = async (e) => {
    e.preventDefault();

    const selectedType = form.furniture_type === "Lainnya" && form.custom_type.trim()
      ? form.custom_type.trim()
      : form.furniture_type;

    if (!selectedType) {
      toast.error("Pilih atau isi jenis furniture yang diinginkan");
      return;
    }

    if (!form.customer_name.trim()) {
      toast.error("Nama lengkap wajib diisi");
      return;
    }

    if (!form.customer_phone.trim()) {
      toast.error("Nomor WhatsApp wajib diisi");
      return;
    }

    let normEgyptPhone = null;
    if (form.phone_number && form.phone_number.trim()) {
      normEgyptPhone = normalizeEgyptPhone(form.phone_number);
      if (!validEgyptPhone(normEgyptPhone)) {
        toast.error("Nomor telepon harus nomor Mesir dengan kode negara +20.");
        return;
      }
    }

    setSubmitting(true);
    try {
      const payload = {
        customer_name: form.customer_name.trim(),
        customer_phone: form.customer_phone.trim(),
        phone_number: normEgyptPhone,
        customer_address: form.customer_address.trim(),
        furniture_type: selectedType,
        dimensions: {
          length: form.length ? String(form.length) : null,
          width: form.width ? String(form.width) : null,
          height: form.height ? String(form.height) : null,
          notes: form.dimension_notes ? form.dimension_notes.trim() : null,
        },
        material: form.material || "",
        reference_photos: photos,
        budget_estimation_le: form.budget_estimation_le ? Number(form.budget_estimation_le) : null,
        notes: form.notes.trim(),
      };

      const { data } = await api.post("/custom-requests", payload);
      setSuccessData(data);
      toast.success("Request custom berhasil diajukan!");
    } catch (err) {
      toast.error(err.response?.data?.detail || "Gagal mengajukan request custom");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#F9F6F0] py-4 pb-20 sm:py-8 sm:pb-24">
      <div className="mx-auto max-w-3xl px-3 sm:px-6">
        <button
          onClick={() => navigate(-1)}
          className="mb-4 inline-flex items-center gap-1 text-xs sm:text-sm font-medium text-[#8B5A2B] hover:underline"
        >
          <ChevronLeft size={16} /> Kembali
        </button>

        {successData ? (
          <div className="overflow-hidden rounded-3xl border border-[#E5DCC5] bg-white p-6 sm:p-8 text-center shadow-sm">
            <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-full bg-emerald-50 text-emerald-600">
              <CheckCircle2 size={36} />
            </div>

            <h1 className="mt-4 font-heading text-2xl font-bold text-[#2C1E16] sm:text-3xl">
              Request Custom Berhasil Dibuat!
            </h1>

            <p className="mt-2 text-sm text-[#5C4A3D]">
              Nomor tiket request Anda:
            </p>

            <div className="mt-1 inline-block rounded-xl border border-[#E5DCC5] bg-[#FBF9F4] px-4 py-2 font-mono text-lg font-bold text-[#8B5A2B]">
              {successData.ticket_number}
            </div>

            <div className="mx-auto mt-6 max-w-md rounded-2xl border border-amber-200 bg-amber-50/70 p-4 text-left text-xs sm:text-sm text-amber-900">
              <p className="font-semibold">Langkah Selanjutnya:</p>
              <p className="mt-1">
                Tekan tombol di bawah untuk langsung terhubung ke WhatsApp Sogil Furniture. Detail request Anda telah disiapkan secara rapi agar tim kami bisa langsung memberikan estimasi biaya dan waktu produksi.
              </p>
            </div>

            <div className="mt-6 flex flex-col gap-3 sm:flex-row sm:justify-center">
              <a
                href={successData.whatsapp_url}
                target="_blank"
                rel="noreferrer"
                className="w-full sm:w-auto"
              >
                <Button className="h-12 w-full rounded-full bg-[#25D366] px-8 text-sm font-semibold text-white hover:bg-[#1EBE5D] shadow-md">
                  <MessageCircle size={18} className="mr-2" /> Lanjutkan ke WhatsApp
                </Button>
              </a>

              <Button
                variant="outline"
                onClick={() => navigate("/")}
                className="h-12 w-full sm:w-auto rounded-full border-[#E5DCC5] px-6 text-sm text-[#5C4A3D]"
              >
                Kembali ke Beranda
              </Button>
            </div>
          </div>
        ) : (
          <div className="space-y-6">
            {/* Header Card */}
            <div className="rounded-3xl border border-[#E5DCC5] bg-gradient-to-br from-[#8B5A2B] to-[#5C3B18] p-6 text-white shadow-sm sm:p-8">
              <div className="inline-flex items-center gap-2 rounded-full bg-white/20 px-3 py-1 text-xs font-semibold text-white backdrop-blur-sm">
                <Sparkles size={14} /> Pesanan Custom Sogil
              </div>
              <h1 className="mt-3 font-heading text-2xl font-bold tracking-tight sm:text-3xl">
                Wujudkan Furniture Impian Anda
              </h1>
              <p className="mt-2 text-xs text-white/90 sm:text-sm leading-relaxed">
                Punya desain sendiri, foto inspirasi dari internet, atau ukuran ruangan yang spesifik? Kirimkan detailnya ke kami, tim Sogil Furniture siap membantu menghitung estimasi biaya dan memproduksinya dengan material terbaik.
              </p>
            </div>

            {/* Form */}
            <form onSubmit={handleSubmit} className="space-y-5 rounded-3xl border border-[#E5DCC5] bg-white p-5 sm:p-8 shadow-sm">
              {/* 1. Upload Foto Referensi / Sketsa */}
              <div>
                <Label className="block text-sm font-bold text-[#2C1E16]">
                  1. Foto Referensi / Sketsa Desain
                </Label>
                <p className="mt-0.5 text-xs text-[#8B7355]">
                  Lampirkan foto dari Pinterest, Google, atau sketsa corat-coret tangan (maksimal 5 foto).
                </p>

                <div className="mt-3 flex flex-wrap gap-3">
                  {photos.map((url, idx) => (
                    <div
                      key={idx}
                      className="group relative h-24 w-24 overflow-hidden rounded-xl border border-[#E5DCC5] bg-[#FBF9F4]"
                    >
                      <img
                        src={url}
                        alt="Referensi"
                        className="h-full w-full object-cover"
                      />
                      <button
                        type="button"
                        onClick={() => removePhoto(idx)}
                        className="absolute right-1 top-1 flex h-6 w-6 items-center justify-center rounded-full bg-red-600 text-white opacity-90 transition-opacity hover:opacity-100"
                        title="Hapus foto"
                      >
                        <X size={14} />
                      </button>
                    </div>
                  ))}

                  {photos.length < 5 && (
                    <label className="flex h-24 w-24 cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed border-[#D5C7AF] bg-[#FBF9F4] text-[#8B7355] transition-colors hover:border-[#8B5A2B] hover:bg-[#F4EFE6]">
                      {uploading ? (
                        <span className="text-xs font-medium animate-pulse">Mengunggah...</span>
                      ) : (
                        <>
                          <Upload size={20} className="text-[#8B5A2B]" />
                          <span className="mt-1 text-[10px] font-semibold">Tambah Foto</span>
                        </>
                      )}
                      <input
                        type="file"
                        accept="image/png, image/jpeg, image/webp"
                        multiple
                        onChange={handlePhotoUpload}
                        disabled={uploading}
                        className="hidden"
                      />
                    </label>
                  )}
                </div>
              </div>

              {/* 2. Jenis Furniture */}
              <div className="border-t border-[#F1EBE0] pt-5">
                <Label className="block text-sm font-bold text-[#2C1E16]">
                  2. Jenis Furniture <span className="text-red-500">*</span>
                </Label>
                <div className="mt-2.5 flex flex-wrap gap-2">
                  {FURNITURE_TYPES.map((type) => {
                    const isSelected = form.furniture_type === type;
                    return (
                      <button
                        key={type}
                        type="button"
                        onClick={() => setForm({ ...form, furniture_type: type })}
                        className={`rounded-xl border px-3.5 py-2 text-xs sm:text-sm font-medium transition-colors ${
                          isSelected
                            ? "border-[#8B5A2B] bg-[#8B5A2B] text-white"
                            : "border-[#E5DCC5] bg-white text-[#5C4A3D] hover:bg-[#FBF9F4]"
                        }`}
                      >
                        {type}
                      </button>
                    );
                  })}
                </div>

                {form.furniture_type === "Lainnya" && (
                  <Input
                    type="text"
                    placeholder="Tuliskan jenis furniture yang Anda inginkan..."
                    value={form.custom_type}
                    onChange={(e) => setForm({ ...form, custom_type: e.target.value })}
                    className="mt-3 bg-[#FBF9F4]"
                  />
                )}
              </div>

              {/* 3. Ukuran */}
              <div className="border-t border-[#F1EBE0] pt-5">
                <Label className="block text-sm font-bold text-[#2C1E16]">
                  3. Perkiraan Ukuran (cm)
                </Label>
                <p className="mt-0.5 text-xs text-[#8B7355]">
                  Isi ukuran yang diinginkan atau sesuaikan dengan ruangan Anda.
                </p>

                <div className="mt-3 grid grid-cols-3 gap-2 sm:gap-4">
                  <div>
                    <span className="text-[11px] font-semibold text-[#8B7355]">Panjang (P)</span>
                    <Input
                      type="number"
                      placeholder="misal: 100"
                      value={form.length}
                      onChange={(e) => setForm({ ...form, length: e.target.value })}
                      className="mt-1 bg-[#FBF9F4]"
                    />
                  </div>
                  <div>
                    <span className="text-[11px] font-semibold text-[#8B7355]">Lebar (L)</span>
                    <Input
                      type="number"
                      placeholder="misal: 50"
                      value={form.width}
                      onChange={(e) => setForm({ ...form, width: e.target.value })}
                      className="mt-1 bg-[#FBF9F4]"
                    />
                  </div>
                  <div>
                    <span className="text-[11px] font-semibold text-[#8B7355]">Tinggi (T)</span>
                    <Input
                      type="number"
                      placeholder="misal: 75"
                      value={form.height}
                      onChange={(e) => setForm({ ...form, height: e.target.value })}
                      className="mt-1 bg-[#FBF9F4]"
                    />
                  </div>
                </div>

                <Input
                  type="text"
                  placeholder="Catatan ukuran tambahan (opsional, misal: tinggi rak atas 30 cm)"
                  value={form.dimension_notes}
                  onChange={(e) => setForm({ ...form, dimension_notes: e.target.value })}
                  className="mt-2.5 bg-[#FBF9F4] text-xs"
                />
              </div>

              {/* 4. Pilihan Bahan & Finishing */}
              <div className="border-t border-[#F1EBE0] pt-5">
                <Label className="block text-sm font-bold text-[#2C1E16]">
                  4. Pilihan Bahan & Finishing
                </Label>
                <p className="mt-0.5 text-xs text-[#8B7355]">
                  Pilih bahan dan finishing yang diinginkan, atau konsultasikan jika belum yakin.
                </p>

                <div className="mt-3 space-y-3">
                  {/* Baris 1: Bahan */}
                  <div>
                    <span className="text-[11px] font-semibold text-[#8B7355]">Bahan</span>
                    <div className="mt-1.5 flex flex-wrap gap-2">
                      {BAHAN_CHOICES.map((choice) => {
                        const isSelected = selectedBahan === choice;
                        return (
                          <button
                            key={choice}
                            type="button"
                            onClick={() => handleSelectBahan(choice)}
                            className={`rounded-xl border px-3.5 py-1.5 text-xs sm:text-sm font-medium transition-colors ${
                              isSelected
                                ? "border-[#8B5A2B] bg-[#8B5A2B] text-white"
                                : "border-[#E5DCC5] bg-white text-[#5C4A3D] hover:bg-[#FBF9F4]"
                            }`}
                          >
                            {choice}
                          </button>
                        );
                      })}
                    </div>
                  </div>

                  {/* Baris 2: Finishing */}
                  <div>
                    <span className="text-[11px] font-semibold text-[#8B7355]">Finishing</span>
                    <div className="mt-1.5 flex flex-wrap gap-2">
                      {FINISHING_CHOICES.map((choice) => {
                        const isSelected = selectedFinishing === choice;
                        return (
                          <button
                            key={choice}
                            type="button"
                            onClick={() => handleSelectFinishing(choice)}
                            className={`rounded-xl border px-3.5 py-1.5 text-xs sm:text-sm font-medium transition-colors ${
                              isSelected
                                ? "border-[#8B5A2B] bg-[#8B5A2B] text-white"
                                : "border-[#E5DCC5] bg-white text-[#5C4A3D] hover:bg-[#FBF9F4]"
                            }`}
                          >
                            {choice}
                          </button>
                        );
                      })}
                    </div>
                  </div>

                  {/* Baris 3: Belum Yakin */}
                  <div>
                    <button
                      type="button"
                      onClick={handleSelectUnsure}
                      className={`rounded-xl border px-3.5 py-1.5 text-xs sm:text-sm font-medium transition-colors ${
                        isUnsure
                          ? "border-[#8B5A2B] bg-[#8B5A2B] text-white"
                          : "border-[#E5DCC5] bg-white text-[#5C4A3D] hover:bg-[#FBF9F4]"
                      }`}
                    >
                      Belum Yakin (Konsultasikan)
                    </button>
                  </div>
                </div>
              </div>

              {/* 5. Catatan Kebutuhan Khusus & Budget */}
              <div className="border-t border-[#F1EBE0] pt-5">
                <Label className="block text-sm font-bold text-[#2C1E16]">
                  5. Keterangan Tambahan & Kebutuhan Khusus
                </Label>
                <Textarea
                  placeholder="Ceritakan detail ruangan, fungsionalitas khusus (misal: harus muat galon, ada laci berkunci, knockdown/bisa dibongkar-pasang, dll)..."
                  value={form.notes}
                  onChange={(e) => setForm({ ...form, notes: e.target.value })}
                  className="mt-2 min-h-[90px] bg-[#FBF9F4]"
                />

                <div className="mt-3">
                  <span className="text-xs font-semibold text-[#8B7355]">
                    Estimasi Budget Anda (Opsional, dalam LE)
                  </span>
                  <Input
                    type="number"
                    placeholder="Contoh: 1500"
                    value={form.budget_estimation_le}
                    onChange={(e) => setForm({ ...form, budget_estimation_le: e.target.value })}
                    className="mt-1 max-w-xs bg-[#FBF9F4]"
                  />
                </div>
              </div>

              {/* 6. Informasi Kontak */}
              <div className="border-t border-[#F1EBE0] pt-5">
                <Label className="block text-sm font-bold text-[#2C1E16]">
                  6. Informasi Kontak Anda <span className="text-red-500">*</span>
                </Label>

                <div className="mt-3 grid gap-3 sm:grid-cols-2">
                  <div>
                    <span className="text-xs font-semibold text-[#8B7355]">Nama Lengkap</span>
                    <Input
                      type="text"
                      placeholder="Nama Anda"
                      value={form.customer_name}
                      onChange={(e) => setForm({ ...form, customer_name: e.target.value })}
                      required
                      className="mt-1 bg-[#FBF9F4]"
                    />
                  </div>
                  <div>
                    <span className="text-xs font-semibold text-[#8B7355]">Nomor WhatsApp *</span>
                    <Input
                      type="tel"
                      placeholder="Contoh: +62xxxxxxxxxx"
                      value={form.customer_phone}
                      onChange={(e) => setForm({ ...form, customer_phone: e.target.value })}
                      required
                      className="mt-1 bg-[#FBF9F4]"
                    />
                    <p className="mt-1 text-[11px] text-[#8B7355]">
                      Gunakan format internasional dengan kode negara, misalnya +20, +62, atau +60.
                    </p>
                  </div>
                </div>

                <div className="mt-3">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-semibold text-[#8B7355]">Nomor Telepon</span>
                    <span className="text-[11px] text-[#8B7355]">(Opsional — khusus nomor Mesir)</span>
                  </div>
                  <div className="relative mt-1 flex items-center">
                    <span className="absolute left-3 text-xs font-medium text-[#8B7355] select-none">+20</span>
                    <Input
                      type="tel"
                      placeholder="1x xxxx xxxx"
                      value={form.phone_number}
                      onChange={(e) => setForm({ ...form, phone_number: e.target.value })}
                      data-testid="input-custom-phone-number"
                      className="bg-[#FBF9F4] pl-11"
                    />
                  </div>
                  <p className="mt-1 text-[11px] text-[#8B7355]">
                    Nomor panggilan telepon lokal Mesir (opsional jika memiliki nomor Mesir).
                  </p>
                </div>

                <div className="mt-3">
                  <span className="text-xs font-semibold text-[#8B7355]">Alamat / Wilayah di Cairo (Opsional)</span>
                  <Input
                    type="text"
                    placeholder="Contoh: Darasah, Hay Asyir, Buuts..."
                    value={form.customer_address}
                    onChange={(e) => setForm({ ...form, customer_address: e.target.value })}
                    className="mt-1 bg-[#FBF9F4]"
                  />
                </div>
              </div>

              {/* Submit Button */}
              <div className="pt-4">
                <Button
                  type="submit"
                  disabled={submitting || uploading}
                  className="h-12 w-full rounded-full bg-[#8B5A2B] text-sm font-semibold text-white hover:bg-[#6B4423] shadow-md transition-all"
                >
                  {submitting ? "Memproses Request..." : "Kirim Request & Hubungi via WhatsApp"}
                </Button>
                <p className="mt-2 text-center text-[11px] text-[#8B7355]">
                  Data Anda tersimpan di sistem kami dan akan otomatis membuka WhatsApp untuk memulai konsultasi.
                </p>
              </div>
            </form>
          </div>
        )}
      </div>
    </div>
  );
}
