import React, { useState, useEffect } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { Menu, X, ShoppingCart, Globe, User, Smartphone } from "lucide-react";
import { Logo } from "./Logo";
import { Button } from "./ui/button";
import { useCart } from "../context/CartContext";
import { useLang } from "../context/LanguageContext";
import PwaInstallModal from "./PwaInstallModal";

export const Header = ({ storeInfo }) => {
  const [open, setOpen] = useState(false);
  const [pwaOpen, setPwaOpen] = useState(false);
  const location = useLocation();
  const navigate = useNavigate();
  const { count } = useCart();
  const { t, lang, setLang, langs } = useLang();

  useEffect(() => { setOpen(false); }, [location.pathname]);

  const NAV = [
    { to: "/", label: t("nav.beranda") },
    { to: "/produk", label: t("nav.produk") },
    { to: "/cara-pesan", label: t("nav.cara_pesan") },
    { to: "/lacak", label: t("nav.lacak") },
    { to: "/kontak", label: t("nav.kontak") },
  ];

  const LangSelect = ({ mobile = false }) => (
  <div className="relative shrink-0">
    <Globe
      size={15}
      className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-[#8B7355]"
    />

    <select
      value={lang}
      onChange={(e) => setLang(e.target.value)}
      data-testid="language-select"
      aria-label={t("nav.pilih_bahasa")}
      className={`h-9 appearance-none rounded-full border border-[#E5DCC5] bg-white text-sm text-[#2C1E16] focus:outline-none ${
        mobile ? "w-[58px] pl-7 pr-2" : "pl-8 pr-6"
      }`}
    >
      {langs.map((l) => (
        <option key={l.code} value={l.code}>
          {mobile ? l.code.toUpperCase() : l.label}
        </option>
      ))}
    </select>
  </div>
);

  const CartBtn = () => (
    <Link to="/keranjang" data-testid="header-cart" className="relative flex h-10 w-10 items-center justify-center rounded-full border border-[#E5DCC5] bg-white text-[#2C1E16]">
      <ShoppingCart size={18} />
      {count > 0 && <span className="absolute -right-1 -top-1 flex h-5 min-w-[20px] items-center justify-center rounded-full bg-[#8B5A2B] px-1 text-[10px] font-bold text-white" data-testid="cart-count">{count}</span>}
    </Link>
  );

  return (
    <header className="sticky top-0 z-40 border-b border-[#E5DCC5] bg-[#F9F6F0]/95 backdrop-blur-md">
      <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3 sm:px-6">
        <Link
          to="/"
          data-testid="header-logo-link"
          className="min-w-0 shrink"
        >
          <Logo
            logoUrl={storeInfo?.logo_url}
            showText
          />
        </Link>

        <nav className="hidden items-center gap-1 md:flex">
          {NAV.map((n) => (
            <Link key={n.to} to={n.to} className={`rounded-full px-4 py-2 text-sm font-medium transition-colors ${location.pathname === n.to ? "bg-[#EFE6D5] text-[#2C1E16]" : "text-[#5C4A3D] hover:bg-[#EFE6D5]"}`}>{n.label}</Link>
          ))}
          <button
            type="button"
            onClick={() => setPwaOpen(true)}
            className="flex items-center gap-1.5 rounded-full border border-[#8B5A2B]/30 bg-[#FAF5EE] px-3.5 py-1.5 text-xs font-semibold text-[#8B5A2B] hover:bg-[#F3ECE0] transition-colors"
            title="Pasang Aplikasi di Layar HP"
          >
            <Smartphone size={14} /> Pasang di HP
          </button>
          <span className="mx-1"><LangSelect /></span>
          <Link to="/akun" data-testid="header-account" className="flex h-10 w-10 items-center justify-center rounded-full border border-[#E5DCC5] bg-white text-[#2C1E16]"><User size={18} /></Link>
          <CartBtn />
        </nav>

        <div className="flex shrink-0 items-center gap-1.5 sm:gap-2 md:hidden">
          <button
            type="button"
            onClick={() => setPwaOpen(true)}
            className="flex h-10 w-10 items-center justify-center rounded-full border border-[#8B5A2B]/40 bg-[#FAF5EE] text-[#8B5A2B]"
            title="Pasang Aplikasi"
          >
            <Smartphone size={18} />
          </button>
          <LangSelect mobile />
          <Link to="/akun" data-testid="mobile-account" className="flex h-10 w-10 items-center justify-center rounded-full border border-[#E5DCC5] bg-white text-[#2C1E16]"><User size={18} /></Link>
          <CartBtn />
          <button className="p-2 text-[#2C1E16]" onClick={() => setOpen(!open)} data-testid="mobile-menu-toggle">{open ? <X size={24} /> : <Menu size={24} />}</button>
        </div>
      </div>

      {open && (
        <div className="border-t border-[#E5DCC5] bg-[#F9F6F0] md:hidden" data-testid="mobile-menu">
          <nav className="mx-auto flex max-w-6xl flex-col gap-1 px-4 py-3">
            {NAV.map((n) => <Link key={n.to} to={n.to} className="rounded-xl px-4 py-3 text-base font-medium text-[#2C1E16] hover:bg-[#EFE6D5]">{n.label}</Link>)}
            <button
              type="button"
              onClick={() => { setOpen(false); setPwaOpen(true); }}
              className="flex items-center gap-2 rounded-xl px-4 py-3 text-base font-semibold text-[#8B5A2B] bg-[#FAF5EE] hover:bg-[#EFE6D5] mt-1 text-left"
            >
              <Smartphone size={18} /> Pasang Aplikasi di Layar HP
            </button>
          </nav>
        </div>
      )}

      <PwaInstallModal
        isOpen={pwaOpen}
        onClose={() => setPwaOpen(false)}
        mode="customer"
      />
    </header>
  );
};

export default Header;
