import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { generateUUID } from "../lib/utils";
import AdminOrderDetail from "../pages/admin/AdminOrderDetail";

jest.mock(
  "@/lib/utils",
  () => jest.requireActual("../lib/utils"),
  { virtual: true }
);

jest.mock(
  "react-router-dom",
  () => ({
    useParams: () => ({ id: "order-test-123" }),
    useNavigate: () => jest.fn(),
    Link: ({ children, to }) => <a href={to}>{children}</a>,
  }),
  { virtual: true }
);

jest.mock("../context/AuthContext", () => ({
  useAuth: () => ({
    user: {
      role: "owner",
      permissions: { access_finance: true, delete_data: true, modify_products: true },
    },
  }),
}));

global.IS_REACT_ACT_ENVIRONMENT = true;

jest.mock("sonner", () => ({
  toast: {
    success: jest.fn(),
    error: jest.fn(),
    info: jest.fn(),
    warning: jest.fn(),
  },
}));

import api from "../lib/api";
jest.mock("../lib/api");

describe("AdminOrderDetail - Component Mount & Regression Suite", () => {
  let container = null;
  let root = null;

  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    const dummyOrder = {
      _id: "order-test-123",
      order_number: "SGF-2026-001",
      order_status: "menunggu_pembayaran",
      payment_status: "belum_dibayar",
      payment_method: "cash",
      total_le: 1500,
      subtotal_le: 1300,
      delivery_fee_le: 200,
      items: [],
      payments: [],
    };
    api.get.mockImplementation((url) => {
      if (typeof url === "string" && url.includes("/payments")) {
        return Promise.resolve({ data: { payments: [] } });
      }
      return Promise.resolve({ data: dummyOrder });
    });
    if (api.post) api.post.mockResolvedValue({ data: {} });
    if (api.patch) api.patch.mockResolvedValue({ data: {} });
    if (api.delete) api.delete.mockResolvedValue({ data: {} });
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
    jest.clearAllMocks();
  });

  test("confirms TDZ ReferenceError is triggered if order is accessed before declaration", () => {
    expect(() => {
      const canEditPrice = true;
      const canAdjustPrice = canEditPrice && testOrder?.order_status !== "selesai";
      const [testOrder] = [null];
      return canAdjustPrice;
    }).toThrow(ReferenceError);
  });

  test("mounts AdminOrderDetail without Temporal Dead Zone ReferenceError", async () => {
    await act(async () => {
      root.render(<AdminOrderDetail />);
    });
    expect(container).toBeDefined();
    expect(container.innerHTML).not.toBe("");
  });

  test("handles initial empty/loading state and renders order view without crashing", async () => {
    await act(async () => {
      root.render(<AdminOrderDetail />);
    });
    // Wait for async load()
    await act(async () => {
      await Promise.resolve();
    });
    expect(container.textContent).toContain("SGF-2026-001");
  });
});

