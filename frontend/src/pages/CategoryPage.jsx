import React, { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, PackageOpen } from "lucide-react";
import api from "../lib/api";
import { CATEGORY_LABELS } from "../lib/constants";
import ProductCard from "../components/ProductCard";
import { Skeleton } from "../components/ui/skeleton";
import { useLang } from "../context/LanguageContext";
import { buildCategoryPreviews } from "../lib/catalog";

const CATEGORY_KEYS = {
  rak: "cat.rak",
  meja: "cat.meja",
  meja_rak: "cat.meja_rak",
  papan_tulis: "cat.papan_tulis",
  blockboard: "cat.blockboard",
  custom: "cat.custom",
};

const CATEGORY_DESCRIPTION_KEYS = {
  rak: "cat.rak_desc",
  meja: "cat.meja_desc",
  meja_rak: "cat.meja_rak_desc",
  papan_tulis: "cat.papan_tulis_desc",
  blockboard: "cat.blockboard_desc",
  custom: "cat.custom_desc",
};

function ProductGridSkeleton() {
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4 sm:gap-5">
      {[1, 2, 3, 4, 5, 6].map((item) => (
        <div
          key={item}
          className="overflow-hidden rounded-2xl border border-[#E5DCC5] bg-white p-3"
        >
          <Skeleton className="aspect-[4/5] w-full rounded-xl" />
          <Skeleton className="mt-3 h-3 w-16 rounded" />
          <Skeleton className="mt-2 h-5 w-3/4 rounded" />
          <Skeleton className="mt-2 h-4 w-1/2 rounded" />
        </div>
      ))}
    </div>
  );
}

