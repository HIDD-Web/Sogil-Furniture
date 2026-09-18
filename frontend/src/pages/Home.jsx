import React, { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Sparkles } from "lucide-react";
import api from "../lib/api";
import { CATEGORY_LABELS } from "../lib/constants";
import { ProductImage } from "../components/ProductImage";
import CategorySection from "../components/CategorySection";
import HelpSheet from "../components/HelpSheet";
import { Skeleton } from "../components/ui/skeleton";
import { Button } from "../components/ui/button";
import { useLang } from "../context/LanguageContext";
import { Logo } from "../components/Logo";

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
  custom: "Kumpulan karya dan desain custom pilihan dari Sogil Furniture.",
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
            <Skeleton className="aspect-[4/5] w-full rounded-xl" />
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
  const [categories, setCategories] = useState([]);
  const [store, setStore] = useState(null);
  const [loading, setLoading] = useState(true);
  const [showSplash, setShowSplash] = useState(() => {
    return !sessionStorage.getItem("sogil_splash_seen");
  });

  useEffect(() => {
    let mounted = true;

    Promise.all([
      api.get("/products"),
      api.get("/store-info").catch(() => ({ data: null })),
      api.get("/categories").catch(() => ({ data: [] })),
    ])
      .then(([prodRes, storeRes, catRes]) => {
        if (mounted) {
          setProducts(Array.isArray(prodRes.data) ? prodRes.data : []);
          if (storeRes?.data) setStore(storeRes.data);
          if (Array.isArray(catRes?.data) && catRes.data.length > 0) {
            setCategories(catRes.data);
          }
        }
      })
      .catch(() => {
        if (mounted) setProducts([]);
      })
      .finally(() => {
        if (mounted) setLoading(false);
      });

    if (showSplash) {
      sessionStorage.setItem("sogil_splash_seen", "true");
      const timer = window.setTimeout(() => {
        if (mounted) setShowSplash(false);
      }, 1000);

      return () => {
        mounted = false;
        window.clearTimeout(timer);
      };
    } else {
      return () => {
        mounted = false;
      };
    }
  }, [showSplash]);

  const categoryOrder = useMemo(() => {
    if (categories.length > 0) {
      return categories.map((c) => c.key);
    }
    return CATEGORY_ORDER;
  }, [categories]);

  const categoryDescriptions = useMemo(() => {
    const map = { ...CATEGORY_DESCRIPTIONS };
    categories.forEach((c) => {
      if (c.description) map[c.key] = c.description;
    });
    return map;
  }, [categories]);

  const categoryLabels = useMemo(() => {
    const map = { ...CATEGORY_LABELS };
    categories.forEach((c) => {
      if (c.name) map[c.key] = c.name;
    });
    return map;
  }, [categories]);

  const groupedProducts = useMemo(() => {
    const groups = {};

    categoryOrder.forEach((category) => {
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
  }, [products, categoryOrder]);

  const visibleCategories = useMemo(
    () =>
      categoryOrder.filter(
        (category) => groupedProducts[category]?.length > 0
      ),
    [groupedProducts, categoryOrder]
  );

  if (showSplash) {
    return (
      <div
        className="flex min-h-[75vh] items-center justify-center bg-[#F9F6F0] px-6"
        data-testid="home-splash"
      >
        <div className="flex flex-col items-center text-center">
          <div className="mx-auto flex items-center justify-center">
            <Logo size={76} showText={false} logoUrl={store?.logo_url} />
          </div>

          <h1 className="mt-4 font-heading text-2xl font-bold tracking-tight text-[#2C1E16]">
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

          {/* Dynamic Category Quick-Scroll Pills */}
          {visibleCategories.length > 0 && (
            <div className="mt-5 sm:mt-6 -mx-4 px-4 overflow-x-auto scrollbar-none flex items-center gap-2 pb-1">
              {visibleCategories.map((category) => {
                const catLabel = categoryLabels[category] || (CATEGORY_KEYS[category] ? t(CATEGORY_KEYS[category]) : (CATEGORY_LABELS[category] || category));
                return (
                  <button
                    key={category}
                    type="button"
                    onClick={() => {
                      const el = document.getElementById(`category-sec-${category}`);
                      if (el) {
                        el.scrollIntoView({ behavior: "smooth", block: "start" });
                      }
                    }}
                    className="inline-flex shrink-0 items-center gap-1.5 rounded-full border border-[#E5DCC5] bg-white px-3.5 py-1.5 text-xs font-semibold text-[#5C4A3D] shadow-xs transition-all active:scale-95 hover:border-[#8B5A2B] hover:bg-[#F5EFEB] hover:text-[#8B5A2B]"
                    data-testid={`quick-category-${category}`}
                  >
                    <span>{catLabel}</span>
                  </button>
                );
              })}
            </div>
          )}
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
          visibleCategories.map((category) => {
            const catObj = categories.find((c) => c.key === category);
            return (
              <CategorySection
                key={category}
                category={category}
                title={categoryLabels[category] || (CATEGORY_KEYS[category] ? t(CATEGORY_KEYS[category]) : (CATEGORY_LABELS[category] || category))}
                description={categoryDescriptions[category] || CATEGORY_DESCRIPTIONS[category]}
                products={groupedProducts[category]}
                featuredPreviewIds={catObj?.featured_preview_ids || []}
              />
            );
          })
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

      {!loading && (
        <section className="mx-auto max-w-6xl px-4 py-4 sm:px-6">
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 rounded-3xl border border-[#E5DCC5] bg-gradient-to-r from-[#FBF9F4] to-[#F2ECE1] p-5 sm:p-7 shadow-sm">
            <div className="space-y-1">
              <div className="inline-flex items-center gap-1.5 rounded-full bg-[#8B5A2B]/10 px-3 py-0.5 text-xs font-semibold text-[#8B5A2B]">
                <Sparkles size={13} /> Pesanan Custom
              </div>
              <h3 className="font-heading text-lg sm:text-xl font-bold text-[#2C1E16]">
                Punya Ukuran atau Desain Furniture Sendiri?
              </h3>
              <p className="max-w-xl text-xs sm:text-sm text-[#5C4A3D]">
                Lampirkan foto referensi, tentukan ukuran sesuai kebutuhan ruang Anda di Cairo, dan dapatkan estimasi biaya langsung dari tim Sogil Furniture.
              </p>
            </div>
            <Link to="/request-custom" className="shrink-0">
              <Button className="h-11 rounded-full bg-[#8B5A2B] px-6 text-sm font-semibold text-white hover:bg-[#6B4423] shadow-sm">
                Ajukan Request Custom
              </Button>
            </Link>
          </div>
        </section>
      )}

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