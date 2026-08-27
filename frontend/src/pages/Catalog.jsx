import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import api from "../lib/api";
import { fmtLE } from "../lib/format";
import { CATEGORY_LABELS } from "../lib/constants";
import { ProductImage } from "../components/ProductImage";
import { useLang } from "../context/LanguageContext";
import { Button } from "../components/ui/button";
import { Badge } from "../components/ui/badge";

export default function Catalog() {
  const [products, setProducts] = useState([]);
  const [loading, setLoading] = useState(true);
  const { t } = useLang();

  useEffect(() => { api.get("/products").then((r) => setProducts(r.data)).finally(() => setLoading(false)); }, []);

  return (
    <div className="mx-auto max-w-6xl px-4 py-10 sm:px-6">
      <h1 className="font-heading text-3xl font-bold tracking-tight text-[#2C1E16] sm:text-4xl">{t("cat.pilihan")}</h1>
      <p className="mt-2 max-w-lg text-[#5C4A3D]">{t("cat.pilihan_sub")}</p>

      {loading ? <div className="mt-10 text-center text-[#8B7355]">{t("cat.memuat")}</div> : (
        <div className="mt-8 grid gap-5 sm:grid-cols-2 lg:grid-cols-3" data-testid="product-grid">
          {products.map((p) => (
            <div key={p.id} data-testid={`product-card-${p.slug}`} className="flex flex-col rounded-2xl border border-[#E5DCC5] bg-white p-3 shadow-sm transition-shadow hover:shadow-md">
              <div className="overflow-hidden rounded-xl"><ProductImage url={p.display_image} alt={p.name} /></div>
              <div className="flex flex-1 flex-col p-2">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-medium uppercase tracking-wide text-[#8B7355]">{CATEGORY_LABELS[p.category]}</span>
                  {!p.configurable && <Badge variant="outline" className="border-amber-300 bg-amber-50 text-[10px] text-amber-700">{t("cat.segera")}</Badge>}
                </div>
                <h3 className="mt-1 font-heading text-lg font-semibold text-[#2C1E16]">{p.name}</h3>
                <p className="mt-1 line-clamp-2 text-sm text-[#5C4A3D]">{p.description}</p>
                <div className="mt-3">
                  {p.configurable && p.starting_price_le > 0 ? <div className="text-sm text-[#5C4A3D]">{t("cat.mulai")} <span className="font-semibold text-[#8B5A2B]">{fmtLE(p.starting_price_le)} LE</span></div> : <span className="text-xs text-[#8B7355]">{t("cat.konfirmasi_wa")}</span>}
                </div>
                <Link to={`/produk/${p.slug}`} className="mt-3" data-testid={`select-product-${p.slug}`}><Button className="h-11 w-full rounded-xl bg-[#8B5A2B] hover:bg-[#6B4423]">{t("btn.pilih_produk")}</Button></Link>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
