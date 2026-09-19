import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import api from "../../lib/api";
import { fmtLE } from "../../lib/format";
import { ShoppingBag, Clock, Loader, PackageCheck, CheckCircle2, XCircle, Wallet, CircleDollarSign } from "lucide-react";

const CARDS = [
  { key: "total", label: "Total Pesanan", icon: ShoppingBag, color: "text-[#8B5A2B]", filter: null },
  { key: "pesanan_masuk", label: "Pesanan Masuk", icon: Clock, color: "text-amber-600", filter: { status: "pesanan_masuk" } },
  { key: "dikonfirmasi", label: "Dikonfirmasi", icon: CheckCircle2, color: "text-blue-600", filter: { status: "dikonfirmasi" } },
  { key: "diproses", label: "Diproses", icon: Loader, color: "text-indigo-600", filter: { status: "diproses" } },
  { key: "siap", label: "Siap Kirim/Ambil", icon: PackageCheck, color: "text-teal-600", filter: { status: "siap" } },
  { key: "selesai", label: "Selesai", icon: CheckCircle2, color: "text-green-600", filter: { status: "selesai" } },
  { key: "dibatalkan", label: "Dibatalkan", icon: XCircle, color: "text-red-600", filter: { status: "dibatalkan" } },
  { key: "lunas", label: "Sudah Lunas", icon: CircleDollarSign, color: "text-green-700", filter: { payment_status: "lunas" } },
  { key: "belum_dibayar", label: "Belum Dibayar", icon: CircleDollarSign, color: "text-red-500", filter: { payment_status: "belum_dibayar" } },
  { key: "dp", label: "DP", icon: CircleDollarSign, color: "text-amber-500", filter: { payment_status: "dp" } },
];

export default function AdminOverview() {
  const [stats, setStats] = useState(null);
  const navigate = useNavigate();
  useEffect(() => {
    api.get("/admin/overview")
      .then((r) => setStats(r.data))
      .catch(() => {});
  }, []);

  const go = (filter) => {
    if (!filter) return navigate("/admin/orders");
    const q = new URLSearchParams(filter).toString();
    navigate(`/admin/orders?${q}`);
  };

  return (
    <div>
      <h1 className="font-heading text-2xl font-bold text-[#2C1E16]">Overview</h1>
      <p className="mt-1 text-sm text-[#8B7355]">Klik kartu untuk melihat pesanan terkait.</p>
      <div className="mt-4 sm:mt-6 grid grid-cols-2 gap-2.5 sm:gap-4 lg:grid-cols-4">
        {CARDS.map((c) => (
          <button key={c.key} onClick={() => go(c.filter)} data-testid={`stat-${c.key}`}
            className="rounded-xl sm:rounded-2xl border border-[#E5DCC5] bg-white p-3 sm:p-5 text-left shadow-xs transition-shadow hover:shadow-md">
            <div className="flex items-center justify-between gap-1">
              <span className="text-xs sm:text-sm font-medium text-[#5C4A3D] line-clamp-1">{c.label}</span>
              <c.icon size={18} className={`${c.color} shrink-0`} />
            </div>
            <div className="mt-1.5 sm:mt-2 font-heading text-xl sm:text-3xl font-bold text-[#2C1E16]">{stats?.[c.key] ?? "-"}</div>
          </button>
        ))}
        <div className="col-span-2 sm:col-span-2 lg:col-span-4 rounded-xl sm:rounded-2xl border border-[#E5DCC5] bg-[#8B5A2B] p-3.5 sm:p-5 text-white shadow-xs" data-testid="stat-revenue">
          <div className="flex items-center justify-between"><span className="text-xs sm:text-sm text-white/80">Estimasi Pendapatan (non-batal)</span><Wallet size={18} className="shrink-0" /></div>
          <div className="mt-1 sm:mt-2 font-heading text-xl sm:text-3xl font-bold">{fmtLE(stats?.estimated_revenue_le || 0)} LE</div>
        </div>
      </div>
    </div>
  );
}
