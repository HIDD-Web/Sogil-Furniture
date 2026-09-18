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
  featuredPreviewIds = [],
}) {
  const { t } = useLang();

  const previews = useMemo(() => buildCategoryPreviews(products), [products]);

  // Accurate starting price: prefer product starting_price_le (true base price) or preview prices
  const startingPrice = useMemo(() => {
    const baseProductPrices = products
      .map((p) => Number(p.starting_price_le) || 0)
      .filter((pr) => pr > 0);

    if (baseProductPrices.length > 0) {
      return Math.min(...baseProductPrices);
    }

    const previewPrices = previews
      .map((p) => Number(p.price) || 0)
      .filter((price) => price > 0);

    return previewPrices.length > 0 ? Math.min(...previewPrices) : null;
  }, [products, previews]);

  // Display 3 featured previews configured from admin dashboard, or fallback to first 3
  const displayPreviews = useMemo(() => {
    const explicitIds =
      Array.isArray(featuredPreviewIds) && featuredPreviewIds.length > 0
        ? featuredPreviewIds
        : products.find(
            (p) =>
              Array.isArray(p.featured_preview_ids) &&
              p.featured_preview_ids.length > 0
          )?.featured_preview_ids;

    if (Array.isArray(explicitIds) && explicitIds.length > 0) {
      const selected = [];
      explicitIds.forEach((fid) => {
        const found = previews.find(
          (p) =>
            p.id === fid ||
            p.id.endsWith(`-${fid}`) ||
            p.config?.id === fid ||
            (p.config?.length &&
              `${p.config.length}_${p.config.level}_${p.config.type}` === fid)
        );
        if (found && !selected.some((x) => x.id === found.id)) {
          selected.push(found);
        }
      });
      // Fill remaining if fewer than 3
      if (selected.length < 3) {
        previews.forEach((p) => {
          if (selected.length < 3 && !selected.some((x) => x.id === p.id)) {
            selected.push(p);
          }
        });
      }
      return selected.slice(0, 3);
    }

    return previews.slice(0, 3);
  }, [previews, featuredPreviewIds, products]);

  if (!previews.length) return null;

  return (
    <section id={`category-sec-${category}`} className="py-6 sm:py-9 scroll-mt-20">
      <div className="mb-3.5 flex items-end justify-between gap-4">
        <div className="min-w-0">
          <h2 className="font-heading text-xl font-bold tracking-tight text-[#2C1E16] sm:text-2xl">
            {title}
          </h2>

          {startingPrice && (
            <p className="mt-0.5 text-xs sm:text-sm text-[#5C4A3D]">
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
          className="flex shrink-0 items-center gap-1 text-xs sm:text-sm font-medium text-[#8B5A2B] hover:underline"
        >
          {t("home.lihat_semua")}
          <ArrowRight size={15} />
        </Link>
      </div>

      {/* Desktop/Tablet Grid: 3 columns */}
      <div
        className="hidden sm:grid sm:grid-cols-3 sm:gap-5"
        data-testid={`category-products-${category}`}
      >
        {displayPreviews.map((preview) => (
          <ProductCard key={preview.id} preview={preview} />
        ))}
      </div>

      {/* Mobile Horizontal Scroll: 1 row with cards sized identically to CategoryPage grid */}
      <div
        className="sm:hidden -mx-4 px-4 overflow-x-auto snap-x snap-mandatory flex gap-3 pb-2 scrollbar-none touch-pan-x"
        style={{ WebkitOverflowScrolling: "touch" }}
      >
        {displayPreviews.map((preview) => (
          <div key={preview.id} className="w-[43vw] min-w-[155px] max-w-[180px] shrink-0 snap-start flex flex-col">
            <ProductCard preview={preview} />
          </div>
        ))}

        {/* Action card to view full catalog */}
        <div className="w-[34vw] min-w-[125px] max-w-[145px] shrink-0 snap-start flex">
          <Link
            to={`/produk/kategori/${category}`}
            data-testid={`category-mobile-view-all-${category}`}
            className="group flex flex-1 flex-col items-center justify-center rounded-2xl border-2 border-dashed border-[#D5C7B0] bg-[#F5EFEB] p-3 text-center transition-all active:scale-[0.98] hover:border-[#8B5A2B]"
          >
            <div className="flex h-10 w-10 items-center justify-center rounded-full bg-[#8B5A2B] text-white shadow-sm transition-transform group-hover:scale-110">
              <ArrowRight size={18} />
            </div>

            <div className="mt-2.5 font-heading text-xs font-bold text-[#2C1E16] line-clamp-2">
              {t("home.lihat_semua")}
            </div>

            <div className="mt-0.5 text-[11px] text-[#8B7355] line-clamp-1">
              {title}
            </div>

            <span className="mt-2 inline-flex items-center rounded-full bg-[#E5DCC5]/50 px-2 py-0.5 text-[10px] font-semibold text-[#8B5A2B]">
              {previews.length} variasi
            </span>
          </Link>
        </div>
      </div>
    </section>
  );
}