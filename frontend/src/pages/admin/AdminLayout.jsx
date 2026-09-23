import React, { useState } from "react";
import { NavLink, Outlet, useNavigate, Navigate } from "react-router-dom";
import api from "../../lib/api";
import { useAuth } from "../../context/AuthContext";
import { Logo } from "../../components/Logo";
import { LayoutDashboard, ShoppingBag, Sparkles, Package, Layers, Settings, LogOut, Menu, X, BarChart3, Wallet, Users, Ticket, Gift, UserRound, Smartphone } from "lucide-react";
import { Button } from "../../components/ui/button";
import PwaInstallModal from "../../components/PwaInstallModal";

export default function AdminLayout() {
  const { user, checked, logout } = useAuth();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [pwaModalOpen, setPwaModalOpen] = useState(false);
  const [storeInfo, setStoreInfo] = useState(null);

  React.useEffect(() => {
    api.get("/store-info").then((r) => setStoreInfo(r.data)).catch(() => {});
  }, []);

  if (!checked || user === null) return <div className="flex min-h-screen items-center justify-center text-[#8B7355]">Memuat...</div>;
  if (!user) return <Navigate to="/admin/login" replace />;

  const currentLogo = storeInfo?.logo_url || user?.logo_url;

  const perms = user.permissions || {};
  const isOwner = user.role === "owner";
  const LINKS = [
    { to: "/admin", label: "Overview", icon: LayoutDashboard, end: true, show: true },
    { to: "/admin/orders", label: "Pesanan", icon: ShoppingBag, show: perms.manage_orders || isOwner },
    { to: "/admin/custom-requests", label: "Request Custom", icon: Sparkles, show: perms.manage_orders || isOwner },
    { to: "/admin/analytics", label: "Analitik", icon: BarChart3, show: perms.manage_orders || isOwner },
    { to: "/admin/products", label: "Produk", icon: Package, show: perms.modify_products || isOwner },
    { to: "/admin/finance", label: "Keuangan", icon: Wallet, show: perms.access_finance || isOwner },
    { to: "/admin/finance/statistics", label: "Statistik", icon: BarChart3, show: perms.access_finance || isOwner },
    { to: "/admin/export", label: "Export Data", icon: Wallet, show: perms.access_finance || perms.manage_orders || isOwner },
    { to: "/admin/discounts", label: "Diskon", icon: Ticket, show: perms.manage_settings || isOwner },
    { to: "/admin/referrals", label: "Referral", icon: Gift, show: perms.manage_settings || isOwner },
    { to: "/admin/customers", label: "Pelanggan", icon: UserRound, show: perms.manage_orders || isOwner },
    { to: "/admin/admins", label: "Akun Tim", icon: Users, show: isOwner },
    { to: "/admin/settings", label: "Pengaturan", icon: Settings, show: perms.manage_settings || isOwner },
  ].filter((l) => l.show);

  const doLogout = async () => { await logout(); navigate("/admin/login"); };
  const Items = () => (<>{LINKS.map((l) => (
    <NavLink key={l.to} to={l.to} end={l.end} onClick={() => setOpen(false)} data-testid={`admin-nav-${l.label.toLowerCase().replace(/\s/g, "-")}`}
      className={({ isActive }) => `flex items-center gap-3 rounded-xl px-4 py-3 text-sm font-medium transition-colors ${isActive ? "bg-[#8B5A2B] text-white" : "text-[#5C4A3D] hover:bg-[#EFE6D5]"}`}>
      <l.icon size={18} /> {l.label}
    </NavLink>))}</>);

  return (
    <div className="min-h-screen bg-[#F9F6F0]">
      <div className="flex items-center justify-between border-b border-[#E5DCC5] bg-white px-4 py-3 lg:hidden">
        <Logo size={36} logoUrl={currentLogo} />
        <button onClick={() => setOpen(!open)} data-testid="admin-mobile-toggle" className="p-2">{open ? <X /> : <Menu />}</button>
      </div>
      <div className="flex">
        <aside className="sticky top-0 hidden h-screen w-64 shrink-0 flex-col border-r border-[#E5DCC5] bg-white p-4 lg:flex">
          <div className="px-2 py-2"><Logo logoUrl={currentLogo} /></div>
          <div className="mt-1 px-2 text-xs text-[#8B7355]">{user.name} · {user.role}</div>
          <nav className="mt-4 flex flex-1 flex-col gap-1 overflow-y-auto"><Items /></nav>
          <div className="pt-3 border-t border-[#F1EBE0] space-y-2">
            <Button
              variant="outline"
              onClick={() => setPwaModalOpen(true)}
              className="w-full justify-start rounded-xl border-[#8B5A2B]/30 bg-[#FAF5EE] text-[#8B5A2B] hover:bg-[#F3ECE0] text-xs font-semibold"
            >
              <Smartphone size={15} className="mr-2 text-[#8B5A2B]" /> Pasang di Layar HP
            </Button>
            <Button variant="outline" onClick={doLogout} data-testid="admin-logout" className="w-full rounded-xl border-[#E5DCC5] text-[#5C4A3D]">
              <LogOut size={16} className="mr-2" /> Keluar
            </Button>
          </div>
        </aside>
        {open && (
          <div className="absolute z-30 w-full border-b border-[#E5DCC5] bg-white p-4 lg:hidden">
            <nav className="flex flex-col gap-1"><Items /></nav>
            <Button
              variant="outline"
              onClick={() => { setOpen(false); setPwaModalOpen(true); }}
              className="mt-2 w-full rounded-xl border-[#8B5A2B]/30 bg-[#FAF5EE] text-[#8B5A2B] hover:bg-[#F3ECE0] text-xs font-semibold"
            >
              <Smartphone size={15} className="mr-2 text-[#8B5A2B]" /> Pasang di Layar HP
            </Button>
            <Button variant="outline" onClick={doLogout} className="mt-2 w-full rounded-xl border-[#E5DCC5] text-[#5C4A3D]"><LogOut size={16} className="mr-2" /> Keluar</Button>
          </div>
        )}
        <main className="min-w-0 flex-1 p-4 sm:p-6 lg:p-8"><Outlet /></main>
      </div>

      <PwaInstallModal
        isOpen={pwaModalOpen}
        onClose={() => setPwaModalOpen(false)}
        mode="admin"
      />
    </div>
  );
}
