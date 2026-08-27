import React, { useState, useEffect } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { Menu, X, ShoppingCart, Globe } from "lucide-react";
import { Logo } from "./Logo";
import { Button } from "./ui/button";
import { useCart } from "../context/CartContext";
import { useLang } from "../context/LanguageContext";

export const Header = ({ storeInfo }) => {
  const [open, setOpen] = useState(false);
  const location = useLocation();
  const navigate = useNavigate();
  const { count } = useCart();
  const { t, lang, setLang, langs } = useLang();

  useEffect(() => { setOpen(false); }, [location.pathname]);

  const NAV = [
    { to: "/", label: t("nav.beranda") },
    { to: "/produk", label: t("nav.produk") },
    { to: "/cara-pesan", label: t("nav.cara_pesan") },
    { to: "/kontak", label: t("nav.kontak") },
  ];

  const LangSelect = () => (
    <div className="relative">
      <Globe size={16} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-[#8B7355]" />
      <select value={lang} onChange={(e) => setLang(e.target.value)} data-testid="language-select"
        className="h-9 appearance-none rounded-full border border-[#E5DCC5] bg-white pl-8 pr-6 text-sm text-[#2C1E16] focus:outline-none">
        {langs.map((l) => <option key={l.code} value={l.code}>{l.label}</option>)}
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
        <Link to="/" data-testid="header-logo-link"><Logo logoUrl={storeInfo?.logo_url} /></Link>

        <nav className="hidden items-center gap-1 md:flex">
          {NAV.map((n) => (
            <Link key={n.to} to={n.to} className={`rounded-full px-4 py-2 text-sm font-medium transition-colors ${location.pathname === n.to ? "bg-[#EFE6D5] text-[#2C1E16]" : "text-[#5C4A3D] hover:bg-[#EFE6D5]"}`}>{n.label}</Link>
          ))}
          <span className="mx-1"><LangSelect /></span>
          <CartBtn />
        </nav>

        <div className="flex items-center gap-2 md:hidden">
          <LangSelect />
          <CartBtn />
          <button className="p-2 text-[#2C1E16]" onClick={() => setOpen(!open)} data-testid="mobile-menu-toggle">{open ? <X size={24} /> : <Menu size={24} />}</button>
        </div>
      </div>

      {open && (
        <div className="border-t border-[#E5DCC5] bg-[#F9F6F0] md:hidden" data-testid="mobile-menu">
          <nav className="mx-auto flex max-w-6xl flex-col gap-1 px-4 py-3">
            {NAV.map((n) => <Link key={n.to} to={n.to} className="rounded-xl px-4 py-3 text-base font-medium text-[#2C1E16] hover:bg-[#EFE6D5]">{n.label}</Link>)}
          </nav>
        </div>
      )}
    </header>
  );
};

export default Header;
