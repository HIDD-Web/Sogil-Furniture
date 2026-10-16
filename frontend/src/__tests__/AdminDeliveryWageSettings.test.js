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
    useLocation: () => ({ pathname: "/admin/delivery-wage-settings" }),
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

import AdminDeliveryWageSettings from "../pages/admin/AdminDeliveryWageSettings";

describe("AdminDeliveryWageSettings - Tiered Delivery Helper Wage Policy UI", () => {
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
      if (url === "/admin/delivery-wage-policy") {
        return Promise.resolve({
          data: {
            base_wage_per_order_le: 50.0,
            unusual_amount_threshold_le: 100.0,
            max_helper_wage_per_order_le: 500.0,
            currency: "EGP",
            rounding_policy: "piastre_round_half_up",
            updated_at: "2026-10-16T12:00:00Z",
            updated_by_name: "Boss Owner",
          },
        });
      }
      if (url === "/admin/delivery-wage-policy/history") {
        return Promise.resolve({
          data: [
            {
              _id: "hist_1",
              action: "update_delivery_wage_policy",
              performed_by_name: "Boss Owner",
              timestamp: "2026-10-16T12:00:00Z",
              metadata: {
                previous: { base_wage_per_order_le: 40.0 },
                new: { base_wage_per_order_le: 50.0 },
                changed_fields: ["base_wage_per_order_le"],
              },
            },
            {
              _id: "hist_2",
              action: "delivery_wage_threshold_override",
              performed_by_name: "Staff Ops",
              timestamp: "2026-10-16T12:30:00Z",
              metadata: {
                order_number: "ORD-101",
                trip_number: "TRP-001",
                recorded_amount_le: 200.0,
                threshold_le: 100.0,
                override_reason: "Lantai 4 tanpa lift",
              },
            },
            {
              _id: "hist_3",
              action: "delivery_wage_hard_cap_rejection",
              performed_by_name: "Staff Ops",
              timestamp: "2026-10-16T13:00:00Z",
              metadata: {
                order_number: "ORD-102",
                trip_number: "TRP-001",
                attempted_amount_le: 600.0,
                hard_cap_le: 500.0,
              },
            },
          ],
        });
      }
      return Promise.reject(new Error(`Unhandled GET url: ${url}`));
    });

    api.put.mockResolvedValue({
      data: {
        base_wage_per_order_le: 60.0,
        unusual_amount_threshold_le: 150.0,
        max_helper_wage_per_order_le: 600.0,
      },
    });
  });

  afterEach(() => {
    act(() => {
      root.unmount();
    });
    container.remove();
    container = null;
  });

  test("1. Renders 3 tiered fields: base wage (50), threshold (100), and hard cap (500)", async () => {
    await act(async () => {
      root.render(<AdminDeliveryWageSettings />);
    });

    expect(container.textContent).toContain("Tarif Dasar Upah per Pesanan (EGP)");
    expect(container.textContent).toContain("Batas Konfirmasi Nominal (EGP)");
    expect(container.textContent).toContain("Batas Maksimum Keras (EGP)");

    const inputs = container.querySelectorAll("input[type='number']");
    expect(inputs.length).toBeGreaterThanOrEqual(3);
    expect(inputs[0].value).toBe("50");
    expect(inputs[1].value).toBe("100");
    expect(inputs[2].value).toBe("500");
  });

  test("2. Displays history badges for updates, overrides, and hard cap rejections", async () => {
    await act(async () => {
      root.render(<AdminDeliveryWageSettings />);
    });

    expect(container.textContent).toContain("Kebijakan");
    expect(container.textContent).toContain("Konfirmasi Override");
    expect(container.textContent).toContain("Ditolak Hard Cap");
    expect(container.textContent).toContain("Lantai 4 tanpa lift");
    expect(container.textContent).toContain("600 LE (Batas Keras: 500 LE) — Ditolak");
  });

  test("3. Owner can save updated tiered policy with valid base <= threshold < hardCap", async () => {
    await act(async () => {
      root.render(<AdminDeliveryWageSettings />);
    });

    const inputs = container.querySelectorAll("input[type='number']");
    const baseInput = inputs[0];
    const threshInput = inputs[1];
    const capInput = inputs[2];

    await act(async () => {
      const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
      nativeSetter.call(baseInput, "60");
      baseInput.dispatchEvent(new Event("change", { bubbles: true }));

      nativeSetter.call(threshInput, "150");
      threshInput.dispatchEvent(new Event("change", { bubbles: true }));

      nativeSetter.call(capInput, "600");
      capInput.dispatchEvent(new Event("change", { bubbles: true }));
    });

    const saveBtn = Array.from(container.querySelectorAll("button")).find(
      (b) => b.textContent.includes("Simpan Pengaturan Upah")
    );
    expect(saveBtn).not.toBeNull();

    await act(async () => {
      saveBtn.click();
    });

    expect(api.put).toHaveBeenCalledWith(
      "/admin/delivery-wage-policy",
      expect.objectContaining({
        base_wage_per_order_le: 60,
        unusual_amount_threshold_le: 150,
        max_helper_wage_per_order_le: 600,
        currency: "EGP",
        rounding_policy: "piastre_round_half_up",
      })
    );
  });

  test("4. Client validation prevents threshold >= hardCap", async () => {
    await act(async () => {
      root.render(<AdminDeliveryWageSettings />);
    });

    const inputs = container.querySelectorAll("input[type='number']");
    const threshInput = inputs[1];
    const capInput = inputs[2];

    await act(async () => {
      const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
      nativeSetter.call(threshInput, "500");
      threshInput.dispatchEvent(new Event("change", { bubbles: true }));

      nativeSetter.call(capInput, "500");
      capInput.dispatchEvent(new Event("change", { bubbles: true }));
    });

    const saveBtn = Array.from(container.querySelectorAll("button")).find(
      (b) => b.textContent.includes("Simpan Pengaturan Upah")
    );

    await act(async () => {
      saveBtn.click();
    });

    expect(api.put).not.toHaveBeenCalled();
    expect(mockToast.error).toHaveBeenCalledWith(
      expect.stringContaining("harus lebih kecil dari batas maksimum keras")
    );
  });

  test("5. Finance role non-owner views page in read-only mode with disabled inputs", async () => {
    mockUser = {
      role: "admin",
      permissions: { access_finance: true },
    };

    await act(async () => {
      root.render(<AdminDeliveryWageSettings />);
    });

    expect(container.textContent).toContain("Mode Baca Saja");
    const inputs = container.querySelectorAll("input[type='number']");
    expect(inputs[0].disabled).toBe(true);
    expect(inputs[1].disabled).toBe(true);
    expect(inputs[2].disabled).toBe(true);

    const saveBtn = Array.from(container.querySelectorAll("button")).find(
      (b) => b.textContent.includes("Simpan Kebijakan")
    );
    expect(saveBtn).toBeUndefined();
  });
});
