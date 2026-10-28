import React, { useEffect, useState, useMemo } from "react";
import api from "../../lib/api";
import { formatApiError, fmtLE } from "../../lib/format";
import { useAuth } from "../../context/AuthContext";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Textarea } from "../../components/ui/textarea";
import {
  CircleDollarSign,
  ShieldCheck,
  ShieldAlert,
  Save,
  RotateCcw,
  Calculator,
  History,
  AlertTriangle,
  Info,
  CheckCircle2,
  Coins,
  Hammer,
  Truck,
  ShoppingBag,
  UserCheck,
  Users,
  Calendar,
  ArrowRight,
  X,
} from "lucide-react";
import { toast } from "sonner";

/**
 * Shared Exact Integer Piastre Allocation Utility (Frontend).
 * 100% parity with backend distribute_wage_piastres:
 * - 1 EGP = 100 piastres
 * - Quotient = floor(totalPiastres / n)
 * - Remainder = totalPiastres % n
 * - First remainder workers receive +1 piastre
 * - Checksum guarantees exact sum without any drift.
 */
function calculatePiastreAllocations(totalAmount, count) {
  const n = Math.max(1, parseInt(count, 10) || 1);
  const totalPiastres = Math.round((Number(totalAmount) || 0) * 100);
  if (totalPiastres < 0) return { list: [], totalPiastres: 0, checksum: 0 };

  const quotient = Math.floor(totalPiastres / n);
  const remainder = totalPiastres % n;

  const list = [];
  let checksum = 0;
  for (let i = 0; i < n; i++) {
    const p = i < remainder ? quotient + 1 : quotient;
    checksum += p;
    list.push({
      index: i + 1,
      piastres: p,
      amount_le: (p / 100).toFixed(2),
      pct: totalPiastres > 0 ? ((p / totalPiastres) * 100).toFixed(1) : 0,
    });
  }
  return { list, totalPiastres, checksum };
}

