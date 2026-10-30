import React, { act } from "react";
import { createRoot } from "react-dom/client";

jest.mock(
  "react-router-dom",
  () => ({
    useParams: () => ({ id: "order-123" }),
    useNavigate: () => jest.fn(),
    Link: ({ children, to }) => <a href={to}>{children}</a>,
  }),
  { virtual: true }
);

import AdminOrderDetail from "../pages/admin/AdminOrderDetail";
import AdminWageOverrideCard from "../components/admin/AdminWageOverrideCard";

jest.mock(
  "@/lib/utils",
  () => jest.requireActual("../lib/utils"),
  { virtual: true }
);

let mockCurrentUser = {
  role: "owner",
  permissions: { access_finance: true, delete_data: true, modify_products: true },
};

jest.mock("../context/AuthContext", () => ({
  useAuth: () => ({
    user: mockCurrentUser,
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

describe("Phase 08.4D — Owner Admin Wage Override UI Test Suite", () => {
  let container = null;
  let root = null;

  const sampleWorkers = [
    { id: "admin_siti", _id: "admin_siti", name: "Siti Admin", role: "admin" },
    { id: "admin_budi", _id: "admin_budi", name: "Budi Staff", role: "admin" },
  ];

  const defaultPolicyContext = {
    enabled: true,
    is_configured: true,
    default_wage_per_order_le: 150.0,
    default_recipient_id: "admin_siti",
    default_recipient_name: "Siti Admin",
    unusual_amount_threshold_le: 300.0,
    max_wage_per_order_le: 500.0,
    currency: "EGP",
  };

  const defaultGetConfig = {
    order_id: "order-123",
    order_number: "SGF-2026-001",
    payment_status: "unpaid",
    is_override: false,
    saved_override: null,
    effective_configuration: {
      source: "policy_default",
      is_override: false,
      amount_le: 150.0,
      recipient_id: "admin_siti",
      recipient_name: "Siti Admin",
      override_reason: null,
    },
    policy_context: defaultPolicyContext,
    obligation_state: null,
    blocked_state: null,
    is_editable: true,
    editing_restriction_reason: null,
  };

  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    mockCurrentUser = {
      role: "owner",
      permissions: { access_finance: true, delete_data: true, modify_products: true },
    };
    jest.clearAllMocks();
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

  // --------------------------------------------------------------------------
  // Group 1: Access Control & Role Awareness
  // --------------------------------------------------------------------------

  test("1. Renders AdminWageOverrideCard for authorized Owner", async () => {
    mockCurrentUser = { role: "owner", permissions: {} };
    api.get.mockImplementation((url) => {
      if (url.includes("/admin-wage")) {
        return Promise.resolve({ data: defaultGetConfig });
      }
      return Promise.resolve({ data: {} });
    });

    await act(async () => {
      root.render(
        <AdminWageOverrideCard
          orderId="order-123"
          order={{ order_number: "SGF-2026-001" }}
          isOwner={true}
          workers={sampleWorkers}
        />
      );
    });

    expect(container.querySelector('[data-testid="admin-wage-override-card"]')).not.toBeNull();
    expect(container.textContent).toContain("Upah Admin Per Pesanan");
    expect(container.textContent).toContain("Owner Only");
  });

  test("2. Does NOT render AdminWageOverrideCard for non-owner role", async () => {
    mockCurrentUser = { role: "admin", permissions: { access_finance: true } };

    await act(async () => {
      root.render(
        <AdminWageOverrideCard
          orderId="order-123"
          order={{ order_number: "SGF-2026-001" }}
          isOwner={false}
          workers={sampleWorkers}
        />
      );
    });

    expect(container.querySelector('[data-testid="admin-wage-override-card"]')).toBeNull();
    expect(api.get).not.toHaveBeenCalledWith(expect.stringContaining("/admin-wage"));
  });

  // --------------------------------------------------------------------------
  // Group 2: Loading & Error States
  // --------------------------------------------------------------------------

  test("3. Displays loading state while fetching admin wage configuration", async () => {
    let resolveGet;
    api.get.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveGet = resolve;
        })
    );

    act(() => {
      root.render(
        <AdminWageOverrideCard
          orderId="order-123"
          order={{ order_number: "SGF-2026-001" }}
          isOwner={true}
          workers={sampleWorkers}
        />
      );
    });

    expect(container.querySelector('[data-testid="admin-wage-loading"]')).not.toBeNull();
    expect(container.textContent).toContain("Memuat konfigurasi upah admin...");

    await act(async () => {
      resolveGet({ data: defaultGetConfig });
    });

    expect(container.querySelector('[data-testid="admin-wage-loading"]')).toBeNull();
    expect(container.textContent).toContain("Upah Admin Per Pesanan");
  });

  test("4. Displays friendly error alert when GET fails", async () => {
    api.get.mockRejectedValueOnce({
      response: { data: { detail: "Sesi tidak valid atau telah berakhir" } },
    });

    await act(async () => {
      root.render(
        <AdminWageOverrideCard
          orderId="order-123"
          order={{ order_number: "SGF-2026-001" }}
          isOwner={true}
          workers={sampleWorkers}
        />
      );
    });

    const errBox = container.querySelector('[data-testid="admin-wage-load-error"]');
    expect(errBox).not.toBeNull();
    expect(errBox.textContent).toContain("Sesi tidak valid atau telah berakhir");
  });

  // --------------------------------------------------------------------------
  // Group 3: Effective Configuration Display (Default vs Override)
  // --------------------------------------------------------------------------

  test("5. Displays policy default configuration clearly when no override is set", async () => {
    api.get.mockResolvedValueOnce({ data: defaultGetConfig });

    await act(async () => {
      root.render(
        <AdminWageOverrideCard
          orderId="order-123"
          order={{ order_number: "SGF-2026-001" }}
          isOwner={true}
          workers={sampleWorkers}
        />
      );
    });

    expect(container.querySelector('[data-testid="badge-override-status"]').textContent).toContain(
      "Kebijakan Default Global"
    );
    expect(container.querySelector('[data-testid="effective-admin-wage-amount"]').textContent).toContain(
      "150 LE"
    );
    expect(container.querySelector('[data-testid="effective-admin-wage-recipient"]').textContent).toContain(
      "Siti Admin"
    );
  });

  test("6. Displays explicit override configuration and reason when override is active", async () => {
    const overrideConfig = {
      ...defaultGetConfig,
      is_override: true,
      saved_override: {
        is_override: true,
        amount_le: 220.0,
        recipient_id: "admin_budi",
        recipient_name: "Budi Staff",
        override_reason: "Penanganan order kustom kompleks",
      },
      effective_configuration: {
        source: "override",
        is_override: true,
        amount_le: 220.0,
        recipient_id: "admin_budi",
        recipient_name: "Budi Staff",
        override_reason: "Penanganan order kustom kompleks",
      },
    };

    api.get.mockResolvedValueOnce({ data: overrideConfig });

    await act(async () => {
      root.render(
        <AdminWageOverrideCard
          orderId="order-123"
          order={{ order_number: "SGF-2026-001" }}
          isOwner={true}
          workers={sampleWorkers}
        />
      );
    });

    expect(container.querySelector('[data-testid="badge-override-status"]').textContent).toContain(
      "Tarif Khusus (Override)"
    );
    expect(container.querySelector('[data-testid="effective-admin-wage-amount"]').textContent).toContain(
      "220 LE"
    );
    expect(container.querySelector('[data-testid="effective-admin-wage-recipient"]').textContent).toContain(
      "Budi Staff"
    );
    const reasonBox = container.querySelector('[data-testid="admin-wage-override-reason-box"]');
    expect(reasonBox).not.toBeNull();
    expect(reasonBox.textContent).toContain("Penanganan order kustom kompleks");
  });

  // --------------------------------------------------------------------------
  // Group 4: Modal Form Interactions, Input Validation & Explicit Clear
  // --------------------------------------------------------------------------

  test("7. Opens modal and submits valid override mutation with correct payload", async () => {
    api.get.mockResolvedValue({ data: defaultGetConfig });
    api.put.mockResolvedValueOnce({
      data: {
        message: "Override upah admin berhasil diatur",
        saved_override: { is_override: true, amount_le: 200.0 },
      },
    });

    await act(async () => {
      root.render(
        <AdminWageOverrideCard
          orderId="order-123"
          order={{ order_number: "SGF-2026-001" }}
          isOwner={true}
          workers={sampleWorkers}
        />
      );
    });

    // Open modal
    const openBtn = container.querySelector('[data-testid="btn-open-admin-wage-modal"]');
    await act(async () => {
      openBtn.click();
    });

    expect(container.querySelector('[data-testid="modal-admin-wage-override"]')).not.toBeNull();

    // Select Override mode
    const overrideRadio = container.querySelector('[data-testid="radio-mode-override"]');
    await act(async () => {
      overrideRadio.click();
    });

    // Set amount to 200
    const amountInput = container.querySelector('[data-testid="input-override-amount"]');
    await act(async () => {
      const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
      nativeSetter.call(amountInput, "200");
      amountInput.dispatchEvent(new Event("input", { bubbles: true }));
    });

    // Set recipient to Budi
    const recipientSelect = container.querySelector('[data-testid="select-override-recipient"]');
    await act(async () => {
      recipientSelect.value = "admin_budi";
      recipientSelect.dispatchEvent(new Event("change", { bubbles: true }));
    });

    // Set reason
    const reasonInput = container.querySelector('[data-testid="textarea-override-reason"]');
    await act(async () => {
      const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, "value").set;
      nativeSetter.call(reasonInput, "Bonus koordinasi material khusus");
      reasonInput.dispatchEvent(new Event("input", { bubbles: true }));
    });

    // Submit form
    const submitBtn = container.querySelector('[data-testid="btn-submit-admin-wage"]');
    await act(async () => {
      submitBtn.click();
    });

    expect(api.put).toHaveBeenCalledWith(
      "/admin/orders/order-123/admin-wage",
      {
        is_override: true,
        amount_le: 200.0,
        recipient_id: "admin_budi",
        override_reason: "Bonus koordinasi material khusus",
      }
    );
  });

  test("8. Submitting override above threshold requires reason (validation feedback)", async () => {
    api.get.mockResolvedValueOnce({ data: defaultGetConfig });

    await act(async () => {
      root.render(
        <AdminWageOverrideCard
          orderId="order-123"
          order={{ order_number: "SGF-2026-001" }}
          isOwner={true}
          workers={sampleWorkers}
        />
      );
    });

    // Open modal
    await act(async () => {
      container.querySelector('[data-testid="btn-open-admin-wage-modal"]').click();
    });

    // Select Override mode
    await act(async () => {
      container.querySelector('[data-testid="radio-mode-override"]').click();
    });

    // Set amount to 350 (threshold is 300) with empty reason
    const amountInput = container.querySelector('[data-testid="input-override-amount"]');
    await act(async () => {
      const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
      nativeSetter.call(amountInput, "350");
      amountInput.dispatchEvent(new Event("input", { bubbles: true }));
    });

    // Submit form without reason
    await act(async () => {
      container.querySelector('[data-testid="btn-submit-admin-wage"]').click();
    });

    const errAlert = container.querySelector('[data-testid="form-error-alert"]');
    expect(errAlert).not.toBeNull();
    expect(errAlert.textContent).toContain("melebihi ambang tidak wajar (300 LE)");
    expect(api.put).not.toHaveBeenCalled();
  });

  test("9. Explicit clearing of override sends is_override: false restoring policy default", async () => {
    const overrideConfig = {
      ...defaultGetConfig,
      is_override: true,
      saved_override: {
        is_override: true,
        amount_le: 250.0,
        recipient_id: "admin_budi",
      },
    };
    api.get.mockResolvedValue({ data: overrideConfig });
    api.put.mockResolvedValueOnce({
      data: { message: "Override upah admin dinonaktifkan" },
    });

    await act(async () => {
      root.render(
        <AdminWageOverrideCard
          orderId="order-123"
          order={{ order_number: "SGF-2026-001" }}
          isOwner={true}
          workers={sampleWorkers}
        />
      );
    });

    // Open modal
    await act(async () => {
      container.querySelector('[data-testid="btn-open-admin-wage-modal"]').click();
    });

    // Switch to Default mode
    await act(async () => {
      container.querySelector('[data-testid="radio-mode-default"]').click();
    });

    // Enter clear reason
    const clearReasonInput = container.querySelector('[data-testid="input-clear-reason"]');
    await act(async () => {
      const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
      nativeSetter.call(clearReasonInput, "Kembali ke tarif standar toko");
      clearReasonInput.dispatchEvent(new Event("input", { bubbles: true }));
    });

    // Submit
    await act(async () => {
      container.querySelector('[data-testid="btn-submit-admin-wage"]').click();
    });

    expect(api.put).toHaveBeenCalledWith(
      "/admin/orders/order-123/admin-wage",
      {
        is_override: false,
        amount_le: null,
        recipient_id: null,
        override_reason: "Kembali ke tarif standar toko",
      }
    );
  });

  // --------------------------------------------------------------------------
  // Group 5: Lifecycle Restrictions & Financial Safety
  // --------------------------------------------------------------------------

  test("10. Accrued obligation displays existing obligation details and integrity warning", async () => {
    const accruedConfig = {
      ...defaultGetConfig,
      is_editable: true,
      obligation_state: {
        obligation_id: "wob-001",
        obligation_number: "WOB-2026-0088",
        status: "accrued",
        amount_le: 150.0,
        worker_id: "admin_siti",
        worker_name: "Siti Admin",
        accrued_at: "2026-10-28T10:00:00Z",
      },
    };
    api.get.mockResolvedValueOnce({ data: accruedConfig });

    await act(async () => {
      root.render(
        <AdminWageOverrideCard
          orderId="order-123"
          order={{ order_number: "SGF-2026-001", payment_status: "lunas" }}
          isOwner={true}
          workers={sampleWorkers}
        />
      );
    });

    expect(container.querySelector('[data-testid="admin-wage-obligation-box"]')).not.toBeNull();
    expect(container.querySelector('[data-testid="badge-obligation-status"]').textContent).toContain("accrued");
    expect(container.textContent).toContain("WOB-2026-0088");
    expect(container.textContent).toContain("Kewajiban upah telah terbit");
    expect(container.textContent).toContain("tidak otomatis mengubah nominal kewajiban yang sudah tercatat");
  });

  test("11. Partially paid and paid obligations show restriction alert and disable edit button", async () => {
    const paidConfig = {
      ...defaultGetConfig,
      is_editable: false,
      editing_restriction_reason: "Kewajiban upah (WOB-2026-0099) sudah berstatus 'paid'",
      obligation_state: {
        obligation_id: "wob-002",
        obligation_number: "WOB-2026-0099",
        status: "paid",
        amount_le: 150.0,
        worker_name: "Siti Admin",
      },
    };
    api.get.mockResolvedValueOnce({ data: paidConfig });

    await act(async () => {
      root.render(
        <AdminWageOverrideCard
          orderId="order-123"
          order={{ order_number: "SGF-2026-001", payment_status: "lunas" }}
          isOwner={true}
          workers={sampleWorkers}
        />
      );
    });

    // Edit button should be hidden/disabled
    expect(container.querySelector('[data-testid="btn-open-admin-wage-modal"]')).toBeNull();

    // Restriction alert is displayed
    const restrictAlert = container.querySelector('[data-testid="admin-wage-restriction-alert"]');
    expect(restrictAlert).not.toBeNull();
    expect(restrictAlert.textContent).toContain("sudah berstatus 'paid'");
  });

  test("12. Displays blocked conflict alert without triggering automatic mutation", async () => {
    const blockedConfig = {
      ...defaultGetConfig,
      blocked_state: {
        status: "blocked_hard_cap_conflict",
        reason: "Nominal upah override (600 LE) melebihi batas maksimum aktif (500 LE)",
        attempted_amount_le: 600.0,
        max_wage_per_order_le: 500.0,
      },
    };
    api.get.mockResolvedValueOnce({ data: blockedConfig });

    await act(async () => {
      root.render(
        <AdminWageOverrideCard
          orderId="order-123"
          order={{ order_number: "SGF-2026-001" }}
          isOwner={true}
          workers={sampleWorkers}
        />
      );
    });

    const blockAlert = container.querySelector('[data-testid="admin-wage-blocked-alert"]');
    expect(blockAlert).not.toBeNull();
    expect(blockAlert.textContent).toContain("Akrual Upah Terblokir (Blocked Conflict)");
    expect(blockAlert.textContent).toContain("melebihi batas maksimum aktif (500 LE)");

    // No PUT or POST mutation executed automatically
    expect(api.put).not.toHaveBeenCalled();
    expect(api.post).not.toHaveBeenCalled();
  });

  test("13. Handles HTTP 409 Conflict gracefully and prompts refresh", async () => {
    api.get.mockResolvedValue({ data: defaultGetConfig });
    api.put.mockRejectedValueOnce({
      response: {
        status: 409,
        data: {
          detail: "Konflik konkurensi: Data pesanan telah diubah oleh proses lain. Silakan muat ulang dan coba kembali.",
        },
      },
    });

    await act(async () => {
      root.render(
        <AdminWageOverrideCard
          orderId="order-123"
          order={{ order_number: "SGF-2026-001" }}
          isOwner={true}
          workers={sampleWorkers}
        />
      );
    });

    // Open and submit
    await act(async () => {
      container.querySelector('[data-testid="btn-open-admin-wage-modal"]').click();
    });
    await act(async () => {
      container.querySelector('[data-testid="btn-submit-admin-wage"]').click();
    });

    // Shows conflict message and reload button
    expect(container.querySelector('[data-testid="btn-conflict-reload"]')).not.toBeNull();
    expect(container.textContent).toContain("Konflik konkurensi: Data pesanan telah diubah");
  });

  test("14. Displays backend hard-cap validation error without silently altering amount", async () => {
    api.get.mockResolvedValue({ data: defaultGetConfig });
    api.put.mockRejectedValueOnce({
      response: {
        status: 422,
        data: {
          detail: "Nominal upah (600 LE) melebihi batas maksimum kebijakan aktif (500 LE)",
        },
      },
    });

    await act(async () => {
      root.render(
        <AdminWageOverrideCard
          orderId="order-123"
          order={{ order_number: "SGF-2026-001" }}
          isOwner={true}
          workers={sampleWorkers}
        />
      );
    });

    await act(async () => {
      container.querySelector('[data-testid="btn-open-admin-wage-modal"]').click();
    });
    await act(async () => {
      container.querySelector('[data-testid="radio-mode-override"]').click();
    });

    const amountInput = container.querySelector('[data-testid="input-override-amount"]');
    await act(async () => {
      const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
      nativeSetter.call(amountInput, "600");
      amountInput.dispatchEvent(new Event("input", { bubbles: true }));
    });

    const reasonInput = container.querySelector('[data-testid="textarea-override-reason"]');
    await act(async () => {
      const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, "value").set;
      nativeSetter.call(reasonInput, "Alasan permintaan nominal khusus 600 LE");
      reasonInput.dispatchEvent(new Event("input", { bubbles: true }));
    });

    await act(async () => {
      container.querySelector('[data-testid="btn-submit-admin-wage"]').click();
    });

    expect(container.querySelector('[data-testid="form-error-alert"]').textContent).toContain(
      "melebihi batas maksimum kebijakan aktif (500 LE)"
    );
    // Amount is preserved as 600 (not silently altered or clamped)
    expect(amountInput.value).toBe("600");
  });
});
