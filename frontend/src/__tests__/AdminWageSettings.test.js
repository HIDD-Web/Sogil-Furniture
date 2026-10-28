import React, { act } from "react";
import { createRoot } from "react-dom/client";

jest.mock(
  "@/lib/utils",
  () => jest.requireActual("../lib/utils"),
  { virtual: true }
);

jest.mock(
  "react-router-dom",
  () => ({
    useNavigate: () => jest.fn(),
    useParams: () => ({}),
    useLocation: () => ({ pathname: "/admin/wage-settings" }),
  }),
  { virtual: true }
);

global.IS_REACT_ACT_ENVIRONMENT = true;

const mockToast = {
  success: jest.fn(),
  error: jest.fn(),
  info: jest.fn(),
};
jest.mock("sonner", () => ({
  toast: {
    success: (...args) => mockToast.success(...args),
    error: (...args) => mockToast.error(...args),
    info: (...args) => mockToast.info(...args),
  },
}));

let mockUser = {
  role: "owner",
  permissions: { access_finance: true },
};
jest.mock("../context/AuthContext", () => ({
  useAuth: () => ({ user: mockUser }),
}));

import api from "../lib/api";
jest.mock("../lib/api");

import AdminWageSettings from "../pages/admin/AdminWageSettings";

describe("AdminWageSettings - Centralized Multi-Category Wage Settings UI", () => {
  let container = null;
  let root = null;

  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    jest.clearAllMocks();

    mockUser = {
      role: "owner",
      permissions: { access_finance: true },
    };

    api.get.mockImplementation((url) => {
      if (url === "/admin/wage-policies") {
        return Promise.resolve({
          data: {
            production: {
              default_wage_per_unit_le: null,
              unusual_amount_threshold_le: null,
              max_wage_per_unit_le: null,
              enabled: false,
              is_configured: false,
            },
            delivery: {
              base_wage_per_order_le: 50.0,
              unusual_amount_threshold_le: 100.0,
              max_helper_wage_per_order_le: 500.0,
              enabled: true,
              is_configured: true,
              currency: "EGP",
            },
            material_purchase: {
              default_wage_per_purchase_le: 50.0,
              unusual_amount_threshold_le: 100.0,
              max_wage_per_purchase_le: 300.0,
              max_buyers: 5,
              enabled: true,
              is_configured: true,
            },
            admin: {
              default_wage_per_order_le: null,
              default_recipient_id: null,
              default_recipient_name: null,
              unusual_amount_threshold_le: null,
              max_wage_per_order_le: null,
              enabled: false,
              is_configured: false,
            },
          },
        });
      }
      if (url.includes("/history")) {
        return Promise.resolve({
          data: [
            {
              _id: "hist_prod_1",
              action: "update_production_wage_policy",
              performed_by_name: "Owner Boss",
              timestamp: "2026-10-25T10:00:00Z",
              metadata: {
                change_reason: "Penyesuaian tarif akhir tahun",
                new: { default_wage_per_unit_le: 75.0, unusual_amount_threshold_le: 150.0, max_wage_per_unit_le: 400.0 },
                previous: { default_wage_per_unit_le: 60.0 },
                changed_fields: ["default_wage_per_unit_le"],
              },
            },
          ],
        });
      }
      if (url === "/admin/workers") {
        return Promise.resolve({
          data: [
            { id: "worker_1", name: "Joko Supriyanto", role: "employee" },
            { id: "admin_1", name: "Sarah Administrasi", role: "admin" },
          ],
        });
      }
      return Promise.reject(new Error(`Unhandled GET url: ${url}`));
    });

    api.put.mockResolvedValue({
      data: { is_configured: true },
    });
  });

  afterEach(() => {
    act(() => {
      if (root) root.unmount();
    });
    if (container && container.parentNode) {
      container.parentNode.removeChild(container);
    }
    container = null;
    root = null;
  });

  test("1. Renders all 4 category tabs and shows unconfigured warning for unconfigured policies", async () => {
    await act(async () => {
      root.render(<AdminWageSettings defaultTab="production" />);
    });

    expect(container.textContent).toContain("Pengaturan Upah");
    expect(container.textContent).toContain("Upah Produksi");
    expect(container.textContent).toContain("Upah Pengiriman");
    expect(container.textContent).toContain("Upah Belanja Bahan");
    expect(container.textContent).toContain("Upah Admin");

    // Unconfigured status badge & notice for production
    expect(container.textContent).toContain("Belum Dikonfigurasi");
    expect(container.textContent).toContain("Tarif dasar dan batas atas upah produksi belum ditetapkan");
  });

  test("2. Tab switching navigates cleanly between categories", async () => {
    await act(async () => {
      root.render(<AdminWageSettings defaultTab="production" />);
    });

    // Switch to delivery tab
    const deliveryTabBtn = Array.from(container.querySelectorAll("button")).find(
      (b) => b.textContent.includes("Upah Pengiriman")
    );
    expect(deliveryTabBtn).not.toBeNull();

    await act(async () => {
      deliveryTabBtn.click();
    });

    expect(container.textContent).toContain("Tarif Dasar Upah per Pesanan (EGP)");
    expect(container.textContent).toContain("Batas Konfirmasi Nominal (EGP)");
    expect(container.textContent).toContain("Batas Maksimum Keras (EGP)");

    // Switch to material purchase tab
    const materialTabBtn = Array.from(container.querySelectorAll("button")).find(
      (b) => b.textContent.includes("Upah Belanja Bahan")
    );
    await act(async () => {
      materialTabBtn.click();
    });

    expect(container.textContent).toContain("Tarif Dasar per Belanja (EGP)");
    expect(container.textContent).toContain("Maksimum Pembeli (Orang)");

    // Switch to admin wage tab
    const adminTabBtn = Array.from(container.querySelectorAll("button")).find(
      (b) => b.textContent.includes("Upah Admin")
    );
    await act(async () => {
      adminTabBtn.click();
    });

    expect(container.textContent).toContain("Tarif Upah per Pesanan (EGP)");
    expect(container.textContent).toContain("Penerima Default (Akun Tim)");
    expect(container.textContent).toContain("Sarah Administrasi (admin)");
  });

  test("3. Owner can configure and save Production Wage Policy with mandatory reason", async () => {
    await act(async () => {
      root.render(<AdminWageSettings defaultTab="production" />);
    });

    const inputs = container.querySelectorAll("input[type='number']");
    expect(inputs.length).toBeGreaterThanOrEqual(3);

    const baseInput = inputs[0];
    const threshInput = inputs[1];
    const capInput = inputs[2];

    const reasonTextarea = container.querySelector("textarea[name='change_reason']");
    expect(reasonTextarea).not.toBeNull();

    await act(async () => {
      const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
      nativeSetter.call(baseInput, "75");
      baseInput.dispatchEvent(new Event("change", { bubbles: true }));

      nativeSetter.call(threshInput, "150");
      threshInput.dispatchEvent(new Event("change", { bubbles: true }));

      nativeSetter.call(capInput, "400");
      capInput.dispatchEvent(new Event("change", { bubbles: true }));

      const areaSetter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, "value").set;
      areaSetter.call(reasonTextarea, "Penyesuaian tarif produksi baru");
      reasonTextarea.dispatchEvent(new Event("change", { bubbles: true }));
    });

    const saveBtn = Array.from(container.querySelectorAll("button")).find(
      (b) => b.textContent.includes("Simpan Pengaturan Upah Produksi")
    );
    expect(saveBtn).not.toBeNull();

    await act(async () => {
      saveBtn.click();
    });

    expect(api.put).toHaveBeenCalledWith(
      "/admin/wage-policies/production",
      expect.objectContaining({
        default_wage_per_unit_le: 75,
        unusual_amount_threshold_le: 150,
        max_wage_per_unit_le: 400,
        change_reason: "Penyesuaian tarif produksi baru",
      })
    );
  });

  test("4. Owner can configure and save Admin Wage Policy with default recipient and reason", async () => {
    await act(async () => {
      root.render(<AdminWageSettings defaultTab="admin" />);
    });

    const inputs = container.querySelectorAll("input[type='number']");
    const wageInput = inputs[0];
    const threshInput = inputs[1];
    const capInput = inputs[2];

    const select = container.querySelector("select");
    expect(select).not.toBeNull();

    const reasonTextarea = container.querySelector("textarea[name='change_reason']");
    expect(reasonTextarea).not.toBeNull();

    await act(async () => {
      const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
      nativeSetter.call(wageInput, "25");
      wageInput.dispatchEvent(new Event("change", { bubbles: true }));

      nativeSetter.call(threshInput, "50");
      threshInput.dispatchEvent(new Event("change", { bubbles: true }));

      nativeSetter.call(capInput, "150");
      capInput.dispatchEvent(new Event("change", { bubbles: true }));

      const selectSetter = Object.getOwnPropertyDescriptor(window.HTMLSelectElement.prototype, "value").set;
      selectSetter.call(select, "admin_1");
      select.dispatchEvent(new Event("change", { bubbles: true }));

      const areaSetter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, "value").set;
      areaSetter.call(reasonTextarea, "Penyesuaian penerima default upah admin");
      reasonTextarea.dispatchEvent(new Event("change", { bubbles: true }));
    });

    const saveBtn = Array.from(container.querySelectorAll("button")).find(
      (b) => b.textContent.includes("Simpan Pengaturan Upah Admin")
    );
    expect(saveBtn).not.toBeNull();

    await act(async () => {
      saveBtn.click();
    });

    expect(api.put).toHaveBeenCalledWith(
      "/admin/wage-policies/admin",
      expect.objectContaining({
        default_wage_per_order_le: 25,
        default_recipient_id: "admin_1",
        unusual_amount_threshold_le: 50,
        max_wage_per_order_le: 150,
        change_reason: "Penyesuaian penerima default upah admin",
      })
    );
  });

  test("5. Non-owner (Finance user) sees read-only mode and cannot save", async () => {
    mockUser = {
      role: "manager",
      permissions: { access_finance: true },
    };

    await act(async () => {
      root.render(<AdminWageSettings defaultTab="production" />);
    });

    expect(container.textContent).toContain("Mode Baca Saja (Tim Keuangan)");
    const saveBtn = Array.from(container.querySelectorAll("button")).find(
      (b) => b.textContent.includes("Simpan Pengaturan Upah Produksi")
    );
    expect(saveBtn).toBeUndefined();

    const inputs = container.querySelectorAll("input[type='number']");
    for (const inp of inputs) {
      expect(inp.disabled).toBe(true);
    }
  });

  test("6. User without access_finance permission is restricted", async () => {
    mockUser = {
      role: "employee",
      permissions: { access_finance: false },
    };

    await act(async () => {
      root.render(<AdminWageSettings defaultTab="production" />);
    });

    expect(container.textContent).toContain("Akses Terbatas");
    expect(container.textContent).toContain("Halaman ini hanya dapat diakses oleh Owner atau Administrator Keuangan");
  });

  test("7. Production Wage Simulator calculates exact piastres and quick quantity buttons update results", async () => {
    await act(async () => {
      root.render(<AdminWageSettings defaultTab="production" />);
    });

    expect(container.textContent).toContain("Simulator Distribusi Upah Produksi & Uji Ambang Batas");
    expect(container.textContent).toContain("Simulasi ini hanya untuk estimasi");

    // Quick quantity button: click "25"
    const btn25 = Array.from(container.querySelectorAll("button")).find((b) => b.textContent === "25");
    expect(btn25).not.toBeUndefined();

    await act(async () => {
      btn25.click();
    });

    // 25 units @ 75 EGP = 1.875 EGP (187500 piastres)
    expect(container.textContent).toContain("1.875 EGP");
    expect(container.textContent).toContain("187500 piastre");
    expect(container.textContent).toContain("100% Eksak");
  });

  test("8. Semantic No-Op detection prevents false API call and notifies user", async () => {
    await act(async () => {
      root.render(<AdminWageSettings defaultTab="delivery" />);
    });

    // In delivery tab, loaded policy is already 50, 100, 500, enabled: true.
    // Click save without changing any value
    const saveBtn = Array.from(container.querySelectorAll("button")).find(
      (b) => b.textContent.includes("Simpan Pengaturan Upah")
    );
    expect(saveBtn).not.toBeNull();

    await act(async () => {
      saveBtn.click();
    });

    expect(api.put).not.toHaveBeenCalled();
    expect(mockToast.info).toHaveBeenCalledWith("Tidak ada perubahan konfigurasi terdeteksi.");
  });

  test("9. Mandatory change reason validation rejects empty reason on genuine changes", async () => {
    await act(async () => {
      root.render(<AdminWageSettings defaultTab="production" />);
    });

    const inputs = container.querySelectorAll("input[type='number']");
    const baseInput = inputs[0];
    const threshInput = inputs[1];
    const capInput = inputs[2];

    await act(async () => {
      const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
      nativeSetter.call(baseInput, "80");
      baseInput.dispatchEvent(new Event("change", { bubbles: true }));

      nativeSetter.call(threshInput, "160");
      threshInput.dispatchEvent(new Event("change", { bubbles: true }));

      nativeSetter.call(capInput, "450");
      capInput.dispatchEvent(new Event("change", { bubbles: true }));
    });

    const saveBtn = Array.from(container.querySelectorAll("button")).find(
      (b) => b.textContent.includes("Simpan Pengaturan Upah Produksi")
    );

    // Save with empty reason
    await act(async () => {
      saveBtn.click();
    });

    expect(api.put).not.toHaveBeenCalled();
    expect(mockToast.error).toHaveBeenCalledWith("Alasan perubahan kebijakan wajib diisi minimal 3 karakter.");
  });

  test("10. Material Purchasing Simulator calculates exact integer allocations across buyers", async () => {
    await act(async () => {
      root.render(<AdminWageSettings defaultTab="material_purchase" />);
    });

    expect(container.textContent).toContain("Simulator Distribusi Upah Belanja Bahan & Uji Ambang Batas");
    expect(container.textContent).toContain("50 EGP");
    expect(container.textContent).toContain("5000 piastre");
    expect(container.textContent).toContain("100% Eksak");
  });

  test("11. Admin Wage Simulator supports Scenario A volume split and Scenario B effective date", async () => {
    await act(async () => {
      root.render(<AdminWageSettings defaultTab="admin" />);
    });

    expect(container.textContent).toContain("Simulator Akumulasi Upah Admin & Transisi Penerima");
    expect(container.textContent).toContain("Skenario A: Pembagian Volume Antar Penerima");

    // Check Scenario A calculation
    expect(container.textContent).toContain("Penerima 1 (Admin Sebelumnya)");
    expect(container.textContent).toContain("Penerima 2 (Admin Baru / Pengganti)");

    // Switch to Scenario B
    const scenarioBBtn = Array.from(container.querySelectorAll("button")).find(
      (b) => b.textContent.includes("Skenario B")
    );
    expect(scenarioBBtn).not.toBeNull();

    await act(async () => {
      scenarioBBtn.click();
    });

    expect(container.textContent).toContain("Tanggal Efektif Transisi");
    expect(container.textContent).toContain("Catatan Keterbatasan Historis");
    expect(container.textContent).toContain("Hasil Proyeksi Transisi Tanggal Efektif");
  });

  test("12. Category-Scoped Audit History displays actor, timestamp, reason, and diffs", async () => {
    await act(async () => {
      root.render(<AdminWageSettings defaultTab="production" />);
    });

    expect(container.textContent).toContain("Riwayat Kebijakan & Audit Upah — Upah Produksi");
    expect(container.textContent).toContain("Owner Boss");
    expect(container.textContent).toContain("Penyesuaian tarif akhir tahun");
    expect(container.textContent).toContain("Dasar: 75 LE");
  });
});
