import React, { useEffect, useMemo, useState } from "react";
import api from "../lib/api";
import { CATEGORY_LABELS } from "../lib/constants";
import { ProductImage } from "../components/ProductImage";
import CategorySection from "../components/CategorySection";
import HelpSheet from "../components/HelpSheet";
import { Skeleton } from "../components/ui/skeleton";
import { useLang } from "../context/LanguageContext";

const CATEGORY_ORDER = [
  "rak",
  "meja",
  "meja_rak",
  "papan_tulis",
  "blockboard",
  "custom",
];

const CATEGORY_KEYS = {
  rak: "cat.rak",
  meja: "cat.meja",
  meja_rak: "cat.meja_rak",
  papan_tulis: "cat.papan_tulis",
  blockboard: "cat.blockboard",
  custom: "cat.custom",
};

const CATEGORY_DESCRIPTIONS = {
  rak: "Rapikan kitab, buku, dan barang dengan lebih teratur.",
  meja: "Meja belajar yang nyaman untuk ruang dan kebutuhanmu.",
  meja_rak: "Praktis untuk belajar sekaligus menyimpan barang.",
  papan_tulis: "Cocok untuk belajar, mengajar, dan berbagai kebutuhan.",
  blockboard: "Pilihan papan tulis untuk kebutuhan belajar dan aktivitasmu.",
  custom: "Punya desain sendiri? Temukan pilihan custom dari Sogil.",
};

function ProductSectionSkeleton() {
  return (
    <section className="py-7 sm:py-9">
      <div className="mb-4">
        <Skeleton className="h-6 w-32 rounded-lg" />
        <Skeleton className="mt-2 h-4 w-24 rounded-lg" />
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 sm:gap-5">
        {[1, 2, 3].map((item) => (
          <div
            key={item}
            className="overflow-hidden rounded-2xl border border-[#E5DCC5] bg-white p-3"
          >
            <Skeleton className="aspect-[4/3] w-full rounded-xl" />
            <Skeleton className="mt-3 h-3 w-16 rounded" />
            <Skeleton className="mt-2 h-5 w-3/4 rounded" />
            <Skeleton className="mt-2 h-4 w-1/2 rounded" />
          </div>
        ))}
      </div>
    </section>
  );
}

export default function Home() {
  const { t } = useLang();
  const [products, setProducts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showSplash, setShowSplash] = useState(true);

  useEffect(() => {
    let mounted = true;

    api
      .get("/products")
      .then((response) => {
        if (mounted) {
          setProducts(Array.isArray(response.data) ? response.data : []);
        }
      })
      .catch(() => {
        if (mounted) setProducts([]);
      })
      .finally(() => {
        if (mounted) setLoading(false);
      });

    const timer = window.setTimeout(() => {
      if (mounted) setShowSplash(false);
    }, 1100);

    return () => {
      mounted = false;
      window.clearTimeout(timer);
    };
  }, []);

  const groupedProducts = useMemo(() => {
    const groups = {};

    CATEGORY_ORDER.forEach((category) => {
      groups[category] = [];
    });

    products.forEach((product) => {
      if (!product?.active) return;

      const category = product.category;

      if (!groups[category]) {
        groups[category] = [];
      }

      groups[category].push(product);
    });

    return groups;
  }, [products]);

  const visibleCategories = useMemo(
    () =>
      Object.keys(groupedProducts).filter(
        (category) => groupedProducts[category]?.length > 0
      ),
    [groupedProducts]
  );

  if (showSplash) {
    return (
      <div
        className="flex min-h-[70vh] items-center justify-center bg-[#F9F6F0] px-6"
        data-testid="home-splash"
      >
        <div className="text-center">
          <div className="mx-auto flex h-20 w-20 items-center justify-center rounded-3xl border border-[#E5DCC5] bg-white shadow-sm">
            <span className="font-heading text-3xl font-bold text-[#8B5A2B]">
              S
            </span>
          </div>

          <h1 className="mt-5 font-heading text-2xl font-bold text-[#2C1E16]">
            Sogil Furniture
          </h1>

          <p className="mt-2 text-sm text-[#8B7355]">
            {t("home.welcome")}
          </p>
        </div>
      </div>
    );
  }

  return (
    <main className="bg-[#F9F6F0]">
      <section className="mx-auto max-w-6xl px-4 pb-5 pt-8 sm:px-6 sm:pb-7 sm:pt-10">
        <div className="max-w-2xl">
          <p className="text-sm font-medium text-[#8B5A2B]">
            {t("home.welcome")}
          </p>

          <h1 className="mt-2 font-heading text-3xl font-bold leading-tight tracking-tight text-[#2C1E16] sm:text-4xl">
            {t("home.title")}
          </h1>

          <p className="mt-3 max-w-xl text-sm leading-relaxed text-[#5C4A3D] sm:text-base">
            {t("home.subtitle")}
          </p>
        </div>
      </section>

      <section
        className="mx-auto max-w-6xl px-4 pb-8 sm:px-6"
        data-testid="home-categories"
      >
        <div className="mb-1">
          <h2 className="font-heading text-xl font-bold text-[#2C1E16] sm:text-2xl">
            {t("home.choose_title")}
          </h2>
          <p className="mt-1 text-sm text-[#5C4A3D]">
            {t("home.choose_subtitle")}
          </p>
        </div>

        {loading ? (
          <>
            <ProductSectionSkeleton />
            <ProductSectionSkeleton />
          </>
        ) : visibleCategories.length > 0 ? (
          visibleCategories.map((category) => (
            <CategorySection
              key={category}
              category={category}
              title={t(CATEGORY_KEYS[category])}
              description={CATEGORY_DESCRIPTIONS[category]}
              products={groupedProducts[category]}
            />
          ))
        ) : (
          <div
            className="mt-8 rounded-2xl border border-dashed border-[#D9CCB7] bg-white px-5 py-10 text-center"
            data-testid="home-empty-state"
          >
            <div className="mx-auto w-fit rounded-2xl bg-[#EFE6D5] p-3 text-[#8B5A2B]">
              <ProductImage url="" ratio="aspect-square" className="h-14 w-14" />
            </div>

            <h3 className="mt-4 font-heading text-lg font-semibold text-[#2C1E16]">
              {t("home.empty_title")}
            </h3>

            <p className="mt-1 text-sm text-[#5C4A3D]">
              {t("home.empty_subtitle")}
            </p>
          </div>
        )}
      </section>

      {!loading && products.length > 0 && (
        <section className="mx-auto max-w-6xl px-4 pb-14 sm:px-6">
          <div className="rounded-2xl border border-[#E5DCC5] bg-[#EFE6D5] px-5 py-5 sm:px-6">
            <h2 className="font-heading text-lg font-bold text-[#2C1E16]">
              {t("home.help_title")}
            </h2>

            <p className="mt-1 max-w-xl text-sm leading-relaxed text-[#5C4A3D]">
              {t("home.help_subtitle")}
            </p>

            <p className="mt-3 text-sm font-semibold text-[#8B5A2B]">
              {t("home.help_prompt")}
            </p>
          </div>
        </section>
      )}

      <HelpSheet />
    </main>
  );
}