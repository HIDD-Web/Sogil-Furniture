import React, { useEffect, useMemo, useState } from "react";
import { useParams, useNavigate, useSearchParams } from "react-router-dom";
import api, { imgUrl } from "../lib/api";
import { fmtLE, fmtIDR } from "../lib/format";
import { computeBreakdown } from "../lib/pricing";
import { matchPhoto } from "../lib/photoMatch";
import { ProductImage } from "../components/ProductImage";
import { useCart } from "../context/CartContext";
import { useLang } from "../context/LanguageContext";
import { Button } from "../components/ui/button";
import { Textarea } from "../components/ui/textarea";
import { Label } from "../components/ui/label";
import { toast } from "sonner";
import { Minus, Plus, ChevronLeft, Info, ShoppingCart, Zap } from "lucide-react";

const CATEGORY_KEYS = {
  rak: "cat.rak",
  meja: "cat.meja",
  meja_rak: "cat.meja_rak",
  papan_tulis: "cat.papan_tulis",
  blockboard: "cat.blockboard",
  custom: "cat.custom",
};

const Chip = ({ active, onClick, children, testid }) => (
  <button type="button" onClick={onClick} data-testid={testid}
    className={`min-h-[38px] sm:min-h-[44px] rounded-xl border px-3 py-1.5 sm:px-4 sm:py-2 text-xs sm:text-sm font-medium transition-all ${active ? "border-[#8B5A2B] bg-[#8B5A2B] text-white shadow-sm" : "border-[#E5DCC5] bg-white text-[#2C1E16] hover:border-[#8B5A2B]"}`}>
    {children}
  </button>
);

