import React, { useMemo } from "react";
import { Link } from "react-router-dom";
import { ArrowRight } from "lucide-react";
import ProductCard from "./ProductCard";
import { fmtLE } from "../lib/format";
import { useLang } from "../context/LanguageContext";
import { buildCategoryPreviews } from "../lib/catalog";

export default function CategorySection({
  category,
  title,
  products = [],
}) {
  const { t } = useLang();

  const previews = useMemo(() => buildCategoryPreviews(products), [products]);

  if (!previews.length) return null;

  const startingPrices = previews
    .map((p) => Number(p.price) || 0)
    .filter((price) => price > 0);

  const startingPrice =
    startingPrices.length > 0 ? Math.min(...startingPrices) : null;

  const displayPreviews = previews.slice(0, 3);

  return (
    <section className="py-7 sm:py-9">
      <div className="mb-4 flex items-end justify-between gap-4">
        <div className="min-w-0">
          <h2 className="font-heading text-xl font-bold tracking-tight text-[#2C1E16] sm:text-2xl">
            {title}
          </h2>

          {startingPrice && (
            <p className="mt-1 text-sm text-[#5C4A3D]">
              {t("cat.mulai")}{" "}
              <span className="font-semibold text-[#8B5A2B]">
                {fmtLE(startingPrice)} LE
              </span>
            </p>
          )}
        </div>

        <Link
          to={`/produk/kategori/${category}`}
          data-testid={`category-view-all-${category}`}
          className="flex shrink-0 items-center gap-1 text-sm font-medium text-[#8B5A2B] hover:underline"
        >
          {t("home.lihat_semua")}
          <ArrowRight size={15} />
        </Link>
      </div>

      <div
        className="grid grid-cols-2 gap-3 sm:grid-cols-3 sm:gap-5"
        data-testid={`category-products-${category}`}
      >
        {displayPreviews.map((preview) => (
          <ProductCard key={preview.id} preview={preview} />
        ))}
      </div>
    </section>
  );
}