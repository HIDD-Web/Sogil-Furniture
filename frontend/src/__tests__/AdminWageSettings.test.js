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
};
jest.mock("sonner", () => ({
  toast: {
    success: (...args) => mockToast.success(...args),
    error: (...args) => mockToast.error(...args),
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
              default_wage_per_purchase_le: null,
              unusual_amount_threshold_le: null,
              max_wage_per_purchase_le: null,
              max_buyers: 5,
              enabled: false,
              is_configured: false,
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
      if (url === "/admin/delivery-wage-policy/history") {
        return Promise.resolve({
          data: [],
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

  test("3. Owner can configure and save Production Wage Policy", async () => {
    await act(async () => {
      root.render(<AdminWageSettings defaultTab="production" />);
    });

    const inputs = container.querySelectorAll("input[type='number']");
    expect(inputs.length).toBeGreaterThanOrEqual(3);

    const baseInput = inputs[0];
    const threshInput = inputs[1];
    const capInput = inputs[2];

    await act(async () => {
      const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
      nativeSetter.call(baseInput, "75");
      baseInput.dispatchEvent(new Event("change", { bubbles: true }));

      nativeSetter.call(threshInput, "150");
      threshInput.dispatchEvent(new Event("change", { bubbles: true }));

      nativeSetter.call(capInput, "400");
      capInput.dispatchEvent(new Event("change", { bubbles: true }));
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
      })
    );
  });

  test("4. Owner can configure and save Admin Wage Policy with default recipient", async () => {
    await act(async () => {
      root.render(<AdminWageSettings defaultTab="admin" />);
    });

    const inputs = container.querySelectorAll("input[type='number']");
    const wageInput = inputs[0];
    const threshInput = inputs[1];
    const capInput = inputs[2];

    const select = container.querySelector("select");
    expect(select).not.toBeNull();

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
});
