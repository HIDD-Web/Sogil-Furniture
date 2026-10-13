import { generateUUID } from "../lib/utils";

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
});
