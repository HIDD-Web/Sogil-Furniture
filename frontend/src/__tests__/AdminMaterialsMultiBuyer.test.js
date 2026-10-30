import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { calculatePiastreAllocations } from "../pages/admin/AdminMaterials";

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
    useLocation: () => ({ pathname: "/admin/materials" }),
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
  permissions: { modify_products: true, access_finance: true },
};
jest.mock("../context/AuthContext", () => ({
  useAuth: () => ({ user: mockUser }),
}));

import api from "../lib/api";
jest.mock("../lib/api");

import AdminMaterials from "../pages/admin/AdminMaterials";

describe("Phase 10: Multi-Buyer Material Purchase Wages Frontend Suite", () => {
  let container = null;
  let root = null;

  const mockWorkers = [
    { id: "worker_1", name: "Ahmad Tukang", role: "Tukang Kayu", status: "active" },
    { id: "worker_2", name: "Budi Tukang", role: "Tukang Potong", status: "active" },
    { id: "worker_3", name: "Citra Tukang", role: "Tukang Amplas", status: "active" },
    { id: "worker_4", name: "Dedi Tukang", role: "Tukang Cat", status: "active" },
  ];

  const mockActivePolicy = {
    policy_type: "material_purchase",
    is_configured: true,
    enabled: true,
    default_wage_per_purchase_le: 100,
    max_buyers: 3,
    unusual_amount_threshold_le: 200,
    max_wage_per_purchase_le: 300,
    currency: "EGP",
    rounding_policy: "piastre_round_half_up",
  };

  const mockMaterials = [
    {
      id: "mat_1",
      name: "Kayu Jati Solid",
      specs: "10x10 x 400 cm",
      unit: "batang",
      current_stock: 15,
      latest_price: 500,
      latest_currency: "EGP",
      status: "active",
    },
  ];

  const mockPurchases = [
    {
      id: "pb_1",
      purchase_number: "PB-202610-0001",
      material_id: "mat_1",
      material_name: "Kayu Jati Solid",
      quantity: 5,
      unit_price: 500,
      total_amount: 2500,
      currency: "EGP",
      purchase_date: "2026-10-30",
      supplier_name: "Toko Kayu Barokah",
      buyer_wage_amount: 100,
      buyer_worker_name: "Ahmad Tukang, Budi Tukang",
      buyer_workers: [
        { worker_id: "worker_1", name: "Ahmad Tukang", allocated_amount_le: "50.00" },
        { worker_id: "worker_2", name: "Budi Tukang", allocated_amount_le: "50.00" },
      ],
      is_void: false,
    },
  ];

  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    jest.clearAllMocks();

    api.get.mockImplementation((url) => {
      if (url === "/admin/wage-policies/material_purchase") {
        return Promise.resolve({ data: mockActivePolicy });
      }
      if (url === "/admin/materials") {
        return Promise.resolve({ data: mockMaterials });
      }
      if (url === "/admin/materials/purchases") {
        return Promise.resolve({ data: mockPurchases });
      }
      if (url === "/admin/materials/stock-summary") {
        return Promise.resolve({ data: { total_items: 1, total_stock_value_le: 7500 } });
      }
      if (url === "/admin/materials/transformations") {
        return Promise.resolve({ data: [] });
      }
      if (url === "/admin/workers") {
        return Promise.resolve({ data: mockWorkers });
      }
      if (url === "/admin/settings") {
        return Promise.resolve({ data: { exchange_rate_idr_per_le: 357 } });
      }
      return Promise.resolve({ data: {} });
    });
  });

  afterEach(() => {
    if (root) {
      act(() => {
        root.unmount();
      });
    }
    if (container && container.parentNode) {
      container.parentNode.removeChild(container);
    }
  });

  describe("1. calculatePiastreAllocations algorithm tests", () => {
    test("divides 100 LE across 1 buyer with zero remainder", () => {
      const res = calculatePiastreAllocations(100, 1);
      expect(res.list).toHaveLength(1);
      expect(res.list[0].amount_le).toBe("100.00");
      expect(res.list[0].piastres).toBe(10000);
      expect(res.checksum).toBe(10000);
    });

    test("divides 100 LE across 2 buyers equally (50.00 LE each)", () => {
      const res = calculatePiastreAllocations(100, 2);
      expect(res.list).toHaveLength(2);
      expect(res.list[0].amount_le).toBe("50.00");
      expect(res.list[1].amount_le).toBe("50.00");
      expect(res.checksum).toBe(10000);
    });

    test("divides 100 LE across 3 buyers with exact integer piastres (33.34, 33.33, 33.33)", () => {
      const res = calculatePiastreAllocations(100, 3);
      expect(res.list).toHaveLength(3);
      expect(res.list[0].amount_le).toBe("33.34");
      expect(res.list[1].amount_le).toBe("33.33");
      expect(res.list[2].amount_le).toBe("33.33");
      expect(res.checksum).toBe(10000);
      const totalLE = res.list.reduce((sum, item) => sum + Number(item.amount_le), 0);
      expect(totalLE).toBe(100);
    });

    test("divides uneven 100.07 LE across 3 buyers with zero drift", () => {
      const res = calculatePiastreAllocations(100.07, 3);
      expect(res.list).toHaveLength(3);
      expect(res.list[0].amount_le).toBe("33.36");
      expect(res.list[1].amount_le).toBe("33.36");
      expect(res.list[2].amount_le).toBe("33.35");
      expect(res.checksum).toBe(10007);
      const totalLE = Number(res.list.reduce((sum, item) => sum + Number(item.amount_le), 0).toFixed(2));
      expect(totalLE).toBe(100.07);
    });

    test("handles zero or empty values gracefully", () => {
      const res = calculatePiastreAllocations(0, 3);
      expect(res.list).toHaveLength(0);
      expect(res.totalPiastres).toBe(0);
    });
  });

  describe("2. UI Rendering and Multi-Buyer Interaction", () => {
    test("loads material purchase wage policy on mount and displays multi-buyer history", async () => {
      await act(async () => {
        root.render(<AdminMaterials />);
      });

      expect(api.get).toHaveBeenCalledWith("/admin/wage-policies/material_purchase");

      // Switch to Riwayat Pembelian tab
      const purchasesTabBtn = Array.from(container.querySelectorAll("button")).find(
        (b) => b.textContent.includes("Riwayat Pembelian")
      );
      expect(purchasesTabBtn).toBeTruthy();
      await act(async () => {
        purchasesTabBtn.click();
      });

      // Multi-buyer summary rendered in table
      expect(container.textContent).toContain("Upah (100 LE - 2 Orang)");
      expect(container.textContent).toContain("Ahmad Tukang (50.00 LE)");
      expect(container.textContent).toContain("Budi Tukang (50.00 LE)");
    });

    test("opens record purchase modal, toggles wage, and allows adding up to max_buyers", async () => {
      await act(async () => {
        root.render(<AdminMaterials />);
      });

      // Find 'Catat Pembelian' button
      const recordBtn = Array.from(container.querySelectorAll("button")).find(
        (b) => b.textContent.includes("Catat Pembelian")
      );
      expect(recordBtn).toBeTruthy();

      await act(async () => {
        recordBtn.click();
      });

      // Check modal open
      expect(container.textContent).toContain("Catat Pembelian Bahan");

      // Check policy badge
      expect(container.textContent).toContain("Maks 3 Pembeli");

      // Find checkbox to enable wage
      const enableWageCb = container.querySelector('[data-testid="purchase-form-enable-wage"]');
      expect(enableWageCb).toBeTruthy();
      expect(enableWageCb.checked).toBe(false);

      // Check it
      await act(async () => {
        enableWageCb.click();
      });
      expect(enableWageCb.checked).toBe(true);

      // Nominal default filled from policy (100 LE)
      const wageInput = container.querySelector('[data-testid="purchase-form-buyer-wage-amount"]');
      expect(wageInput.value).toBe("100");

      // Initially 1 buyer row
      expect(container.textContent).toContain("Pembeli #1");
      expect(container.textContent).not.toContain("Pembeli #2");

      // Add buyer button exists
      const addBuyerBtn = container.querySelector('[data-testid="purchase-form-add-buyer"]');
      expect(addBuyerBtn).toBeTruthy();

      // Click add buyer (buyer #2)
      await act(async () => {
        addBuyerBtn.click();
      });
      expect(container.textContent).toContain("Pembeli #2");

      // Click add buyer again (buyer #3)
      await act(async () => {
        addBuyerBtn.click();
      });
      expect(container.textContent).toContain("Pembeli #3");

      // Now at max_buyers (3): Add button should be hidden
      const addBuyerBtnAfterMax = container.querySelector('[data-testid="purchase-form-add-buyer"]');
      expect(addBuyerBtnAfterMax).toBeNull();
    });

    test("shows hard cap warning when nominal exceeds max_wage_per_purchase_le (300 LE)", async () => {
      await act(async () => {
        root.render(<AdminMaterials />);
      });

      const recordBtn = Array.from(container.querySelectorAll("button")).find(
        (b) => b.textContent.includes("Catat Pembelian")
      );
      await act(async () => {
        recordBtn.click();
      });

      const enableWageCb = container.querySelector('[data-testid="purchase-form-enable-wage"]');
      await act(async () => {
        enableWageCb.click();
      });

      const wageInput = container.querySelector('[data-testid="purchase-form-buyer-wage-amount"]');
      await act(async () => {
        const nativeInputSetter = Object.getOwnPropertyDescriptor(
          window.HTMLInputElement.prototype,
          "value"
        ).set;
        nativeInputSetter.call(wageInput, "350");
        wageInput.dispatchEvent(new Event("input", { bubbles: true }));
        wageInput.dispatchEvent(new Event("change", { bubbles: true }));
      });

      expect(container.textContent).toContain("Melebihi batas maksimum keras (300 LE)");
    });

    test("shows confirmation checkbox and notes when nominal exceeds threshold (200 LE)", async () => {
      await act(async () => {
        root.render(<AdminMaterials />);
      });

      const recordBtn = Array.from(container.querySelectorAll("button")).find(
        (b) => b.textContent.includes("Catat Pembelian")
      );
      await act(async () => {
        recordBtn.click();
      });

      const enableWageCb = container.querySelector('[data-testid="purchase-form-enable-wage"]');
      await act(async () => {
        enableWageCb.click();
      });

      const wageInput = container.querySelector('[data-testid="purchase-form-buyer-wage-amount"]');
      await act(async () => {
        const nativeInputSetter = Object.getOwnPropertyDescriptor(
          window.HTMLInputElement.prototype,
          "value"
        ).set;
        nativeInputSetter.call(wageInput, "250");
        wageInput.dispatchEvent(new Event("input", { bubbles: true }));
        wageInput.dispatchEvent(new Event("change", { bubbles: true }));
      });

      // Warning appears
      expect(container.textContent).toContain("melebihi batas konfirmasi (200 LE)");
      const confirmCb = container.querySelector('[data-testid="purchase-form-confirm-unusual"]');
      expect(confirmCb).toBeTruthy();
      const notesInput = container.querySelector('[data-testid="purchase-form-buyer-wage-notes"]');
      expect(notesInput).toBeTruthy();
    });

    test("displays informational alert when policy is inactive", async () => {
      api.get.mockImplementation((url) => {
        if (url === "/admin/wage-policies/material_purchase") {
          return Promise.resolve({ data: { ...mockActivePolicy, enabled: false } });
        }
        if (url === "/admin/materials") return Promise.resolve({ data: mockMaterials });
        if (url === "/admin/materials/purchases") return Promise.resolve({ data: [] });
        if (url === "/admin/materials/stock-summary") return Promise.resolve({ data: {} });
        if (url === "/admin/materials/transformations") return Promise.resolve({ data: [] });
        if (url === "/admin/workers") return Promise.resolve({ data: mockWorkers });
        if (url === "/admin/settings") return Promise.resolve({ data: {} });
        return Promise.resolve({ data: {} });
      });

      await act(async () => {
        root.render(<AdminMaterials />);
      });

      const recordBtn = Array.from(container.querySelectorAll("button")).find(
        (b) => b.textContent.includes("Catat Pembelian")
      );
      await act(async () => {
        recordBtn.click();
      });

      expect(container.textContent).toContain("Kebijakan Upah Belanja Bahan Dinonaktifkan");
      expect(container.querySelector('[data-testid="purchase-form-enable-wage"]')).toBeNull();
    });
  });
});
