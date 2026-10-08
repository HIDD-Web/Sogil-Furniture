import React, { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import api from "../../lib/api";
import { fmtLE } from "../../lib/format";
import { ORDER_STATUS, PAYMENT_STATUS } from "../../lib/constants";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { useAuth } from "../../context/AuthContext";
import {
  ShoppingBag,
  Clock,
  Loader,
  PackageCheck,
  CheckCircle2,
  XCircle,
  CircleDollarSign,
  Search,
  Wallet,
} from "lucide-react";
import { toast } from "sonner";

const SUMMARY_CARDS = [
  { key: "total", label: "Total Pesanan", icon: ShoppingBag, color: "text-[#8B5A2B]", filterType: "all" },
  { key: "pesanan_masuk", label: "Pesanan Masuk", icon: Clock, color: "text-amber-600", filterType: "status", filterValue: "pesanan_masuk" },
  { key: "dikonfirmasi", label: "Dikonfirmasi", icon: CheckCircle2, color: "text-blue-600", filterType: "status", filterValue: "dikonfirmasi" },
  { key: "diproses", label: "Diproses", icon: Loader, color: "text-indigo-600", filterType: "status", filterValue: "diproses" },
  { key: "siap", label: "Siap Kirim/Ambil", icon: PackageCheck, color: "text-teal-600", filterType: "status", filterValue: "siap" },
  { key: "selesai", label: "Selesai", icon: CheckCircle2, color: "text-green-600", filterType: "status", filterValue: "selesai" },
  { key: "dibatalkan", label: "Dibatalkan", icon: XCircle, color: "text-red-600", filterType: "status", filterValue: "dibatalkan" },
  { key: "lunas", label: "Sudah Lunas", icon: CircleDollarSign, color: "text-green-700", filterType: "payment", filterValue: "lunas" },
  { key: "belum_dibayar", label: "Belum Dibayar", icon: CircleDollarSign, color: "text-red-500", filterType: "payment", filterValue: "belum_dibayar" },
  { key: "dp", label: "DP", icon: CircleDollarSign, color: "text-amber-500", filterType: "payment", filterValue: "dp" },
];

const FILTER_TABS = [
  { id: "all", label: "Semua", filterType: "all" },
  { id: "pesanan_masuk", label: "Pesanan Masuk", filterType: "status", filterValue: "pesanan_masuk" },
  { id: "dikonfirmasi", label: "Dikonfirmasi", filterType: "status", filterValue: "dikonfirmasi" },
  { id: "diproses", label: "Diproses", filterType: "status", filterValue: "diproses" },
  { id: "siap", label: "Siap Kirim/Ambil", filterType: "status", filterValue: "siap" },
  { id: "selesai", label: "Selesai", filterType: "status", filterValue: "selesai" },
  { id: "dibatalkan", label: "Dibatalkan", filterType: "status", filterValue: "dibatalkan" },
  { id: "lunas", label: "Sudah Lunas", filterType: "payment", filterValue: "lunas" },
  { id: "belum_dibayar", label: "Belum Dibayar", filterType: "payment", filterValue: "belum_dibayar" },
  { id: "dp", label: "DP", filterType: "payment", filterValue: "dp" },
];

export default function AdminOrders() {
  const { user } = useAuth();
  const [orders, setOrders] = useState([]);
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [appliedQ, setAppliedQ] = useState("");
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const status = params.get("status");
  const payment = params.get("payment_status");

  const loadStats = () => {
    api.get("/admin/overview")
      .then((r) => setStats(r.data))
      .catch(() => {});
  };

  useEffect(() => {
    loadStats();
  }, []);

  const loadOrders = () => {
    setLoading(true);
    const q = {};
    if (status) q.status = status;
    if (payment) q.payment_status = payment;
    if (appliedQ) q.q = appliedQ;

    api.get("/admin/orders", { params: q })
      .then((r) => {
        setOrders(Array.isArray(r.data) ? r.data : []);
      })
      .catch((err) => toast.error(err.response?.data?.detail || "Gagal memuat pesanan"))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    loadOrders();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status, payment, appliedQ]);

  const handleFilterSelect = (filterType, filterValue) => {
    const next = new URLSearchParams(params);
    if (!filterType || filterType === "all") {
      next.delete("status");
      next.delete("payment_status");
    } else if (filterType === "status") {
      next.delete("payment_status");
      next.set("status", filterValue);
    } else if (filterType === "payment") {
      next.delete("status");
      next.set("payment_status", filterValue);
    }
    setParams(next);
  };

  const isCardActive = (card) => {
    if (card.filterType === "all") {
      return !status && !payment;
    }
    if (card.filterType === "status") {
      return status === card.filterValue;
    }
    if (card.filterType === "payment") {
      return payment === card.filterValue;
    }
    return false;
  };

  return (
    <div className="space-y-4 sm:space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <div>
          <h1 className="font-heading text-xl sm:text-2xl font-bold text-[#2C1E16]">Pesanan</h1>
          <p className="mt-0.5 text-xs sm:text-sm text-[#8B7355]">
            Kelola dan pantau seluruh pesanan pelanggan.
          </p>
        </div>
        {stats?.estimated_revenue_le !== undefined && (
          <div
            className="rounded-2xl border border-[#E5DCC5] bg-[#8B5A2B] px-3.5 py-2 sm:px-4 sm:py-2.5 text-white shadow-xs flex items-center justify-between sm:justify-start gap-2.5 shrink-0"
            data-testid="stat-revenue"
          >
            <div className="flex items-center gap-2">
              <Wallet size={16} className="text-white/80 shrink-0" />
              <span className="text-xs text-white/90">Estimasi Pendapatan:</span>
            </div>
            <span className="font-heading text-sm sm:text-base font-bold whitespace-nowrap">
              {fmtLE(stats?.estimated_revenue_le || 0)} LE
            </span>
          </div>
        )}
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-2.5 sm:gap-3">
        {SUMMARY_CARDS.map((card) => {
          const isActive = isCardActive(card);
          return (
            <button
              key={card.key}
              onClick={() => handleFilterSelect(card.filterType, card.filterValue)}
              data-testid={`stat-${card.key}`}
              className={`rounded-2xl border p-3 sm:p-4 text-left transition-all ${
                isActive
                  ? "border-[#8B5A2B] bg-[#FAF5EE] shadow-xs ring-1 ring-[#8B5A2B]"
                  : "border-[#E5DCC5] bg-white hover:bg-[#FBF9F4]"
              }`}
            >
              <div className="flex items-center justify-between gap-1">
                <span className="text-[11px] sm:text-xs font-medium text-[#8B7355] truncate">
                  {card.label}
                </span>
                <card.icon size={15} className={`${card.color} shrink-0`} />
              </div>
              <div
                className={`mt-1 font-heading text-lg sm:text-2xl font-bold ${
                  isActive ? "text-[#8B5A2B]" : "text-[#2C1E16]"
                }`}
              >
                {stats?.[card.key] ?? "-"}
              </div>
            </button>
          );
        })}
      </div>

      {/* Filter Tabs & Search */}
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        {/* Status Filter Chips */}
        <div className="flex gap-1.5 overflow-x-auto pb-1 text-xs">
          {FILTER_TABS.map((tab) => {
            const isTabActive =
              tab.filterType === "all"
                ? !status && !payment
                : tab.filterType === "status"
                ? status === tab.filterValue
                : payment === tab.filterValue;
            return (
              <button
                key={tab.id}
                onClick={() => handleFilterSelect(tab.filterType, tab.filterValue)}
                className={`shrink-0 rounded-xl px-3 py-1.5 font-medium transition-colors ${
                  isTabActive
                    ? "bg-[#8B5A2B] text-white"
                    : "border border-[#E5DCC5] bg-white text-[#5C4A3D] hover:bg-[#FBF9F4]"
                }`}
              >
                {tab.label}
              </button>
            );
          })}
        </div>

        {/* Search */}
        <div className="flex gap-2 w-full lg:w-auto">
          <div className="relative flex-1 lg:w-64">
            <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#8B7355]" />
            <Input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && setAppliedQ(search.trim())}
              placeholder="Cari no. pesanan, customer..."
              data-testid="order-search"
              className="bg-white pl-8 text-xs sm:text-sm h-9"
            />
          </div>
          <Button
            onClick={() => setAppliedQ(search.trim())}
            data-testid="order-search-btn"
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
              data-testid="order-search-clear"
              className="rounded-xl border-[#E5DCC5] text-xs h-9 px-2.5 text-[#5C4A3D]"
            >
              Reset
            </Button>
          )}
          {(status || payment) && (
            <Button
              variant="outline"
              onClick={() => handleFilterSelect("all")}
              data-testid="clear-filter"
              className="rounded-xl border-[#8B5A2B] text-xs h-9 px-2.5 text-[#8B5A2B] shrink-0"
            >
              Hapus Filter
            </Button>
          )}
        </div>
      </div>

      {/* Content */}
      {loading ? (
        <div className="py-16 text-center text-sm text-[#8B7355]">Memuat data pesanan...</div>
      ) : orders.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-[#E5DCC5] bg-white p-12 text-center">
          <ShoppingBag size={36} className="mx-auto text-[#8B7355]/60 mb-2" />
          <p className="text-sm font-medium text-[#5C4A3D]">Belum ada pesanan yang sesuai</p>
          <p className="mt-1 text-xs text-[#8B7355]">
            Coba ubah filter atau kata kunci pencarian
          </p>
        </div>
      ) : (
        <>
          {/* Mobile View: Order Cards */}
          <div className="space-y-3 md:hidden">
            {orders.map((o) => {
              const orderId = o.id || o._id;
              const payCfg = PAYMENT_STATUS[o.payment_status] || { label: o.payment_status, color: "bg-stone-100 text-stone-700" };
              const stCfg = ORDER_STATUS[o.order_status] || { label: o.order_status, color: "bg-stone-100 text-stone-700" };
              const itemsList = (o.items || [o.item]).filter(Boolean);
              return (
                <div
                  key={orderId}
                  onClick={() => navigate(`/admin/orders/${orderId}`)}
                  data-testid={`order-card-${o.order_number}`}
                  className="cursor-pointer rounded-2xl border border-[#E5DCC5] bg-white p-4 shadow-xs transition-shadow hover:shadow-sm"
                >
                  <div className="flex items-start justify-between gap-2 border-b border-[#F1EBE0] pb-2.5">
                    <div>
                      <span className="font-mono text-xs font-bold text-[#8B5A2B]">{o.order_number}</span>
                      <p className="text-[11px] text-[#8B7355]">
                        {new Date(o.created_at).toLocaleDateString("id-ID", {
                          day: "numeric",
                          month: "short",
                          year: "numeric",
                        })}
                      </p>
                    </div>
                    <div className="flex flex-wrap gap-1 items-center justify-end">
                      <div className="flex flex-col items-end gap-0.5">
                        <Badge variant="outline" className={`px-2 py-0.5 text-[10px] ${payCfg.color}`}>
                          {payCfg.label}
                        </Badge>
                        {o.legacy_dp_unknown && (
                          <span className="text-[9px] text-amber-700 font-medium">
                            Nominal Tidak Tersedia
                          </span>
                        )}
                      </div>
                      <Badge variant="outline" className={`px-2 py-0.5 text-[10px] ${stCfg.color}`}>
                        {stCfg.label}
                      </Badge>
                    </div>
                  </div>

                  <div className="mt-2.5 flex items-center justify-between gap-2">
                    <div>
                      <span className="font-semibold text-sm text-[#2C1E16]">{o.customer_name || "-"}</span>
                      {o.customer_phone && <p className="text-xs text-[#8B7355]">{o.customer_phone}</p>}
                    </div>
                    <div className="text-right">
                      <span className="font-heading text-sm font-bold text-[#2C1E16]">{fmtLE(o.total_le)} LE</span>
                    </div>
                  </div>

                  <p className="mt-2 text-xs text-[#5C4A3D] line-clamp-1">
                    {itemsList.map((it) => it?.product_name_snapshot).filter(Boolean).join(", ") || "-"}
                  </p>

                  <div className="mt-2.5 flex items-center justify-between border-t border-[#F1EBE0] pt-2 text-[11px] text-[#8B7355]">
                    <span>{o.delivery_method === "delivery" ? (o.delivery_zone_name || "Delivery") : "Ambil Sendiri"}</span>
                    <span className="text-[#8B5A2B] font-medium">Detail &rarr;</span>
                  </div>
                </div>
              );
            })}
          </div>

          {/* Desktop View: Full Table */}
          <div className="hidden md:block overflow-hidden rounded-2xl border border-[#E5DCC5] bg-white shadow-xs">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-[#F1EBE0] text-left text-xs uppercase tracking-wide text-[#8B7355]">
                  <tr>
                    <th className="px-4 py-3">No. Pesanan</th>
                    <th className="px-4 py-3">Tanggal</th>
                    <th className="px-4 py-3">Customer</th>
                    <th className="px-4 py-3">Produk</th>
                    <th className="px-4 py-3">Kirim</th>
                    <th className="px-4 py-3">Total</th>
                    <th className="px-4 py-3">Bayar</th>
                    <th className="px-4 py-3">Status</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#F1EBE0]">
                  {orders.map((o) => {
                    const orderId = o.id || o._id;
                    const payCfg = PAYMENT_STATUS[o.payment_status] || { label: o.payment_status, color: "bg-stone-100 text-stone-700" };
                    const stCfg = ORDER_STATUS[o.order_status] || { label: o.order_status, color: "bg-stone-100 text-stone-700" };
                    const itemsList = (o.items || [o.item]).filter(Boolean);
                    return (
                      <tr
                        key={orderId}
                        onClick={() => navigate(`/admin/orders/${orderId}`)}
                        data-testid={`order-row-${o.order_number}`}
                        className="cursor-pointer hover:bg-[#FBF9F4] transition-colors"
                      >
                        <td className="px-4 py-3 font-semibold text-[#8B5A2B] whitespace-nowrap">
                          {o.order_number}
                        </td>
                        <td className="px-4 py-3 text-xs text-[#8B7355] whitespace-nowrap">
                          {new Date(o.created_at).toLocaleDateString("id-ID", {
                            day: "numeric",
                            month: "short",
                            year: "numeric",
                          })}
                        </td>
                        <td className="px-4 py-3">
                          <div className="font-medium text-[#2C1E16]">{o.customer_name || "-"}</div>
                          {o.customer_phone && <div className="text-xs text-[#8B7355]">{o.customer_phone}</div>}
                        </td>
                        <td className="px-4 py-3 text-[#5C4A3D] max-w-xs">
                          <div className="truncate text-xs">
                            {itemsList.map((it) => it?.product_name_snapshot).filter(Boolean).join(", ") || "-"}
                          </div>
                        </td>
                        <td className="px-4 py-3 text-xs text-[#5C4A3D] whitespace-nowrap">
                          {o.delivery_method === "delivery" ? (o.delivery_zone_name || "Delivery") : "Ambil Sendiri"}
                        </td>
                        <td className="px-4 py-3 font-bold text-[#2C1E16] whitespace-nowrap">
                          {fmtLE(o.total_le)} LE
                        </td>
                        <td className="px-4 py-3 whitespace-nowrap">
                          <div className="flex flex-col gap-0.5">
                            <Badge variant="outline" className={payCfg.color}>
                              {payCfg.label}
                            </Badge>
                            {o.legacy_dp_unknown && (
                              <span className="text-[10px] text-amber-700 font-medium">
                                Nominal Tidak Tersedia
                              </span>
                            )}
                          </div>
                        </td>
                        <td className="px-4 py-3 whitespace-nowrap">
                          <Badge variant="outline" className={stCfg.color}>
                            {stCfg.label}
                          </Badge>
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
