import React, { useState, useEffect } from "react";
import { createPortal } from "react-dom";
import { Button } from "./ui/button";
import {
  Smartphone,
  Share,
  PlusSquare,
  MoreVertical,
  Download,
  CheckCircle,
  X,
  Shield,
  Sparkles
} from "lucide-react";

export default function PwaInstallModal({ isOpen, onClose, mode = "customer" }) {
  const [activeTab, setActiveTab] = useState("ios");
  const [deferredPrompt, setDeferredPrompt] = useState(null);
  const [isStandalone, setIsStandalone] = useState(false);

  useEffect(() => {
    // Detect iOS
    const isIos = /iPad|iPhone|iPod/.test(navigator.userAgent) && !window.MSStream;
    setActiveTab(isIos ? "ios" : "android");

    // Detect standalone
    const standalone =
      window.matchMedia("(display-mode: standalone)").matches ||
      window.navigator.standalone === true;
    setIsStandalone(standalone);

    // Listen for beforeinstallprompt on Android/Chrome
    const handleBeforeInstall = (e) => {
      e.preventDefault();
      setDeferredPrompt(e);
    };

    window.addEventListener("beforeinstallprompt", handleBeforeInstall);
    return () => {
      window.removeEventListener("beforeinstallprompt", handleBeforeInstall);
    };
  }, []);

  if (!isOpen) return null;

  const handleInstallClick = async () => {
    if (deferredPrompt) {
      deferredPrompt.prompt();
      const choiceResult = await deferredPrompt.userChoice;
      if (choiceResult.outcome === "accepted") {
        setDeferredPrompt(null);
        onClose();
      }
    }
  };

  const isAdmin = mode === "admin";

  return createPortal(
    <div className="fixed inset-0 z-[9999] overflow-y-auto bg-black/60 backdrop-blur-xs p-4 flex items-center justify-center">
      <div className="relative w-full max-w-md my-auto rounded-3xl border border-[#E5DCC5] bg-white p-5 sm:p-7 shadow-2xl max-h-[85vh] overflow-y-auto">
        <button
          onClick={onClose}
          className="absolute right-4 top-4 rounded-full p-1.5 text-[#8B7355] hover:bg-[#FAF5EE] hover:text-[#2C1E16] transition-colors"
        >
          <X size={18} />
        </button>

        {/* Header */}
        <div className="text-center pb-2">
          <div
            className={`mx-auto mb-3 flex h-14 w-14 items-center justify-center rounded-2xl shadow-sm ${
              isAdmin ? "bg-[#2C1E16] text-amber-300" : "bg-[#8B5A2B] text-white"
            }`}
          >
            {isAdmin ? <Shield size={28} /> : <Smartphone size={28} />}
          </div>
          <h2 className="font-heading text-lg sm:text-xl font-bold text-[#2C1E16]">
            {isAdmin ? "Pasang Dashboard Tim di HP" : "Pasang Aplikasi di Layar HP"}
          </h2>
          <p className="mt-1 text-xs text-[#8B7355] leading-relaxed">
            {isAdmin
              ? "Buka langsung menu manajemen pesanan & operasional Sogil Furniture dari layar HP tanpa mengetik alamat web lagi."
              : "Akses katalog furniture, konfigurator produk, dan konsultasi custom langsung dari layar utama HP Anda."}
          </p>

          <div
            className={`mt-2.5 inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-[11px] font-semibold ${
              isAdmin
                ? "bg-[#FAF5EE] text-[#8B5A2B] border border-[#E5DCC5]"
                : "bg-amber-50 text-amber-800 border border-amber-200"
            }`}
          >
            <Sparkles size={13} />
            {isAdmin
              ? "Langsung membuka Dashboard Tim Sogil"
              : "Langsung membuka Beranda Katalog Sogil"}
          </div>
        </div>

        {isStandalone ? (
          <div className="mt-4 rounded-2xl bg-emerald-50 border border-emerald-200 p-4 text-center">
            <CheckCircle className="mx-auto text-emerald-600 mb-1" size={24} />
            <p className="text-xs font-semibold text-emerald-900">
              Aplikasi Sudah Terpasang!
            </p>
            <p className="text-[11px] text-emerald-700 mt-0.5">
              Anda sedang membuka aplikasi ini langsung dari layar utama HP.
            </p>
          </div>
        ) : (
          <>
            {/* Direct Install Button (If Chrome/Android prompt is ready) */}
            {deferredPrompt && (
              <div className="mt-3 mb-2">
                <Button
                  onClick={handleInstallClick}
                  className={`w-full rounded-2xl py-3 font-semibold text-sm flex items-center justify-center gap-2 shadow-md ${
                    isAdmin
                      ? "bg-[#2C1E16] hover:bg-[#1A120D] text-white"
                      : "bg-[#8B5A2B] hover:bg-[#6B4423] text-white"
                  }`}
                >
                  <Download size={16} /> Pasang Sekarang (Instal Otomatis)
                </Button>
              </div>
            )}

            {/* Tab Selector */}
            <div className="mt-4 flex rounded-xl bg-[#FAF5EE] p-1 border border-[#E5DCC5]">
              <button
                onClick={() => setActiveTab("ios")}
                className={`flex-1 rounded-lg py-1.5 text-xs font-semibold transition-all ${
                  activeTab === "ios"
                    ? "bg-white text-[#2C1E16] shadow-xs"
                    : "text-[#8B7355] hover:text-[#2C1E16]"
                }`}
              >
                iPhone / iPad (iOS)
              </button>
              <button
                onClick={() => setActiveTab("android")}
                className={`flex-1 rounded-lg py-1.5 text-xs font-semibold transition-all ${
                  activeTab === "android"
                    ? "bg-white text-[#2C1E16] shadow-xs"
                    : "text-[#8B7355] hover:text-[#2C1E16]"
                }`}
              >
                Android / Chrome
              </button>
            </div>

            {/* Step-by-Step Instructions */}
            <div className="mt-4 space-y-3">
              {activeTab === "ios" ? (
                <>
                  <div className="flex items-start gap-3 rounded-2xl border border-[#F1EBE0] bg-[#FAF5EE]/50 p-3">
                    <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-[#8B5A2B] text-xs font-bold text-white">
                      1
                    </div>
                    <div className="text-xs text-[#2C1E16] leading-relaxed">
                      Buka web ini di browser <strong className="font-semibold text-[#8B5A2B]">Safari</strong>, lalu ketuk tombol <strong className="font-semibold text-[#8B5A2B]">Bagikan (Share)</strong>{" "}
                      <Share size={13} className="inline-block text-[#8B5A2B] mx-0.5 -mt-0.5" /> di bilah bawah layar iPhone Anda.
                    </div>
                  </div>

                  <div className="flex items-start gap-3 rounded-2xl border border-[#F1EBE0] bg-[#FAF5EE]/50 p-3">
                    <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-[#8B5A2B] text-xs font-bold text-white">
                      2
                    </div>
                    <div className="text-xs text-[#2C1E16] leading-relaxed">
                      Gulir menu ke bawah dan ketuk opsi <strong className="font-semibold text-[#8B5A2B]">"Tambahkan ke Layar Utama" (Add to Home Screen)</strong>{" "}
                      <PlusSquare size={13} className="inline-block text-[#8B5A2B] mx-0.5 -mt-0.5" />.
                    </div>
                  </div>

                  <div className="flex items-start gap-3 rounded-2xl border border-[#F1EBE0] bg-[#FAF5EE]/50 p-3">
                    <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-[#8B5A2B] text-xs font-bold text-white">
                      3
                    </div>
                    <div className="text-xs text-[#2C1E16] leading-relaxed">
                      Ketuk tombol <strong className="font-semibold text-[#8B5A2B]">"Tambah" (Add)</strong> di pojok kanan atas. Ikon Sogil akan langsung muncul di layar utama HP Anda layaknya aplikasi biasa!
                    </div>
                  </div>
                </>
              ) : (
                <>
                  <div className="flex items-start gap-3 rounded-2xl border border-[#F1EBE0] bg-[#FAF5EE]/50 p-3">
                    <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-[#8B5A2B] text-xs font-bold text-white">
                      1
                    </div>
                    <div className="text-xs text-[#2C1E16] leading-relaxed">
                      Buka web ini di browser <strong className="font-semibold text-[#8B5A2B]">Google Chrome</strong>, lalu ketuk ikon <strong className="font-semibold text-[#8B5A2B]">Titik Tiga (⋮)</strong>{" "}
                      <MoreVertical size={13} className="inline-block text-[#8B5A2B] mx-0.5 -mt-0.5" /> di pojok kanan atas.
                    </div>
                  </div>

                  <div className="flex items-start gap-3 rounded-2xl border border-[#F1EBE0] bg-[#FAF5EE]/50 p-3">
                    <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-[#8B5A2B] text-xs font-bold text-white">
                      2
                    </div>
                    <div className="text-xs text-[#2C1E16] leading-relaxed">
                      Pilih menu <strong className="font-semibold text-[#8B5A2B]">"Instal Aplikasi"</strong> atau <strong className="font-semibold text-[#8B5A2B]">"Tambahkan ke Layar Utama"</strong>.
                    </div>
                  </div>

                  <div className="flex items-start gap-3 rounded-2xl border border-[#F1EBE0] bg-[#FAF5EE]/50 p-3">
                    <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-[#8B5A2B] text-xs font-bold text-white">
                      3
                    </div>
                    <div className="text-xs text-[#2C1E16] leading-relaxed">
                      Ketuk <strong className="font-semibold text-[#8B5A2B]">"Instal"</strong> untuk mengonfirmasi. Aplikasi akan otomatis terpasang di HP Anda.
                    </div>
                  </div>
                </>
              )}
            </div>
          </>
        )}

        <div className="mt-5 pt-3 border-t border-[#F1EBE0] flex justify-end">
          <Button
            variant="outline"
            onClick={onClose}
            className="w-full rounded-2xl text-xs sm:text-sm border-[#E5DCC5] font-medium"
          >
            Mengerti & Tutup
          </Button>
        </div>
      </div>
    </div>,
    document.body
  );
}
