import React, { useState } from "react";
import api from "../lib/api";
import { fmtLE, fmtIDR, formatApiError } from "../lib/format";
import { config_summary_client } from "../lib/summary";
import { ORDER_STATUS, PAYMENT_STATUS } from "../lib/constants";
import { useLang } from "../context/LanguageContext";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Badge } from "../components/ui/badge";
import { PackageSearch } from "lucide-react";
import { toast } from "sonner";

export default function GuestTrackOrder() {
  const { t } = useLang();
  const [f, setF] = useState({ order_number: "", phone: "" });
  const [order, setOrder] = useState(null);
  const [loading, setLoading] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    if (!f.order_number || !f.phone) return toast.error(t("track.err_fill"));
    setLoading(true);
    try {
      const r = await api.post("/orders/track", f);
      setOrder(r.data);
    } catch (err) {
      setOrder(null);
      toast.error(formatApiError(err.response?.data?.detail));
    } finally { setLoading(false); }
  };

  const items = order ? (order.items || []) : [];

  return (
    <div className="mx-auto max-w-lg px-4 py-12 sm:px-6">
      <div className="rounded-2xl border border-[#E5DCC5] bg-white p-6 shadow-sm">
        <div className="flex justify-center"><div className="flex h-12 w-12 items-center justify-center rounded-full bg-[#EFE6D5] text-[#8B5A2B]"><PackageSearch /></div></div>
        <h1 className="mt-3 text-center font-heading text-xl font-bold text-[#2C1E16]">{t("track.title")}</h1>
        <p className="mt-1 text-center text-xs text-[#8B7355]">{t("track.desc")}</p>
        <form onSubmit={submit} className="mt-5 space-y-3">
          <div><Label className="mb-1 block text-sm">{t("track.order_num")}</Label><Input value={f.order_number} onChange={(e) => setF({ ...f, order_number: e.target.value })} placeholder="SGF-20260827-001" data-testid="track-order-number" className="bg-white" required /></div>
          <div><Label className="mb-1 block text-sm">{t("track.phone")}</Label><Input value={f.phone} onChange={(e) => setF({ ...f, phone: e.target.value })} placeholder="+201234567890" data-testid="track-phone" className="bg-white" required /></div>
          <Button type="submit" disabled={loading} data-testid="track-submit" className="h-11 w-full rounded-xl bg-[#8B5A2B] hover:bg-[#6B4423]">{loading ? t("track.searching") : t("track.btn_track")}</Button>
        </form>
      </div>

      {order && (
        <div className="mt-6 rounded-2xl border border-[#E5DCC5] bg-white p-6 shadow-sm" data-testid="track-result">
          <div className="flex items-center justify-between">
            <div className="font-heading text-lg font-bold text-[#8B5A2B]">{order.order_number}</div>
            <div className="flex gap-1">
              <Badge variant="outline" className={PAYMENT_STATUS[order.payment_status]?.color}>{PAYMENT_STATUS[order.payment_status]?.label || order.payment_status}</Badge>
              <Badge variant="outline" className={ORDER_STATUS[order.order_status]?.color}>{ORDER_STATUS[order.order_status]?.label || order.order_status}</Badge>
            </div>
          </div>
          <div className="mt-1 text-sm text-[#8B7355]">{t("track.for_customer")} {order.customer_name} · {(order.created_at || "").slice(0, 10)}</div>
          <div className="mt-3 space-y-1.5 border-t border-dashed border-[#E5DCC5] pt-3">
            {items.map((it, i) => it && (
              <div key={i} className="flex justify-between text-sm">
                <span className="text-[#5C4A3D]">{it.product_name_snapshot}{config_summary_client(it.category, it.configuration_snapshot) ? ` — ${config_summary_client(it.category, it.configuration_snapshot)}` : ""} ×{it.quantity}</span>
                <span className="font-medium text-[#2C1E16]">{fmtLE(it.subtotal_le)} LE</span>
              </div>
            ))}
          </div>
          <div className="mt-3 space-y-1 border-t border-dashed border-[#E5DCC5] pt-3 text-sm">
            <div className="flex justify-between"><span className="text-[#5C4A3D]">Subtotal</span><span>{fmtLE(order.subtotal_le)} LE</span></div>
            {order.discount_le > 0 && <div className="flex justify-between text-green-700"><span>Diskon</span><span>-{fmtLE(order.discount_le)} LE</span></div>}
            {order.referral_discount_le > 0 && <div className="flex justify-between text-green-700"><span>Diskon Referral</span><span>-{fmtLE(order.referral_discount_le)} LE</span></div>}
            {order.points_redeemed_le > 0 && <div className="flex justify-between text-green-700"><span>Penukaran Poin</span><span>-{fmtLE(order.points_redeemed_le)} LE</span></div>}
            <div className="flex justify-between"><span className="text-[#5C4A3D]">{order.delivery_method === "delivery" ? `Ongkir${order.delivery_zone_name ? ` (${order.delivery_zone_name})` : ""}` : "Ambil di Toko"}</span><span>{fmtLE(order.delivery_fee_le)} LE</span></div>
            <div className="flex justify-between border-t border-dashed border-[#E5DCC5] pt-2 font-bold text-[#8B5A2B]"><span>Total</span><span>{fmtLE(order.total_le)} LE</span></div>
            <div className="text-right text-xs text-[#8B7355]">≈ {fmtIDR(order.estimated_total_idr)} · Rp{fmtLE(order.exchange_rate_idr_per_le)}/LE</div>
          </div>
        </div>
      )}
    </div>
  );
}