export default function ProductConfigure() {
  const { slug } = useParams();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { t } = useLang();
  const { addItem } = useCart();
  const [product, setProduct] = useState(null);
  const [store, setStore] = useState(null);
  const [config, setConfig] = useState({ custom_size: false });
  const [quantity, setQuantity] = useState(1);
  const [customNote, setCustomNote] = useState("");

  useEffect(() => {
    Promise.all([api.get(`/products/${slug}`), api.get("/store-info")]).then(([p, s]) => {
      setProduct(p.data); setStore(s.data);
      const pr = p.data.pricing || {};
      const grps = Array.isArray(pr.groups) ? pr.groups : null;
      let init = { custom_size: false };
      if (grps) {
        grps.forEach((g) => { if ((g.options || []).length) init[g.key] = g.options[0]; });
      }
      else if (p.data.category === "rak") {
        init = {
          length: (pr.lengths || [])[0],
          level: (pr.levels || [])[0],
          type: "B",
          finishing: "Natural",
          custom_size: false,
        };
      }
      else if (p.data.category === "meja") {
        init = {
          size: (pr.sizes || [])[0],
          height: (pr.heights || [])[0],
          finishing: "Natural",
          custom_size: false,
        };
      }
      else if (p.data.category === "meja_rak") {
        init = {
          variant: (pr.variants || [])[0],
          type: "B",
          finishing: "Natural",
          custom_size: false,
        };
      }

      searchParams.forEach((val, key) => {
        if (val && key !== "custom_size") {
          init[key] = val;
        }
      });

      setConfig(init);
    }).catch(() => toast.error(t("err.product_not_found")));
  }, [slug, searchParams, t]);

  const rate = store?.exchange_rate_idr_per_le || 357;
  const breakdown = useMemo(() => (product ? computeBreakdown(product, config, quantity) : null), [product, config, quantity]);
  const photoMatch = useMemo(() => (product ? matchPhoto(product, config) : { photo: null, exact: false }), [product, config]);
  const isConfigurable = product?.configurable;
  const set = (k, v) => setConfig((c) => ({ ...c, [k]: v }));
  const [gidx, setGidx] = useState(0);
  useEffect(() => { setGidx(0); }, [photoMatch.photo?.id]);

  const canAdd = () => {
    if (!isConfigurable) return true;
    const g = product.pricing?.groups;
    if (Array.isArray(g)) return g.every((x) => config[x.key]);
    if (config.custom_size) return customNote.trim().length > 0;
    if (product.category === "rak") return config.length && config.level && config.type && config.finishing;
    if (product.category === "meja") return config.size && config.height && config.finishing;
    if (product.category === "meja_rak") return config.variant && config.type && config.finishing;
    return true;
  };

  const buildItem = () => {
    const p = product.pricing || {};
    const grps = Array.isArray(p.groups) ? p.groups : null;
    let cfg = config.custom_size ? { ...config, custom_note: customNote } : { ...config };
    if (grps && !config.custom_size) {
      const g0 = grps[0];
      if (p.design_details && g0 && p.design_details[config[g0.key]]) {
        cfg._summary = `${config[g0.key]} — ${p.design_details[config[g0.key]].join(" · ")}`;
      } else {
        cfg._summary = grps.map((g) => config[g.key]).filter(Boolean).join(", ");
      }
    }
    return {
      product: { id: product.id, slug: product.slug, name: product.name, category: product.category, image: photoMatch.photo ? (photoMatch.photo.main_url || photoMatch.photo.front_url) : product.display_image },
      config: cfg,
      quantity, breakdown: { ...breakdown }, label: product.name,
    };
  };

  const addToCart = (thenCheckout) => {
    if (!canAdd()) { toast.error(config.custom_size ? t("err.custom_note") : t("err.cfg")); return; }
    addItem(buildItem());
    if (thenCheckout) navigate("/checkout");
    else toast.success(t("err.cart_added"));
  };

  if (!product) return <div className="py-20 text-center text-[#8B7355]">{t("cat.memuat")}</div>;
  const pr = product.pricing || {};
  const groups = Array.isArray(pr.groups) ? pr.groups : null;
  const isFixed = pr.price_model === "additive";
  const ph = photoMatch.photo;
  const photoSlots = ph ? [ph.main_url, ph.front_url, ph.side_url, ...(ph.images || [])].filter(Boolean) : [];
  const gi = Math.min(gidx, Math.max(0, photoSlots.length - 1));

  return (
    <div className="mx-auto max-w-6xl px-3 py-3 pb-36 sm:px-6 sm:py-6 lg:pb-10">
      <button onClick={() => navigate("/produk")} className="mb-2.5 inline-flex items-center gap-1 text-xs sm:text-sm font-medium text-[#8B5A2B]" data-testid="back-to-catalog">
        <ChevronLeft size={16} /> {t("cfg.kembali_produk")}
      </button>

      <div className="grid gap-6 lg:grid-cols-[1fr_360px]">
        <div className="space-y-3.5 sm:space-y-6" data-testid="step-config">
          {/* Photo preview */}
          <div>
            <div className="overflow-hidden rounded-2xl border border-[#E5DCC5] bg-white shadow-sm">
              {photoSlots.length ? (
                <div className="relative h-[210px] xs:h-[230px] sm:h-[280px] lg:h-[380px] w-full overflow-hidden bg-[#FBF9F4] flex items-center justify-center p-2">
                  <img src={imgUrl(photoSlots[gi])} alt={product.name} className="h-full w-full object-contain transition-all duration-300" data-testid="config-photo-main" />
                </div>
              ) : (
                <ProductImage url={product.display_image} alt={product.name} ratio="aspect-[16/10] sm:aspect-[4/3]" />
              )}
            </div>
            {photoSlots.length > 1 && (
              <div className="mt-1.5 flex gap-1.5 overflow-x-auto pb-1" data-testid="gallery-thumbs">
                {photoSlots.map((u, i) => (
                  <button key={i} onClick={() => setGidx(i)} data-testid={`gallery-thumb-${i}`} className={`h-11 w-10 sm:h-14 sm:w-12 shrink-0 overflow-hidden rounded-lg border-2 transition-colors ${i === gi ? "border-[#8B5A2B]" : "border-[#E5DCC5]"}`}>
                    <img src={imgUrl(u)} alt="" className="h-full w-full object-cover" />
                  </button>
                ))}
              </div>
            )}
            <div className="mt-1.5 flex items-center justify-between">
              {ph && (
                <p className={`text-[11px] sm:text-xs font-medium ${photoMatch.exact ? "text-[#5C7063]" : "text-amber-700"}`} data-testid="photo-match-label">
                  {photoMatch.exact ? `✓ ${t("cfg.exact_photo")}` : `ⓘ ${t("cfg.ref_photo")}`}
                </p>
              )}
              {config.length && (
                <span className="text-[11px] font-medium text-[#8B7355]">
                  {config.length} cm · {config.level} Tingkat · Tipe {config.type}
                </span>
              )}
            </div>
          </div>

          <div className="border-b border-[#E5DCC5]/60 pb-2.5">
            <div className="text-[10px] sm:text-xs font-medium uppercase tracking-wider text-[#8B7355]">
             {CATEGORY_KEYS[product.category]
              ? t(CATEGORY_KEYS[product.category])
              : product.category}
            </div>
            <h1 className="font-heading text-lg sm:text-2xl font-bold text-[#2C1E16]">{product.name}</h1>
            {product.description && (
              <p className="mt-0.5 text-xs sm:text-sm text-[#5C4A3D] line-clamp-2 sm:line-clamp-none">{product.description}</p>
            )}
          </div>

          {!isConfigurable && (
            <div className="rounded-2xl border border-amber-200 bg-amber-50 p-5">
              <div className="flex items-start gap-3"><Info className="mt-0.5 text-amber-600" size={20} />
                <div><div className="font-heading font-semibold text-amber-800">{t("cfg.segera_t")}</div>
                  <p className="mt-1 text-sm text-amber-700">{t("cfg.segera_d")}</p></div>
              </div>
            </div>
          )}

          {isConfigurable && (
            <>
              {!isFixed && product.category === "custom" && (
              <div>
                <Label className="mb-2 block font-heading text-sm font-semibold text-[#2C1E16]">{t("cfg.jenis_pesanan")}</Label>
                <div className="flex flex-wrap gap-2">
                  <Chip active={!config.custom_size} onClick={() => set("custom_size", false)} testid="opt-standard">{t("cfg.ukuran_standar")}</Chip>
                  <Chip active={config.custom_size} onClick={() => set("custom_size", true)} testid="opt-custom">{t("cfg.ukuran_custom")}</Chip>
                </div>
              </div>
              )}

              {config.custom_size ? (
                <div className="rounded-2xl border border-[#E5DCC5] bg-white p-5">
                  <p className="text-sm text-[#5C4A3D]">{t("cfg.custom_info")}</p>
                  <Textarea value={customNote} onChange={(e) => setCustomNote(e.target.value)} data-testid="custom-note" placeholder={t("cfg.custom_ph")} className="mt-3 min-h-[100px] bg-[#FBF9F4]" />
                  <p className="mt-2 text-xs text-amber-700">{t("cfg.custom_note")}</p>
                </div>
              ) : (
                <>
                  {groups && groups.map((g) => (
                    <Section key={g.key} title={g.label || g.key} note={product.option_notes?.[g.key]}>
                      {(g.options || []).map((o) => <Chip key={o} active={config[g.key] === o} onClick={() => set(g.key, o)} testid={`opt-${g.key}-${o}`}>{o}</Chip>)}
                    </Section>
                  ))}
                  {pr.design_details && groups && groups[0] && pr.design_details[config[groups[0].key]] && (
                    <div className="rounded-2xl border border-[#E5DCC5] bg-[#FBF9F4] p-4" data-testid="custom-design-details">
                      <div className="mb-2 font-heading text-sm font-semibold text-[#2C1E16]">
                        {t("cfg.spesifikasi_desain")}
                      </div>
                      <ul className="space-y-1 text-sm text-[#5C4A3D]">
                        {pr.design_details[config[groups[0].key]].map((d, i) => <li key={i} className="flex gap-2"><span className="text-[#8B5A2B]">•</span><span>{d}</span></li>)}
                      </ul>
                    </div>
                  )}
                  {!groups && product.category === "rak" && (<>
                    <Section title={t("cfg.pilih_ukuran")} note={product.option_notes?.length}>{(pr.lengths || []).map((l) => <Chip key={l} active={config.length === l} onClick={() => set("length", l)} testid={`opt-length-${l}`}>{l} cm</Chip>)}</Section>
                    <Section title={t("cfg.jumlah_tingkat")} note={product.option_notes?.level}>{(pr.levels || []).map((l) => <Chip key={l} active={config.level === l} onClick={() => set("level", l)} testid={`opt-level-${l}`}>{l} {t("cfg.tingkat")}</Chip>)}</Section>
                    <Section title={t("cfg.tipe_rak")} hint={t("cfg.tipe_hint")} note={product.option_notes?.type}>{(pr.types || []).filter((tp) => tp !== "B+" && tp !== "A+").map((tp) => <Chip key={tp} active={config.type === tp} onClick={() => set("type", tp)} testid={`opt-type-${tp}`}>{t("cfg.tipe")} {tp}</Chip>)}</Section>
                    <Section title={t("cfg.jenis_finishing")} note={product.option_notes?.finishing}>{(pr.finishings || []).map((f) => <Chip key={f} active={config.finishing === f} onClick={() => set("finishing", f)} testid={`opt-finishing-${f}`}>{f}</Chip>)}</Section>
                  </>)}
                  {!groups && product.category === "meja" && (<>
                    <Section title={t("cfg.ukuran_tabletop")} note={product.option_notes?.size}>{(pr.sizes || []).map((s) => <Chip key={s} active={config.size === s} onClick={() => set("size", s)} testid={`opt-size-${s}`}>{s} cm</Chip>)}</Section>
                    <Section title={t("cfg.tinggi_meja")} note={product.option_notes?.height}>
                      {(pr.heights || []).map((h) => (
                      <Chip
                        key={h}
                        active={config.height === h}
                        onClick={() => set("height", h)}
                        testid={`opt-height-${h}`}
                      >
                        {h} cm{" "}
                        {h === "30"
                          ? `(${t("cfg.lesehan")})`
                          : h === "75"
                            ? `(${t("cfg.kursi")})`
                            : ""}
                      </Chip>
                    ))}
                  </Section>
                    <Section title={t("cfg.jenis_finishing")} note={product.option_notes?.finishing}>{(pr.finishings || []).map((f) => <Chip key={f} active={config.finishing === f} onClick={() => set("finishing", f)} testid={`opt-finishing-${f}`}>{f}</Chip>)}</Section>
                  </>)}
                  {!groups && product.category === "meja_rak" && (<>
                    <Section title={t("cfg.pilih_varian")} note={product.option_notes?.variant}>{(pr.variants || []).map((v) => <Chip key={v} active={config.variant === v} onClick={() => set("variant", v)} testid={`opt-variant-${v}`}>{v}</Chip>)}</Section>
                    <Section title={t("cfg.tipe")} hint={t("cfg.tipe_hint")} note={product.option_notes?.type}>{(pr.types || []).map((tp) => <Chip key={tp} active={config.type === tp} onClick={() => set("type", tp)} testid={`opt-type-${tp}`}>{t("cfg.tipe")} {tp}</Chip>)}</Section>
                    <Section title={t("cfg.jenis_finishing")} note={product.option_notes?.finishing}>{(pr.finishings || []).map((f) => <Chip key={f} active={config.finishing === f} onClick={() => set("finishing", f)} testid={`opt-finishing-${f}`}>{f}</Chip>)}</Section>
                  </>)}
                  <Section title={t("cfg.jumlah")}>
                    <div className="flex items-center gap-3">
                      <button onClick={() => setQuantity((q) => Math.max(1, q - 1))} data-testid="qty-minus" className="flex h-12 w-12 items-center justify-center rounded-xl border border-[#E5DCC5] bg-white hover:border-[#8B5A2B]"><Minus size={18} /></button>
                      <span className="w-10 text-center text-lg font-semibold" data-testid="qty-value">{quantity}</span>
                      <button onClick={() => setQuantity((q) => q + 1)} data-testid="qty-plus" className="flex h-12 w-12 items-center justify-center rounded-xl border border-[#E5DCC5] bg-white hover:border-[#8B5A2B]"><Plus size={18} /></button>
                    </div>
                  </Section>
                </>
              )}

              <div className="hidden gap-3 lg:flex">
                <Button variant="outline" onClick={() => addToCart(false)} data-testid="add-to-cart-desktop" className="h-12 rounded-full border-[#8B5A2B] px-6 text-[#8B5A2B] hover:bg-[#EFE6D5]"><ShoppingCart size={18} className="mr-2" /> {t("btn.add_to_cart")}</Button>
                <Button onClick={() => addToCart(true)} data-testid="order-now-desktop" className="h-12 rounded-full bg-[#8B5A2B] px-8 hover:bg-[#6B4423]"><Zap size={18} className="mr-2" /> {t("btn.order_now")}</Button>
              </div>
            </>
          )}
          {!isConfigurable && (
            <div className="hidden gap-3 lg:flex">
              <Button onClick={() => addToCart(true)} data-testid="order-now-desktop" className="h-12 rounded-full bg-[#8B5A2B] px-8 hover:bg-[#6B4423]">{t("btn.order_now")}</Button>
            </div>
          )}
        </div>

        {/* Sticky summary desktop */}
        <div className="hidden lg:block">
          <div className="sticky top-24">
            <Summary t={t} breakdown={breakdown} rate={rate} isConfigurable={isConfigurable} custom={config.custom_size} />
          </div>
        </div>
      </div>

      {/* Mobile sticky bar */}
      <div className="fixed bottom-0 left-0 z-40 w-full border-t border-[#E5DCC5] bg-white/95 p-2.5 sm:p-3 shadow-[0_-4px_16px_rgba(0,0,0,0.06)] backdrop-blur-md lg:hidden">
        <div className="flex items-center justify-between px-1">
          <div>
            <div className="text-[10px] text-[#8B7355]">{t("sum.estimasi_total")}</div>
            <div className="font-heading text-lg sm:text-xl font-bold text-[#2C1E16]" data-testid="mobile-total-le">{config.custom_size || !isConfigurable ? "—" : `${fmtLE(breakdown?.subtotal || 0)} LE`}</div>
          </div>
          <div className="flex gap-2">
            {isConfigurable && <Button variant="outline" onClick={() => addToCart(false)} data-testid="add-to-cart-mobile" className="h-10 sm:h-12 rounded-full border-[#8B5A2B] px-3.5 text-[#8B5A2B]"><ShoppingCart size={17} /></Button>}
            <Button onClick={() => addToCart(true)} data-testid="order-now-mobile" className="h-10 sm:h-12 rounded-full bg-[#8B5A2B] px-5 sm:px-6 text-sm hover:bg-[#6B4423]">{t("btn.order_now")}</Button>
          </div>
        </div>
      </div>
    </div>
  );
}