export default function AdminWageSettings({ defaultTab = "production" }) {
  const { user } = useAuth();
  const isOwner = user?.role === "owner";
  const hasFinance = user?.permissions?.access_finance || isOwner;

  const [activeTab, setActiveTab] = useState(defaultTab);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [workers, setWorkers] = useState([]);

  // Policies current edit state
  const [policies, setPolicies] = useState({
    production: {
      default_wage_per_unit_le: "",
      unusual_amount_threshold_le: "",
      max_wage_per_unit_le: "",
      enabled: false,
      is_configured: false,
      currency: "EGP",
    },
    delivery: {
      base_wage_per_order_le: 50.0,
      unusual_amount_threshold_le: 100.0,
      max_helper_wage_per_order_le: 500.0,
      enabled: true,
      is_configured: false,
      currency: "EGP",
      rounding_policy: "piastre_round_half_up",
    },
    material_purchase: {
      default_wage_per_purchase_le: "",
      unusual_amount_threshold_le: "",
      max_wage_per_purchase_le: "",
      max_buyers: 5,
      enabled: false,
      is_configured: false,
      currency: "EGP",
    },
    admin: {
      default_wage_per_order_le: "",
      default_recipient_id: "",
      default_recipient_name: "",
      unusual_amount_threshold_le: "",
      max_wage_per_order_le: "",
      enabled: false,
      is_configured: false,
      currency: "EGP",
    },
  });

  // Authoritative saved policy state for semantic dirty / no-op detection
  const [savedPolicies, setSavedPolicies] = useState({});

  // Policy change reasons per category
  const [changeReasons, setChangeReasons] = useState({
    production: "",
    delivery: "",
    material_purchase: "",
    admin: "",
  });

  // Category-scoped audit histories
  const [categoryHistories, setCategoryHistories] = useState({
    production: [],
    delivery: [],
    material_purchase: [],
    admin: [],
  });

  // Simulator States: Production
  const [simProdRate, setSimProdRate] = useState(75.0);
  const [simProdQty, setSimProdQty] = useState(10);
  const [simProdWorkerCount, setSimProdWorkerCount] = useState(2);

  // Simulator States: Delivery
  const [simAmount, setSimAmount] = useState(50.0);
  const [simHelperCount, setSimHelperCount] = useState(3);
  const [testModalOpen, setTestModalOpen] = useState(false);
  const [testOverrideReason, setTestOverrideReason] = useState("");

  // Simulator States: Material Purchasing
  const [simMatAmount, setSimMatAmount] = useState(50.0);
  const [simMatBuyerCount, setSimMatBuyerCount] = useState(2);

  // Simulator States: Admin
  const [simAdminWage, setSimAdminWage] = useState(25.0);
  const [simAdminMode, setSimAdminMode] = useState("scenario_a");
  const [simAdminRecip1, setSimAdminRecip1] = useState("Admin Lama");
  const [simAdminOrders1, setSimAdminOrders1] = useState(15);
  const [simAdminRecip2, setSimAdminRecip2] = useState("Admin Baru");
  const [simAdminOrders2, setSimAdminOrders2] = useState(25);
  const [simAdminSwitchDate, setSimAdminSwitchDate] = useState(
    new Date().toISOString().split("T")[0]
  );
  const [simAdminPreOrders, setSimAdminPreOrders] = useState(12);
  const [simAdminPostOrders, setSimAdminPostOrders] = useState(18);

  const loadCategoryHistory = async (cat) => {
    try {
      const url =
        cat === "delivery"
          ? "/admin/delivery-wage-policy/history"
          : `/admin/wage-policies/${cat}/history`;
      const histRes = await api.get(url);
      setCategoryHistories((prev) => ({
        ...prev,
        [cat]: Array.isArray(histRes.data) ? histRes.data : [],
      }));
    } catch {
      // Non-critical history loading failure
    }
  };

  const loadData = async () => {
    try {
      setLoading(true);
      let loadedAll = false;

      // 1. Fetch all wage policies from unified endpoint
      try {
        const res = await api.get("/admin/wage-policies");
        if (res.data) {
          loadedAll = true;
          const loaded = {
            production: {
              default_wage_per_unit_le: res.data.production?.default_wage_per_unit_le ?? "",
              unusual_amount_threshold_le: res.data.production?.unusual_amount_threshold_le ?? "",
              max_wage_per_unit_le: res.data.production?.max_wage_per_unit_le ?? "",
              enabled: res.data.production?.enabled ?? false,
              is_configured: Boolean(res.data.production?.is_configured),
              currency: res.data.production?.currency || "EGP",
            },
            delivery: {
              base_wage_per_order_le: res.data.delivery?.base_wage_per_order_le ?? 50.0,
              unusual_amount_threshold_le: res.data.delivery?.unusual_amount_threshold_le ?? 100.0,
              max_helper_wage_per_order_le: res.data.delivery?.max_helper_wage_per_order_le ?? 500.0,
              enabled: res.data.delivery?.enabled ?? true,
              is_configured: Boolean(res.data.delivery?.is_configured),
              currency: res.data.delivery?.currency || "EGP",
              rounding_policy: res.data.delivery?.rounding_policy || "piastre_round_half_up",
            },
            material_purchase: {
              default_wage_per_purchase_le: res.data.material_purchase?.default_wage_per_purchase_le ?? "",
              unusual_amount_threshold_le: res.data.material_purchase?.unusual_amount_threshold_le ?? "",
              max_wage_per_purchase_le: res.data.material_purchase?.max_wage_per_purchase_le ?? "",
              max_buyers: res.data.material_purchase?.max_buyers ?? 5,
              enabled: res.data.material_purchase?.enabled ?? false,
              is_configured: Boolean(res.data.material_purchase?.is_configured),
              currency: res.data.material_purchase?.currency || "EGP",
            },
            admin: {
              default_wage_per_order_le: res.data.admin?.default_wage_per_order_le ?? "",
              default_recipient_id: res.data.admin?.default_recipient_id ?? "",
              default_recipient_name: res.data.admin?.default_recipient_name ?? "",
              unusual_amount_threshold_le: res.data.admin?.unusual_amount_threshold_le ?? "",
              max_wage_per_order_le: res.data.admin?.max_wage_per_order_le ?? "",
              enabled: res.data.admin?.enabled ?? false,
              is_configured: Boolean(res.data.admin?.is_configured),
              currency: res.data.admin?.currency || "EGP",
            },
          };
          setPolicies(loaded);
          setSavedPolicies(JSON.parse(JSON.stringify(loaded)));

          if (loaded.production.default_wage_per_unit_le) {
            setSimProdRate(Number(loaded.production.default_wage_per_unit_le));
          }
          if (loaded.delivery.base_wage_per_order_le) {
            setSimAmount(Number(loaded.delivery.base_wage_per_order_le));
          }
          if (loaded.material_purchase.default_wage_per_purchase_le) {
            setSimMatAmount(Number(loaded.material_purchase.default_wage_per_purchase_le));
          }
          if (loaded.admin.default_wage_per_order_le) {
            setSimAdminWage(Number(loaded.admin.default_wage_per_order_le));
          }
          if (loaded.admin.default_recipient_name) {
            setSimAdminRecip1(loaded.admin.default_recipient_name);
          }
        }
      } catch {
        // Fallback for isolated legacy delivery test mocks
      }

      // Fallback: If unified endpoint not found, load delivery directly
      if (!loadedAll) {
        try {
          const dRes = await api.get("/admin/delivery-wage-policy");
          if (dRes?.data) {
            const delivPol = {
              base_wage_per_order_le: Number(dRes.data.base_wage_per_order_le) || 50.0,
              unusual_amount_threshold_le: Number(dRes.data.unusual_amount_threshold_le) || 100.0,
              max_helper_wage_per_order_le: Number(dRes.data.max_helper_wage_per_order_le) || 500.0,
              currency: dRes.data.currency || "EGP",
              rounding_policy: dRes.data.rounding_policy || "piastre_round_half_up",
              enabled: dRes.data.enabled ?? true,
              is_configured: Boolean(dRes.data.is_configured),
            };
            setPolicies((prev) => ({
              ...prev,
              delivery: delivPol,
            }));
            setSavedPolicies((prev) => ({
              ...prev,
              delivery: JSON.parse(JSON.stringify(delivPol)),
            }));
            setSimAmount(delivPol.base_wage_per_order_le);
          }
        } catch (dErr) {
          toast.error("Gagal memuat kebijakan upah: " + formatApiError(dErr.response?.data?.detail));
        }
      }

      // 2. Load audit history for active tab
      await loadCategoryHistory(activeTab);

      // 3. Load workers list for admin wage recipient selection
      try {
        const wRes = await api.get("/admin/workers");
        setWorkers(Array.isArray(wRes.data) ? wRes.data : []);
      } catch {
        // Non-critical
      }
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (hasFinance) {
      loadData();
    }
  }, [hasFinance]);

  // Refetch category audit history on tab change
  useEffect(() => {
    if (hasFinance && activeTab) {
      loadCategoryHistory(activeTab);
    }
  }, [activeTab, hasFinance]);

  // Production Simulator Calculation
  const simProdAllocations = useMemo(() => {
    const totalWage = (Number(simProdRate) || 0) * (Number(simProdQty) || 0);
    return {
      totalWage,
      ...calculatePiastreAllocations(totalWage, simProdWorkerCount),
    };
  }, [simProdRate, simProdQty, simProdWorkerCount]);

  // Delivery Simulator Calculation
  const simDeliveryAllocations = useMemo(() => {
    return calculatePiastreAllocations(simAmount, simHelperCount);
  }, [simAmount, simHelperCount]);

  // Material Purchase Simulator Calculation
  const simMatAllocations = useMemo(() => {
    return calculatePiastreAllocations(simMatAmount, simMatBuyerCount);
  }, [simMatAmount, simMatBuyerCount]);

  // Admin Simulator Scenario A Calculation
  const simAdminScenarioA = useMemo(() => {
    const rate = Number(simAdminWage) || 0;
    const orders1 = Math.max(0, parseInt(simAdminOrders1, 10) || 0);
    const orders2 = Math.max(0, parseInt(simAdminOrders2, 10) || 0);
    const totalOrders = orders1 + orders2;
    const payout1 = orders1 * rate;
    const payout2 = orders2 * rate;
    const totalPayout = totalOrders * rate;
    return {
      rate,
      orders1,
      orders2,
      totalOrders,
      payout1,
      payout2,
      totalPayout,
    };
  }, [simAdminWage, simAdminOrders1, simAdminOrders2]);

  // Admin Simulator Scenario B (Date Switch) Calculation
  const simAdminScenarioB = useMemo(() => {
    const rate = Number(simAdminWage) || 0;
    const preOrders = Math.max(0, parseInt(simAdminPreOrders, 10) || 0);
    const postOrders = Math.max(0, parseInt(simAdminPostOrders, 10) || 0);
    const totalOrders = preOrders + postOrders;
    const prePayout = preOrders * rate;
    const postPayout = postOrders * rate;
    const totalPayout = totalOrders * rate;
    return {
      rate,
      preOrders,
      postOrders,
      totalOrders,
      prePayout,
      postPayout,
      totalPayout,
    };
  }, [simAdminWage, simAdminPreOrders, simAdminPostOrders]);

  // Semantic No-Op Detection Helper
  const checkIsNoOp = (cat) => {
    const cur = policies[cat];
    const orig = savedPolicies[cat];
    if (!orig || !orig.is_configured) return false;

    if (cat === "production") {
      return (
        Number(cur.default_wage_per_unit_le) === Number(orig.default_wage_per_unit_le) &&
        Number(cur.unusual_amount_threshold_le) === Number(orig.unusual_amount_threshold_le) &&
        Number(cur.max_wage_per_unit_le) === Number(orig.max_wage_per_unit_le) &&
        Boolean(cur.enabled) === Boolean(orig.enabled)
      );
    }
    if (cat === "delivery") {
      return (
        Number(cur.base_wage_per_order_le) === Number(orig.base_wage_per_order_le) &&
        Number(cur.unusual_amount_threshold_le) === Number(orig.unusual_amount_threshold_le) &&
        Number(cur.max_helper_wage_per_order_le) === Number(orig.max_helper_wage_per_order_le) &&
        Boolean(cur.enabled) === Boolean(orig.enabled)
      );
    }
    if (cat === "material_purchase") {
      return (
        Number(cur.default_wage_per_purchase_le) === Number(orig.default_wage_per_purchase_le) &&
        Number(cur.unusual_amount_threshold_le) === Number(orig.unusual_amount_threshold_le) &&
        Number(cur.max_wage_per_purchase_le) === Number(orig.max_wage_per_purchase_le) &&
        parseInt(cur.max_buyers, 10) === parseInt(orig.max_buyers, 10) &&
        Boolean(cur.enabled) === Boolean(orig.enabled)
      );
    }
    if (cat === "admin") {
      return (
        Number(cur.default_wage_per_order_le) === Number(orig.default_wage_per_order_le) &&
        String(cur.default_recipient_id || "") === String(orig.default_recipient_id || "") &&
        Number(cur.unusual_amount_threshold_le) === Number(orig.unusual_amount_threshold_le) &&
        Number(cur.max_wage_per_order_le) === Number(orig.max_wage_per_order_le) &&
        Boolean(cur.enabled) === Boolean(orig.enabled)
      );
    }
    return false;
  };

  // Category Save Handler with Semantic No-Op Detection and Mandatory Change Reason
  const handleSavePolicy = async (category) => {
    if (!isOwner) {
      toast.error("Hanya Owner/CEO yang memiliki hak untuk mengubah kebijakan upah.");
      return;
    }

    // 1. Client-side Policy Values & Hierarchy Validation FIRST
    if (category === "delivery") {
      const pol = policies.delivery;
      const baseWage = Number(pol.base_wage_per_order_le);
      const threshold = Number(pol.unusual_amount_threshold_le);
      const hardCap = Number(pol.max_helper_wage_per_order_le);

      if (isNaN(baseWage) || baseWage < 0) {
        toast.error("Tarif dasar upah harus berupa angka valid dan tidak boleh negatif.");
        return;
      }
      if (isNaN(threshold) || threshold <= 0) {
        toast.error("Batas konfirmasi nominal tidak wajar harus lebih besar dari 0.");
        return;
      }
      if (isNaN(hardCap) || hardCap <= 0) {
        toast.error("Batas maksimum keras upah (hard cap) harus lebih besar dari 0.");
        return;
      }
      if (baseWage > threshold) {
        toast.error(`Tarif dasar (${baseWage} LE) tidak boleh melebihi batas konfirmasi (${threshold} LE).`);
        return;
      }
      if (threshold >= hardCap) {
        toast.error(
          `Batas konfirmasi (${threshold} LE) harus lebih kecil dari batas maksimum keras (${hardCap} LE). Hubungan yang diwajibkan: dasar <= batas konfirmasi < batas maksimum keras.`
        );
        return;
      }
    } else if (category === "production") {
      const pol = policies.production;
      const defaultWage = Number(pol.default_wage_per_unit_le);
      const threshold = Number(pol.unusual_amount_threshold_le);
      const hardCap = Number(pol.max_wage_per_unit_le);

      if (isNaN(defaultWage) || defaultWage < 0) {
        toast.error("Tarif dasar upah produksi harus berupa angka valid dan tidak boleh negatif.");
        return;
      }
      if (isNaN(threshold) || threshold <= 0) {
        toast.error("Batas konfirmasi nominal tidak wajar harus lebih besar dari 0.");
        return;
      }
      if (isNaN(hardCap) || hardCap <= 0) {
        toast.error("Batas maksimum keras upah produksi harus lebih besar dari 0.");
        return;
      }
      if (defaultWage > threshold) {
        toast.error(`Tarif dasar (${defaultWage} LE) tidak boleh melebihi batas konfirmasi (${threshold} LE).`);
        return;
      }
      if (threshold >= hardCap) {
        toast.error(
          `Batas konfirmasi (${threshold} LE) harus lebih kecil dari batas maksimum keras (${hardCap} LE).`
        );
        return;
      }
    } else if (category === "material_purchase") {
      const pol = policies.material_purchase;
      const defaultWage = Number(pol.default_wage_per_purchase_le);
      const threshold = Number(pol.unusual_amount_threshold_le);
      const hardCap = Number(pol.max_wage_per_purchase_le);
      const maxBuyers = parseInt(pol.max_buyers, 10);

      if (isNaN(defaultWage) || defaultWage < 0) {
        toast.error("Tarif dasar upah belanja bahan harus berupa angka valid dan tidak boleh negatif.");
        return;
      }
      if (isNaN(threshold) || threshold <= 0) {
        toast.error("Batas konfirmasi nominal tidak wajar harus lebih besar dari 0.");
        return;
      }
      if (isNaN(hardCap) || hardCap <= 0) {
        toast.error("Batas maksimum keras upah belanja bahan harus lebih besar dari 0.");
        return;
      }
      if (isNaN(maxBuyers) || maxBuyers < 1 || maxBuyers > 5) {
        toast.error("Batas maksimum pembeli bahan harus di antara 1 dan 5.");
        return;
      }
      if (defaultWage > threshold) {
        toast.error(`Tarif dasar (${defaultWage} LE) tidak boleh melebihi batas konfirmasi (${threshold} LE).`);
        return;
      }
      if (threshold >= hardCap) {
        toast.error(
          `Batas konfirmasi (${threshold} LE) harus lebih kecil dari batas maksimum keras (${hardCap} LE).`
        );
        return;
      }
    } else if (category === "admin") {
      const pol = policies.admin;
      const defaultWage = Number(pol.default_wage_per_order_le);
      const threshold = Number(pol.unusual_amount_threshold_le);
      const hardCap = Number(pol.max_wage_per_order_le);

      if (isNaN(defaultWage) || defaultWage < 0) {
        toast.error("Tarif dasar upah admin harus berupa angka valid dan tidak boleh negatif.");
        return;
      }
      if (isNaN(threshold) || threshold <= 0) {
        toast.error("Batas konfirmasi nominal tidak wajar harus lebih besar dari 0.");
        return;
      }
      if (isNaN(hardCap) || hardCap <= 0) {
        toast.error("Batas maksimum keras upah admin harus lebih besar dari 0.");
        return;
      }
      if (defaultWage > threshold) {
        toast.error(`Tarif dasar (${defaultWage} LE) tidak boleh melebihi batas konfirmasi (${threshold} LE).`);
        return;
      }
      if (threshold >= hardCap) {
        toast.error(
          `Batas konfirmasi (${threshold} LE) harus lebih kecil dari batas maksimum keras (${hardCap} LE).`
        );
        return;
      }
    }

    // 2. Semantic No-Op check
    if (checkIsNoOp(category)) {
      toast.info("Tidak ada perubahan konfigurasi terdeteksi.");
      return;
    }

    // 3. Reason validation for genuine change (with backward-compatibility fallback for legacy delivery wrapper)
    let reason = (changeReasons[category] || "").trim();
    if (!reason && category === "delivery") {
      reason = "Penyesuaian kebijakan upah pengiriman";
    }

    if (!reason || reason.length < 3) {
      toast.error("Alasan perubahan kebijakan wajib diisi minimal 3 karakter.");
      return;
    }
    if (reason.length > 500) {
      toast.error("Alasan perubahan kebijakan maksimal 500 karakter.");
      return;
    }

    try {
      setSaving(true);

      if (category === "delivery") {
        const pol = policies.delivery;
        const payload = {
          base_wage_per_order_le: Number(pol.base_wage_per_order_le),
          unusual_amount_threshold_le: Number(pol.unusual_amount_threshold_le),
          max_helper_wage_per_order_le: Number(pol.max_helper_wage_per_order_le),
          currency: pol.currency || "EGP",
          rounding_policy: "piastre_round_half_up",
          enabled: pol.enabled ?? true,
          change_reason: reason,
        };

        await api.put("/admin/delivery-wage-policy", payload);
        toast.success("Kebijakan upah pengiriman berhasil disimpan!");
      } else if (category === "production") {
        const pol = policies.production;
        const payload = {
          default_wage_per_unit_le: Number(pol.default_wage_per_unit_le),
          unusual_amount_threshold_le: Number(pol.unusual_amount_threshold_le),
          max_wage_per_unit_le: Number(pol.max_wage_per_unit_le),
          enabled: Boolean(pol.enabled),
          currency: pol.currency || "EGP",
          change_reason: reason,
        };

        await api.put("/admin/wage-policies/production", payload);
        toast.success("Kebijakan upah produksi berhasil disimpan!");
      } else if (category === "material_purchase") {
        const pol = policies.material_purchase;
        const payload = {
          default_wage_per_purchase_le: Number(pol.default_wage_per_purchase_le),
          unusual_amount_threshold_le: Number(pol.unusual_amount_threshold_le),
          max_wage_per_purchase_le: Number(pol.max_wage_per_purchase_le),
          max_buyers: parseInt(pol.max_buyers, 10),
          enabled: Boolean(pol.enabled),
          currency: pol.currency || "EGP",
          change_reason: reason,
        };

        await api.put("/admin/wage-policies/material_purchase", payload);
        toast.success("Kebijakan upah belanja bahan berhasil disimpan!");
      } else if (category === "admin") {
        const pol = policies.admin;
        const payload = {
          default_wage_per_order_le: Number(pol.default_wage_per_order_le),
          default_recipient_id: pol.default_recipient_id || null,
          unusual_amount_threshold_le: Number(pol.unusual_amount_threshold_le),
          max_wage_per_order_le: Number(pol.max_wage_per_order_le),
          enabled: Boolean(pol.enabled),
          currency: pol.currency || "EGP",
          change_reason: reason,
        };

        await api.put("/admin/wage-policies/admin", payload);
        toast.success("Kebijakan upah admin berhasil disimpan!");
      }

      // Clear the used change reason
      setChangeReasons((prev) => ({ ...prev, [category]: "" }));

      // Reload data and category audit history
      await loadData();
      await loadCategoryHistory(category);
    } catch (err) {
      toast.error("Gagal menyimpan: " + formatApiError(err.response?.data?.detail));
    } finally {
      setSaving(false);
    }
  };

  if (!hasFinance) {
    return (
      <div className="rounded-2xl border border-red-200 bg-red-50 p-6 text-center text-red-700">
        <ShieldAlert size={40} className="mx-auto mb-2 text-red-500" />
        <h2 className="text-lg font-bold">Akses Terbatas</h2>
        <p className="text-sm">Halaman ini hanya dapat diakses oleh Owner atau Administrator Keuangan.</p>
      </div>
    );
  }

  const tabsConfig = [
    {
      id: "production",
      label: "Upah Produksi",
      icon: Hammer,
      isConfigured: policies.production.is_configured,
    },
    {
      id: "delivery",
      label: "Upah Pengiriman",
      icon: Truck,
      isConfigured: policies.delivery.is_configured,
    },
    {
      id: "material_purchase",
      label: "Upah Belanja Bahan",
      icon: ShoppingBag,
      isConfigured: policies.material_purchase.is_configured,
    },
    {
      id: "admin",
      label: "Upah Admin",
      icon: UserCheck,
      isConfigured: policies.admin.is_configured,
    },
  ];

  return (
    <div className="max-w-4xl space-y-6">
      {/* Page Header */}
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between border-b border-[#E5DCC5] pb-4">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="font-heading text-2xl font-bold text-[#2C1E16]">Pengaturan Upah</h1>
            {isOwner ? (
              <span className="inline-flex items-center gap-1 rounded-full bg-emerald-100 px-2.5 py-0.5 text-xs font-semibold text-emerald-800">
                <ShieldCheck size={12} /> Owner
              </span>
            ) : (
              <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2.5 py-0.5 text-xs font-semibold text-amber-800">
                <Info size={12} /> Keuangan (Mode Baca)
              </span>
            )}
          </div>
          <p className="mt-1 text-xs sm:text-sm text-[#8B7355]">
            Pusat konfigurasi tarif upah bertingkat, simulator distribusi piastre eksak, dan audit log riwayat kebijakan untuk seluruh kategori kewajiban upah.
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={loadData}
          className="rounded-xl border-[#E5DCC5] text-[#5C4A3D] hover:bg-[#EFE6D5]"
        >
          <RotateCcw size={14} className="mr-1" /> Muat Ulang
        </Button>
      </div>

      {/* Role Alert / Notice */}
      {!isOwner && (
        <div className="rounded-xl border border-amber-200 bg-amber-50 p-3.5 text-xs sm:text-sm text-amber-900 flex items-start gap-2.5">
          <Info size={18} className="text-amber-600 shrink-0 mt-0.5" />
          <div>
            <span className="font-semibold">Mode Baca Saja (Tim Keuangan):</span> Anda dapat melihat kebijakan aktif, mensimulasikan alokasi upah, dan memverifikasi batas konfirmasi. Perubahan kebijakan dasar hanya dapat disimpan oleh Owner/CEO.
          </div>
        </div>
      )}

      {/* Category Navigation Tabs */}
      <div className="flex flex-wrap gap-2 border-b border-[#E5DCC5]/60 pb-2">
        {tabsConfig.map((t) => {
          const IconComponent = t.icon;
          const isActive = activeTab === t.id;
          return (
            <button
              key={t.id}
              type="button"
              onClick={() => setActiveTab(t.id)}
              className={`flex items-center gap-2 px-3.5 py-2 rounded-xl text-xs sm:text-sm font-semibold transition-all ${
                isActive
                  ? "bg-[#8B5A2B] text-white shadow-sm"
                  : "bg-white text-[#5C4A3D] border border-[#E5DCC5] hover:bg-[#FAF8F5]"
              }`}
            >
              <IconComponent size={16} />
              <span>{t.label}</span>
              {!t.isConfigured && (
                <span
                  className={`ml-1 text-[10px] px-1.5 py-0.2 rounded-full font-bold ${
                    isActive ? "bg-amber-400 text-stone-900" : "bg-amber-100 text-amber-800"
                  }`}
                >
                  Belum Disetel
                </span>
              )}
            </button>
          );
        })}
      </div>

      {/* TAB 1: UPAH PRODUKSI */}
      {activeTab === "production" && (
        <div className="space-y-6">
          <div className="rounded-2xl border border-[#E5DCC5] bg-white p-5 sm:p-6 shadow-sm space-y-5">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2 font-heading text-sm font-bold uppercase tracking-wider text-[#8B5A2B]">
                <Hammer size={18} /> Kebijakan Upah Produksi Bertingkat
              </div>
              {!policies.production.is_configured && (
                <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2.5 py-0.5 text-xs font-semibold text-amber-800">
                  <AlertTriangle size={12} /> Belum Dikonfigurasi
                </span>
              )}
            </div>

            {!policies.production.is_configured && (
              <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-xs sm:text-sm text-amber-900 space-y-1">
                <div className="font-bold flex items-center gap-1.5">
                  <AlertTriangle size={16} className="text-amber-600" /> Perhatian: Kebijakan Belum Dikonfigurasi
                </div>
                <p className="text-amber-800 text-xs">
                  Tarif dasar dan batas atas upah produksi belum ditetapkan secara resmi oleh Owner. Penugasan produksi tidak dapat menghitung upah otomatis sampai parameter di bawah ini disimpan dan diaktifkan.
                </p>
              </div>
            )}

            {loading ? (
              <div className="py-8 text-center text-sm text-[#8B7355]">Memuat kebijakan...</div>
            ) : (
              <div className="space-y-4">
                <div className="grid gap-5 sm:grid-cols-3">
                  <div>
                    <Label className="block text-sm font-semibold text-[#2C1E16] mb-1">
                      Tarif Dasar per Unit (EGP)
                    </Label>
                    <div className="relative">
                      <Input
                        type="number"
                        min="0"
                        step="1"
                        disabled={!isOwner || saving}
                        value={policies.production.default_wage_per_unit_le}
                        onChange={(e) =>
                          setPolicies({
                            ...policies,
                            production: { ...policies.production, default_wage_per_unit_le: e.target.value },
                          })
                        }
                        placeholder="Contoh: 75"
                        className="bg-white pr-12 font-medium"
                      />
                      <span className="absolute right-3 top-2.5 text-xs font-bold text-[#8B7355]">EGP</span>
                    </div>
                    <p className="mt-1 text-xs text-[#8B7355]">
                      Tarif acuan upah per unit produk jadi yang akan dibagi di antara pekerja bertugas.
                    </p>
                  </div>

                  <div>
                    <Label className="block text-sm font-semibold text-[#2C1E16] mb-1">
                      Batas Konfirmasi Nominal (EGP)
                    </Label>
                    <div className="relative">
                      <Input
                        type="number"
                        min="1"
                        step="10"
                        disabled={!isOwner || saving}
                        value={policies.production.unusual_amount_threshold_le}
                        onChange={(e) =>
                          setPolicies({
                            ...policies,
                            production: { ...policies.production, unusual_amount_threshold_le: e.target.value },
                          })
                        }
                        placeholder="Contoh: 150"
                        className="bg-white pr-12 font-medium"
                      />
                      <span className="absolute right-3 top-2.5 text-xs font-bold text-[#8B7355]">EGP</span>
                    </div>
                    <p className="mt-1 text-xs text-[#8B7355]">
                      Ambang peringatan. Di atas batas ini mewajibkan konfirmasi dan alasan penyesuaian tarif.
                    </p>
                  </div>

                  <div>
                    <Label className="block text-sm font-semibold text-[#2C1E16] mb-1">
                      Batas Maksimum Keras (EGP)
                    </Label>
                    <div className="relative">
                      <Input
                        type="number"
                        min="1"
                        step="10"
                        disabled={!isOwner || saving}
                        value={policies.production.max_wage_per_unit_le}
                        onChange={(e) =>
                          setPolicies({
                            ...policies,
                            production: { ...policies.production, max_wage_per_unit_le: e.target.value },
                          })
                        }
                        placeholder="Contoh: 400"
                        className="bg-white pr-12 font-medium text-rose-700"
                      />
                      <span className="absolute right-3 top-2.5 text-xs font-bold text-rose-600">EGP</span>
                    </div>
                    <p className="mt-1 text-xs text-[#8B7355]">
                      Plafon mutlak. Penugasan dengan tarif melebihi batas ini otomatis ditolak oleh sistem.
                    </p>
                  </div>
                </div>

                <div className="flex items-center gap-2 pt-2">
                  <input
                    type="checkbox"
                    id="prod-enabled"
                    disabled={!isOwner || saving}
                    checked={Boolean(policies.production.enabled)}
                    onChange={(e) =>
                      setPolicies({
                        ...policies,
                        production: { ...policies.production, enabled: e.target.checked },
                      })
                    }
                    className="rounded border-[#E5DCC5] text-[#8B5A2B] focus:ring-[#8B5A2B]"
                  />
                  <Label htmlFor="prod-enabled" className="text-xs sm:text-sm font-semibold text-[#2C1E16] cursor-pointer">
                    Aktifkan Kebijakan Upah Produksi Otomatis
                  </Label>
                </div>

                {/* Policy Change Reason (Mandatory for Updates) */}
                {isOwner && (
                  <div className="pt-2">
                    <Label htmlFor="reason-production" className="block text-xs font-semibold text-[#2C1E16] mb-1">
                      Alasan Perubahan Kebijakan <span className="text-rose-600">*</span>
                    </Label>
                    <Textarea
                      id="reason-production"
                      name="change_reason"
                      rows={2}
                      disabled={saving}
                      value={changeReasons.production}
                      onChange={(e) =>
                        setChangeReasons({ ...changeReasons, production: e.target.value })
                      }
                      placeholder="Contoh: Penyesuaian tarif berdasarkan keputusan rapat direksi"
                      className="bg-white text-xs font-medium"
                      maxLength={500}
                    />
                    <div className="flex justify-between text-[11px] text-[#8B7355] mt-1">
                      <span>Wajib diisi jika mengubah konfigurasi kebijakan upah produksi.</span>
                      <span>{changeReasons.production.length}/500</span>
                    </div>
                  </div>
                )}

                <div className="rounded-xl border border-[#F1EBE0] bg-[#FAF8F5] p-3.5 space-y-1">
                  <div className="text-xs font-semibold text-[#5C4A3D] flex items-center gap-1.5">
                    <Coins size={14} className="text-[#8B5A2B]" /> Aturan Kebijakan Bertingkat: 0 &le; Tarif Dasar &le; Batas Konfirmasi &lt; Batas Maksimum Keras
                  </div>
                  <p className="text-xs text-[#8B7355]">
                    Alokasi pekerja produksi dibagi menggunakan integer piastre eksak (1 piastre = 0.01 EGP) dengan jaminan zero money drift.
                  </p>
                </div>

                {isOwner && (
                  <div className="pt-2 flex justify-end">
                    <Button
                      onClick={() => handleSavePolicy("production")}
                      disabled={saving || loading}
                      className="rounded-xl bg-[#8B5A2B] hover:bg-[#6B4423] text-white px-5"
                    >
                      <Save size={16} className="mr-1.5" />
                      {saving ? "Menyimpan..." : "Simpan Pengaturan Upah Produksi"}
                    </Button>
                  </div>
                )}
              </div>
            )}
          </div>

          {/* PRODUCTION WAGE SIMULATOR */}
          <div className="rounded-2xl border border-[#E5DCC5] bg-white p-5 sm:p-6 shadow-sm space-y-5">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2 font-heading text-sm font-bold uppercase tracking-wider text-[#8B5A2B]">
                <Calculator size={18} /> Simulator Distribusi Upah Produksi &amp; Uji Ambang Batas
              </div>
              <span className="text-xs text-[#8B7355]">Alat Bantu Estimasi</span>
            </div>

            <div className="rounded-xl border border-sky-200 bg-sky-50/60 p-3 text-xs text-sky-950 flex items-start gap-2">
              <Info size={16} className="text-sky-600 shrink-0 mt-0.5" />
              <span>
                <strong>Simulasi ini hanya untuk estimasi.</strong> Tidak membuat kewajiban upah, transaksi keuangan, atau penugasan riil di database.
              </span>
            </div>

            <div className="grid gap-4 sm:grid-cols-3 bg-[#F9F6F0] p-4 rounded-xl border border-[#E5DCC5]/60">
              <div>
                <Label className="text-xs font-semibold text-[#5C4A3D]">Tarif per Unit (EGP)</Label>
                <div className="relative mt-1">
                  <Input
                    type="number"
                    min="0"
                    step="5"
                    disabled={!isOwner}
                    value={simProdRate}
                    onChange={(e) => setSimProdRate(e.target.value)}
                    className="bg-white pr-12 text-sm font-bold text-[#2C1E16]"
                  />
                  <span className="absolute right-3 top-2.5 text-xs font-bold text-[#8B7355]">EGP</span>
                </div>
              </div>

              <div>
                <Label className="text-xs font-semibold text-[#5C4A3D]">Kuantitas Produksi (Unit)</Label>
                <div className="relative mt-1">
                  <Input
                    type="number"
                    min="1"
                    step="1"
                    disabled={!isOwner}
                    value={simProdQty}
                    onChange={(e) => setSimProdQty(e.target.value)}
                    className="bg-white pr-14 text-sm font-bold text-[#2C1E16]"
                  />
                  <span className="absolute right-3 top-2.5 text-xs font-bold text-[#8B7355]">Unit</span>
                </div>
                <div className="flex items-center gap-1 mt-1.5 flex-wrap">
                  {[1, 5, 10, 25, 50].map((q) => (
                    <button
                      key={q}
                      type="button"
                      onClick={() => setSimProdQty(q)}
                      className={`px-2 py-0.5 text-[11px] font-bold rounded border transition-colors ${
                        Number(simProdQty) === q
                          ? "bg-[#8B5A2B] text-white border-[#8B5A2B]"
                          : "bg-white text-[#5C4A3D] border-[#E5DCC5] hover:bg-[#EFE6D5]"
                      }`}
                    >
                      {q}
                    </button>
                  ))}
                </div>
              </div>

              <div>
                <Label className="text-xs font-semibold text-[#5C4A3D]">Jumlah Pekerja Ditugaskan</Label>
                <div className="flex items-center gap-1.5 mt-1">
                  {[1, 2, 3, 4, 5].map((cnt) => (
                    <button
                      key={cnt}
                      type="button"
                      onClick={() => setSimProdWorkerCount(cnt)}
                      className={`flex-1 py-2 text-xs font-bold rounded-lg border transition-colors ${
                        simProdWorkerCount === cnt
                          ? "bg-[#8B5A2B] text-white border-[#8B5A2B]"
                          : "bg-white text-[#5C4A3D] border-[#E5DCC5] hover:bg-[#EFE6D5]"
                      }`}
                    >
                      {cnt}
                    </button>
                  ))}
                </div>
              </div>
            </div>

            {/* Production Tier Status Badges */}
            {policies.production.max_wage_per_unit_le &&
              Number(simProdRate) > Number(policies.production.max_wage_per_unit_le) && (
                <div className="rounded-xl border border-rose-300 bg-rose-50 p-4 text-xs sm:text-sm text-rose-950 flex items-start gap-2.5">
                  <ShieldAlert size={20} className="text-rose-600 shrink-0 mt-0.5" />
                  <div>
                    <span className="font-bold">
                      Tarif Melebihi Batas Maksimum Keras ({policies.production.max_wage_per_unit_le} EGP):
                    </span>
                    <p className="mt-0.5 text-xs text-rose-800">
                      Sistem backend akan <strong>MENOLAK OTOMATIS</strong> penugasan ini dengan HTTP 422. Konfirmasi petugas dan alasan tidak dapat melewati batas ini.
                    </p>
                  </div>
                </div>
              )}

            {policies.production.unusual_amount_threshold_le &&
              policies.production.max_wage_per_unit_le &&
              Number(simProdRate) > Number(policies.production.unusual_amount_threshold_le) &&
              Number(simProdRate) <= Number(policies.production.max_wage_per_unit_le) && (
                <div className="rounded-xl border border-amber-300 bg-amber-50 p-4 text-xs sm:text-sm text-amber-950 flex items-start gap-2.5">
                  <AlertTriangle size={20} className="text-amber-600 shrink-0 mt-0.5" />
                  <div>
                    <span className="font-bold">
                      Tarif Memerlukan Konfirmasi Petugas ({policies.production.unusual_amount_threshold_le} -{" "}
                      {policies.production.max_wage_per_unit_le} EGP):
                    </span>
                    <p className="mt-0.5 text-xs text-amber-800">
                      Pada alur penugasan produksi, sistem mewajibkan otorisasi Owner dan alasan penyesuaian tarif tertulis minimal 3 karakter.
                    </p>
                  </div>
                </div>
              )}

            {policies.production.unusual_amount_threshold_le &&
              Number(simProdRate) <= Number(policies.production.unusual_amount_threshold_le) && (
                <div className="rounded-xl border border-emerald-300 bg-emerald-50 p-3 text-xs sm:text-sm text-emerald-950 flex items-center gap-2.5">
                  <CheckCircle2 size={18} className="text-emerald-600 shrink-0" />
                  <div>
                    <span className="font-bold">
                      Tarif Standar (&le; {policies.production.unusual_amount_threshold_le} EGP):
                    </span>
                    <span className="ml-1 text-xs text-emerald-800">
                      Diproses secara normal tanpa memerlukan konfirmasi override tarif.
                    </span>
                  </div>
                </div>
              )}

            {/* Production Breakdown Table */}
            <div className="overflow-x-auto rounded-xl border border-[#E5DCC5]">
              <table className="w-full text-left text-xs sm:text-sm">
                <thead className="bg-[#FAF8F5] text-xs font-bold uppercase tracking-wider text-[#8B7355] border-b border-[#E5DCC5]">
                  <tr>
                    <th className="py-2.5 px-3">Pekerja</th>
                    <th className="py-2.5 px-3">Alokasi (EGP)</th>
                    <th className="py-2.5 px-3">Satuan Piastre</th>
                    <th className="py-2.5 px-3">Proporsi</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#F1EBE0]">
                  {simProdAllocations.list.map((a) => (
                    <tr key={a.index} className="hover:bg-[#FAF8F5]/60">
                      <td className="py-2.5 px-3 font-medium text-[#2C1E16]">Pekerja {a.index}</td>
                      <td className="py-2.5 px-3 font-mono font-bold text-[#8B5A2B]">{fmtLE(a.amount_le)} EGP</td>
                      <td className="py-2.5 px-3 text-[#5C4A3D] font-mono">{a.piastres} piastre</td>
                      <td className="py-2.5 px-3 text-[#8B7355]">{a.pct}%</td>
                    </tr>
                  ))}
                </tbody>
                <tfoot className="bg-[#FAF8F5] border-t border-[#E5DCC5] font-bold text-xs sm:text-sm">
                  <tr>
                    <td className="py-2.5 px-3 text-[#2C1E16]">Total Upah ({simProdQty} unit @ {simProdRate} EGP)</td>
                    <td className="py-2.5 px-3 font-mono text-[#8B5A2B]">{fmtLE(simProdAllocations.totalWage)} EGP</td>
                    <td className="py-2.5 px-3 font-mono text-[#5C4A3D]">
                      {simProdAllocations.totalPiastres} piastre
                    </td>
                    <td className="py-2.5 px-3 text-emerald-700 flex items-center gap-1">
                      <CheckCircle2 size={13} /> 100% Eksak
                    </td>
                  </tr>
                </tfoot>
              </table>
            </div>
          </div>

          {/* PRODUCTION AUDIT HISTORY */}
          <AuditHistoryCard category="production" history={categoryHistories.production} />
        </div>
      )}

      {/* TAB 2: UPAH PENGIRIMAN */}
      {activeTab === "delivery" && (
        <div className="space-y-6">
          <div className="rounded-2xl border border-[#E5DCC5] bg-white p-5 sm:p-6 shadow-sm space-y-5">
            <div className="flex items-center gap-2 font-heading text-sm font-bold uppercase tracking-wider text-[#8B5A2B]">
              <CircleDollarSign size={18} /> Kebijakan Upah Helper Bertingkat
            </div>

            {loading ? (
              <div className="py-8 text-center text-sm text-[#8B7355]">Memuat kebijakan...</div>
            ) : (
              <div className="space-y-4">
                <div className="grid gap-5 sm:grid-cols-3">
                  <div>
                    <Label className="block text-sm font-semibold text-[#2C1E16] mb-1">
                      Tarif Dasar Upah per Pesanan (EGP)
                    </Label>
                    <div className="relative">
                      <Input
                        type="number"
                        min="0"
                        step="1"
                        disabled={!isOwner || saving}
                        value={policies.delivery.base_wage_per_order_le}
                        onChange={(e) =>
                          setPolicies({
                            ...policies,
                            delivery: { ...policies.delivery, base_wage_per_order_le: e.target.value },
                          })
                        }
                        className="bg-white pr-12 font-medium"
                      />
                      <span className="absolute right-3 top-2.5 text-xs font-bold text-[#8B7355]">EGP</span>
                    </div>
                    <p className="mt-1 text-xs text-[#8B7355]">
                      Tarif standar per pesanan sukses yang dibagi rata kepada seluruh helper internal trip.
                    </p>
                  </div>

                  <div>
                    <Label className="block text-sm font-semibold text-[#2C1E16] mb-1">
                      Batas Konfirmasi Nominal (EGP)
                    </Label>
                    <div className="relative">
                      <Input
                        type="number"
                        min="1"
                        step="10"
                        disabled={!isOwner || saving}
                        value={policies.delivery.unusual_amount_threshold_le}
                        onChange={(e) =>
                          setPolicies({
                            ...policies,
                            delivery: { ...policies.delivery, unusual_amount_threshold_le: e.target.value },
                          })
                        }
                        className="bg-white pr-12 font-medium"
                      />
                      <span className="absolute right-3 top-2.5 text-xs font-bold text-[#8B7355]">EGP</span>
                    </div>
                    <p className="mt-1 text-xs text-[#8B7355]">
                      Ambang peringatan. Di atas batas ini butuh konfirmasi dan alasan tertulis (Default: 100 EGP).
                    </p>
                  </div>

                  <div>
                    <Label className="block text-sm font-semibold text-[#2C1E16] mb-1">
                      Batas Maksimum Keras (EGP)
                    </Label>
                    <div className="relative">
                      <Input
                        type="number"
                        min="1"
                        step="10"
                        disabled={!isOwner || saving}
                        value={policies.delivery.max_helper_wage_per_order_le}
                        onChange={(e) =>
                          setPolicies({
                            ...policies,
                            delivery: { ...policies.delivery, max_helper_wage_per_order_le: e.target.value },
                          })
                        }
                        className="bg-white pr-12 font-medium text-rose-700"
                      />
                      <span className="absolute right-3 top-2.5 text-xs font-bold text-rose-600">EGP</span>
                    </div>
                    <p className="mt-1 text-xs text-[#8B7355]">
                      Plafon liabilitas mutlak. Di atas batas ini otomatis ditolak oleh backend (Default: 500 EGP).
                    </p>
                  </div>
                </div>

                {/* Policy Change Reason (Mandatory for Updates) */}
                {isOwner && (
                  <div className="pt-2">
                    <Label htmlFor="reason-delivery" className="block text-xs font-semibold text-[#2C1E16] mb-1">
                      Alasan Perubahan Kebijakan <span className="text-rose-600">*</span>
                    </Label>
                    <Textarea
                      id="reason-delivery"
                      name="change_reason"
                      rows={2}
                      disabled={saving}
                      value={changeReasons.delivery}
                      onChange={(e) =>
                        setChangeReasons({ ...changeReasons, delivery: e.target.value })
                      }
                      placeholder="Contoh: Penyesuaian tarif standar helper rute antar kota"
                      className="bg-white text-xs font-medium"
                      maxLength={500}
                    />
                    <div className="flex justify-between text-[11px] text-[#8B7355] mt-1">
                      <span>Wajib diisi jika mengubah konfigurasi kebijakan upah pengiriman.</span>
                      <span>{changeReasons.delivery.length}/500</span>
                    </div>
                  </div>
                )}

                <div className="rounded-xl border border-[#F1EBE0] bg-[#FAF8F5] p-3.5 space-y-1">
                  <div className="text-xs font-semibold text-[#5C4A3D] flex items-center gap-1.5">
                    <Coins size={14} className="text-[#8B5A2B]" /> Aturan Kebijakan Bertingkat: Dasar &le; Batas Konfirmasi &lt; Batas Maksimum Keras
                  </div>
                  <p className="text-xs text-[#8B7355]">
                    Sistem menggunakan aritmatika integer piastre eksak (1 piastre = 0.01 EGP). Seluruh alokasi helper selalu berjumlah persis 100% dari total upah tanpa ada selisih uang mengambang.
                  </p>
                </div>

                {isOwner && (
                  <div className="pt-2 flex justify-end">
                    <Button
                      onClick={() => handleSavePolicy("delivery")}
                      disabled={saving || loading}
                      className="rounded-xl bg-[#8B5A2B] hover:bg-[#6B4423] text-white px-5"
                    >
                      <Save size={16} className="mr-1.5" />
                      {saving ? "Menyimpan..." : "Simpan Pengaturan Upah"}
                    </Button>
                  </div>
                )}
              </div>
            )}
          </div>

          {/* DELIVERY LIVE ALLOCATION PREVIEW & THRESHOLD SIMULATOR */}
          <div className="rounded-2xl border border-[#E5DCC5] bg-white p-5 sm:p-6 shadow-sm space-y-5">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2 font-heading text-sm font-bold uppercase tracking-wider text-[#8B5A2B]">
                <Calculator size={18} /> Simulator Distribusi Upah &amp; Uji Ambang Batas
              </div>
              <span className="text-xs text-[#8B7355]">Alat Bantu Estimasi</span>
            </div>

            <div className="rounded-xl border border-sky-200 bg-sky-50/60 p-3 text-xs text-sky-950 flex items-start gap-2">
              <Info size={16} className="text-sky-600 shrink-0 mt-0.5" />
              <span>
                <strong>Simulasi ini hanya untuk estimasi.</strong> Tidak membuat kewajiban upah, transaksi keuangan, atau mengubah data pesanan.
              </span>
            </div>

            <div className="grid gap-4 sm:grid-cols-2 bg-[#F9F6F0] p-4 rounded-xl border border-[#E5DCC5]/60">
              <div>
                <Label className="text-xs font-semibold text-[#5C4A3D]">Nominal Simulasi (EGP)</Label>
                <div className="relative mt-1">
                  <Input
                    type="number"
                    min="0"
                    step="5"
                    disabled={!isOwner}
                    value={simAmount}
                    onChange={(e) => setSimAmount(e.target.value)}
                    className="bg-white pr-12 text-sm font-bold text-[#2C1E16]"
                  />
                  <span className="absolute right-3 top-2.5 text-xs font-bold text-[#8B7355]">EGP</span>
                </div>
              </div>

              <div>
                <Label className="text-xs font-semibold text-[#5C4A3D]">Jumlah Helper Ditugaskan</Label>
                <div className="flex items-center gap-2 mt-1">
                  {[1, 2, 3, 4, 5].map((count) => (
                    <button
                      key={count}
                      type="button"
                      onClick={() => setSimHelperCount(count)}
                      className={`flex-1 py-2 text-xs font-bold rounded-lg border transition-colors ${
                        simHelperCount === count
                          ? "bg-[#8B5A2B] text-white border-[#8B5A2B]"
                          : "bg-white text-[#5C4A3D] border-[#E5DCC5] hover:bg-[#EFE6D5]"
                      }`}
                    >
                      {count} Helper
                    </button>
                  ))}
                </div>
              </div>
            </div>

            {/* Tier Status Badges */}
            {Number(simAmount) > Number(policies.delivery.max_helper_wage_per_order_le) && (
              <div className="rounded-xl border border-rose-300 bg-rose-50 p-4 text-xs sm:text-sm text-rose-950 flex items-start gap-2.5">
                <ShieldAlert size={20} className="text-rose-600 shrink-0 mt-0.5" />
                <div>
                  <span className="font-bold">
                    Nominal Melebihi Batas Maksimum Keras ({policies.delivery.max_helper_wage_per_order_le} EGP):
                  </span>
                  <p className="mt-0.5 text-xs text-rose-800">
                    Sistem backend akan <strong>MENOLAK OTOMATIS</strong> pengajuan ini dengan HTTP 422. Konfirmasi petugas dan alasan tidak dapat melewati batas ini.
                  </p>
                </div>
              </div>
            )}

            {Number(simAmount) > Number(policies.delivery.unusual_amount_threshold_le) &&
              Number(simAmount) <= Number(policies.delivery.max_helper_wage_per_order_le) && (
                <div className="rounded-xl border border-amber-300 bg-amber-50 p-4 text-xs sm:text-sm text-amber-950 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
                  <div className="flex items-start gap-2.5">
                    <AlertTriangle size={20} className="text-amber-600 shrink-0 mt-0.5" />
                    <div>
                      <span className="font-bold">
                        Nominal Memerlukan Konfirmasi Petugas ({policies.delivery.unusual_amount_threshold_le} -{" "}
                        {policies.delivery.max_helper_wage_per_order_le} EGP):
                      </span>
                      <p className="mt-0.5 text-xs text-amber-800">
                        Pada alur serah terima, sistem mewajibkan checkbox konfirmasi kebenaran nominal dan alasan tertulis minimal 5 karakter.
                      </p>
                    </div>
                  </div>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => {
                      setTestOverrideReason("");
                      setTestModalOpen(true);
                    }}
                    className="shrink-0 rounded-xl border-amber-400 bg-white text-amber-900 hover:bg-amber-100 text-xs font-semibold"
                  >
                    Uji Coba Dialog Konfirmasi
                  </Button>
                </div>
              )}

            {Number(simAmount) <= Number(policies.delivery.unusual_amount_threshold_le) && (
              <div className="rounded-xl border border-emerald-300 bg-emerald-50 p-3 text-xs sm:text-sm text-emerald-950 flex items-center gap-2.5">
                <CheckCircle2 size={18} className="text-emerald-600 shrink-0" />
                <div>
                  <span className="font-bold">
                    Nominal Standar (&le; {policies.delivery.unusual_amount_threshold_le} EGP):
                  </span>
                  <span className="ml-1 text-xs text-emerald-800">
                    Diproses secara normal tanpa memerlukan dialog konfirmasi khusus.
                  </span>
                </div>
              </div>
            )}

            {/* Breakdown Table */}
            <div className="overflow-x-auto rounded-xl border border-[#E5DCC5]">
              <table className="w-full text-left text-xs sm:text-sm">
                <thead className="bg-[#FAF8F5] text-xs font-bold uppercase tracking-wider text-[#8B7355] border-b border-[#E5DCC5]">
                  <tr>
                    <th className="py-2.5 px-3">Helper</th>
                    <th className="py-2.5 px-3">Alokasi (EGP)</th>
                    <th className="py-2.5 px-3">Satuan Piastre</th>
                    <th className="py-2.5 px-3">Proporsi</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#F1EBE0]">
                  {simDeliveryAllocations.list.map((a) => (
                    <tr key={a.index} className="hover:bg-[#FAF8F5]/60">
                      <td className="py-2.5 px-3 font-medium text-[#2C1E16]">Helper {a.index}</td>
                      <td className="py-2.5 px-3 font-mono font-bold text-[#8B5A2B]">{fmtLE(a.amount_le)} EGP</td>
                      <td className="py-2.5 px-3 text-[#5C4A3D] font-mono">{a.piastres} piastre</td>
                      <td className="py-2.5 px-3 text-[#8B7355]">{a.pct}%</td>
                    </tr>
                  ))}
                </tbody>
                <tfoot className="bg-[#FAF8F5] border-t border-[#E5DCC5] font-bold text-xs sm:text-sm">
                  <tr>
                    <td className="py-2.5 px-3 text-[#2C1E16]">Total Alokasi Terdistribusi</td>
                    <td className="py-2.5 px-3 font-mono text-[#8B5A2B]">{fmtLE(simAmount)} EGP</td>
                    <td className="py-2.5 px-3 font-mono text-[#5C4A3D]">
                      {simDeliveryAllocations.totalPiastres} piastre
                    </td>
                    <td className="py-2.5 px-3 text-emerald-700 flex items-center gap-1">
                      <CheckCircle2 size={13} /> 100% Eksak
                    </td>
                  </tr>
                </tfoot>
              </table>
            </div>
          </div>

          {/* DELIVERY CHANGE HISTORY */}
          <AuditHistoryCard category="delivery" history={categoryHistories.delivery} />
        </div>
      )}

      {/* TAB 3: UPAH BELANJA BAHAN */}
      {activeTab === "material_purchase" && (
        <div className="space-y-6">
          <div className="rounded-2xl border border-[#E5DCC5] bg-white p-5 sm:p-6 shadow-sm space-y-5">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2 font-heading text-sm font-bold uppercase tracking-wider text-[#8B5A2B]">
                <ShoppingBag size={18} /> Kebijakan Upah Belanja Bahan Bertingkat
              </div>
              {!policies.material_purchase.is_configured && (
                <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2.5 py-0.5 text-xs font-semibold text-amber-800">
                  <AlertTriangle size={12} /> Belum Dikonfigurasi
                </span>
              )}
            </div>

            {!policies.material_purchase.is_configured && (
              <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-xs sm:text-sm text-amber-900 space-y-1">
                <div className="font-bold flex items-center gap-1.5">
                  <AlertTriangle size={16} className="text-amber-600" /> Perhatian: Kebijakan Belum Dikonfigurasi
                </div>
                <p className="text-amber-800 text-xs">
                  Tarif dasar upah belanja bahan per transaksi dan batas pembeli belum ditetapkan secara resmi oleh Owner. Transaksi belanja bahan belum dapat menghitung alokasi upah otomatis sampai parameter di bawah disimpan.
                </p>
              </div>
            )}

            {loading ? (
              <div className="py-8 text-center text-sm text-[#8B7355]">Memuat kebijakan...</div>
            ) : (
              <div className="space-y-4">
                <div className="grid gap-5 sm:grid-cols-4">
                  <div>
                    <Label className="block text-sm font-semibold text-[#2C1E16] mb-1">
                      Tarif Dasar per Belanja (EGP)
                    </Label>
                    <div className="relative">
                      <Input
                        type="number"
                        min="0"
                        step="1"
                        disabled={!isOwner || saving}
                        value={policies.material_purchase.default_wage_per_purchase_le}
                        onChange={(e) =>
                          setPolicies({
                            ...policies,
                            material_purchase: {
                              ...policies.material_purchase,
                              default_wage_per_purchase_le: e.target.value,
                            },
                          })
                        }
                        placeholder="Contoh: 50"
                        className="bg-white pr-12 font-medium"
                      />
                      <span className="absolute right-3 top-2.5 text-xs font-bold text-[#8B7355]">EGP</span>
                    </div>
                    <p className="mt-1 text-xs text-[#8B7355]">
                      Tarif standar per nota belanja bahan yang dibagi rata ke seluruh pembeli.
                    </p>
                  </div>

                  <div>
                    <Label className="block text-sm font-semibold text-[#2C1E16] mb-1">
                      Maksimum Pembeli (Orang)
                    </Label>
                    <Input
                      type="number"
                      min="1"
                      max="5"
                      step="1"
                      disabled={!isOwner || saving}
                      value={policies.material_purchase.max_buyers}
                      onChange={(e) =>
                        setPolicies({
                          ...policies,
                          material_purchase: { ...policies.material_purchase, max_buyers: e.target.value },
                        })
                      }
                      className="bg-white font-medium"
                    />
                    <p className="mt-1 text-xs text-[#8B7355]">
                      Batas maksimum pekerja yang boleh ditugaskan belanja per transaksi (1-5 orang, default: 5).
                    </p>
                  </div>

                  <div>
                    <Label className="block text-sm font-semibold text-[#2C1E16] mb-1">
                      Batas Konfirmasi (EGP)
                    </Label>
                    <div className="relative">
                      <Input
                        type="number"
                        min="1"
                        step="10"
                        disabled={!isOwner || saving}
                        value={policies.material_purchase.unusual_amount_threshold_le}
                        onChange={(e) =>
                          setPolicies({
                            ...policies,
                            material_purchase: {
                              ...policies.material_purchase,
                              unusual_amount_threshold_le: e.target.value,
                            },
                          })
                        }
                        placeholder="Contoh: 100"
                        className="bg-white pr-12 font-medium"
                      />
                      <span className="absolute right-3 top-2.5 text-xs font-bold text-[#8B7355]">EGP</span>
                    </div>
                    <p className="mt-1 text-xs text-[#8B7355]">
                      Ambang konfirmasi nominal tidak wajar untuk belanja bahan.
                    </p>
                  </div>

                  <div>
                    <Label className="block text-sm font-semibold text-[#2C1E16] mb-1">
                      Batas Maksimum Keras (EGP)
                    </Label>
                    <div className="relative">
                      <Input
                        type="number"
                        min="1"
                        step="10"
                        disabled={!isOwner || saving}
                        value={policies.material_purchase.max_wage_per_purchase_le}
                        onChange={(e) =>
                          setPolicies({
                            ...policies,
                            material_purchase: {
                              ...policies.material_purchase,
                              max_wage_per_purchase_le: e.target.value,
                            },
                          })
                        }
                        placeholder="Contoh: 300"
                        className="bg-white pr-12 font-medium text-rose-700"
                      />
                      <span className="absolute right-3 top-2.5 text-xs font-bold text-rose-600">EGP</span>
                    </div>
                    <p className="mt-1 text-xs text-[#8B7355]">
                      Plafon keras upah belanja bahan yang ditolak otomatis jika dilampaui.
                    </p>
                  </div>
                </div>

                <div className="flex items-center gap-2 pt-2">
                  <input
                    type="checkbox"
                    id="mat-enabled"
                    disabled={!isOwner || saving}
                    checked={Boolean(policies.material_purchase.enabled)}
                    onChange={(e) =>
                      setPolicies({
                        ...policies,
                        material_purchase: { ...policies.material_purchase, enabled: e.target.checked },
                      })
                    }
                    className="rounded border-[#E5DCC5] text-[#8B5A2B] focus:ring-[#8B5A2B]"
                  />
                  <Label htmlFor="mat-enabled" className="text-xs sm:text-sm font-semibold text-[#2C1E16] cursor-pointer">
                    Aktifkan Kebijakan Upah Belanja Bahan
                  </Label>
                </div>

                {/* Policy Change Reason (Mandatory for Updates) */}
                {isOwner && (
                  <div className="pt-2">
                    <Label htmlFor="reason-material" className="block text-xs font-semibold text-[#2C1E16] mb-1">
                      Alasan Perubahan Kebijakan <span className="text-rose-600">*</span>
                    </Label>
                    <Textarea
                      id="reason-material"
                      name="change_reason"
                      rows={2}
                      disabled={saving}
                      value={changeReasons.material_purchase}
                      onChange={(e) =>
                        setChangeReasons({ ...changeReasons, material_purchase: e.target.value })
                      }
                      placeholder="Contoh: Menyesuaikan kuota pembeli bahan dan tarif dasar pasar kayu"
                      className="bg-white text-xs font-medium"
                      maxLength={500}
                    />
                    <div className="flex justify-between text-[11px] text-[#8B7355] mt-1">
                      <span>Wajib diisi jika mengubah konfigurasi kebijakan belanja bahan.</span>
                      <span>{changeReasons.material_purchase.length}/500</span>
                    </div>
                  </div>
                )}

                <div className="rounded-xl border border-[#F1EBE0] bg-[#FAF8F5] p-3.5 space-y-1">
                  <div className="text-xs font-semibold text-[#5C4A3D] flex items-center gap-1.5">
                    <Coins size={14} className="text-[#8B5A2B]" /> Aturan Kebijakan Bertingkat: 0 &le; Tarif Dasar &le; Batas Konfirmasi &lt; Batas Maksimum Keras
                  </div>
                  <p className="text-xs text-[#8B7355]">
                    Seluruh pembagian upah belanja bahan multi-pembeli menggunakan utility presisi integer piastre eksak tanpa selisih floating point.
                  </p>
                </div>

                {isOwner && (
                  <div className="pt-2 flex justify-end">
                    <Button
                      onClick={() => handleSavePolicy("material_purchase")}
                      disabled={saving || loading}
                      className="rounded-xl bg-[#8B5A2B] hover:bg-[#6B4423] text-white px-5"
                    >
                      <Save size={16} className="mr-1.5" />
                      {saving ? "Menyimpan..." : "Simpan Pengaturan Upah Belanja Bahan"}
                    </Button>
                  </div>
                )}
              </div>
            )}
          </div>

          {/* MATERIAL PURCHASING WAGE SIMULATOR */}
          <div className="rounded-2xl border border-[#E5DCC5] bg-white p-5 sm:p-6 shadow-sm space-y-5">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2 font-heading text-sm font-bold uppercase tracking-wider text-[#8B5A2B]">
                <Calculator size={18} /> Simulator Distribusi Upah Belanja Bahan &amp; Uji Ambang Batas
              </div>
              <span className="text-xs text-[#8B7355]">Alat Bantu Estimasi</span>
            </div>

            <div className="rounded-xl border border-sky-200 bg-sky-50/60 p-3 text-xs text-sky-950 flex items-start gap-2">
              <Info size={16} className="text-sky-600 shrink-0 mt-0.5" />
              <span>
                <strong>Simulasi ini hanya untuk estimasi.</strong> Tidak membuat kewajiban upah belanja, transaksi keuangan, atau mengubah stok bahan.
              </span>
            </div>

            <div className="grid gap-4 sm:grid-cols-2 bg-[#F9F6F0] p-4 rounded-xl border border-[#E5DCC5]/60">
              <div>
                <Label className="text-xs font-semibold text-[#5C4A3D]">Nominal Upah Belanja (EGP)</Label>
                <div className="relative mt-1">
                  <Input
                    type="number"
                    min="0"
                    step="5"
                    disabled={!isOwner}
                    value={simMatAmount}
                    onChange={(e) => setSimMatAmount(e.target.value)}
                    className="bg-white pr-12 text-sm font-bold text-[#2C1E16]"
                  />
                  <span className="absolute right-3 top-2.5 text-xs font-bold text-[#8B7355]">EGP</span>
                </div>
              </div>

              <div>
                <Label className="text-xs font-semibold text-[#5C4A3D]">
                  Jumlah Pembeli Ditugaskan (Maks: {policies.material_purchase.max_buyers || 5})
                </Label>
                <div className="flex items-center gap-2 mt-1">
                  {Array.from(
                    { length: Math.min(5, Math.max(1, parseInt(policies.material_purchase.max_buyers, 10) || 5)) },
                    (_, i) => i + 1
                  ).map((cnt) => (
                    <button
                      key={cnt}
                      type="button"
                      onClick={() => setSimMatBuyerCount(cnt)}
                      className={`flex-1 py-2 text-xs font-bold rounded-lg border transition-colors ${
                        simMatBuyerCount === cnt
                          ? "bg-[#8B5A2B] text-white border-[#8B5A2B]"
                          : "bg-white text-[#5C4A3D] border-[#E5DCC5] hover:bg-[#EFE6D5]"
                      }`}
                    >
                      {cnt} Pembeli
                    </button>
                  ))}
                </div>
              </div>
            </div>

            {/* Material Purchase Tier Status Badges */}
            {policies.material_purchase.max_wage_per_purchase_le &&
              Number(simMatAmount) > Number(policies.material_purchase.max_wage_per_purchase_le) && (
                <div className="rounded-xl border border-rose-300 bg-rose-50 p-4 text-xs sm:text-sm text-rose-950 flex items-start gap-2.5">
                  <ShieldAlert size={20} className="text-rose-600 shrink-0 mt-0.5" />
                  <div>
                    <span className="font-bold">
                      Nominal Melebihi Batas Maksimum Keras ({policies.material_purchase.max_wage_per_purchase_le} EGP):
                    </span>
                    <p className="mt-0.5 text-xs text-rose-800">
                      Sistem backend akan <strong>MENOLAK OTOMATIS</strong> pengajuan upah belanja bahan ini dengan HTTP 422.
                    </p>
                  </div>
                </div>
              )}

            {policies.material_purchase.unusual_amount_threshold_le &&
              policies.material_purchase.max_wage_per_purchase_le &&
              Number(simMatAmount) > Number(policies.material_purchase.unusual_amount_threshold_le) &&
              Number(simMatAmount) <= Number(policies.material_purchase.max_wage_per_purchase_le) && (
                <div className="rounded-xl border border-amber-300 bg-amber-50 p-4 text-xs sm:text-sm text-amber-950 flex items-start gap-2.5">
                  <AlertTriangle size={20} className="text-amber-600 shrink-0 mt-0.5" />
                  <div>
                    <span className="font-bold">
                      Nominal Memerlukan Konfirmasi Petugas ({policies.material_purchase.unusual_amount_threshold_le} -{" "}
                      {policies.material_purchase.max_wage_per_purchase_le} EGP):
                    </span>
                    <p className="mt-0.5 text-xs text-amber-800">
                      Pada pencatatan transaksi belanja bahan, sistem mewajibkan konfirmasi dan alasan tertulis dari petugas.
                    </p>
                  </div>
                </div>
              )}

            {policies.material_purchase.unusual_amount_threshold_le &&
              Number(simMatAmount) <= Number(policies.material_purchase.unusual_amount_threshold_le) && (
                <div className="rounded-xl border border-emerald-300 bg-emerald-50 p-3 text-xs sm:text-sm text-emerald-950 flex items-center gap-2.5">
                  <CheckCircle2 size={18} className="text-emerald-600 shrink-0" />
                  <div>
                    <span className="font-bold">
                      Nominal Standar (&le; {policies.material_purchase.unusual_amount_threshold_le} EGP):
                    </span>
                    <span className="ml-1 text-xs text-emerald-800">
                      Diproses secara normal tanpa memerlukan konfirmasi override nominal.
                    </span>
                  </div>
                </div>
              )}

            {/* Breakdown Table */}
            <div className="overflow-x-auto rounded-xl border border-[#E5DCC5]">
              <table className="w-full text-left text-xs sm:text-sm">
                <thead className="bg-[#FAF8F5] text-xs font-bold uppercase tracking-wider text-[#8B7355] border-b border-[#E5DCC5]">
                  <tr>
                    <th className="py-2.5 px-3">Pembeli</th>
                    <th className="py-2.5 px-3">Alokasi (EGP)</th>
                    <th className="py-2.5 px-3">Satuan Piastre</th>
                    <th className="py-2.5 px-3">Proporsi</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[#F1EBE0]">
                  {simMatAllocations.list.map((a) => (
                    <tr key={a.index} className="hover:bg-[#FAF8F5]/60">
                      <td className="py-2.5 px-3 font-medium text-[#2C1E16]">Pembeli {a.index}</td>
                      <td className="py-2.5 px-3 font-mono font-bold text-[#8B5A2B]">{fmtLE(a.amount_le)} EGP</td>
                      <td className="py-2.5 px-3 text-[#5C4A3D] font-mono">{a.piastres} piastre</td>
                      <td className="py-2.5 px-3 text-[#8B7355]">{a.pct}%</td>
                    </tr>
                  ))}
                </tbody>
                <tfoot className="bg-[#FAF8F5] border-t border-[#E5DCC5] font-bold text-xs sm:text-sm">
                  <tr>
                    <td className="py-2.5 px-3 text-[#2C1E16]">Total Alokasi Terdistribusi</td>
                    <td className="py-2.5 px-3 font-mono text-[#8B5A2B]">{fmtLE(simMatAmount)} EGP</td>
                    <td className="py-2.5 px-3 font-mono text-[#5C4A3D]">
                      {simMatAllocations.totalPiastres} piastre
                    </td>
                    <td className="py-2.5 px-3 text-emerald-700 flex items-center gap-1">
                      <CheckCircle2 size={13} /> 100% Eksak
                    </td>
                  </tr>
                </tfoot>
              </table>
            </div>
          </div>

          {/* MATERIAL PURCHASE AUDIT HISTORY */}
          <AuditHistoryCard category="material_purchase" history={categoryHistories.material_purchase} />
        </div>
      )}

      {/* TAB 4: UPAH ADMIN */}
      {activeTab === "admin" && (
        <div className="space-y-6">
          <div className="rounded-2xl border border-[#E5DCC5] bg-white p-5 sm:p-6 shadow-sm space-y-5">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2 font-heading text-sm font-bold uppercase tracking-wider text-[#8B5A2B]">
                <UserCheck size={18} /> Kebijakan Upah Admin Bertingkat
              </div>
              {!policies.admin.is_configured && (
                <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2.5 py-0.5 text-xs font-semibold text-amber-800">
                  <AlertTriangle size={12} /> Belum Dikonfigurasi
                </span>
              )}
            </div>

            {!policies.admin.is_configured && (
              <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-xs sm:text-sm text-amber-900 space-y-1">
                <div className="font-bold flex items-center gap-1.5">
                  <AlertTriangle size={16} className="text-amber-600" /> Perhatian: Kebijakan Belum Dikonfigurasi
                </div>
                <p className="text-amber-800 text-xs">
                  Tarif upah admin per pesanan dan penerima default belum ditetapkan oleh Owner. Akrual kewajiban upah admin belum akan dibuat sampai kebijakan disimpan dan diaktifkan.
                </p>
              </div>
            )}

            {loading ? (
              <div className="py-8 text-center text-sm text-[#8B7355]">Memuat kebijakan...</div>
            ) : (
              <div className="space-y-4">
                <div className="grid gap-5 sm:grid-cols-4">
                  <div>
                    <Label className="block text-sm font-semibold text-[#2C1E16] mb-1">
                      Tarif Upah per Pesanan (EGP)
                    </Label>
                    <div className="relative">
                      <Input
                        type="number"
                        min="0"
                        step="1"
                        disabled={!isOwner || saving}
                        value={policies.admin.default_wage_per_order_le}
                        onChange={(e) =>
                          setPolicies({
                            ...policies,
                            admin: { ...policies.admin, default_wage_per_order_le: e.target.value },
                          })
                        }
                        placeholder="Contoh: 25"
                        className="bg-white pr-12 font-medium"
                      />
                      <span className="absolute right-3 top-2.5 text-xs font-bold text-[#8B7355]">EGP</span>
                    </div>
                    <p className="mt-1 text-xs text-[#8B7355]">
                      Tarif kompensasi admin operasional per pesanan yang berhasil dicatat/diproses.
                    </p>
                  </div>

                  <div>
                    <Label className="block text-sm font-semibold text-[#2C1E16] mb-1">
                      Penerima Default (Akun Tim)
                    </Label>
                    <select
                      disabled={!isOwner || saving}
                      value={policies.admin.default_recipient_id || ""}
                      onChange={(e) => {
                        const selId = e.target.value;
                        const found = workers.find((w) => String(w.id) === String(selId));
                        setPolicies({
                          ...policies,
                          admin: {
                            ...policies.admin,
                            default_recipient_id: selId,
                            default_recipient_name: found ? found.name : "",
                          },
                        });
                      }}
                      className="w-full h-10 rounded-md border border-[#E5DCC5] bg-white px-3 py-2 text-xs sm:text-sm font-medium text-[#2C1E16] focus:outline-none focus:ring-2 focus:ring-[#8B5A2B]"
                    >
                      <option value="">-- Pilih Penerima Default --</option>
                      {workers.map((w) => (
                        <option key={w.id} value={w.id}>
                          {w.name} ({w.role})
                        </option>
                      ))}
                    </select>
                    <p className="mt-1 text-xs text-[#8B7355]">
                      Penerima kewajiban upah admin default jika tidak dialihkan per pesanan.
                    </p>
                  </div>

                  <div>
                    <Label className="block text-sm font-semibold text-[#2C1E16] mb-1">
                      Batas Konfirmasi (EGP)
                    </Label>
                    <div className="relative">
                      <Input
                        type="number"
                        min="1"
                        step="10"
                        disabled={!isOwner || saving}
                        value={policies.admin.unusual_amount_threshold_le}
                        onChange={(e) =>
                          setPolicies({
                            ...policies,
                            admin: { ...policies.admin, unusual_amount_threshold_le: e.target.value },
                          })
                        }
                        placeholder="Contoh: 50"
                        className="bg-white pr-12 font-medium"
                      />
                      <span className="absolute right-3 top-2.5 text-xs font-bold text-[#8B7355]">EGP</span>
                    </div>
                    <p className="mt-1 text-xs text-[#8B7355]">
                      Ambang konfirmasi nominal tidak wajar untuk upah admin.
                    </p>
                  </div>

                  <div>
                    <Label className="block text-sm font-semibold text-[#2C1E16] mb-1">
                      Batas Maksimum Keras (EGP)
                    </Label>
                    <div className="relative">
                      <Input
                        type="number"
                        min="1"
                        step="10"
                        disabled={!isOwner || saving}
                        value={policies.admin.max_wage_per_order_le}
                        onChange={(e) =>
                          setPolicies({
                            ...policies,
                            admin: { ...policies.admin, max_wage_per_order_le: e.target.value },
                          })
                        }
                        placeholder="Contoh: 150"
                        className="bg-white pr-12 font-medium text-rose-700"
                      />
                      <span className="absolute right-3 top-2.5 text-xs font-bold text-rose-600">EGP</span>
                    </div>
                    <p className="mt-1 text-xs text-[#8B7355]">
                      Plafon keras upah admin per pesanan yang ditolak jika dilampaui.
                    </p>
                  </div>
                </div>

                <div className="flex items-center gap-2 pt-2">
                  <input
                    type="checkbox"
                    id="admin-enabled"
                    disabled={!isOwner || saving}
                    checked={Boolean(policies.admin.enabled)}
                    onChange={(e) =>
                      setPolicies({
                        ...policies,
                        admin: { ...policies.admin, enabled: e.target.checked },
                      })
                    }
                    className="rounded border-[#E5DCC5] text-[#8B5A2B] focus:ring-[#8B5A2B]"
                  />
                  <Label htmlFor="admin-enabled" className="text-xs sm:text-sm font-semibold text-[#2C1E16] cursor-pointer">
                    Aktifkan Kebijakan Upah Admin Otomatis
                  </Label>
                </div>

                {/* Policy Change Reason (Mandatory for Updates) */}
                {isOwner && (
                  <div className="pt-2">
                    <Label htmlFor="reason-admin" className="block text-xs font-semibold text-[#2C1E16] mb-1">
                      Alasan Perubahan Kebijakan <span className="text-rose-600">*</span>
                    </Label>
                    <Textarea
                      id="reason-admin"
                      name="change_reason"
                      rows={2}
                      disabled={saving}
                      value={changeReasons.admin}
                      onChange={(e) =>
                        setChangeReasons({ ...changeReasons, admin: e.target.value })
                      }
                      placeholder="Contoh: Perubahan penerima default upah admin dan penyesuaian tarif per order"
                      className="bg-white text-xs font-medium"
                      maxLength={500}
                    />
                    <div className="flex justify-between text-[11px] text-[#8B7355] mt-1">
                      <span>Wajib diisi jika mengubah konfigurasi kebijakan upah admin.</span>
                      <span>{changeReasons.admin.length}/500</span>
                    </div>
                  </div>
                )}

                <div className="rounded-xl border border-[#F1EBE0] bg-[#FAF8F5] p-3.5 space-y-1">
                  <div className="text-xs font-semibold text-[#5C4A3D] flex items-center gap-1.5">
                    <Coins size={14} className="text-[#8B5A2B]" /> Aturan Kebijakan Bertingkat: 0 &le; Tarif Dasar &le; Batas Konfirmasi &lt; Batas Maksimum Keras
                  </div>
                  <p className="text-xs text-[#8B7355]">
                    Upah admin disalurkan ke akun pekerja internal dalam satuan EGP eksak tanpa toleransi kebocoran desimal.
                  </p>
                </div>

                {isOwner && (
                  <div className="pt-2 flex justify-end">
                    <Button
                      onClick={() => handleSavePolicy("admin")}
                      disabled={saving || loading}
                      className="rounded-xl bg-[#8B5A2B] hover:bg-[#6B4423] text-white px-5"
                    >
                      <Save size={16} className="mr-1.5" />
                      {saving ? "Menyimpan..." : "Simpan Pengaturan Upah Admin"}
                    </Button>
                  </div>
                )}
              </div>
            )}
          </div>

          {/* ADMIN WAGE SIMULATOR */}
          <div className="rounded-2xl border border-[#E5DCC5] bg-white p-5 sm:p-6 shadow-sm space-y-5">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2 font-heading text-sm font-bold uppercase tracking-wider text-[#8B5A2B]">
                <Calculator size={18} /> Simulator Akumulasi Upah Admin &amp; Transisi Penerima
              </div>
              <span className="text-xs text-[#8B7355]">Alat Bantu Estimasi</span>
            </div>

            <div className="rounded-xl border border-sky-200 bg-sky-50/60 p-3 text-xs text-sky-950 flex items-start gap-2">
              <Info size={16} className="text-sky-600 shrink-0 mt-0.5" />
              <span>
                <strong>Simulasi ini hanya untuk estimasi dan perencanaan manajerial.</strong> Tidak membuat kewajiban upah riil, tidak mengubah data pesanan, dan tidak mengubah penerima historis di database.
              </span>
            </div>

            <div className="grid gap-4 sm:grid-cols-2 bg-[#F9F6F0] p-4 rounded-xl border border-[#E5DCC5]/60">
              <div>
                <Label className="text-xs font-semibold text-[#5C4A3D]">Tarif Upah per Pesanan (EGP)</Label>
                <div className="relative mt-1">
                  <Input
                    type="number"
                    min="0"
                    step="5"
                    disabled={!isOwner}
                    value={simAdminWage}
                    onChange={(e) => setSimAdminWage(e.target.value)}
                    className="bg-white pr-12 text-sm font-bold text-[#2C1E16]"
                  />
                  <span className="absolute right-3 top-2.5 text-xs font-bold text-[#8B7355]">EGP</span>
                </div>
              </div>

              <div>
                <Label className="text-xs font-semibold text-[#5C4A3D]">Penerima Default Kebijakan Saat Ini</Label>
                <div className="mt-1 flex items-center gap-2 rounded-lg border border-[#E5DCC5] bg-white px-3 py-2 text-xs font-medium text-[#2C1E16]">
                  <UserCheck size={16} className="text-[#8B5A2B]" />
                  <span>
                    {policies.admin.default_recipient_name || "Belum Ditentukan"}
                  </span>
                  {policies.admin.default_recipient_id && (
                    <span className="text-[10px] text-[#8B7355] font-mono">
                      ({policies.admin.default_recipient_id})
                    </span>
                  )}
                </div>
              </div>
            </div>

            {/* Admin Tier Status Badges */}
            {policies.admin.max_wage_per_order_le &&
              Number(simAdminWage) > Number(policies.admin.max_wage_per_order_le) && (
                <div className="rounded-xl border border-rose-300 bg-rose-50 p-4 text-xs sm:text-sm text-rose-950 flex items-start gap-2.5">
                  <ShieldAlert size={20} className="text-rose-600 shrink-0 mt-0.5" />
                  <div>
                    <span className="font-bold">
                      Tarif Melebihi Batas Maksimum Keras ({policies.admin.max_wage_per_order_le} EGP):
                    </span>
                    <p className="mt-0.5 text-xs text-rose-800">
                      Sistem backend akan <strong>MENOLAK OTOMATIS</strong> akrual upah admin dengan tarif di atas batas ini.
                    </p>
                  </div>
                </div>
              )}

            {policies.admin.unusual_amount_threshold_le &&
              policies.admin.max_wage_per_order_le &&
              Number(simAdminWage) > Number(policies.admin.unusual_amount_threshold_le) &&
              Number(simAdminWage) <= Number(policies.admin.max_wage_per_order_le) && (
                <div className="rounded-xl border border-amber-300 bg-amber-50 p-4 text-xs sm:text-sm text-amber-950 flex items-start gap-2.5">
                  <AlertTriangle size={20} className="text-amber-600 shrink-0 mt-0.5" />
                  <div>
                    <span className="font-bold">
                      Tarif Memerlukan Konfirmasi Petugas ({policies.admin.unusual_amount_threshold_le} -{" "}
                      {policies.admin.max_wage_per_order_le} EGP):
                    </span>
                    <p className="mt-0.5 text-xs text-amber-800">
                      Ambang peringatan. Penugasan atau akrual khusus mewajibkan konfirmasi dan pencatatan alasan tertulis.
                    </p>
                  </div>
                </div>
              )}

            {policies.admin.unusual_amount_threshold_le &&
              Number(simAdminWage) <= Number(policies.admin.unusual_amount_threshold_le) && (
                <div className="rounded-xl border border-emerald-300 bg-emerald-50 p-3 text-xs sm:text-sm text-emerald-950 flex items-center gap-2.5">
                  <CheckCircle2 size={18} className="text-emerald-600 shrink-0" />
                  <div>
                    <span className="font-bold">
                      Tarif Standar (&le; {policies.admin.unusual_amount_threshold_le} EGP):
                    </span>
                    <span className="ml-1 text-xs text-emerald-800">
                      Diproses secara normal tanpa memerlukan konfirmasi override.
                    </span>
                  </div>
                </div>
              )}

            {/* Admin Simulation Modes */}
            <div className="space-y-4">
              <div className="flex border-b border-[#E5DCC5]">
                <button
                  type="button"
                  onClick={() => setSimAdminMode("scenario_a")}
                  className={`pb-2 px-4 text-xs sm:text-sm font-bold border-b-2 transition-colors ${
                    simAdminMode === "scenario_a"
                      ? "border-[#8B5A2B] text-[#8B5A2B]"
                      : "border-transparent text-[#8B7355] hover:text-[#2C1E16]"
                  }`}
                >
                  Skenario A: Pembagian Volume Antar Penerima
                </button>
                <button
                  type="button"
                  onClick={() => setSimAdminMode("scenario_b")}
                  className={`pb-2 px-4 text-xs sm:text-sm font-bold border-b-2 transition-colors ${
                    simAdminMode === "scenario_b"
                      ? "border-[#8B5A2B] text-[#8B5A2B]"
                      : "border-transparent text-[#8B7355] hover:text-[#2C1E16]"
                  }`}
                >
                  Skenario B: Simulasi Tanggal Efektif Transisi
                </button>
              </div>

              {/* SCENARIO A: ALLOCATION BY ORDER VOLUME */}
              {simAdminMode === "scenario_a" && (
                <div className="space-y-4">
                  <p className="text-xs text-[#8B7355]">
                    Simulasikan pemisahan kewajiban upah admin jika dua administrator berbagi tanggung jawab pesanan dalam periode yang sama.
                  </p>

                  <div className="grid gap-4 sm:grid-cols-2">
                    <div className="p-4 rounded-xl border border-[#E5DCC5] bg-white space-y-3">
                      <div className="text-xs font-bold text-[#8B5A2B] uppercase tracking-wider flex items-center gap-1.5">
                        <Users size={14} /> Penerima 1 (Admin Sebelumnya)
                      </div>
                      <div>
                        <Label className="text-xs text-[#5C4A3D]">Nama / Label Penerima 1</Label>
                        <Input
                          type="text"
                          value={simAdminRecip1}
                          onChange={(e) => setSimAdminRecip1(e.target.value)}
                          className="mt-1 bg-[#FAF8F5] text-xs font-medium"
                        />
                      </div>
                      <div>
                        <Label className="text-xs text-[#5C4A3D]">Jumlah Pesanan Ditangani</Label>
                        <Input
                          type="number"
                          min="0"
                          step="1"
                          disabled={!isOwner}
                          value={simAdminOrders1}
                          onChange={(e) => setSimAdminOrders1(e.target.value)}
                          className="mt-1 text-sm font-bold"
                        />
                      </div>
                      <div className="pt-2 border-t border-[#F1EBE0] flex justify-between items-center text-xs">
                        <span className="text-[#8B7355]">Estimasi Hak Upah:</span>
                        <span className="font-mono font-bold text-[#8B5A2B] text-sm">
                          {fmtLE(simAdminScenarioA.payout1)} EGP
                        </span>
                      </div>
                    </div>

                    <div className="p-4 rounded-xl border border-[#E5DCC5] bg-white space-y-3">
                      <div className="text-xs font-bold text-[#8B5A2B] uppercase tracking-wider flex items-center gap-1.5">
                        <Users size={14} /> Penerima 2 (Admin Baru / Pengganti)
                      </div>
                      <div>
                        <Label className="text-xs text-[#5C4A3D]">Nama / Label Penerima 2</Label>
                        <Input
                          type="text"
                          disabled={!isOwner}
                          value={simAdminRecip2}
                          onChange={(e) => setSimAdminRecip2(e.target.value)}
                          className="mt-1 bg-[#FAF8F5] text-xs font-medium"
                        />
                      </div>
                      <div>
                        <Label className="text-xs text-[#5C4A3D]">Jumlah Pesanan Ditangani</Label>
                        <Input
                          type="number"
                          min="0"
                          step="1"
                          disabled={!isOwner}
                          value={simAdminOrders2}
                          onChange={(e) => setSimAdminOrders2(e.target.value)}
                          className="mt-1 text-sm font-bold"
                        />
                      </div>
                      <div className="pt-2 border-t border-[#F1EBE0] flex justify-between items-center text-xs">
                        <span className="text-[#8B7355]">Estimasi Hak Upah:</span>
                        <span className="font-mono font-bold text-[#8B5A2B] text-sm">
                          {fmtLE(simAdminScenarioA.payout2)} EGP
                        </span>
                      </div>
                    </div>
                  </div>

                  {/* Scenario A Total Card */}
                  <div className="p-4 rounded-xl border border-[#E5DCC5] bg-[#FAF8F5] flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 text-xs sm:text-sm">
                    <div>
                      <div className="font-bold text-[#2C1E16]">
                        Total Simulasi: {simAdminScenarioA.totalOrders} Pesanan (@ {simAdminWage} EGP)
                      </div>
                      <div className="text-xs text-[#8B7355]">
                        {simAdminRecip1}: {simAdminScenarioA.orders1} pesanan | {simAdminRecip2}: {simAdminScenarioA.orders2} pesanan
                      </div>
                    </div>
                    <div className="text-right">
                      <span className="text-xs text-[#8B7355] block">Total Kewajiban Terhitung:</span>
                      <span className="text-base font-bold font-mono text-[#8B5A2B]">
                        {fmtLE(simAdminScenarioA.totalPayout)} EGP
                      </span>
                    </div>
                  </div>
                </div>
              )}

              {/* SCENARIO B: EFFECTIVE DATE SIMULATION */}
              {simAdminMode === "scenario_b" && (
                <div className="space-y-4">
                  <div className="rounded-xl border border-amber-200 bg-amber-50/70 p-3 text-xs text-amber-900">
                    <span className="font-semibold">Catatan Keterbatasan Historis:</span> Simulasi tanggal efektif ini bersifat hipotetis murni dan tidak memodifikasi kepemilikan pesanan atau penugasan riil di database.
                  </div>

                  <div className="grid gap-4 sm:grid-cols-3 bg-[#F9F6F0] p-4 rounded-xl border border-[#E5DCC5]/60">
                    <div>
                      <Label className="text-xs font-semibold text-[#5C4A3D] flex items-center gap-1">
                        <Calendar size={13} /> Tanggal Efektif Transisi
                      </Label>
                      <Input
                        type="date"
                        value={simAdminSwitchDate}
                        onChange={(e) => setSimAdminSwitchDate(e.target.value)}
                        className="mt-1 bg-white text-xs font-medium"
                      />
                    </div>
                    <div>
                      <Label className="text-xs font-semibold text-[#5C4A3D]">
                        Pesanan Sebelum {simAdminSwitchDate}
                      </Label>
                      <Input
                        type="number"
                        min="0"
                        step="1"
                        disabled={!isOwner}
                        value={simAdminPreOrders}
                        onChange={(e) => setSimAdminPreOrders(e.target.value)}
                        className="mt-1 bg-white text-sm font-bold"
                      />
                    </div>
                    <div>
                      <Label className="text-xs font-semibold text-[#5C4A3D]">
                        Pesanan Sejak {simAdminSwitchDate}
                      </Label>
                      <Input
                        type="number"
                        min="0"
                        step="1"
                        disabled={!isOwner}
                        value={simAdminPostOrders}
                        onChange={(e) => setSimAdminPostOrders(e.target.value)}
                        className="mt-1 bg-white text-sm font-bold"
                      />
                    </div>
                  </div>

                  {/* Scenario B Timeline Breakdown Card */}
                  <div className="p-4 rounded-xl border border-[#E5DCC5] bg-white space-y-3">
                    <div className="text-xs font-bold text-[#8B5A2B] uppercase tracking-wider flex items-center gap-1.5">
                      <ArrowRight size={14} /> Hasil Proyeksi Transisi Tanggal Efektif
                    </div>

                    <div className="grid gap-3 sm:grid-cols-2 text-xs">
                      <div className="p-3 rounded-lg border border-[#F1EBE0] bg-[#FAF8F5]">
                        <span className="text-[#8B7355] block font-medium">
                          Periode Pra-Transisi (&lt; {simAdminSwitchDate})
                        </span>
                        <div className="mt-1 font-bold text-[#2C1E16]">
                          {simAdminScenarioB.preOrders} Pesanan dialokasikan ke:{" "}
                          <span className="text-[#8B5A2B]">{simAdminRecip1 || "Admin Lama"}</span>
                        </div>
                        <div className="mt-2 text-sm font-mono font-bold text-[#8B5A2B]">
                          {fmtLE(simAdminScenarioB.prePayout)} EGP
                        </div>
                      </div>

                      <div className="p-3 rounded-lg border border-[#F1EBE0] bg-[#FAF8F5]">
                        <span className="text-[#8B7355] block font-medium">
                          Periode Pasca-Transisi (&ge; {simAdminSwitchDate})
                        </span>
                        <div className="mt-1 font-bold text-[#2C1E16]">
                          {simAdminScenarioB.postOrders} Pesanan dialokasikan ke:{" "}
                          <span className="text-[#8B5A2B]">{simAdminRecip2 || "Admin Baru"}</span>
                        </div>
                        <div className="mt-2 text-sm font-mono font-bold text-[#8B5A2B]">
                          {fmtLE(simAdminScenarioB.postPayout)} EGP
                        </div>
                      </div>
                    </div>

                    <div className="pt-2 border-t border-[#F1EBE0] flex justify-between items-center text-xs sm:text-sm font-bold">
                      <span>Total Kewajiban Proyeksi ({simAdminScenarioB.totalOrders} pesanan):</span>
                      <span className="font-mono text-[#8B5A2B] text-base">
                        {fmtLE(simAdminScenarioB.totalPayout)} EGP
                      </span>
                    </div>
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* ADMIN AUDIT HISTORY */}
          <AuditHistoryCard category="admin" history={categoryHistories.admin} />
        </div>
      )}

      {/* Threshold Override Interactive Confirmation Modal (Delivery Simulator) */}
      {testModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div className="w-full max-w-md rounded-2xl border border-[#E5DCC5] bg-white p-6 shadow-xl space-y-4 animate-in fade-in zoom-in-95">
            <div className="flex items-center justify-between border-b border-[#F1EBE0] pb-3">
              <div className="flex items-center gap-2 font-heading text-base font-bold text-amber-900">
                <AlertTriangle size={20} className="text-amber-600" />
                Konfirmasi Nominal Tidak Wajar
              </div>
              <button onClick={() => setTestModalOpen(false)} className="text-[#8B7355] hover:text-[#2C1E16]">
                <X size={18} />
              </button>
            </div>

            <div className="space-y-3 text-xs sm:text-sm text-[#5C4A3D]">
              <div className="rounded-xl bg-amber-50 p-3 border border-amber-200">
                <p>
                  Nominal upah yang dimasukkan: <span className="font-bold font-mono text-amber-950">{simAmount} EGP</span>.
                </p>
                <p className="mt-1 text-xs text-amber-800">
                  Batas konfirmasi nominal tidak wajar saat ini adalah{" "}
                  <span className="font-bold">{policies.delivery.unusual_amount_threshold_le} EGP</span>.
                </p>
              </div>

              <p className="text-xs text-[#8B7355]">
                Apakah Anda yakin nominal ini sudah benar dan bukan kesalahan ketik (typo)?
              </p>

              <div>
                <Label className="block text-xs font-semibold text-[#2C1E16] mb-1">
                  Alasan Override Upah <span className="text-red-500">* (minimal 5 karakter)</span>
                </Label>
                <Textarea
                  rows={3}
                  value={testOverrideReason}
                  onChange={(e) => setTestOverrideReason(e.target.value)}
                  placeholder="Contoh: Pengantaran tangga manual ke lantai 5 tanpa lift untuk lemari 3 pintu jati"
                  className="bg-white text-xs"
                />
              </div>
            </div>

            <div className="flex items-center justify-end gap-2 border-t border-[#F1EBE0] pt-3">
              <Button
                variant="outline"
                size="sm"
                onClick={() => setTestModalOpen(false)}
                className="rounded-xl border-[#E5DCC5] text-[#5C4A3D]"
              >
                Batal
              </Button>
              <Button
                size="sm"
                onClick={() => {
                  if (!testOverrideReason || testOverrideReason.trim().length < 5) {
                    toast.error("Alasan override wajib diisi minimal 5 karakter.");
                    return;
                  }
                  toast.success("Konfirmasi valid! Nominal override diizinkan.");
                  setTestModalOpen(false);
                }}
                className="rounded-xl bg-amber-600 hover:bg-amber-700 text-white"
              >
                Konfirmasi & Lanjutkan
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/**
 * Reusable Category-Scoped Audit History Table Component.
 * Supports legacy history gracefully (shows missing reason label without fabricating).
 */
function AuditHistoryCard({ category, history = [] }) {
  const categoryLabels = {
    production: "Upah Produksi",
    delivery: "Upah Pengiriman",
    material_purchase: "Upah Belanja Bahan",
    admin: "Upah Admin",
  };

  const catLabel = categoryLabels[category] || category;

  return (
    <div className="rounded-2xl border border-[#E5DCC5] bg-white p-5 sm:p-6 shadow-sm space-y-4">
      <div className="flex items-center gap-2 font-heading text-sm font-bold uppercase tracking-wider text-[#8B5A2B]">
        <History size={18} /> Riwayat Kebijakan &amp; Audit Upah — {catLabel}
      </div>

      {history.length === 0 ? (
        <div className="py-6 text-center text-xs text-[#8B7355]">
          Belum ada riwayat perubahan terekam untuk {catLabel}. Kebijakan saat ini menggunakan nilai standar awal.
        </div>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-[#E5DCC5]">
          <table className="w-full text-left text-xs">
            <thead className="bg-[#FAF8F5] text-xs font-bold text-[#8B7355] border-b border-[#E5DCC5]">
              <tr>
                <th className="py-2.5 px-3">Waktu</th>
                <th className="py-2.5 px-3">Jenis Kegiatan</th>
                <th className="py-2.5 px-3">Petugas</th>
                <th className="py-2.5 px-3">Alasan Perubahan</th>
                <th className="py-2.5 px-3">Detail &amp; Nilai</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#F1EBE0]">
              {history.map((h, idx) => {
                const action = h.action || "";
                const isPolicyUpdate = action.startsWith("update_") && action.endsWith("_policy");
                const isOverride = action === "delivery_wage_threshold_override";
                const isRejection = action === "delivery_wage_hard_cap_rejection";

                const reason =
                  h.metadata?.change_reason ||
                  h.metadata?.override_reason ||
                  null;

                return (
                  <tr key={h._id || idx} className="hover:bg-[#FAF8F5]/60">
                    <td className="py-2 px-3 text-[#5C4A3D] whitespace-nowrap">
                      {h.timestamp ? new Date(h.timestamp).toLocaleString("id-ID") : "-"}
                    </td>
                    <td className="py-2 px-3 whitespace-nowrap">
                      {isPolicyUpdate && (
                        <span className="inline-flex rounded-md bg-blue-100 px-2 py-0.5 text-[11px] font-semibold text-blue-800">
                          Kebijakan
                        </span>
                      )}
                      {isOverride && (
                        <span className="inline-flex rounded-md bg-amber-100 px-2 py-0.5 text-[11px] font-semibold text-amber-800">
                          Konfirmasi Override
                        </span>
                      )}
                      {isRejection && (
                        <span className="inline-flex rounded-md bg-rose-100 px-2 py-0.5 text-[11px] font-semibold text-rose-800">
                          Ditolak Hard Cap
                        </span>
                      )}
                      {!isPolicyUpdate && !isOverride && !isRejection && (
                        <span className="inline-flex rounded-md bg-stone-100 px-2 py-0.5 text-[11px] font-semibold text-stone-700">
                          {action || "Log"}
                        </span>
                      )}
                    </td>
                    <td className="py-2 px-3 font-medium text-[#2C1E16] whitespace-nowrap">
                      {h.performed_by_name || "Petugas"}
                    </td>
                    <td className="py-2 px-3 text-[#5C4A3D]">
                      {reason ? (
                        <span className="font-medium text-[#2C1E16]">{reason}</span>
                      ) : (
                        <span className="text-stone-400 italic">Tidak tersedia (riwayat lama)</span>
                      )}
                    </td>
                    <td className="py-2 px-3 text-[#5C4A3D]">
                      {isPolicyUpdate && h.metadata?.new && (
                        <span>
                          {category === "production" && (
                            <>
                              Dasar: {h.metadata.new.default_wage_per_unit_le ?? "-"} LE | Ambang: {h.metadata.new.unusual_amount_threshold_le ?? "-"} LE | Cap: {h.metadata.new.max_wage_per_unit_le ?? "-"} LE
                            </>
                          )}
                          {category === "delivery" && (
                            <>
                              Dasar: {h.metadata.new.base_wage_per_order_le ?? "-"} LE | Ambang: {h.metadata.new.unusual_amount_threshold_le ?? "-"} LE | Cap: {h.metadata.new.max_helper_wage_per_order_le ?? "-"} LE
                            </>
                          )}
                          {category === "material_purchase" && (
                            <>
                              Dasar: {h.metadata.new.default_wage_per_purchase_le ?? "-"} LE | Ambang: {h.metadata.new.unusual_amount_threshold_le ?? "-"} LE | Cap: {h.metadata.new.max_wage_per_purchase_le ?? "-"} LE | Max Buyer: {h.metadata.new.max_buyers ?? "-"}
                            </>
                          )}
                          {category === "admin" && (
                            <>
                              Dasar: {h.metadata.new.default_wage_per_order_le ?? "-"} LE | Ambang: {h.metadata.new.unusual_amount_threshold_le ?? "-"} LE | Cap: {h.metadata.new.max_wage_per_order_le ?? "-"} LE | Penerima: {h.metadata.new.default_recipient_name || h.metadata.new.default_recipient_id || "-"}
                            </>
                          )}
                        </span>
                      )}
                      {isOverride && (
                        <span>
                          Pesanan: <span className="font-mono font-medium">{h.entity_identifier || h.metadata?.order_number}</span> | Upah: <strong>{h.metadata?.recorded_amount_le} LE</strong>
                        </span>
                      )}
                      {isRejection && (
                        <span className="text-rose-700">
                          Pesanan: <span className="font-mono">{h.entity_identifier || h.metadata?.order_number}</span> | Dicoba: <strong>{h.metadata?.attempted_amount_le} LE</strong> (Batas Keras: {h.metadata?.hard_cap_le} LE) — Ditolak
                        </span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
