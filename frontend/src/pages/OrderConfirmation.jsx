import React, { useEffect, useState } from "react";
import { useParams, useLocation, Link } from "react-router-dom";
import api from "../lib/api";
import { fmtLE, fmtIDR } from "../lib/format";
import { config_summary_client } from "../lib/summary";
import { useLang } from "../context/LanguageContext";
import { Button } from "../components/ui/button";
import { CheckCircle2, MessageCircle, Copy, Home } from "lucide-react";
import { toast } from "sonner";

export default function OrderConfirmation() {
  const { id } = useParams();
  const location = useLocation();
  const { t } = useLang();
  const [order, setOrder] = useState(location.state?.order || null);

  useEffect(() => { if (!order) api.get(`/orders/${id}`).then((r) => setOrder(r.data)).catch(() => {}); }, [id]);

  useEffect(() => {
    if (order?.whatsapp_number && order?.whatsapp_message) {
      const num = order.whatsapp_number.replace(/[^0-9]/g, "");
      const url = `https://wa.me/${num}?text=${encodeURIComponent(order.whatsapp_message)}`;
      const tm = setTimeout(() => window.open(url, "_blank"), 1200);
      return () => clearTimeout(tm);
    }
  }, [order?.id]);

  if (!order) return <div className="py-20 text-center text-[#8B7355]">...</div>;
  const num = (order.whatsapp_number || "").replace(/[^0-9]/g, "");
  const waUrl = `https://wa.me/${num}?text=${encodeURIComponent(order.whatsapp_message || "")}`;
  const items = order.items || [order.item];
  const copySummary = () => { navigator.clipboard.writeText(order.whatsapp_message || ""); toast.success(t("btn.salin")); };

  return (
    <div className="mx-auto max-w-2xl px-4 py-10 sm:px-6">
      <div className="rounded-2xl border border-[#E5DCC5] bg-white p-6 text-center shadow-sm sm:p-8">
        <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-full bg-green-100 text-green-600"><CheckCircle2 size={36} /></div>
        <h1 className="mt-4 font-heading text-2xl font-bold text-[#2C1E16]">{t("conf.tersimpan")}</h1>
        <p className="mt-1 text-sm text-[#5C4A3D]">{t("conf.nomor")}</p>
        <div className="mt-1 font-heading text-2xl font-bold tracking-tight text-[#8B5A2B]" data-testid="order-number">{order.order_number}</div>

        <div className="mt-6 space-y-1.5 rounded-xl bg-[#EFE6D5] p-4 text-left" data-testid="order-breakdown">
          {items.map((it, i) => it && (
            <div key={i} className="flex justify-between text-sm"><span className="text-[#5C4A3D]">{it.product_name_snapshot} ×{it.quantity}<br /><span className="text-xs text-[#8B7355]">{config_summary_client(it.category, it.configuration_snapshot)}</span></span><span className="font-medium text-[#2C1E16]">{fmtLE(it.subtotal_le)} LE</span></div>
          ))}
          <div className="flex justify-between border-t border-dashed border-[#D8C9AD] pt-2 text-sm"><span className="text-[#5C4A3D]">Subtotal</span><span className="font-medium text-[#2C1E16]">{fmtLE(order.subtotal_le)} LE</span></div>
          {order.discount_le > 0 && <div className="flex justify-between text-sm text-green-700" data-testid="conf-discount"><span>Diskon{order.discount_code ? ` (${order.discount_code})` : ""}</span><span>-{fmtLE(order.discount_le)} LE</span></div>}
          {order.referral_discount_le > 0 && <div className="flex justify-between text-sm text-green-700" data-testid="conf-referral-discount"><span>Diskon Referral{order.referral?.code ? ` (${order.referral.code})` : ""}</span><span>-{fmtLE(order.referral_discount_le)} LE</span></div>}
          {order.points_redeemed_le > 0 && <div className="flex justify-between text-sm text-green-700"><span>Penukaran Poin</span><span>-{fmtLE(order.points_redeemed_le)} LE</span></div>}
          <div className="flex justify-between text-sm"><span className="text-[#5C4A3D]">Ongkir</span><span className="font-medium text-[#2C1E16]">{fmtLE(order.delivery_fee_le)} LE</span></div>
          <div className="flex justify-between border-t border-dashed border-[#D8C9AD] pt-2"><span className="text-sm text-[#5C4A3D]">{t("conf.estimasi_total")}</span>
            <span className="text-right"><span className="block font-heading text-lg font-bold text-[#8B5A2B]">{fmtLE(order.total_le)} LE</span><span className="block text-xs text-[#8B7355]">≈ {fmtIDR(order.estimated_total_idr)} · Rp{fmtLE(order.exchange_rate_idr_per_le)}/LE</span></span>
          </div>
        </div>

        {order.requires_admin_confirmation && <p className="mt-3 rounded-lg bg-amber-50 p-2 text-xs text-amber-700">{t("conf.perlu_konfirmasi")}</p>}
        <p className="mt-5 text-sm text-[#5C4A3D]">{t("conf.wa_info")}</p>

        <a href={waUrl} target="_blank" rel="noreferrer" data-testid="whatsapp-button">
          <Button className="mt-4 h-12 w-full rounded-full bg-[#25D366] text-base hover:bg-[#1eb556]"><MessageCircle size={20} className="mr-2" /> {t("conf.lanjut_wa")}</Button>
        </a>
        <div className="mt-3 flex gap-3">
          <Button variant="outline" onClick={copySummary} data-testid="copy-summary" className="h-11 flex-1 rounded-full border-[#8B5A2B] text-[#8B5A2B]"><Copy size={16} className="mr-1" /> {t("btn.salin")}</Button>
          <Link to="/" className="flex-1"><Button variant="outline" className="h-11 w-full rounded-full border-[#E5DCC5] text-[#5C4A3D]"><Home size={16} className="mr-1" /> {t("btn.beranda")}</Button></Link>
        </div>
      </div>
    </div>
  );
}