export default function CategoryPage() {
  const { category } = useParams();
  const { t } = useLang();

  const [products, setProducts] = useState([]);
  const [categories, setCategories] = useState([]);
  const [store, setStore] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let mounted = true;

    Promise.all([
      api.get("/products"),
      api.get("/categories").catch(() => ({ data: [] })),
      api.get("/store-info").catch(() => ({ data: null })),
    ])
      .then(([prodRes, catRes, storeRes]) => {
        if (mounted) {
          setProducts(Array.isArray(prodRes.data) ? prodRes.data : []);
          if (Array.isArray(catRes?.data)) setCategories(catRes.data);
          if (storeRes?.data) setStore(storeRes.data);
        }
      })
      .catch(() => {
        if (mounted) setProducts([]);
      })
      .finally(() => {
        if (mounted) setLoading(false);
      });

    return () => {
      mounted = false;
    };
  }, []);

  const categoryProducts = useMemo(
    () =>
      products
        .filter(
          (product) =>
            product?.active !== false && product?.category === category
        )
        .sort((a, b) => {
          const orderA = Number(a?.sort_order) || 0;
          const orderB = Number(b?.sort_order) || 0;
          return orderA - orderB;
        }),
    [products, category]
  );

  const categoryPreviews = useMemo(
    () => buildCategoryPreviews(categoryProducts),
    [categoryProducts]
  );

  const categoryDoc = useMemo(
    () => categories.find((c) => c.key === category),
    [categories, category]
  );

  const hasCategory = Boolean(categoryDoc) || Object.prototype.hasOwnProperty.call(CATEGORY_LABELS, category);

  const title = categoryDoc?.name || (CATEGORY_KEYS[category] ? t(CATEGORY_KEYS[category]) : (CATEGORY_LABELS[category] || category));

  const description = categoryDoc?.description || (CATEGORY_DESCRIPTION_KEYS[category] ? t(CATEGORY_DESCRIPTION_KEYS[category]) : t("cat.default_desc"));

  const whatsappNumber = (store?.whatsapp_number || "201016843442").replace(/[^0-9]/g, "");
  const whatsappUrl = `https://wa.me/${whatsappNumber}?text=${encodeURIComponent(
    "Halo Sogil Furniture, saya ingin konsultasi pemesanan furnitur custom."
  )}`;

  return (
    <main className="min-h-[60vh] bg-[#F9F6F0]">
      <section className="mx-auto max-w-6xl px-4 pb-6 pt-7 sm:px-6 sm:pb-8 sm:pt-9">
        <Link
          to="/"
          data-testid="category-back-home"
          className="inline-flex items-center gap-1.5 text-sm font-medium text-[#8B5A2B] hover:underline"
        >
          <ArrowLeft size={16} />
          {t("btn.kembali")}
        </Link>

        <div className="mt-5">
          <p className="text-sm font-medium text-[#8B5A2B]">
            {t("cat.collection")}
          </p>

          <h1
            className="mt-1 font-heading text-3xl font-bold tracking-tight text-[#2C1E16] sm:text-4xl"
            data-testid="category-title"
          >
            {title}
          </h1>

          <p className="mt-2 max-w-xl text-sm leading-relaxed text-[#5C4A3D] sm:text-base">
            {description}
          </p>
        </div>

        {/* Custom Consultation Banner */}
        {category === "custom" && (
          <div className="mt-6 rounded-2xl border border-[#E5DCC5] bg-[#F4EFE6] p-4 sm:p-5 flex flex-col sm:flex-row sm:items-center justify-between gap-4 shadow-xs">
            <div>
              <h3 className="font-heading font-bold text-base text-[#2C1E16]">
                Punya Ide atau Kebutuhan Furnitur Custom?
              </h3>
              <p className="mt-1 text-xs sm:text-sm text-[#5C4A3D] max-w-xl">
                Sogil Furniture melayani pembuatan furnitur dengan bentuk, ukuran, dan spesifikasi sesuai keinginanmu. Hubungi admin untuk konsultasi desain dan estimasi harga.
              </p>
            </div>
            <div className="flex flex-wrap sm:flex-nowrap gap-2 shrink-0">
              <Link
                to="/request-custom"
                className="inline-flex shrink-0 items-center justify-center gap-1.5 rounded-xl bg-[#8B5A2B] px-4 py-2.5 text-xs sm:text-sm font-semibold text-white shadow-xs hover:bg-[#6B4423] transition-colors"
              >
                Isi Form Request
              </Link>
              <a
                href={whatsappUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex shrink-0 items-center justify-center gap-1.5 rounded-xl bg-[#25D366] px-4 py-2.5 text-xs sm:text-sm font-semibold text-white shadow-xs hover:bg-[#1EBE5D] transition-colors"
              >
                Konsultasi via WA
              </a>
            </div>
          </div>
        )}
      </section>

      <section className="mx-auto max-w-6xl px-4 pb-14 sm:px-6">
        {loading ? (
          <ProductGridSkeleton />
        ) : !hasCategory || categoryPreviews.length === 0 ? (
          <div
            className="rounded-2xl border border-dashed border-[#D9CCB7] bg-white px-5 py-12 text-center"
            data-testid="category-empty-state"
          >
            <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-[#EFE6D5] text-[#8B5A2B]">
              <PackageOpen size={26} strokeWidth={1.6} />
            </div>

            <h2 className="mt-4 font-heading text-lg font-semibold text-[#2C1E16]">
              {t("cat.empty_title")}
            </h2>

            <p className="mx-auto mt-1 max-w-sm text-sm leading-relaxed text-[#5C4A3D]">
              {t("cat.empty_desc")}
            </p>

            <Link
              to="/"
              className="mt-5 inline-flex h-10 items-center rounded-xl bg-[#8B5A2B] px-5 text-sm font-semibold text-white hover:bg-[#6B4423]"
            >
              {t("cat.back_catalog")}
            </Link>
          </div>
        ) : (
          <div
            className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4 sm:gap-5"
            data-testid="category-product-grid"
          >
            {categoryPreviews.map((preview) => (
              <ProductCard
                key={preview.id}
                preview={preview}
              />
            ))}
          </div>
        )}
      </section>
    </main>
  );
}