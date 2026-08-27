import React from "react";
import { useNavigate } from "react-router-dom";
import { Button } from "../components/ui/button";
import { Package, SlidersHorizontal, Receipt, Truck, User, ClipboardCheck, MessageCircle } from "lucide-react";

const STEPS = [
  { icon: Package, title: "Pilih Produk", desc: "Buka katalog dan pilih furniture yang kamu butuhkan." },
  { icon: SlidersHorizontal, title: "Sesuaikan Pesanan", desc: "Atur ukuran, jumlah tingkat, tipe, dan finishing." },
  { icon: Receipt, title: "Lihat Estimasi Harga", desc: "Harga langsung terhitung otomatis, tanpa reload." },
  { icon: Truck, title: "Pilih Pengiriman", desc: "Ambil di toko atau kirim ke alamatmu." },
  { icon: User, title: "Isi Data", desc: "Masukkan nama, no HP, dan alamat." },
  { icon: ClipboardCheck, title: "Review Pesanan", desc: "Periksa kembali semua detail pesananmu." },
  { icon: MessageCircle, title: "Pesan via WhatsApp", desc: "Pesanan tersimpan lalu diarahkan ke WhatsApp admin." },
];

export default function CaraPesan() {
  const navigate = useNavigate();
  return (
    <div className="mx-auto max-w-3xl px-4 py-12 sm:px-6">
      <h1 className="font-heading text-3xl font-bold tracking-tight text-[#2C1E16] sm:text-4xl">Cara Pesan</h1>
      <p className="mt-2 text-[#5C4A3D]">Prosesnya mudah — kamu bisa tahu estimasi harga sendiri tanpa perlu tanya admin dulu.</p>

      <div className="mt-8 space-y-3">
        {STEPS.map((s, i) => (
          <div key={s.title} className="flex items-start gap-4 rounded-2xl border border-[#E5DCC5] bg-white p-5 shadow-sm">
            <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-[#EFE6D5] text-[#8B5A2B]">
              <s.icon size={22} />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="font-heading text-sm font-bold text-[#8B5A2B]">{i + 1}.</span>
                <h3 className="font-heading text-lg font-semibold text-[#2C1E16]">{s.title}</h3>
              </div>
              <p className="mt-0.5 text-sm leading-relaxed text-[#5C4A3D]">{s.desc}</p>
            </div>
          </div>
        ))}
      </div>

      <Button onClick={() => navigate("/produk")} data-testid="carapesan-cta"
        className="mt-8 h-12 w-full rounded-full bg-[#8B5A2B] text-base hover:bg-[#6B4423] sm:w-auto sm:px-8">
        Mulai Pesan Sekarang
      </Button>
    </div>
  );
}
