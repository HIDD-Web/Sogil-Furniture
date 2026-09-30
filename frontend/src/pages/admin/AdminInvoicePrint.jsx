import React, { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import api from "../../lib/api";
import { fmtLE } from "../../lib/format";
import { Button } from "../../components/ui/button";
import { Printer, ChevronLeft, AlertCircle } from "lucide-react";
import { toast } from "sonner";

export default function AdminInvoicePrint() {
  const { id } = useParams();
  const navigate = useNavigate();

  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    setLoading(true);
    api.get(`/admin/invoices/${id}/print`)
      .then((r) => {
        setData(r.data);
      })
      .catch((err) => {
        const msg = err.response?.data?.detail || "Gagal memuat dokumen cetak invoice";
        setError(msg);
        toast.error(msg);
      })
      .finally(() => setLoading(false));
  }, [id]);

  const handlePrint = () => {
    window.print();
  };

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-white text-sm text-[#8B7355]">
        Memuat dokumen invoice untuk cetak...
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center bg-white p-6 text-center space-y-4">
        <AlertCircle size={36} className="text-red-500" />
        <div className="text-base font-semibold text-[#2C1E16]">
          {error || "Dokumen invoice tidak ditemukan"}
        </div>
        <Button
          onClick={() => navigate(`/admin/invoices/${id}`)}
          className="rounded-xl bg-[#8B5A2B] text-xs text-white"
        >
          Kembali ke Detail Invoice
        </Button>
      </div>
    );
  }

  const { invoice, store_info: store } = data;
  const cust = invoice.customer || {};
  const items = invoice.items || [];

  return (
    <div className="min-h-screen bg-neutral-100 py-4 sm:py-8 print:bg-white print:py-0">
      {/* Print Controls Bar (Screen Only - Hidden in Print) */}
      <div className="no-print max-w-[210mm] mx-auto mb-4 px-4 flex items-center justify-between">
        <Button
          variant="outline"
          size="sm"
          onClick={() => navigate(`/admin/invoices/${id}`)}
          className="rounded-xl border-[#E5DCC5] bg-white text-xs text-[#5C4A3D] hover:bg-[#FAF8F5]"
        >
          <ChevronLeft size={15} className="mr-1" /> Kembali ke Detail
        </Button>
        <div className="flex items-center gap-2">
          <span className="text-xs text-[#8B7355] hidden sm:inline">
            Siap cetak standar format A4
          </span>
          <Button
            size="sm"
            onClick={handlePrint}
            className="rounded-xl bg-[#8B5A2B] hover:bg-[#6B4423] text-xs font-semibold text-white shadow-sm"
          >
            <Printer size={14} className="mr-1.5" /> Cetak / Simpan PDF
          </Button>
        </div>
      </div>

      {/* A4 Sheet Container */}
      <div className="invoice-sheet max-w-[210mm] min-h-[297mm] mx-auto bg-white p-8 sm:p-12 shadow-md print:shadow-none print:p-6 print:m-0 print:max-w-none text-neutral-800">
        {/* Header */}
        <div className="flex items-start justify-between border-b-2 border-neutral-800 pb-5">
          <div>
            <div className="font-heading text-2xl sm:text-3xl font-black tracking-tight text-neutral-900">
              {store?.store_name || "SOGIL FURNITURE"}
            </div>
            <div className="text-xs font-medium uppercase tracking-widest text-[#8B5A2B] mt-0.5">
              {store?.tagline || "Furniture & Custom Order"}
            </div>
            <div className="text-[11px] text-neutral-600 mt-2 space-y-0.5">
              {store?.store_address && <div>{store.store_address}</div>}
              {store?.whatsapp_number && <div>WhatsApp: {store.whatsapp_number}</div>}
            </div>
          </div>

          <div className="text-right">
            <div className="text-2xl sm:text-3xl font-black tracking-tight text-neutral-900">
              INVOICE
            </div>
            <div className="font-mono text-sm sm:text-base font-bold text-[#8B5A2B] mt-1">
              {invoice.invoice_number}
            </div>
            <div className="text-xs text-neutral-600 mt-1">
              Tanggal: {new Date(invoice.created_at).toLocaleDateString("id-ID", {
                day: "numeric",
                month: "long",
                year: "numeric",
              })}
            </div>
            <div className="text-xs text-neutral-600">
              No. Pesanan: <strong className="font-mono">{invoice.order_number || "-"}</strong>
            </div>
          </div>
        </div>

        {/* Customer Information Block */}
        <div className="mt-6 rounded-xl border border-neutral-300 bg-neutral-50/50 p-4">
          <div className="text-[10px] font-bold uppercase tracking-wider text-neutral-500 mb-2">
            Ditujukan Kepada (Customer):
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-xs">
            <div>
              <div className="font-bold text-sm text-neutral-900">{cust.name || "-"}</div>
              <div className="text-neutral-700 mt-0.5">WhatsApp: {cust.whatsapp || "-"}</div>
              {cust.egypt_phone && (
                <div className="text-neutral-700">No. Mesir: {cust.egypt_phone}</div>
              )}
            </div>
            <div>
              <span className="text-neutral-500 text-[11px]">Alamat Pengiriman:</span>
              <p className="text-neutral-800 mt-0.5 whitespace-pre-line">
                {cust.address || "Dikonfirmasi langsung via WhatsApp"}
              </p>
            </div>
          </div>
        </div>

        {/* Items Table */}
        <div className="mt-6">
          <table className="w-full text-left text-xs border-collapse">
            <thead>
              <tr className="border-b-2 border-neutral-800 bg-neutral-100 text-neutral-800">
                <th className="py-2.5 px-3 font-bold w-10 text-center">No.</th>
                <th className="py-2.5 px-3 font-bold">Item & Spesifikasi</th>
                <th className="py-2.5 px-3 font-bold w-14 text-center">Qty</th>
                <th className="py-2.5 px-3 font-bold w-24 text-right">Harga (LE)</th>
                <th className="py-2.5 px-3 font-bold w-28 text-right">Total (LE)</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-neutral-200">
              {items.map((it, idx) => {
                const dims = it.dimensions || {};
                const dimsParts = [
                  dims.length && `P: ${dims.length} cm`,
                  dims.width && `L: ${dims.width} cm`,
                  dims.height && `T: ${dims.height} cm`,
                  dims.notes,
                ].filter(Boolean);

                return (
                  <tr key={it.item_id || idx} className="page-break-avoid">
                    <td className="py-3 px-3 text-center align-top font-medium text-neutral-500">
                      {idx + 1}
                    </td>
                    <td className="py-3 px-3 align-top">
                      <div className="font-bold text-neutral-900 text-xs sm:text-sm">
                        {it.name}
                      </div>
                      {it.description && (
                        <p className="text-[11px] text-neutral-600 mt-0.5">{it.description}</p>
                      )}
                      <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-neutral-600">
                        {dimsParts.length > 0 && (
                          <span>Dimensi: {dimsParts.join(" × ")}</span>
                        )}
                        {it.material && <span>Bahan: {it.material}</span>}
                        {it.finishing && <span>Finishing: {it.finishing}</span>}
                      </div>
                      {it.notes && (
                        <div className="text-[11px] text-neutral-700 italic mt-0.5">
                          * {it.notes}
                        </div>
                      )}
                    </td>
                    <td className="py-3 px-3 text-center align-top font-bold text-neutral-800">
                      {it.quantity}
                    </td>
                    <td className="py-3 px-3 text-right align-top text-neutral-700">
                      {fmtLE(it.unit_price)}
                    </td>
                    <td className="py-3 px-3 text-right align-top font-bold text-neutral-900">
                      {fmtLE(it.line_total)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {/* Calculation & Notes Block */}
        <div className="mt-6 pt-2 border-t-2 border-neutral-800 grid grid-cols-1 sm:grid-cols-2 gap-6 page-break-avoid">
          {/* Notes and Payment Information */}
          <div className="space-y-3 text-xs">
            {invoice.customer_note ? (
              <div className="rounded-xl border border-neutral-200 bg-neutral-50 p-3">
                <div className="font-bold text-[11px] uppercase tracking-wide text-neutral-700 mb-1">
                  Catatan Pesanan:
                </div>
                <p className="text-neutral-800 whitespace-pre-wrap leading-relaxed">
                  {invoice.customer_note}
                </p>
              </div>
            ) : null}

            {store?.bank_info && (
              <div className="text-[11px] text-neutral-600">
                <div className="font-bold uppercase tracking-wide text-neutral-700 mb-0.5">
                  Informasi Pembayaran:
                </div>
                <div className="whitespace-pre-line font-mono text-[11px] bg-neutral-50 p-2.5 rounded-lg border border-neutral-200">
                  {store.bank_info}
                </div>
              </div>
            )}
          </div>

          {/* Pricing Totals Table */}
          <div className="space-y-1.5 text-xs">
            <div className="flex justify-between py-1 border-b border-neutral-200 text-neutral-700">
              <span>Subtotal</span>
              <span className="font-semibold text-neutral-900">{fmtLE(invoice.subtotal)} LE</span>
            </div>

            {invoice.discount_amount > 0 && (
              <div className="flex justify-between py-1 border-b border-neutral-200 text-red-700">
                <span>Diskon</span>
                <span>-{fmtLE(invoice.discount_amount)} LE</span>
              </div>
            )}

            {invoice.delivery_fee > 0 && (
              <div className="flex justify-between py-1 border-b border-neutral-200 text-neutral-700">
                <span>Biaya Pengiriman</span>
                <span>+{fmtLE(invoice.delivery_fee)} LE</span>
              </div>
            )}

            {invoice.additional_fee > 0 && (
              <div className="flex justify-between py-1 border-b border-neutral-200 text-neutral-700">
                <span>Biaya Tambahan</span>
                <span>+{fmtLE(invoice.additional_fee)} LE</span>
              </div>
            )}

            <div className="flex justify-between pt-2 text-sm sm:text-base font-bold text-neutral-900 border-t-2 border-neutral-900">
              <span>TOTAL</span>
              <span className="font-heading text-[#8B5A2B]">{fmtLE(invoice.total)} LE</span>
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="mt-10 pt-4 border-t border-neutral-300 text-center text-[10px] text-neutral-500 space-y-1 page-break-avoid">
          <p className="font-semibold text-neutral-700">
            Terima kasih telah mempercayakan kebutuhan furniture Anda kepada Sogil Furniture.
          </p>
          <p>
            Dokumen ini diterbitkan resmi sebagai bukti penawaran dan rincian pesanan.
          </p>
        </div>
      </div>

      {/* Embedded CSS for Print Optimization */}
      <style>{`
        @media print {
          body {
            background: white !important;
            color: black !important;
          }
          .no-print {
            display: none !important;
          }
          .invoice-sheet {
            max-width: 100% !important;
            margin: 0 !important;
            padding: 0 !important;
            box-shadow: none !important;
            border: none !important;
          }
          .page-break-avoid {
            page-break-inside: avoid;
            break-inside: avoid;
          }
          @page {
            size: A4 portrait;
            margin: 15mm 15mm 15mm 15mm;
          }
        }
      `}</style>
    </div>
  );
}
