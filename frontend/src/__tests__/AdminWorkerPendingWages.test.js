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
    useLocation: () => ({ pathname: "/admin/wages/pending" }),
    NavLink: ({ children, to, className, ...props }) => (
      <a href={to} className={typeof className === "function" ? className({ isActive: false }) : className} {...props}>
        {children}
      </a>
    ),
    Link: ({ children, to, ...props }) => (
      <a href={to} {...props}>
        {children}
      </a>
    ),
  }),
  { virtual: true }
);

global.IS_REACT_ACT_ENVIRONMENT = true;

jest.mock("sonner", () => ({
  toast: {
    success: jest.fn(),
    error: jest.fn(),
  },
}));

import api from "../lib/api";
jest.mock("../lib/api");

import AdminWorkerPendingWages, { generateUUID } from "../pages/admin/AdminWorkerPendingWages";

describe("AdminWorkerPendingWages - Unit & Component Mount Tests", () => {
  let container = null;
  let root = null;

  const mockSummary = {
    total_accrued_le: 500.0,
    total_paid_le: 200.0,
    total_pending_wages_le: 300.0,
    pending_obligations_count: 2,
    workers_summary: [
      {
        worker_id: "w_1",
        worker_name: "Ahmed Tukang",
        total_accrued_le: 500.0,
        total_paid_le: 200.0,
        total_le: 300.0,
        count: 2,
      },
    ],
  };

  const mockObligations = [
    {
      id: "ob_1",
      obligation_number: "WOB-202610-0001",
      worker_name: "Ahmed Tukang",
      order_number: "ORD-101",
      task_category: "frame",
      pricing_basis: "per_unit",
      total_amount_le: 300.0,
      paid_amount_le: 100.0,
      remaining_amount_le: 200.0,
      status: "partially_paid",
    },
  ];

  const mockSettlements = [
    {
      id: "st_1",
      settlement_number: "WST-202610-0001",
      worker_name: "Ahmed Tukang",
      settlement_date: "2026-10-13",
      amount_le: 100.0,
      payment_method: "cash",
      status: "recorded",
    },
  ];

  const mockEmployees = [
    { id: "w_1", name: "Ahmed Tukang", role: "worker" },
  ];

  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);

    api.get.mockImplementation((url) => {
      if (url === "/admin/wages/pending-summary") {
        return Promise.resolve({ data: mockSummary });
      }
      if (url === "/admin/wage-obligations") {
        return Promise.resolve({ data: { obligations: mockObligations, total: 1 } });
      }
      if (url === "/admin/wages/settlements") {
        return Promise.resolve({ data: { settlements: mockSettlements, total: 1 } });
      }
      if (url === "/admin/employees") {
        return Promise.resolve({ data: mockEmployees });
      }
      if (url && url.includes("/pending-wages")) {
        return Promise.resolve({
          data: {
            worker_id: "w_1",
            worker_name: "Ahmed Tukang",
            total_pending_wages_le: 300.0,
            default_locked_exchange_rate: 357.0,
            obligations: [
              {
                ...mockObligations[0],
                locked_exchange_rate: 357.0,
              },
            ],
          },
        });
      }
      return Promise.resolve({ data: {} });
    });

    api.post.mockResolvedValue({
      data: { id: "st_new", settlement_number: "WST-202610-0002" },
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
    jest.clearAllMocks();
  });

  test("generateUUID generates valid RFC4122 v4 UUID", () => {
    const uuid1 = generateUUID();
    const uuid2 = generateUUID();
    expect(uuid1).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i);
    expect(uuid1).not.toEqual(uuid2);
  });

  test("mounts AdminWorkerPendingWages and renders summary cards with correct data", async () => {
    await act(async () => {
      root.render(<AdminWorkerPendingWages />);
    });

    const page = container.querySelector('[data-testid="worker-pending-wages-page"]');
    expect(page).not.toBeNull();

    const pendingCard = container.querySelector('[data-testid="total-pending-wages"]');
    expect(pendingCard).not.toBeNull();
    expect(pendingCard.textContent).toContain("300");

    const paidCard = container.querySelector('[data-testid="total-paid-wages"]');
    expect(paidCard).not.toBeNull();
    expect(paidCard.textContent).toContain("200");
  });

  test("renders workers summary table row with Bayar Upah button", async () => {
    await act(async () => {
      root.render(<AdminWorkerPendingWages />);
    });

    const row = container.querySelector('[data-testid="worker-summary-row-w_1"]');
    expect(row).not.toBeNull();
    expect(row.textContent).toContain("Ahmed Tukang");
    expect(row.textContent).toContain("300");

    const settleBtn = container.querySelector('[data-testid="settle-btn-w_1"]');
    expect(settleBtn).not.toBeNull();
    expect(settleBtn.disabled).toBe(false);
  });

  test("clicking Bayar Upah opens settlement modal with pre-filled pending amount", async () => {
    await act(async () => {
      root.render(<AdminWorkerPendingWages />);
    });

    const settleBtn = container.querySelector('[data-testid="settle-btn-w_1"]');
    await act(async () => {
      settleBtn.click();
    });

    const modal = container.querySelector('[data-testid="settle-wage-modal"]');
    expect(modal).not.toBeNull();

    const amountInput = container.querySelector('[data-testid="settle-amount-input"]');
    expect(amountInput).not.toBeNull();
    expect(amountInput.value).toBe("300");
  });

  test("submitting settlement sends correct payload and prevents double-click", async () => {
    await act(async () => {
      root.render(<AdminWorkerPendingWages />);
    });

    const settleBtn = container.querySelector('[data-testid="settle-btn-w_1"]');
    await act(async () => {
      settleBtn.click();
    });

    const submitBtn = container.querySelector('[data-testid="submit-settle-btn"]');
    expect(submitBtn).not.toBeNull();

    await act(async () => {
      submitBtn.click();
    });

    expect(api.post).toHaveBeenCalledWith(
      "/admin/wages/settlements",
      expect.objectContaining({
        worker_id: "w_1",
        amount_le: 300,
        payment_method: "cash",
        idempotency_key: expect.any(String),
      })
    );
  });

  test("settlement detail modal shows administrative warning and submits void", async () => {
    window.confirm = jest.fn(() => true);

    await act(async () => {
      root.render(<AdminWorkerPendingWages />);
    });

    const stTabBtn = container.querySelector('[data-testid="tab-settlements"]');
    await act(async () => {
      stTabBtn.click();
    });

    const viewDetailBtn = container.querySelector('[data-testid="settlement-row-st_1"] button');
    expect(viewDetailBtn).not.toBeNull();
    await act(async () => {
      viewDetailBtn.click();
    });

    const detailModal = container.querySelector('[data-testid="settlement-detail-modal"]');
    expect(detailModal).not.toBeNull();
    expect(detailModal.textContent).toContain("Batalkan Pembayaran Upah (Administratif)");
    expect(detailModal.textContent).toContain("Pembatalan ini membatalkan pencatatan pengeluaran kas di buku besar");

    const reasonInput = container.querySelector('[data-testid="void-reason-input"]');
    expect(reasonInput).not.toBeNull();
    await act(async () => {
      const nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
      nativeInputValueSetter.call(reasonInput, "Salah input nominal");
      reasonInput.dispatchEvent(new Event("change", { bubbles: true }));
    });

    const voidBtn = container.querySelector('[data-testid="confirm-void-btn"]');
    expect(voidBtn).not.toBeNull();
    await act(async () => {
      voidBtn.click();
    });

    expect(window.confirm).toHaveBeenCalledWith(
      expect.stringContaining("PERINGATAN: Tindakan ini membatalkan pencatatan pengeluaran kas di buku besar")
    );
    expect(api.post).toHaveBeenCalledWith(
      "/admin/wages/settlements/st_1/void",
      { reason: "Salah input nominal" }
    );
  });

  test("settling in IDR displays locked exchange rate and calculates payout", async () => {
    await act(async () => {
      root.render(<AdminWorkerPendingWages />);
    });

    const settleBtn = container.querySelector('[data-testid="settle-btn-w_1"]');
    await act(async () => {
      settleBtn.click();
    });

    const idrBtn = container.querySelector('[data-testid="settle-currency-idr-btn"]');
    expect(idrBtn).not.toBeNull();

    await act(async () => {
      idrBtn.click();
    });

    const lockedRateDisplay = container.querySelector('[data-testid="locked-rate-display"]');
    expect(lockedRateDisplay).not.toBeNull();
    expect(lockedRateDisplay.textContent).toContain("357");

    const estimatedPayout = container.querySelector('[data-testid="estimated-idr-payout"]');
    expect(estimatedPayout).not.toBeNull();
    expect(estimatedPayout.textContent).toContain("107.100");

    const submitBtn = container.querySelector('[data-testid="submit-settle-btn"]');
    await act(async () => {
      submitBtn.click();
    });

    expect(api.post).toHaveBeenCalledWith(
      "/admin/wages/settlements",
      expect.objectContaining({
        worker_id: "w_1",
        amount_le: 300,
        payment_currency: "IDR",
        settlement_rate: 357,
        is_rate_override: false,
        payment_method: "bank_transfer",
      })
    );
  });

  test("submitting IDR settlement with rate override sends override reason and new rate", async () => {
    await act(async () => {
      root.render(<AdminWorkerPendingWages />);
    });

    const settleBtn = container.querySelector('[data-testid="settle-btn-w_1"]');
    await act(async () => {
      settleBtn.click();
    });

    const idrBtn = container.querySelector('[data-testid="settle-currency-idr-btn"]');
    await act(async () => {
      idrBtn.click();
    });

    const overrideToggle = container.querySelector('[data-testid="rate-override-toggle"]');
    expect(overrideToggle).not.toBeNull();
    await act(async () => {
      overrideToggle.click();
    });

    const rateInput = container.querySelector('[data-testid="settle-override-rate-input"]');
    const reasonInput = container.querySelector('[data-testid="settle-override-reason-input"]');
    expect(rateInput).not.toBeNull();
    expect(reasonInput).not.toBeNull();

    await act(async () => {
      const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
      nativeSetter.call(rateInput, "365");
      rateInput.dispatchEvent(new Event("change", { bubbles: true }));
      rateInput.dispatchEvent(new Event("input", { bubbles: true }));

      nativeSetter.call(reasonInput, "Penyesuaian kurs BCA");
      reasonInput.dispatchEvent(new Event("change", { bubbles: true }));
      reasonInput.dispatchEvent(new Event("input", { bubbles: true }));
    });

    const submitBtn = container.querySelector('[data-testid="submit-settle-btn"]');
    await act(async () => {
      submitBtn.click();
    });

    expect(api.post).toHaveBeenCalledWith(
      "/admin/wages/settlements",
      expect.objectContaining({
        worker_id: "w_1",
        amount_le: 300,
        payment_currency: "IDR",
        settlement_rate: 365,
        is_rate_override: true,
        override_reason: "Penyesuaian kurs BCA",
      })
    );
  });

  test("customizing actual IDR payout displays variance warning and sends actual_payout_amount", async () => {
    await act(async () => {
      root.render(<AdminWorkerPendingWages />);
    });

    const settleBtn = container.querySelector('[data-testid="settle-btn-w_1"]');
    await act(async () => {
      settleBtn.click();
    });

    const idrBtn = container.querySelector('[data-testid="settle-currency-idr-btn"]');
    await act(async () => {
      idrBtn.click();
    });

    const customPayoutToggle = container.querySelector('[data-testid="custom-payout-toggle"]');
    expect(customPayoutToggle).not.toBeNull();
    await act(async () => {
      customPayoutToggle.click();
    });

    const actualPayoutInput = container.querySelector('[data-testid="settle-actual-payout-input"]');
    expect(actualPayoutInput).not.toBeNull();
    expect(actualPayoutInput.value).toBe("107100");

    // Edit to 108000 (+900 variance)
    await act(async () => {
      const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
      nativeSetter.call(actualPayoutInput, "108000");
      actualPayoutInput.dispatchEvent(new Event("change", { bubbles: true }));
      actualPayoutInput.dispatchEvent(new Event("input", { bubbles: true }));
    });

    const varianceWarning = container.querySelector('[data-testid="payout-variance-warning"]');
    expect(varianceWarning).not.toBeNull();
    expect(varianceWarning.textContent).toContain("+Rp 900");
    expect(varianceWarning.textContent).toContain("300 LE");

    // Provide note for variance
    const notesInput = container.querySelector('[data-testid="settle-notes-input"]');
    await act(async () => {
      const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, "value").set;
      nativeSetter.call(notesInput, "Pembulatan transfer bank");
      notesInput.dispatchEvent(new Event("change", { bubbles: true }));
      notesInput.dispatchEvent(new Event("input", { bubbles: true }));
    });

    const submitBtn = container.querySelector('[data-testid="submit-settle-btn"]');
    await act(async () => {
      submitBtn.click();
    });

    expect(api.post).toHaveBeenCalledWith(
      "/admin/wages/settlements",
      expect.objectContaining({
        worker_id: "w_1",
        amount_le: 300,
        payment_currency: "IDR",
        actual_payout_amount: 108000,
        notes: "Pembulatan transfer bank",
      })
    );
  });

  test("settlement detail modal renders IDR payout amount, exchange rate, and variance notice", async () => {
    const mockIdrSettlements = [
      {
        id: "st_idr",
        settlement_number: "WST-202610-0099",
        worker_name: "Ahmed Tukang",
        settlement_date: "2026-10-15",
        amount_le: 200.0,
        payout_currency: "IDR",
        payout_amount: 72000.0,
        standard_payout_amount: 71400.0,
        variance_idr: 600.0,
        locked_exchange_rate: 357.0,
        settlement_rate: 357.0,
        is_rate_override: false,
        payment_method: "bank_transfer",
        status: "recorded",
      },
    ];

    api.get.mockImplementation((url) => {
      if (url === "/admin/wages/settlements") {
        return Promise.resolve({ data: { settlements: mockIdrSettlements, total: 1 } });
      }
      if (url === "/admin/wages/pending-summary") {
        return Promise.resolve({ data: mockSummary });
      }
      if (url === "/admin/wage-obligations") {
        return Promise.resolve({ data: { obligations: mockObligations, total: 1 } });
      }
      if (url === "/admin/employees") {
        return Promise.resolve({ data: mockEmployees });
      }
      return Promise.resolve({ data: {} });
    });

    await act(async () => {
      root.render(<AdminWorkerPendingWages />);
    });

    const stTabBtn = container.querySelector('[data-testid="tab-settlements"]');
    await act(async () => {
      stTabBtn.click();
    });

    const viewDetailBtn = container.querySelector('[data-testid="view-settlement-btn-st_idr"]');
    expect(viewDetailBtn).not.toBeNull();
    await act(async () => {
      viewDetailBtn.click();
    });

    const detailModal = container.querySelector('[data-testid="settlement-detail-modal"]');
    expect(detailModal).not.toBeNull();
    expect(detailModal.textContent).toContain("WST-202610-0099");

    const idrPayout = container.querySelector('[data-testid="detail-payout-idr"]');
    expect(idrPayout).not.toBeNull();
    expect(idrPayout.textContent).toContain("72.000");

    const varianceNotice = container.querySelector('[data-testid="detail-variance-notice"]');
    expect(varianceNotice).not.toBeNull();
    expect(varianceNotice.textContent).toContain("+Rp 600");
  });

  test("handles settlement API conflict error and displays error message without false success", async () => {
    const { toast } = require("sonner");
    toast.success.mockClear();

    await act(async () => {
      root.render(<AdminWorkerPendingWages />);
    });

    const settleBtn = container.querySelector('[data-testid="settle-btn-w_1"]');
    expect(settleBtn).not.toBeNull();
    await act(async () => {
      settleBtn.click();
    });

    const modal = container.querySelector('[data-testid="settle-wage-modal"]');
    expect(modal).not.toBeNull();

    const conflictError = Object.assign(new Error("Saldo kewajiban upah telah berubah"), {
      response: {
        status: 409,
        data: { detail: "Saldo kewajiban upah telah berubah" },
      },
      msg: "Saldo kewajiban upah telah berubah",
    });

    api.post.mockRejectedValueOnce(conflictError);

    const submitBtn = container.querySelector('[data-testid="submit-settle-btn"]');
    expect(submitBtn).not.toBeNull();

    await act(async () => {
      submitBtn.click();
    });

    // 1. Verifies api.post was called with expected settlement payload
    expect(api.post).toHaveBeenCalledWith(
      "/admin/wages/settlements",
      expect.objectContaining({
        worker_id: "w_1",
        amount_le: 300,
      })
    );

    // 2. Verifies UI does NOT falsely indicate success
    expect(toast.success).not.toHaveBeenCalled();

    // 3. Verifies error message is displayed to the user
    expect(container.textContent).toContain("Saldo kewajiban upah telah berubah");

    // 4. Verifies modal remains open for user review
    expect(container.querySelector('[data-testid="settle-wage-modal"]')).not.toBeNull();

    // 5. Verifies submit control is not permanently disabled
    expect(submitBtn.disabled).toBe(false);
  });
});
