import React, { useEffect, useState } from "react";
import { useNavigate, useSearchParams, Link } from "react-router-dom";
import api from "../../lib/api";
import { fmtLE } from "../../lib/format";
import { INVOICE_STATUS } from "../../lib/constants";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { useAuth } from "../../context/AuthContext";
import { Plus, Search, FileText, Printer, Eye, ExternalLink } from "lucide-react";
import { toast } from "sonner";

export default function AdminInvoices() {
  const { user } = useAuth();
  const [invoices, setInvoices] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [appliedQ, setAppliedQ] = useState("");
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const statusFilter = params.get("status") || "all";

  const [globalCounts, setGlobalCounts] = useState({
    all: 0,
    draft: 0,
    sent: 0,
    claimed: 0,
    converted: 0,
    cancelled: 0,
  });

  const loadGlobalCounts = () => {
    api.get("/admin/invoices")
      .then((r) => {
        const allList = Array.isArray(r.data) ? r.data : [];
        setGlobalCounts({
          all: allList.length,
          draft: allList.filter((x) => x.status === "DRAFT").length,
          sent: allList.filter((x) => x.status === "SENT").length,
          claimed: allList.filter((x) => x.status === "CLAIMED").length,
          converted: allList.filter((x) => x.status === "CONVERTED").length,
          cancelled: allList.filter((x) => x.status === "CANCELLED").length,
        });
      })
      .catch(() => {});
  };

  useEffect(() => {
    loadGlobalCounts();
  }, []);

  const loadInvoices = () => {
    setLoading(true);
    const q = {};
    if (statusFilter && statusFilter !== "all") {
      q.status = statusFilter;
    }
    if (appliedQ) {
      q.q = appliedQ;
    }
    api.get("/admin/invoices", { params: q })
      .then((r) => {
        const list = Array.isArray(r.data) ? r.data : [];
        setInvoices(list);
        if ((!statusFilter || statusFilter === "all") && !appliedQ) {
          setGlobalCounts({
            all: list.length,
            draft: list.filter((x) => x.status === "DRAFT").length,
            sent: list.filter((x) => x.status === "SENT").length,
            converted: list.filter((x) => x.status === "CONVERTED").length,
            cancelled: list.filter((x) => x.status === "CANCELLED").length,
          });
        }
      })
      .catch((err) => toast.error(err.response?.data?.detail || "Gagal memuat invoice"))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    loadInvoices();
  }, [statusFilter, appliedQ]);

  const handleStatusTab = (st) => {
    const next = new URLSearchParams(params);
    if (!st || st === "all") {
      next.delete("status");
    } else {
      next.set("status", st);
    }
    setParams(next);
  };

  return (
    <div className="space-y-4 sm:space-y-6">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="font-heading text-xl sm:text-2xl font-bold text-[#2C1E16]">Invoice</h1>
          <p className="mt-0.5 text-xs sm:text-sm text-[#8B7355]">
            Kelola penawaran dan invoice pra-order untuk pesanan custom & manual
          </p>
        </div>
        <Button
          onClick={() => navigate("/admin/invoices/new")}
          className="rounded-xl bg-[#8B5A2B] text-xs sm:text-sm font-semibold hover:bg-[#6B4423] text-white shadow-sm"
        >
          <Plus size={16} className="mr-1.5" /> Buat Invoice
        </Button>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2.5 sm:gap-3">
        {[
          { id: "all", label: "Semua", count: globalCounts.all, color: "text-[#2C1E16]" },
          { id: "DRAFT", label: "Draft", count: globalCounts.draft, color: "text-stone-700" },
          { id: "SENT", label: "Menunggu Klaim", count: globalCounts.sent, color: "text-blue-700" },
          { id: "CLAIMED", label: "Sudah Diklaim", count: globalCounts.claimed, color: "text-amber-700" },
          { id: "CONVERTED", label: "Masuk Pesanan", count: globalCounts.converted, color: "text-emerald-700" },
          { id: "CANCELLED", label: "Dibatalkan", count: globalCounts.cancelled, color: "text-red-700" },
        ].map((card) => {
          const isActive = (card.id === "all" && statusFilter === "all") || statusFilter === card.id;
          return (
            <button
              key={card.id}
              onClick={() => handleStatusTab(card.id)}
              className={`rounded-2xl border p-3 sm:p-4 text-left transition-all ${
                isActive
                  ? "border-[#8B5A2B] bg-[#FAF5EE] shadow-xs ring-1 ring-[#8B5A2B]"
                  : "border-[#E5DCC5] bg-white hover:bg-[#FBF9F4]"
              }`}
            >
              <div className="text-[11px] sm:text-xs font-medium text-[#8B7355] truncate">{card.label}</div>
              <div className={`mt-1 font-heading text-lg sm:text-2xl font-bold ${card.color}`}>
                {card.count}
              </div>
            </button>
          );
        })}
      </div>

      {/* Filter Tabs & Search */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        {/* Status Filter Chips */}
        <div className="flex gap-1.5 overflow-x-auto pb-1 text-xs">
          {[
            { id: "all", label: "Semua" },
            { id: "DRAFT", label: "Draft" },
            { id: "SENT", label: "Menunggu Klaim" },
            { id: "CLAIMED", label: "Sudah Diklaim" },
            { id: "CONVERTED", label: "Masuk Pesanan" },
            { id: "CANCELLED", label: "Dibatalkan" },
          ].map((tab) => (
            <button
              key={tab.id}
              onClick={() => handleStatusTab(tab.id)}
              className={`shrink-0 rounded-xl px-3 py-1.5 font-medium transition-colors ${
                (tab.id === "all" && statusFilter === "all") || statusFilter === tab.id
                  ? "bg-[#8B5A2B] text-white"
                  : "border border-[#E5DCC5] bg-white text-[#5C4A3D] hover:bg-[#FBF9F4]"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>

        {/* Search */}
        <div className="flex gap-2 w-full sm:w-auto">
          <div className="relative flex-1 sm:w-64">
            <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#8B7355]" />
            <Input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && setAppliedQ(search.trim())}
              placeholder="Cari nomor, nama, WA, order..."
              className="bg-white pl-8 text-xs sm:text-sm h-9"
            />
          </div>
          <Button
            onClick={() => setAppliedQ(search.trim())}
            className="rounded-xl bg-[#8B5A2B] text-xs h-9 px-3 hover:bg-[#6B4423]"
          >
            Cari
          </Button>
          {appliedQ && (
            <Button
              variant="outline"
              onClick={() => {
                setSearch("");
                setAppliedQ("");
              }}
              className="rounded-xl border-[#E5DCC5] text-xs h-9 px-2.5 text-[#5C4A3D]"
            >
              Reset
            </Button>
          )}
        </div>
      </div>

      {/* Content */}
      {loading ? (
        <div className="py-16 text-center text-sm text-[#8B7355]">Memuat data invoice...</div>
      ) : invoices.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-[#E5DCC5] bg-white p-12 text-center">
          <FileText size={36} className="mx-auto text-[#8B7355]/60 mb-2" />
          <p className="text-sm font-medium text-[#5C4A3D]">Belum ada invoice yang sesuai</p>
          <p className="mt-1 text-xs text-[#8B7355]">
            Klik tombol &ldquo;Buat Invoice&rdquo; untuk membuat penawaran baru
          </p>
        </div>
      ) : (
        <>
          {/* Mobile Card List (md:hidden) */}
          <div className="space-y-3 md:hidden">
            {invoices.map((inv) => {
              const invId = inv.id || inv._id;
              const statusCfg = INVOICE_STATUS[inv.status] || INVOICE_STATUS.DRAFT;
              const itemCount = (inv.items || []).length;
              return (
                <div
                  key={invId}
                  onClick={() => navigate(`/admin/invoices/${invId}`)}
                  className="cursor-pointer rounded-2xl border border-[#E5DCC5] bg-white p-4 shadow-xs transition-shadow hover:shadow-sm"
                >
                  <div className="flex items-start justify-between gap-2 border-b border-[#F1EBE0] pb-2.5">
                    <div>
                      <span className="font-mono text-xs font-bold text-[#8B5A2B]">
                        {inv.invoice_number}
                      </span>
                      <p className="text-[11px] text-[#8B7355]">
                        {new Date(inv.created_at).toLocaleDateString("id-ID", {
                          day: "numeric",
                          month: "short",
                          year: "numeric",
                        })}
                      </p>
                    </div>
                    <Badge variant="outline" className={`px-2 py-0.5 text-[11px] ${statusCfg.color}`}>
                      {statusCfg.label}
                    </Badge>
                  </div>

                  <div className="mt-2.5 flex items-center justify-between gap-2">
                    <div>
                      <span className="font-semibold text-sm text-[#2C1E16]">
                        {inv.customer?.name || "Tanpa Nama"}
                      </span>
                      <p className="text-xs text-[#8B7355]">{inv.customer?.whatsapp || "-"}</p>
                    </div>
                    <div className="text-right">
                      <span className="text-sm font-bold text-[#8B5A2B]">
                        {fmtLE(inv.total)} LE
                      </span>
                      <p className="text-[11px] text-[#8B7355]">{itemCount} item</p>
                    </div>
                  </div>

                  {inv.order_number && (
                    <div className="mt-2 rounded-xl bg-[#FAF5EE] px-2.5 py-1.5 text-xs text-[#8B5A2B] flex items-center justify-between">
                      <span>Pesanan: <strong>{inv.order_number}</strong></span>
                      <span className="text-[11px] underline">Buka Order &rarr;</span>
                    </div>
                  )}

                  <div className="mt-3 flex items-center justify-end gap-1.5 border-t border-[#F1EBE0] pt-2.5">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={(e) => {
                        e.stopPropagation();
                        navigate(`/admin/invoices/${invId}/print`);
                      }}
                      className="h-8 rounded-lg border-[#E5DCC5] text-xs text-[#5C4A3D]"
                    >
                      <Printer size={13} className="mr-1" /> Cetak
                    </Button>
                    <Button
                      size="sm"
                      onClick={(e) => {
                        e.stopPropagation();
                        navigate(`/admin/invoices/${invId}`);
                      }}
                      className="h-8 rounded-lg bg-[#8B5A2B] text-xs text-white hover:bg-[#6B4423]"
                    >
                      <Eye size={13} className="mr-1" /> Detail
                    </Button>
                  </div>
                </div>
              );
            })}
          </div>

          {/* Desktop Table View (hidden on md-) */}
          <div className="hidden md:block overflow-hidden rounded-2xl border border-[#E5DCC5] bg-white shadow-xs">
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="border-b border-[#E5DCC5] bg-[#FAF5EE] text-[#5C4A3D]">
                  <tr>
                    <th className="px-4 py-3 font-semibold">No. Invoice</th>
                    <th className="px-4 py-3 font-semibold">Customer</th>
                    <th className="px-4 py-3 font-semibold">Total (LE)</th>
                    <th className="px-4 py-3 font-semibold">Status</th>
                    <th className="px-4 py-3 font-semibold">Pesanan</th>
                    <th className="px-4 py-3 font-semibold">Tanggal</th>
                    <th className="px-4 py-3 font-semibold text-right">Aksi</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#F1EBE0]">
                  {invoices.map((inv) => {
                    const invId = inv.id || inv._id;
                    const statusCfg = INVOICE_STATUS[inv.status] || INVOICE_STATUS.DRAFT;
                    return (
                      <tr
                        key={invId}
                        onClick={() => navigate(`/admin/invoices/${invId}`)}
                        className="cursor-pointer hover:bg-[#FAF8F5] transition-colors"
                      >
                        <td className="px-4 py-3">
                          <span className="font-mono font-bold text-[#8B5A2B]">
                            {inv.invoice_number}
                          </span>
                          <div className="text-[11px] text-[#8B7355]">
                            {(inv.items || []).length} item
                          </div>
                        </td>
                        <td className="px-4 py-3">
                          <div className="font-medium text-[#2C1E16]">
                            {inv.customer?.name || "Tanpa Nama"}
                          </div>
                          <div className="text-[11px] text-[#8B7355]">
                            {inv.customer?.whatsapp || "-"}
                          </div>
                        </td>
                        <td className="px-4 py-3 font-bold text-[#8B5A2B]">
                          {fmtLE(inv.total)} LE
                        </td>
                        <td className="px-4 py-3">
                          <Badge variant="outline" className={`px-2 py-0.5 text-[11px] ${statusCfg.color}`}>
                            {statusCfg.label}
                          </Badge>
                        </td>
                        <td className="px-4 py-3">
                          {inv.order_number ? (
                            <Link
                              to={`/admin/orders/${inv.order_id}`}
                              onClick={(e) => e.stopPropagation()}
                              className="inline-flex items-center gap-1 font-mono text-[11px] font-semibold text-purple-700 hover:underline"
                            >
                              {inv.order_number}
                              <ExternalLink size={11} />
                            </Link>
                          ) : (
                            <span className="text-[#8B7355]">-</span>
                          )}
                        </td>
                        <td className="px-4 py-3 text-[#5C4A3D]">
                          {new Date(inv.created_at).toLocaleDateString("id-ID", {
                            day: "numeric",
                            month: "short",
                            year: "numeric",
                          })}
                        </td>
                        <td className="px-4 py-3 text-right">
                          <div className="flex items-center justify-end gap-1.5" onClick={(e) => e.stopPropagation()}>
                            <Button
                              variant="outline"
                              size="sm"
                              onClick={() => navigate(`/admin/invoices/${invId}/print`)}
                              className="h-8 rounded-lg border-[#E5DCC5] text-xs text-[#5C4A3D]"
                              title="Cetak Invoice"
                            >
                              <Printer size={13} className="mr-1" /> Cetak
                            </Button>
                            <Button
                              size="sm"
                              onClick={() => navigate(`/admin/invoices/${invId}`)}
                              className="h-8 rounded-lg bg-[#8B5A2B] text-xs text-white hover:bg-[#6B4423]"
                            >
                              <Eye size={13} className="mr-1" /> Detail
                            </Button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
