import React, { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import api from "../lib/api";
import { fmtLE } from "../lib/format";
import { CATEGORY_LABELS } from "../lib/constants";
import { ProductImage } from "../components/ProductImage";
import { useLang } from "../context/LanguageContext";
import { Button } from "../components/ui/button";
import { ArrowRight, Ruler, Wallet, MessageCircle, Sparkles } from "lucide-react";

export default function Home() {
  const [products, setProducts] = useState([]);
  const { t } = useLang();
  const navigate = useNavigate();
  useEffect(() => { api.get("/products").then((r) => setProducts(r.data)).catch(() => {}); }, []);
  const featured = products.slice(0, 3);
  const FEATURES = [
    { icon: Ruler, t: t("home.f1t"), d: t("home.f1d") },
    { icon: Wallet, t: t("home.f2t"), d: t("home.f2d") },
    { icon: MessageCircle, t: t("home.f3t"), d: t("home.f3d") },
  ];

  return (
    <div>
      <section className="relative overflow-hidden">
        <div className="mx-auto grid max-w-6xl items-center gap-10 px-4 py-14 sm:px-6 md:grid-cols-2 md:py-20">
          <div>
            <span className="inline-flex items-center gap-2 rounded-full border border-[#E5DCC5] bg-white px-3 py-1 text-xs font-medium text-[#8B5A2B]"><Sparkles size={14} /> {t("home.badge")}</span>
            <h1 className="mt-5 font-heading text-4xl font-800 leading-none tracking-tight text-[#2C1E16] sm:text-5xl lg:text-6xl" style={{ fontWeight: 800 }}>{t("home.title")}</h1>
            <p className="mt-5 max-w-md text-base leading-relaxed text-[#5C4A3D]">{t("home.subtitle")}</p>
            <div className="mt-8 flex flex-wrap gap-3">
              <Button onClick={() => navigate("/produk")} data-testid="hero-lihat-produk" className="h-12 rounded-full bg-[#8B5A2B] px-7 text-base hover:bg-[#6B4423]">{t("btn.lihat_produk")} <ArrowRight size={18} className="ml-1" /></Button>
              <Button onClick={() => navigate("/produk")} data-testid="hero-pesan-sekarang" variant="outline" className="h-12 rounded-full border-[#8B5A2B] px-7 text-base text-[#8B5A2B] hover:bg-[#EFE6D5]">{t("btn.pesan_sekarang")}</Button>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-4">
            {[0, 1, 2].map((i) => (
              <div key={i} className={`rounded-2xl border border-[#E5DCC5] bg-white p-3 shadow-sm ${i % 2 ? "mt-6" : ""}`}>
                <ProductImage url={featured[i]?.display_image} ratio="aspect-square" />
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="mx-auto max-w-6xl px-4 sm:px-6">
        <div className="grid gap-4 sm:grid-cols-3">
          {FEATURES.map((f) => (
            <div key={f.t} className="rounded-2xl border border-[#E5DCC5] bg-white p-6 shadow-sm">
              <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-[#EFE6D5] text-[#8B5A2B]"><f.icon size={22} /></div>
              <h3 className="mt-4 font-heading text-lg font-semibold text-[#2C1E16]">{f.t}</h3>
              <p className="mt-1 text-sm leading-relaxed text-[#5C4A3D]">{f.d}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="mx-auto max-w-6xl px-4 py-14 sm:px-6">
        <div className="flex items-end justify-between">
          <div><h2 className="font-heading text-2xl font-bold tracking-tight text-[#2C1E16] sm:text-3xl">{t("home.featured")}</h2><p className="mt-1 text-sm text-[#5C4A3D]">{t("home.featured_sub")}</p></div>
          <Link to="/produk" className="hidden text-sm font-medium text-[#8B5A2B] hover:underline sm:block">{t("home.lihat_semua")}</Link>
        </div>
        <div className="mt-6 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
          {featured.map((p) => (
            <Link key={p.id} to={`/produk/${p.slug}`} data-testid={`featured-product-${p.slug}`} className="group rounded-2xl border border-[#E5DCC5] bg-white p-3 shadow-sm transition-shadow hover:shadow-md">
              <div className="overflow-hidden rounded-xl"><ProductImage url={p.display_image} alt={p.name} /></div>
              <div className="p-2">
                <div className="text-xs font-medium uppercase tracking-wide text-[#8B7355]">{CATEGORY_LABELS[p.category]}</div>
                <h3 className="mt-1 font-heading text-lg font-semibold text-[#2C1E16]">{p.name}</h3>
                {p.starting_price_le > 0 && <div className="mt-1 text-sm text-[#5C4A3D]">{t("cat.mulai")} <span className="font-semibold text-[#8B5A2B]">{fmtLE(p.starting_price_le)} LE</span></div>}
              </div>
            </Link>
          ))}
        </div>
      </section>
    </div>
  );
}
