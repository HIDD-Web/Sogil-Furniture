import React from "react";
import { Link } from "react-router-dom";
import { ArrowRight } from "lucide-react";
import { ProductImage } from "./ProductImage";
import { fmtLE } from "../lib/format";
import { CATEGORY_LABELS } from "../lib/constants";
import { useLang } from "../context/LanguageContext";

export default function ProductCard({ product, preview }) {
  const { t } = useLang();

  // Support both direct preview object or raw product object
  if (!preview && !product) return null;

  const isPreview = Boolean(preview);
  const targetUrl = isPreview ? preview.url : `/produk/${product.slug}`;
  const testId = isPreview
    ? `preview-card-${preview.id}`
    : `product-card-${product.slug}`;
  const imageUrl = isPreview
    ? preview.image
    : product.display_image || (product.photos?.[0]?.main_url);
  const title = isPreview ? preview.title : product.name;
  const subtitle = isPreview ? preview.subtitle : null;
  const category = isPreview ? preview.category : product.category;
  const price = isPreview ? preview.price : product.starting_price_le;
  const isFallback = isPreview ? preview.isFallback : true;

  return (
    <Link
      to={targetUrl}
      data-testid={testId}
      className="group flex flex-col justify-between overflow-hidden rounded-2xl border border-[#E5DCC5] bg-white shadow-sm transition-all duration-200 sm:hover:-translate-y-0.5 sm:hover:shadow-md active:scale-[0.99]"
    >
      <div>
        <div className="overflow-hidden bg-[#FBF9F4]">
          <ProductImage
            url={imageUrl}
            alt={subtitle ? `${title} - ${subtitle}` : title}
            ratio="aspect-[4/5]"
            className="transition-transform duration-300 sm:group-hover:scale-[1.02]"
          />
        </div>

        <div className="p-3.5 pb-2">
          <div className="text-[11px] font-medium uppercase tracking-[0.08em] text-[#8B7355]">
            {CATEGORY_LABELS[category] || category}
          </div>

          <h3 className="mt-1 font-heading text-sm sm:text-base font-semibold leading-snug text-[#2C1E16] line-clamp-2">
            {category === "custom" ? title : (subtitle || title)}
          </h3>
          {category === "custom" && subtitle && (
            <p className="mt-0.5 text-xs text-[#8B7355] line-clamp-1">{subtitle}</p>
          )}

          {price > 0 && (
            <div className="mt-2 text-sm text-[#5C4A3D]">
              {isFallback && <span>{t("cat.mulai")}{" "}</span>}
              <span className="font-semibold text-[#8B5A2B]">
                {fmtLE(price)} LE
              </span>
            </div>
          )}
        </div>
      </div>

      <div className="p-3.5 pt-0">
        <div className="mt-2 flex items-center text-sm font-medium text-[#8B5A2B]">
          {t("btn.lihat_produk")}
          <ArrowRight
            size={15}
            className="ml-1 transition-transform duration-200 group-hover:translate-x-0.5"
          />
        </div>
      </div>
    </Link>
  );
}