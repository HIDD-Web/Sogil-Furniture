import React from "react";
import { Link } from "react-router-dom";
import { Logo } from "./Logo";
import { MapPin, Phone } from "lucide-react";

export const Footer = ({ storeInfo }) => {
  return (
    <footer className="mt-16 border-t border-[#E5DCC5] bg-[#F1EBE0]">
      <div className="mx-auto max-w-6xl px-4 py-10 sm:px-6">
        <div className="grid gap-8 md:grid-cols-3">
          <div>
            <Logo />
            <p className="mt-3 max-w-xs text-sm text-[#5C4A3D]">
              {storeInfo?.tagline || "Kualitas Terbaik, Untuk Ruang Terbaik"}
            </p>
          </div>
          <div className="text-sm text-[#5C4A3D]">
            <div className="mb-2 font-heading font-semibold text-[#2C1E16]">Navigasi</div>
            <div className="flex flex-col gap-1.5">
              <Link to="/produk" className="hover:text-[#8B5A2B]">Produk</Link>
              <Link to="/cara-pesan" className="hover:text-[#8B5A2B]">Cara Pesan</Link>
              <Link to="/kontak" className="hover:text-[#8B5A2B]">Kontak</Link>
            </div>
          </div>
          <div className="text-sm text-[#5C4A3D]">
            <div className="mb-2 font-heading font-semibold text-[#2C1E16]">Toko</div>
            {storeInfo?.store_address && (
              <p className="flex items-start gap-2"><MapPin size={16} className="mt-0.5 shrink-0" />{storeInfo.store_address}</p>
            )}
            {storeInfo?.whatsapp_number && (
              <p className="mt-2 flex items-center gap-2"><Phone size={16} />{storeInfo.whatsapp_number}</p>
            )}
          </div>
        </div>
        <div className="mt-8 border-t border-[#E5DCC5] pt-5 text-xs text-[#8B7355]">
          © {new Date().getFullYear()} Sogil Furniture. Semua harga merupakan estimasi.
        </div>
      </div>
    </footer>
  );
};

export default Footer;
