import React, { useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { Home, PackageSearch, User, Smartphone } from "lucide-react";
import { useLang } from "../context/LanguageContext";
import { useCustomer } from "../context/CustomerContext";
import PwaInstallModal from "./PwaInstallModal";

export const BottomNav = () => {
  const [pwaOpen, setPwaOpen] = useState(false);
  const location = useLocation();
  const { t } = useLang();
  const { customer } = useCustomer();

  const pathname = location.pathname;

  const accountLabel = customer
    ? customer.username
      ? customer.username
      : (t("nav.akun_saya") || "Akun Saya")
    : (t("nav.masuk_akun") || "Masuk Akun");

  const navItems = [
    {
      to: "/",
      label: t("nav.beranda") || "Beranda",
      icon: Home,
      isActive: pathname === "/",
      testid: "bottom-nav-beranda",
    },
    {
      to: "/lacak",
      label: t("nav.lacak") || "Lacak",
      icon: PackageSearch,
      isActive: pathname.startsWith("/lacak"),
      testid: "bottom-nav-lacak",
    },
    {
      to: "/akun",
      label: accountLabel,
      icon: User,
      isActive: pathname.startsWith("/akun"),
      testid: "bottom-nav-account",
    },
  ];

  return (
    <>
      <nav
        data-testid="customer-bottom-nav"
        className="fixed bottom-0 left-0 right-0 z-40 border-t border-[#E5DCC5] bg-[#F9F6F0]/95 backdrop-blur-md shadow-[0_-2px_12px_rgba(44,30,22,0.06)] md:hidden"
      >
        <div className="mx-auto grid h-16 max-w-lg grid-cols-4 items-center px-1">
          {navItems.map((item) => {
            const Icon = item.icon;
            return (
              <Link
                key={item.to}
                to={item.to}
                data-testid={item.testid}
                className={`flex flex-col items-center justify-center py-1 px-1 transition-colors min-w-0 ${
                  item.isActive
                    ? "text-[#8B5A2B] font-semibold"
                    : "text-[#8B7355] hover:text-[#2C1E16] font-medium"
                }`}
              >
                <Icon size={20} className="shrink-0" />
                <span className="mt-1 w-full truncate text-center text-[10px] leading-tight">
                  {item.label}
                </span>
              </Link>
            );
          })}

          <button
            type="button"
            onClick={() => setPwaOpen(true)}
            data-testid="bottom-nav-install"
            className="flex flex-col items-center justify-center py-1 px-1 text-[#8B7355] hover:text-[#8B5A2B] transition-colors min-w-0 font-medium"
            title="Pasang Aplikasi di Layar HP"
          >
            <Smartphone size={20} className="shrink-0 text-[#8B5A2B]" />
            <span className="mt-1 w-full truncate text-center text-[10px] leading-tight">
              {t("nav.pasang_hp") || "Pasang di HP"}
            </span>
          </button>
        </div>
      </nav>

      <PwaInstallModal
        isOpen={pwaOpen}
        onClose={() => setPwaOpen(false)}
        mode="customer"
      />
    </>
  );
};

export default BottomNav;
