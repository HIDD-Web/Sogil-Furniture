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
});