const Section = ({ title, hint, note, children }) => (
  <div className="space-y-1.5">
    <div className="flex flex-wrap items-baseline justify-between gap-x-2">
      <Label className="block font-heading text-xs sm:text-sm font-semibold text-[#2C1E16]">{title}</Label>
      {note && <span className="text-[11px] font-normal text-[#8B5A2B]" data-testid="option-note">{note}</span>}
    </div>
    {hint && <p className="text-[11px] text-[#8B7355] leading-snug">{hint}</p>}
    <div className="flex flex-wrap gap-1.5 sm:gap-2">{children}</div>
  </div>
);

function Summary({ t, breakdown, rate, isConfigurable, custom }) {
  const subtotal = breakdown?.subtotal || 0;
  return (
    <div className="rounded-2xl border border-[#E5DCC5] bg-white p-5 shadow-sm" data-testid="price-summary">
      <h3 className="font-heading text-lg font-bold text-[#2C1E16]">{t("sum.ringkasan")}</h3>
      {custom || !isConfigurable ? (
        <p className="mt-3 text-sm text-[#5C4A3D]">{t("sum.akan_dikonfirmasi")}</p>
      ) : (<>
        <div className="mt-4 space-y-2">
          {breakdown?.lines?.map((l, i) => (
            <div key={i} className="flex justify-between gap-3 text-sm"><span className="text-[#5C4A3D]">{l.label}</span><span className="font-medium text-[#2C1E16]">{l.note ? l.note : `${fmtLE(l.value)} LE`}</span></div>
          ))}
        </div>
        <div className="mt-4 rounded-xl bg-[#EFE6D5] p-4">
          <div className="text-xs font-medium text-[#8B6B45]">{t("sum.estimasi_total")}</div>
          <div className="font-heading text-2xl font-bold text-[#8B5A2B]" data-testid="summary-total-le">{fmtLE(subtotal)} LE</div>
          <div className="text-sm text-[#5C4A3D]" data-testid="summary-total-idr">≈ {fmtIDR(subtotal * rate)}</div>
          <div className="text-[11px] text-[#8B7355]">{t("sum.rate_label")} Rp{fmtLE(rate)}/LE</div>
        </div>
        <p className="mt-3 text-[11px] leading-relaxed text-[#8B7355]">{t("sum.disclaimer")}</p>
      </>)}
    </div>
  );
}
