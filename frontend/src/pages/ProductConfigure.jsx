import React, { useEffect, useMemo, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import api, { imgUrl } from "../lib/api";
import { fmtLE, fmtIDR } from "../lib/format";
import { computeBreakdown } from "../lib/pricing";
import { matchPhoto } from "../lib/photoMatch";
import { CATEGORY_LABELS } from "../lib/constants";
import { ProductImage } from "../components/ProductImage";
import { useCart } from "../context/CartContext";
import { useLang } from "../context/LanguageContext";
import { Button } from "../components/ui/button";
import { Textarea } from "../components/ui/textarea";
import { Label } from "../components/ui/label";
import { toast } from "sonner";
import { Minus, Plus, ChevronLeft, Info, ImageOff, ShoppingCart, Zap } from "lucide-react";

const Chip = ({ active, onClick, children, testid }) => (
  <button type="button" onClick={onClick} data-testid={testid}
    className={`min-h-[48px] rounded-xl border px-4 py-2 text-sm font-medium transition-all ${active ? "border-[#8B5A2B] bg-[#8B5A2B] text-white shadow-sm" : "border-[#E5DCC5] bg-white text-[#2C1E16] hover:border-[#8B5A2B]"}`}>
    {children}
  </button>
);

export default function ProductConfigure() {
  const { slug } = useParams();
  const navigate = useNavigate();
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
      if (p.data.category === "rak") setConfig({ length: (pr.lengths || [])[0], level: (pr.levels || [])[0], type: "B", finishing: "Natural", custom_size: false });
      else if (p.data.category === "meja") setConfig({ size: (pr.sizes || [])[0], height: (pr.heights || [])[0], finishing: "Natural", custom_size: false });
      else if (p.data.category === "meja_rak") setConfig({ variant: (pr.variants || [])[0], type: "B", finishing: "Natural", custom_size: false });
      else setConfig({ custom_size: false });
    }).catch(() => toast.error("Produk tidak ditemukan"));
  }, [slug]);

  const rate = store?.exchange_rate_idr_per_le || 357;
  const breakdown = useMemo(() => (product ? computeBreakdown(product, config, quantity) : null), [product, config, quantity]);
  const photoMatch = useMemo(() => (product ? matchPhoto(product, config) : { photo: null, exact: false }), [product, config]);
  const isConfigurable = product?.configurable;
  const set = (k, v) => setConfig((c) => ({ ...c, [k]: v }));
  const [gidx, setGidx] = useState(0);
  useEffect(() => { setGidx(0); }, [photoMatch.photo?.id]);

  const canAdd = () => {
    if (!isConfigurable) return true;
    if (config.custom_size) return customNote.trim().length > 0;
    if (product.category === "rak") return config.length && config.level && config.type && config.finishing;
    if (product.category === "meja") return config.size && config.height && config.finishing;
    if (product.category === "meja_rak") return config.variant && config.type && config.finishing;
    return true;
  };

  const buildItem = () => ({
    product: { id: product.id, slug: product.slug, name: product.name, category: product.category, image: photoMatch.photo ? (photoMatch.photo.main_url || photoMatch.photo.front_url) : product.display_image },
    config: config.custom_size ? { ...config, custom_note: customNote } : config,
    quantity, breakdown: { ...breakdown }, label: product.name,
  });

  const addToCart = (thenCheckout) => {
    if (!canAdd()) { toast.error(config.custom_size ? t("err.custom_note") : t("err.cfg")); return; }
    addItem(buildItem());
    if (thenCheckout) navigate("/checkout");
    else toast.success(t("err.cart_added"));
  };

  if (!product) return <div className="py-20 text-center text-[#8B7355]">Memuat...</div>;
  const pr = product.pricing || {};
  const ph = photoMatch.photo;
  const photoSlots = ph ? [ph.main_url, ph.front_url, ph.side_url, ...(ph.images || [])].filter(Boolean) : [];
  const gi = Math.min(gidx, Math.max(0, photoSlots.length - 1));

  return (
    <div className="mx-auto max-w-6xl px-4 py-6 pb-40 sm:px-6 lg:pb-10">
      <button onClick={() => navigate("/produk")} className="mb-4 inline-flex items-center gap-1 text-sm text-[#8B5A2B]" data-testid="back-to-catalog">
        <ChevronLeft size={16} /> {t("cfg.kembali_produk")}
      </button>

      <div className="grid gap-8 lg:grid-cols-[1fr_360px]">
        <div className="space-y-6" data-testid="step-config">
          {/* Photo preview */}
          <div>
            <div className="overflow-hidden rounded-2xl border border-[#E5DCC5] bg-white">
              {photoSlots.length ? (
                <div className="aspect-[3/4] w-full overflow-hidden bg-[#FBF9F4]"><img src={imgUrl(photoSlots[gi])} alt={product.name} className="h-full w-full object-contain" data-testid="config-photo-main" /></div>
              ) : (
                <ProductImage url={product.display_image} alt={product.name} />
              )}
            </div>
            {photoSlots.length > 1 && (
              <div className="mt-2 flex gap-2 overflow-x-auto pb-1" data-testid="gallery-thumbs">
                {photoSlots.map((u, i) => (
                  <button key={i} onClick={() => setGidx(i)} data-testid={`gallery-thumb-${i}`} className={`h-16 w-14 shrink-0 overflow-hidden rounded-lg border-2 transition-colors ${i === gi ? "border-[#8B5A2B]" : "border-[#E5DCC5]"}`}>
                    <img src={imgUrl(u)} alt="" className="h-full w-full object-cover" />
                  </button>
                ))}
              </div>
            )}
            {ph && (
              <p className={`mt-2 text-xs ${photoMatch.exact ? "text-[#738678]" : "text-amber-700"}`} data-testid="photo-match-label">
                {photoMatch.exact ? t("cfg.exact_photo") : t("cfg.ref_photo")}
              </p>
            )}
          </div>

          <div>
            <div className="text-xs font-medium uppercase tracking-wide text-[#8B7355]">{CATEGORY_LABELS[product.category]}</div>
            <h1 className="font-heading text-2xl font-bold text-[#2C1E16]">{product.name}</h1>
            <p className="mt-1 text-sm text-[#5C4A3D]">{product.description}</p>
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
              <div>
                <Label className="mb-2 block font-heading text-sm font-semibold text-[#2C1E16]">{t("cfg.jenis_pesanan")}</Label>
                <div className="flex flex-wrap gap-2">
                  <Chip active={!config.custom_size} onClick={() => set("custom_size", false)} testid="opt-standard">{t("cfg.ukuran_standar")}</Chip>
                  <Chip active={config.custom_size} onClick={() => set("custom_size", true)} testid="opt-custom">{t("cfg.ukuran_custom")}</Chip>
                </div>
              </div>

              {config.custom_size ? (
                <div className="rounded-2xl border border-[#E5DCC5] bg-white p-5">
                  <p className="text-sm text-[#5C4A3D]">{t("cfg.custom_info")}</p>
                  <Textarea value={customNote} onChange={(e) => setCustomNote(e.target.value)} data-testid="custom-note" placeholder={t("cfg.custom_ph")} className="mt-3 min-h-[100px] bg-[#FBF9F4]" />
                  <p className="mt-2 text-xs text-amber-700">{t("cfg.custom_note")}</p>
                </div>
              ) : (
                <>
                  {product.category === "rak" && (<>
                    <Section title={t("cfg.pilih_ukuran")} note={product.option_notes?.length}>{(pr.lengths || []).map((l) => <Chip key={l} active={config.length === l} onClick={() => set("length", l)} testid={`opt-length-${l}`}>{l} cm</Chip>)}</Section>
                    <Section title={t("cfg.jumlah_tingkat")} note={product.option_notes?.level}>{(pr.levels || []).map((l) => <Chip key={l} active={config.level === l} onClick={() => set("level", l)} testid={`opt-level-${l}`}>{l} {t("cfg.tingkat")}</Chip>)}</Section>
                    <Section title={t("cfg.tipe_rak")} hint={t("cfg.tipe_hint")} note={product.option_notes?.type}>{(pr.types || []).map((tp) => <Chip key={tp} active={config.type === tp} onClick={() => set("type", tp)} testid={`opt-type-${tp}`}>{t("cfg.tipe")} {tp}</Chip>)}</Section>
                    <Section title={t("cfg.jenis_finishing")} note={product.option_notes?.finishing}>{(pr.finishings || []).map((f) => <Chip key={f} active={config.finishing === f} onClick={() => set("finishing", f)} testid={`opt-finishing-${f}`}>{f}</Chip>)}</Section>
                  </>)}
                  {product.category === "meja" && (<>
                    <Section title={t("cfg.ukuran_tabletop")} note={product.option_notes?.size}>{(pr.sizes || []).map((s) => <Chip key={s} active={config.size === s} onClick={() => set("size", s)} testid={`opt-size-${s}`}>{s} cm</Chip>)}</Section>
                    <Section title={t("cfg.tinggi_meja")} note={product.option_notes?.height}>{(pr.heights || []).map((h) => <Chip key={h} active={config.height === h} onClick={() => set("height", h)} testid={`opt-height-${h}`}>{h} cm {h === "30" ? "(Lesehan)" : h === "75" ? "(Kursi)" : ""}</Chip>)}</Section>
                    <Section title={t("cfg.jenis_finishing")} note={product.option_notes?.finishing}>{(pr.finishings || []).map((f) => <Chip key={f} active={config.finishing === f} onClick={() => set("finishing", f)} testid={`opt-finishing-${f}`}>{f}</Chip>)}</Section>
                  </>)}
                  {product.category === "meja_rak" && (<>
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
      <div className="fixed bottom-0 left-0 z-40 w-full border-t border-[#E5DCC5] bg-white/95 p-3 shadow-[0_-4px_16px_rgba(0,0,0,0.06)] backdrop-blur-md lg:hidden">
        <div className="mb-2 flex items-end justify-between px-1">
          <div>
            <div className="text-[11px] text-[#8B7355]">{t("sum.estimasi_total")}</div>
            <div className="font-heading text-xl font-bold text-[#2C1E16]" data-testid="mobile-total-le">{config.custom_size || !isConfigurable ? "—" : `${fmtLE(breakdown?.subtotal || 0)} LE`}</div>
          </div>
          <div className="flex gap-2">
            {isConfigurable && <Button variant="outline" onClick={() => addToCart(false)} data-testid="add-to-cart-mobile" className="h-12 rounded-full border-[#8B5A2B] px-4 text-[#8B5A2B]"><ShoppingCart size={18} /></Button>}
            <Button onClick={() => addToCart(true)} data-testid="order-now-mobile" className="h-12 rounded-full bg-[#8B5A2B] px-6 hover:bg-[#6B4423]">{t("btn.order_now")}</Button>
          </div>
        </div>
      </div>
    </div>
  );
}

const Section = ({ title, hint, note, children }) => (
  <div>
    <Label className="mb-2 block font-heading text-sm font-semibold text-[#2C1E16]">{title}</Label>
    {hint && <p className="mb-2 text-xs text-[#8B7355]">{hint}</p>}
    {note && <p className="mb-2 text-xs text-[#8B5A2B]" data-testid="option-note">{note}</p>}
    <div className="flex flex-wrap gap-2">{children}</div>
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