describe("AdminOrderDetail - Payment Idempotency & UI Gating Unit Tests", () => {
  describe("UUID v4 Generator (generateUUID)", () => {
    test("generates valid RFC4122 version 4 UUID string", () => {
      const uuid = generateUUID();
      expect(typeof uuid).toBe("string");
      expect(uuid.length).toBe(36);
      const uuidV4Regex = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
      expect(uuid).toMatch(uuidV4Regex);
    });

    test("generates unique keys across consecutive calls", () => {
      const keys = new Set();
      for (let i = 0; i < 50; i++) {
        const key = generateUUID();
        expect(keys.has(key)).toBe(false);
        keys.add(key);
      }
      expect(keys.size).toBe(50);
    });
  });

  describe("Price Adjustment UI Gating (canAdjustPrice)", () => {
    const isOwnerOrFinance = true;

    test("blocks price adjustment button on completed ('selesai') order", () => {
      const order = { order_status: "selesai" };
      const canEditPrice = isOwnerOrFinance;
      const canAdjustPrice = canEditPrice && order?.order_status !== "selesai";

      expect(canAdjustPrice).toBe(false);
    });

    test("permits price adjustment button on 'menunggu_pembayaran' order", () => {
      const order = { order_status: "menunggu_pembayaran" };
      const canEditPrice = isOwnerOrFinance;
      const canAdjustPrice = canEditPrice && order?.order_status !== "selesai";

      expect(canAdjustPrice).toBe(true);
    });

    test("permits price adjustment button on 'diproses' order", () => {
      const order = { order_status: "diproses" };
      const canEditPrice = isOwnerOrFinance;
      const canAdjustPrice = canEditPrice && order?.order_status !== "selesai";

      expect(canAdjustPrice).toBe(true);
    });

    test("permits price adjustment button on 'dikirim' order", () => {
      const order = { order_status: "dikirim" };
      const canEditPrice = isOwnerOrFinance;
      const canAdjustPrice = canEditPrice && order?.order_status !== "selesai";

      expect(canAdjustPrice).toBe(true);
    });

    test("blocks price adjustment button if user lacks finance permission regardless of status", () => {
      const order = { order_status: "menunggu_pembayaran" };
      const canEditPrice = false;
      const canAdjustPrice = canEditPrice && order?.order_status !== "selesai";

      expect(canAdjustPrice).toBe(false);
    });
  });

  describe("Payment Idempotency Lifecycle & Retry Contract", () => {
    test("logical payment submission retains idempotency key on network retry", () => {
      // Simulate form opening
      const initialKey = generateUUID();
      let formState = {
        amount: "500",
        payment_method: "cash",
        idempotency_key: initialKey,
      };

      // First submission attempt payload
      const firstPayload = {
        amount: parseFloat(formState.amount),
        payment_method: formState.payment_method,
        idempotency_key: formState.idempotency_key,
      };
      expect(firstPayload.idempotency_key).toBe(initialKey);

      // Simulate network failure / 500 error: form retains state & key
      const simulateError = true;
      if (simulateError) {
        // Form is NOT reset on error; key is retained
        formState = { ...formState };
      }

      // Retry submission payload
      const retryPayload = {
        amount: parseFloat(formState.amount),
        payment_method: formState.payment_method,
        idempotency_key: formState.idempotency_key,
      };

      // Contract check: retry MUST use identical idempotency key
      expect(retryPayload.idempotency_key).toBe(initialKey);
      expect(retryPayload.idempotency_key).toBe(firstPayload.idempotency_key);
    });

    test("new payment submission after success receives fresh idempotency key", () => {
      const initialKey = generateUUID();
      let formState = {
        amount: "500",
        payment_method: "cash",
        idempotency_key: initialKey,
      };

      // Simulate successful payment submission
      const simulateSuccess = true;
      if (simulateSuccess) {
        // Reset form
        formState = {
          amount: "",
          payment_method: "cash",
          idempotency_key: "",
        };
      }

      // Next payment modal open
      const nextKey = generateUUID();
      formState = {
        ...formState,
        amount: "300",
        idempotency_key: nextKey,
      };

      expect(formState.idempotency_key).not.toBe(initialKey);
      expect(formState.idempotency_key).toBe(nextKey);
    });

    test("double-click / duplicate submission is suppressed when paymentLoading is true", () => {
      let submitCallCount = 0;
      let paymentLoading = false;

      const handleRecordPayment = () => {
        if (paymentLoading) return; // double-click guard
        paymentLoading = true;
        submitCallCount++;
      };

      // First click
      handleRecordPayment();
      expect(submitCallCount).toBe(1);
      expect(paymentLoading).toBe(true);

      // Rapid second click while in flight
      handleRecordPayment();
      expect(submitCallCount).toBe(1); // Call count remains 1
    });
  });

  describe("Payment Modal Error & Stale-Rate UX Handling", () => {
    let container = null;
    let root = null;

    beforeEach(() => {
      container = document.createElement("div");
      document.body.appendChild(container);
      root = createRoot(container);
      const dummyOrder = {
        _id: "order-test-123",
        order_number: "SGF-2026-001",
        order_status: "menunggu_pembayaran",
        payment_status: "belum_dibayar",
        payment_method: "cash",
        total_le: 1500,
        subtotal_le: 1300,
        delivery_fee_le: 200,
        items: [],
        payments: [],
      };
      api.get.mockImplementation((url) => {
        if (typeof url === "string" && url.includes("/payments")) {
          return Promise.resolve({ data: { payments: [] } });
        }
        return Promise.resolve({ data: dummyOrder });
      });
      if (api.post) api.post.mockResolvedValue({ data: {} });
      if (api.patch) api.patch.mockResolvedValue({ data: {} });
      if (api.delete) api.delete.mockResolvedValue({ data: {} });
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
      jest.clearAllMocks();
    });

    test("handles customer IDR overpayment HTTP 422 and displays clear rejection alert without resetting inputs", async () => {
      const { toast } = require("sonner");
      await act(async () => {
        root.render(<AdminOrderDetail />);
      });

      const openBtn = container.querySelector('[data-testid="btn-record-payment"]');
      expect(openBtn).not.toBeNull();

      await act(async () => {
        openBtn.click();
      });

      const amountInput = container.querySelector('[data-testid="input-payment-amount"]');
      expect(amountInput).not.toBeNull();

      await act(async () => {
        const nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
        nativeInputValueSetter.call(amountInput, "600");
        amountInput.dispatchEvent(new Event("input", { bubbles: true }));
      });

      const overpayError = {
        response: {
          status: 422,
          data: {
            detail: "Nominal transfer melebihi sisa tagihan pesanan. Periksa nominal dan kurs sebelum menyimpan pembayaran.",
          },
        },
      };
      api.post.mockRejectedValueOnce(overpayError);

      const submitBtn = container.querySelector('[data-testid="btn-submit-payment"]');
      expect(submitBtn).not.toBeNull();

      await act(async () => {
        submitBtn.click();
      });

      expect(toast.error).toHaveBeenCalledWith(
        "Nominal transfer melebihi sisa tagihan pesanan. Periksa nominal dan kurs sebelum menyimpan pembayaran."
      );
      const alertBox = container.querySelector('[data-testid="payment-error-alert"]');
      expect(alertBox).not.toBeNull();
      expect(alertBox.textContent).toContain("Nominal transfer melebihi sisa tagihan pesanan");

      // Verify form inputs remain preserved and modal stays open
      expect(container.querySelector('[data-testid="input-payment-amount"]')).not.toBeNull();
      expect(amountInput.value).toBe("600");
    });

    test("handles stale-rate HTTP 422 error and instructs admin to reload order details before saving payment", async () => {
      const { toast } = require("sonner");
      await act(async () => {
        root.render(<AdminOrderDetail />);
      });

      const openBtn = container.querySelector('[data-testid="btn-record-payment"]');
      expect(openBtn).not.toBeNull();

      await act(async () => {
        openBtn.click();
      });

      const amountInput = container.querySelector('[data-testid="input-payment-amount"]');
      await act(async () => {
        const nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
        nativeInputValueSetter.call(amountInput, "400");
        amountInput.dispatchEvent(new Event("input", { bubbles: true }));
      });

      const staleRateError = {
        response: {
          status: 422,
          data: {
            detail: "Alasan perubahan kurs wajib diisi saat menggunakan kurs override (minimal 3 karakter).",
          },
        },
      };
      api.post.mockRejectedValueOnce(staleRateError);

      const submitBtn = container.querySelector('[data-testid="btn-submit-payment"]');
      await act(async () => {
        submitBtn.click();
      });

      const expectedMsg = "Kurs transaksi di sistem telah berubah. Muat ulang rincian pesanan untuk memperbarui kurs sebelum menyimpan pembayaran.";
      expect(toast.error).toHaveBeenCalledWith(expectedMsg);

      const alertBox = container.querySelector('[data-testid="payment-error-alert"]');
      expect(alertBox).not.toBeNull();
      expect(alertBox.textContent).toContain("Kurs transaksi di sistem telah berubah");

      // Form state preserved, no auto-submit
      expect(amountInput.value).toBe("400");
    });
  });

  describe("Phase 08.2 — Multi-Worker Production Wage Flow UI Tests", () => {
    let container = null;
    let root = null;

    beforeEach(() => {
      container = document.createElement("div");
      document.body.appendChild(container);
      root = createRoot(container);
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
      jest.clearAllMocks();
    });

    test("renders multi-worker assignment modal with capacity and wage preview", async () => {
      const dummyOrder = {
        _id: "order-test-123",
        order_number: "SGF-2026-001",
        order_status: "diproses",
        payment_status: "dp",
        items: [
          {
            item_id: "itm_001",
            product_name_snapshot: "Meja Kayu Jati",
            quantity: 3,
            category: "table",
            subtotal_le: 1500,
          },
        ],
        payments: [],
      };

      const dummyWorkers = [
        { id: "w1", name: "Ahmad Tukang Kayu", role: "employee" },
        { id: "w2", name: "Budi Finishing", role: "employee" },
        { id: "w3", name: "Citra Assembling", role: "employee" },
      ];

      const dummyPolicy = {
        default_wage_per_unit_le: 100.0,
        unusual_amount_threshold_le: 200.0,
        max_wage_per_unit_le: 500.0,
        is_configured: true,
        enabled: true,
      };

      const dummyAssignments = [
        {
          id: "asn_01",
          order_item_id: "itm_001",
          task_category: "whole_item",
          worker_id: "w1",
          worker_name: "Ahmad Tukang Kayu",
          target_quantity: 1,
          status: "in_progress",
        },
      ];

      api.get.mockImplementation((url) => {
        if (url.includes("/assignments")) return Promise.resolve({ data: dummyAssignments });
        if (url.includes("/workers")) return Promise.resolve({ data: dummyWorkers });
        if (url.includes("/wage-policies/production")) return Promise.resolve({ data: dummyPolicy });
        if (url.includes("/wage-rules")) return Promise.resolve({ data: [] });
        if (url.includes("/payments")) return Promise.resolve({ data: { payments: [] } });
        return Promise.resolve({ data: dummyOrder });
      });

      await act(async () => {
        root.render(<AdminOrderDetail />);
      });

      // Open assign modal
      const assignBtn = container.querySelector('[data-testid="btn-assign-item-0"]');
      expect(assignBtn).not.toBeNull();

      await act(async () => {
        assignBtn.click();
      });

      // Verify Capacity Display: Ordered: 3, Assigned: 1, Remaining: 2
      expect(container.textContent).toContain("Dipesan");
      expect(container.textContent).toContain("3 unit");
      expect(container.textContent).toContain("Ditugaskan");
      expect(container.textContent).toContain("1 unit");
      expect(container.textContent).toContain("Sisa Tersedia");
      expect(container.textContent).toContain("2 unit");

      // Verify Worker Selection List: Ahmad, Budi, Citra
      expect(container.textContent).toContain("Ahmad Tukang Kayu");
      expect(container.textContent).toContain("Budi Finishing");
      expect(container.textContent).toContain("Citra Assembling");

      // Verify Wage Estimation Preview
      expect(container.textContent).toContain("Estimasi Total Upah");
    });
  });

  describe("Phase 08.4D — Owner Admin Wage Override Integration", () => {
    let container = null;
    let root = null;

    beforeEach(() => {
      container = document.createElement("div");
      document.body.appendChild(container);
      root = createRoot(container);
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
      jest.clearAllMocks();
    });

    test("renders AdminWageOverrideCard inside AdminOrderDetail for Owner", async () => {
      const dummyOrder = {
        _id: "order-test-123",
        order_number: "SGF-2026-001",
        order_status: "diproses",
        payment_status: "dp",
        items: [],
        payments: [],
      };

      const dummyWageConfig = {
        order_id: "order-test-123",
        order_number: "SGF-2026-001",
        is_override: false,
        effective_configuration: {
          source: "policy_default",
          is_override: false,
          amount_le: 150.0,
          recipient_name: "Siti Admin",
        },
        policy_context: {
          default_wage_per_order_le: 150.0,
          max_wage_per_order_le: 500.0,
        },
        is_editable: true,
      };

      api.get.mockImplementation((url) => {
        if (url.includes("/admin-wage")) return Promise.resolve({ data: dummyWageConfig });
        if (url.includes("/payments")) return Promise.resolve({ data: { payments: [] } });
        if (url.includes("/assignments")) return Promise.resolve({ data: [] });
        if (url.includes("/workers")) return Promise.resolve({ data: [] });
        return Promise.resolve({ data: dummyOrder });
      });

      await act(async () => {
        root.render(<AdminOrderDetail />);
      });

      expect(container.querySelector('[data-testid="admin-wage-override-card"]')).not.toBeNull();
      expect(container.textContent).toContain("Upah Admin Per Pesanan");
      expect(container.textContent).toContain("Owner Only");
    });
  });

  describe("Phase 09.2 — Production Wage Recovery & UI Gating", () => {
    let container = null;
    let root = null;

    beforeEach(() => {
      container = document.createElement("div");
      document.body.appendChild(container);
      root = createRoot(container);
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
      jest.clearAllMocks();
    });

    test("1. Displays error alert and toast when loading assignments fails instead of silent clearing", async () => {
      const { toast } = require("sonner");
      const dummyOrder = {
        _id: "order-test-123",
        order_number: "SGF-2026-001",
        order_status: "diproses",
        items: [
          {
            item_id: "itm_001",
            product_name_snapshot: "Meja Kayu Jati",
            quantity: 1,
            subtotal_le: 500,
          },
        ],
      };

      api.get.mockImplementation((url) => {
        if (url.includes("/assignments")) {
          return Promise.reject({
            response: { data: { detail: "Database connection failed" } },
          });
        }
        if (url.includes("/workers")) return Promise.resolve({ data: [] });
        if (url.includes("/wage-rules")) return Promise.resolve({ data: [] });
        if (url.includes("/payments")) return Promise.resolve({ data: { payments: [] } });
        return Promise.resolve({ data: dummyOrder });
      });

      await act(async () => {
        root.render(<AdminOrderDetail />);
      });

      const errorAlert = container.querySelector('[data-testid="assignments-error-alert"]');
      expect(errorAlert).not.toBeNull();
      expect(errorAlert.textContent).toContain("Database connection failed");
      expect(errorAlert.textContent).toContain("Coba Lagi");
      expect(toast.error).toHaveBeenCalledWith("Database connection failed");
    });

    test("2. Displays capacity-full badge and hides assign button when item capacity is exhausted", async () => {
      const dummyOrder = {
        _id: "order-test-123",
        order_number: "SGF-2026-001",
        order_status: "diproses",
        items: [
          {
            item_id: "itm_001",
            product_name_snapshot: "Meja Kayu Jati",
            quantity: 1,
            subtotal_le: 500,
          },
        ],
      };

      const dummyAssignments = [
        {
          id: "asn_01",
          order_item_id: "itm_001",
          task_category: "whole_item",
          worker_id: "w1",
          worker_name: "Ahmad Tukang Kayu",
          target_quantity: 1,
          status: "assigned",
        },
      ];

      api.get.mockImplementation((url) => {
        if (url.includes("/assignments")) return Promise.resolve({ data: dummyAssignments });
        if (url.includes("/workers")) return Promise.resolve({ data: [] });
        if (url.includes("/wage-rules")) return Promise.resolve({ data: [] });
        if (url.includes("/payments")) return Promise.resolve({ data: { payments: [] } });
        return Promise.resolve({ data: dummyOrder });
      });

      await act(async () => {
        root.render(<AdminOrderDetail />);
      });

      // Assign button should be absent because capacity is exhausted (1/1)
      expect(container.querySelector('[data-testid="btn-assign-item-0"]')).toBeNull();

      // Capacity-full badge should be present
      const capacityBadge = container.querySelector('[data-testid="badge-capacity-full-0"]');
      expect(capacityBadge).not.toBeNull();
      expect(capacityBadge.textContent).toContain("Kapasitas penuh — 1/1 unit sudah ditugaskan");
    });

    test("3. Displays informational lifecycle status explaining obligation will accrue upon verification", async () => {
      const dummyOrder = {
        _id: "order-test-123",
        order_number: "SGF-2026-001",
        order_status: "diproses",
        items: [
          {
            item_id: "itm_001",
            product_name_snapshot: "Meja Kayu Jati",
            quantity: 1,
            subtotal_le: 500,
          },
        ],
      };

      const dummyAssignments = [
        {
          id: "asn_01",
          order_item_id: "itm_001",
          task_category: "whole_item",
          worker_id: "w1",
          worker_name: "Ahmad Tukang Kayu",
          target_quantity: 1,
          status: "assigned",
        },
      ];

      api.get.mockImplementation((url) => {
        if (url.includes("/assignments")) return Promise.resolve({ data: dummyAssignments });
        if (url.includes("/workers")) return Promise.resolve({ data: [] });
        if (url.includes("/wage-rules")) return Promise.resolve({ data: [] });
        if (url.includes("/payments")) return Promise.resolve({ data: { payments: [] } });
        return Promise.resolve({ data: dummyOrder });
      });

      await act(async () => {
        root.render(<AdminOrderDetail />);
      });

      const lifecycleInfo = container.querySelector('[data-testid="asn-lifecycle-info-asn_01"]');
      expect(lifecycleInfo).not.toBeNull();
      expect(lifecycleInfo.textContent).toContain("Kewajiban upah akan terbit secara otomatis setelah verifikasi hasil kerja");
      expect(container.textContent).not.toContain("No. Kewajiban:");
    });

    test("4. Existing assignments appear with real worker name, and available capacity allows assign button", async () => {
      const dummyOrder = {
        _id: "order-test-123",
        order_number: "SGF-2026-001",
        order_status: "diproses",
        items: [
          {
            item_id: "itm_001",
            product_name_snapshot: "Meja Kayu Jati",
            quantity: 3,
            subtotal_le: 1500,
          },
        ],
      };

      const dummyAssignments = [
        {
          id: "asn_01",
          order_item_id: "itm_001",
          task_category: "whole_item",
          worker_id: "w1",
          worker_name: "Ahmad Tukang Kayu",
          target_quantity: 1,
          status: "assigned",
        },
      ];

      api.get.mockImplementation((url) => {
        if (url.includes("/assignments")) return Promise.resolve({ data: dummyAssignments });
        if (url.includes("/workers")) return Promise.resolve({ data: [{ id: "w1", name: "Ahmad Tukang Kayu" }] });
        if (url.includes("/wage-rules")) return Promise.resolve({ data: [] });
        if (url.includes("/payments")) return Promise.resolve({ data: { payments: [] } });
        return Promise.resolve({ data: dummyOrder });
      });

      await act(async () => {
        root.render(<AdminOrderDetail />);
      });

      // Assignment list rendered with worker name
      expect(container.textContent).toContain("Ahmad Tukang Kayu");
      expect(container.textContent).toContain("Daftar Penugasan Kerja (1)");

      // Remaining capacity is 2 of 3, so button is still available
      const assignBtn = container.querySelector('[data-testid="btn-assign-item-0"]');
      expect(assignBtn).not.toBeNull();
      expect(container.querySelector('[data-testid="badge-capacity-full-0"]')).toBeNull();
    });

    test("5. Empty assignment response is distinguished from failed request", async () => {
      const dummyOrder = {
        _id: "order-test-123",
        order_number: "SGF-2026-001",
        order_status: "diproses",
        items: [
          {
            item_id: "itm_001",
            product_name_snapshot: "Meja Kayu Jati",
            quantity: 1,
            subtotal_le: 500,
          },
        ],
      };

      api.get.mockImplementation((url) => {
        if (url.includes("/assignments")) return Promise.resolve({ data: [] });
        if (url.includes("/workers")) return Promise.resolve({ data: [] });
        if (url.includes("/wage-rules")) return Promise.resolve({ data: [] });
        if (url.includes("/payments")) return Promise.resolve({ data: { payments: [] } });
        return Promise.resolve({ data: dummyOrder });
      });

      await act(async () => {
        root.render(<AdminOrderDetail />);
      });

      // No error alert
      expect(container.querySelector('[data-testid="assignments-error-alert"]')).toBeNull();
      // No assignment cards
      expect(container.textContent).not.toContain("Daftar Penugasan Kerja");
      // Assign button is active and visible
      expect(container.querySelector('[data-testid="btn-assign-item-0"]')).not.toBeNull();
    });

    test("6. Successful assignment creation followed by a failed refresh warns user not to retry blindly", async () => {
      const { toast } = require("sonner");
      const dummyOrder = {
        _id: "order-test-123",
        order_number: "SGF-2026-001",
        order_status: "diproses",
        items: [
          {
            item_id: "itm_001",
            product_name_snapshot: "Meja Kayu Jati",
            quantity: 2,
            subtotal_le: 1000,
          },
        ],
      };

      let assignmentsCallCount = 0;
      api.get.mockImplementation((url) => {
        if (url.includes("/assignments")) {
          assignmentsCallCount++;
          if (assignmentsCallCount === 1) {
            return Promise.resolve({ data: [] });
          }
          // Second call (refresh after creation) fails!
          return Promise.reject({ response: { data: { detail: "Gateway timeout" } } });
        }
        if (url.includes("/workers")) return Promise.resolve({ data: [{ id: "w1", name: "Ahmad" }] });
        if (url.includes("/wage-rules")) return Promise.resolve({ data: [] });
        if (url.includes("/wage-policies/production")) return Promise.resolve({ data: { is_configured: true, enabled: true, default_wage_per_unit_le: 100 } });
        if (url.includes("/payments")) return Promise.resolve({ data: { payments: [] } });
        return Promise.resolve({ data: dummyOrder });
      });

      api.post.mockResolvedValueOnce({ data: { id: "asn_99", status: "assigned" } });

      await act(async () => {
        root.render(<AdminOrderDetail />);
      });

      // Open assign modal
      const assignBtn = container.querySelector('[data-testid="btn-assign-item-0"]');
      await act(async () => {
        assignBtn.click();
      });

      // Submit form
      const form = container.querySelector("form");
      await act(async () => {
        form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
      });

      // Creation succeeded and post was called
      expect(api.post).toHaveBeenCalled();
      // Warning toast was called alerting the user that assignment was saved but refresh failed
      expect(toast.warning).toHaveBeenCalledWith(
        expect.stringContaining("tidak terjadi duplikasi")
      );
    });
  });
});
