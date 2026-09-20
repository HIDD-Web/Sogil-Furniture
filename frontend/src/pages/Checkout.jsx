import React, { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import api from "../lib/api";
import { fmtLE, fmtIDR, formatApiError } from "../lib/format";
import { config_summary_client } from "../lib/summary";
import { normalizePhone, validIntlPhone } from "../lib/photoMatch";
import { useCart } from "../context/CartContext";
import { useLang } from "../context/LanguageContext";
import { useCustomer } from "../context/CustomerContext";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Textarea } from "../components/ui/textarea";
import { Label } from "../components/ui/label";
import { toast } from "sonner";
import { Store, Truck, ChevronLeft } from "lucide-react";

const Chip = ({ active, onClick, children, testid }) => (
  <button type="button" onClick={onClick} data-testid={testid}
    className={`min-h-[48px] rounded-xl border px-4 py-2 text-sm font-medium transition-all ${active ? "border-[#8B5A2B] bg-[#8B5A2B] text-white" : "border-[#E5DCC5] bg-white text-[#2C1E16] hover:border-[#8B5A2B]"}`}>{children}</button>
);

export default function Checkout() {
  const { items, productSubtotal, clear } = useCart();
  const { t } = useLang();
  const { customer } = useCustomer();
  const navigate = useNavigate();
  const [zones, setZones] = useState([]);
  const [store, setStore] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [delivery, setDelivery] = useState({ method: "", zone_id: "" });
  const [cust, setCust] = useState({ name: "", phone: "", address: "", maps: "", payment: "", notes: "" });
  const [disc, setDisc] = useState({ code: "", amount: 0, applied: false });
  const [ref, setRef] = useState({ code: "", amount: 0, applied: false });
  const [pts, setPts] = useState(0);

  const applyReferral = async () => {
    if (!ref.code.trim()) return;
    if (!customer) return toast.error("Login sebagai pelanggan untuk memakai referral");
    try {
      const { data } = await api.post("/referral/validate", { code: ref.code, subtotal: productSubtotal });
      if (data.valid) { setRef((r) => ({ ...r, amount: data.discount_amount, applied: true })); toast.success("Referral diterapkan"); }
      else { setRef((r) => ({ ...r, amount: 0, applied: false })); toast.error(data.message); }
    } catch { toast.error("Kode referral tidak valid"); }
  };
  const maxPts = customer ? Math.min(customer.points_available || 0, productSubtotal * ((store?.point_redeem_max_pct || 50) / 100)) : 0;
  const usedPts = Math.max(0, Math.min(Number(pts) || 0, maxPts));

  const applyDiscount = async () => {
    if (!disc.code.trim()) return;
    try {
      const { data } = await api.post("/discounts/validate", { code: disc.code, subtotal: productSubtotal });
      if (data.valid) { setDisc((d) => ({ ...d, amount: data.discount_amount, applied: true })); toast.success(t("sum.discount_ok")); }
      else { setDisc((d) => ({ ...d, amount: 0, applied: false })); toast.error(data.message || t("sum.discount_bad")); }
    } catch { toast.error(t("sum.discount_bad")); }
  };

  useEffect(() => {
    api.get("/delivery-zones").then((r) => setZones(r.data));
    api.get("/store-info").then((r) => setStore(r.data));
  }, []);

  const rate = store?.exchange_rate_idr_per_le || 357;
  const deliveryFee = useMemo(() => {
    if (delivery.method !== "delivery") return 0;
    const z = zones.find((z) => z.id === delivery.zone_id);
    return z ? Number(z.fee_le) : 0;
  }, [delivery, zones]);
  const totalLE = Math.max(0, productSubtotal - (ref.applied ? ref.amount : (disc.applied ? disc.amount : 0)) - usedPts + deliveryFee);

  if (!items.length) {
    return (
      <div className="mx-auto max-w-2xl px-4 py-16 text-center">
        <p className="text-[#5C4A3D]">{t("cart.empty")}</p>
        <Button onClick={() => navigate("/")} className="mt-4 rounded-full bg-[#8B5A2B] px-8">{t("cart.belanja")}</Button>
      </div>
    );
  }

  const submit = async () => {
    if (!cust.name.trim()) return toast.error(t("err.nama"));
    const phone = normalizePhone(cust.phone);
    if (!validIntlPhone(phone)) return toast.error(t("err.phone"));
    if (!cust.address.trim()) return toast.error(t("err.alamat"));
    if (!delivery.method) return toast.error(t("err.metode"));
    if (delivery.method === "delivery" && !delivery.zone_id) return toast.error(t("err.zona"));
    if (!cust.payment) return toast.error(t("err.bayar"));
    if (cust.maps && !/^https?:\/\//.test(cust.maps)) return toast.error(t("err.maps"));

    setSubmitting(true);
    const notes = [cust.notes, ...items.filter((i) => i.config?.custom_size && i.config?.custom_note).map((i) => `Custom (${i.product.name}): ${i.config.custom_note}`)].filter(Boolean).join(" | ");
    try {
      const { data } = await api.post("/orders", {
        customer_name: cust.name, customer_phone: phone, customer_address: cust.address,
        customer_maps_url: cust.maps, delivery_method: delivery.method,
        delivery_zone_id: delivery.method === "delivery" ? delivery.zone_id : null,
        payment_method: cust.payment, notes,
        discount_code: !ref.applied && disc.applied ? disc.code : null,
        referral_code: ref.applied ? ref.code : null,
        redeem_points: usedPts,
        items: items.map((i) => ({ product_id: i.product.id, config: i.config, quantity: i.quantity })),
      });
      clear();
      navigate(`/pesanan/${data.id}`, { state: { order: data } });
    } catch (e) {
      toast.error(formatApiError(e.response?.data?.detail) || t("err.gagal"));
    } finally { setSubmitting(false); }
  };

  return (
    <div className="mx-auto max-w-6xl px-4 py-6 pb-28 sm:px-6 lg:pb-10">
      <button onClick={() => navigate("/keranjang")} className="mb-4 inline-flex items-center gap-1 text-sm text-[#8B5A2B]" data-testid="checkout-back"><ChevronLeft size={16} /> {t("cart.title")}</button>
      <div className="grid gap-8 lg:grid-cols-[1fr_360px]">
        <div className="space-y-6">
          {/* Delivery */}
          <div data-testid="checkout-delivery">
            <h2 className="font-heading text-xl font-bold text-[#2C1E16]">{t("cart.metode")}</h2>
            <div className="mt-3 grid gap-3 sm:grid-cols-2">
              <button onClick={() => setDelivery({ method: "pickup", zone_id: "" })} data-testid="delivery-pickup" className={`rounded-2xl border p-5 text-left ${delivery.method === "pickup" ? "border-[#8B5A2B] bg-[#EFE6D5]" : "border-[#E5DCC5] bg-white hover:border-[#8B5A2B]"}`}>
                <Store className="text-[#8B5A2B]" size={24} /><div className="mt-2 font-heading font-semibold text-[#2C1E16]">{t("del.ambil")}</div><div className="text-sm text-[#5C4A3D]">{t("del.ambil_d")}</div>
              </button>
              <button onClick={() => setDelivery({ method: "delivery", zone_id: "" })} data-testid="delivery-delivery" className={`rounded-2xl border p-5 text-left ${delivery.method === "delivery" ? "border-[#8B5A2B] bg-[#EFE6D5]" : "border-[#E5DCC5] bg-white hover:border-[#8B5A2B]"}`}>
                <Truck className="text-[#8B5A2B]" size={24} /><div className="mt-2 font-heading font-semibold text-[#2C1E16]">{t("del.kirim")}</div><div className="text-sm text-[#5C4A3D]">{t("del.kirim_d")}</div>
              </button>
            </div>
            {delivery.method === "pickup" && store?.store_address && (
              <div className="mt-3 rounded-2xl border border-[#E5DCC5] bg-white p-4 text-sm text-[#5C4A3D]"><div className="font-medium text-[#2C1E16]">{t("del.alamat_toko")}</div><p className="mt-1">{store.store_address}</p></div>
            )}
            {delivery.method === "delivery" && (
              <div className="mt-3">
                <Label className="mb-2 block font-heading text-sm font-semibold text-[#2C1E16]">{t("del.pilih_zona")}</Label>
                <div className="flex flex-wrap gap-2">{zones.map((z) => <Chip key={z.id} active={delivery.zone_id === z.id} onClick={() => setDelivery((d) => ({ ...d, zone_id: z.id }))} testid={`zone-${z.id}`}>{z.name} · {fmtLE(z.fee_le)} LE</Chip>)}</div>
              </div>
            )}
          </div>

          {/* Customer info */}
          <div className="space-y-4" data-testid="checkout-customer">
            <h2 className="font-heading text-xl font-bold text-[#2C1E16]">{t("chk.title")}</h2>
            <div><Label className="mb-1.5 block text-sm">{t("chk.nama")} *</Label><Input value={cust.name} onChange={(e) => setCust({ ...cust, name: e.target.value })} data-testid="input-name" className="h-12 bg-white" /></div>
            <div>
              <Label className="mb-1.5 block text-sm">{t("chk.no_hp")} * <span className="text-xs text-[#8B7355]">(+kode negara)</span></Label>
              <Input value={cust.phone} onChange={(e) => setCust({ ...cust, phone: e.target.value })} data-testid="input-phone" placeholder={t("chk.phone_ph")} className="h-12 bg-white" />
              <p className="mt-1 text-xs text-[#8B7355]">{t("chk.phone_help")}</p>
            </div>
            <div><Label className="mb-1.5 block text-sm">{t("chk.alamat")} *</Label><Textarea value={cust.address} onChange={(e) => setCust({ ...cust, address: e.target.value })} data-testid="input-address" className="min-h-[80px] bg-white" /></div>
            <div><Label className="mb-1.5 block text-sm">{t("chk.link_maps")} {delivery.method === "delivery" ? t("chk.maps_saran") : t("chk.maps_opsional")}</Label><Input value={cust.maps} onChange={(e) => setCust({ ...cust, maps: e.target.value })} data-testid="input-maps" placeholder="https://maps.google.com/..." className="h-12 bg-white" /></div>
            <div>
              <Label className="mb-2 block font-heading text-sm font-semibold text-[#2C1E16]">{t("chk.metode_bayar")} *</Label>
              <div className="flex flex-wrap gap-2"><Chip active={cust.payment === "cash"} onClick={() => setCust({ ...cust, payment: "cash" })} testid="pay-cash">{t("chk.cash")}</Chip><Chip active={cust.payment === "transfer"} onClick={() => setCust({ ...cust, payment: "transfer" })} testid="pay-transfer">{t("chk.transfer")}</Chip></div>
              {cust.payment === "transfer" && <p className="mt-2 text-xs text-[#5C4A3D]">{t("chk.transfer_note")}</p>}
            </div>
            <div><Label className="mb-1.5 block text-sm">{t("chk.catatan")}</Label><Textarea value={cust.notes} onChange={(e) => setCust({ ...cust, notes: e.target.value })} data-testid="input-notes" className="min-h-[70px] bg-white" /></div>
          </div>
        </div>

        {/* Summary */}
        <div className="lg:sticky lg:top-24 lg:h-fit">
          <div className="rounded-2xl border border-[#E5DCC5] bg-white p-5 shadow-sm" data-testid="checkout-summary">
            <h3 className="font-heading text-lg font-bold text-[#2C1E16]">{t("chk.review")}</h3>
            <div className="mt-3 space-y-2">
              {items.map((it) => (
                <div key={it.cartId} className="flex justify-between gap-3 text-sm">
                  <span className="text-[#5C4A3D]">{it.product.name} <span className="text-[#8B7355]">×{it.quantity}</span><br /><span className="text-xs text-[#8B7355]">{config_summary_client(it.product.category, it.config, t)}</span></span>
                  <span className="font-medium text-[#2C1E16]">{it.breakdown?.requiresConfirm ? "—" : `${fmtLE(it.breakdown?.subtotal || 0)} LE`}</span>
                </div>
              ))}
              <div className="flex justify-between border-t border-dashed border-[#E5DCC5] pt-2 text-sm"><span className="text-[#5C4A3D]">{t("sum.subtotal")}</span><span className="font-medium">{fmtLE(productSubtotal)} LE</span></div>
              {disc.applied && <div className="flex justify-between text-sm text-[#738678]"><span>{t("sum.discount_line")} ({disc.code})</span><span className="font-medium">-{fmtLE(disc.amount)} LE</span></div>}
              <div className="flex justify-between text-sm"><span className="text-[#5C4A3D]">{t("sum.pengiriman")}</span><span className="font-medium">{fmtLE(deliveryFee)} LE</span></div>
            </div>
            <div className="mt-3 flex gap-2">
              <Input value={disc.code} onChange={(e) => setDisc({ ...disc, code: e.target.value, applied: false })} placeholder={t("sum.discount_ph")} data-testid="discount-code" className="h-10 bg-white" />
              <Button onClick={applyDiscount} data-testid="apply-discount" variant="outline" className="h-10 rounded-xl border-[#8B5A2B] text-[#8B5A2B]">{t("sum.discount_apply")}</Button>
            </div>
            {customer && (<>
              {ref.applied && <div className="mt-2 flex justify-between text-sm text-[#738678]"><span>Referral ({ref.code})</span><span className="font-medium">-{fmtLE(ref.amount)} LE</span></div>}
              <div className="mt-2 flex gap-2">
                <Input value={ref.code} onChange={(e) => setRef({ ...ref, code: e.target.value, applied: false })} placeholder="Kode referral" data-testid="referral-code" className="h-10 bg-white" />
                <Button onClick={applyReferral} data-testid="apply-referral" variant="outline" className="h-10 rounded-xl border-[#8B5A2B] text-[#8B5A2B]">Pakai</Button>
              </div>
              {maxPts > 0 && (
                <div className="mt-2">
                  <div className="mb-1 flex justify-between text-xs text-[#8B7355]"><span>Tukar Poin (maks {fmtLE(maxPts)})</span>{usedPts > 0 && <span className="text-[#738678]">-{fmtLE(usedPts)} LE</span>}</div>
                  <Input type="number" value={pts} onChange={(e) => setPts(e.target.value)} placeholder="0" data-testid="redeem-points" className="h-10 bg-white" />
                </div>
              )}
            </>)}
            <div className="mt-4 rounded-xl bg-[#EFE6D5] p-4">
              <div className="text-xs font-medium text-[#8B6B45]">{t("sum.estimasi_total")}</div>
              <div className="font-heading text-2xl font-bold text-[#8B5A2B]" data-testid="checkout-total-le">{fmtLE(totalLE)} LE</div>
              <div className="text-sm text-[#5C4A3D]" data-testid="checkout-total-idr">≈ {fmtIDR(totalLE * rate)}</div>
              <div className="text-[11px] text-[#8B7355]">{t("sum.rate_label")} Rp{fmtLE(rate)}/LE</div>
            </div>
            <p className="mt-3 text-[11px] text-[#8B7355]">{t("chk.disclaimer")}</p>
            <Button onClick={submit} disabled={submitting} data-testid="submit-order" className="mt-4 hidden h-12 w-full rounded-full bg-[#25D366] hover:bg-[#1eb556] lg:flex">{submitting ? "..." : t("btn.submit")}</Button>
          </div>
        </div>
      </div>

      <div className="fixed bottom-0 left-0 z-40 w-full border-t border-[#E5DCC5] bg-white/95 p-3 backdrop-blur-md lg:hidden">
        <Button onClick={submit} disabled={submitting} data-testid="submit-order-mobile" className="h-12 w-full rounded-full bg-[#25D366] hover:bg-[#1eb556]">{submitting ? "..." : `${t("btn.submit")} · ${fmtLE(totalLE)} LE`}</Button>
      </div>
    </div>
  );
}
