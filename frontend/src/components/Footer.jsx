import React from "react";
import { Link } from "react-router-dom";
import { Logo } from "./Logo";
import { MapPin, Instagram, Facebook, Mail, MessageCircle, Music2 } from "lucide-react";

const extractHandle = (url, fallback) => {
  if (!url || typeof url !== "string") return fallback;
  try {
    const raw = url.trim();
    if (!raw) return fallback;
    const parsed = new URL(raw.startsWith("http://") || raw.startsWith("https://") ? raw : `https://${raw}`);
    const pathParts = parsed.pathname.split("/").filter(Boolean);
    if (!pathParts.length) return fallback;
    let handle = pathParts[0].trim();
    if (handle.startsWith("@")) handle = handle.slice(1);
    return handle ? `@${handle}` : fallback;
  } catch {
    return fallback;
  }
};

export const Footer = ({ storeInfo }) => {
  const s = storeInfo || {};
  const waDigits = (s.whatsapp_number || "").replace(/[^0-9]/g, "");
  const contacts = [
    s.whatsapp_number && { icon: MessageCircle, label: s.whatsapp_number, href: `https://wa.me/${waDigits}`, tid: "footer-whatsapp" },
    s.store_maps_url && { icon: MapPin, label: "Lokasi Toko", href: s.store_maps_url, tid: "footer-maps" },
    s.instagram && { icon: Instagram, label: extractHandle(s.instagram, "Instagram"), href: s.instagram, tid: "footer-instagram" },
    s.facebook && { icon: Facebook, label: extractHandle(s.facebook, "Facebook"), href: s.facebook, tid: "footer-facebook" },
    s.tiktok && { icon: Music2, label: extractHandle(s.tiktok, "TikTok"), href: s.tiktok, tid: "footer-tiktok" },
    s.email && { icon: Mail, label: s.email, href: `mailto:${s.email}`, tid: "footer-email" },
  ].filter(Boolean);

  return (
    <footer className="mt-16 border-t border-[#E5DCC5] bg-[#F1EBE0]">
      <div className="mx-auto max-w-6xl px-4 py-10 sm:px-6">
        <div className="grid gap-8 md:grid-cols-3">
          <div>
            <Logo logoUrl={s.logo_url} />
            <p className="mt-3 max-w-xs text-sm text-[#5C4A3D]">{s.tagline || "Kualitas Terbaik, Untuk Ruang Terbaik"}</p>
          </div>
          <div className="text-sm text-[#5C4A3D]">
            <div className="mb-2 font-heading font-semibold text-[#2C1E16]">Navigasi</div>
            <div className="flex flex-col gap-1.5">
              <Link to="/produk" className="hover:text-[#8B5A2B]">Produk</Link>
              <Link to="/cara-pesan" className="hover:text-[#8B5A2B]">Cara Pesan</Link>
              <Link to="/lacak" className="hover:text-[#8B5A2B]" data-testid="footer-track-order">Lacak Pesanan</Link>
              <Link to="/kontak" className="hover:text-[#8B5A2B]">Kontak</Link>
            </div>
          </div>
          <div className="text-sm text-[#5C4A3D]">
            <div className="mb-2 font-heading font-semibold text-[#2C1E16]">Kontak & Toko</div>
            {s.store_address && (
              s.store_maps_url ? (
                <a
                  href={s.store_maps_url}
                  target="_blank"
                  rel="noreferrer"
                  data-testid="footer-address-link"
                  className="mb-3 flex items-start gap-2 hover:text-[#8B5A2B] transition-colors"
                >
                  <MapPin size={16} className="mt-0.5 shrink-0" />
                  <span>{s.store_address}</span>
                </a>
              ) : (
                <p className="mb-3 flex items-start gap-2">
                  <MapPin size={16} className="mt-0.5 shrink-0" />
                  <span>{s.store_address}</span>
                </p>
              )
            )}
            <div className="flex flex-col gap-1.5">
              {contacts.map((c) => (
                <a key={c.tid} href={c.href} target="_blank" rel="noreferrer" data-testid={c.tid} className="inline-flex items-center gap-2 hover:text-[#8B5A2B]">
                  <c.icon size={16} /> {c.label}
                </a>
              ))}
            </div>
          </div>
        </div>
        <div className="mt-8 border-t border-[#E5DCC5] pt-5 text-xs text-[#8B7355]">© {new Date().getFullYear()} {s.store_name || "Sogil Furniture"}. Semua harga merupakan estimasi.</div>
      </div>
    </footer>
  );
};

export default Footer;
