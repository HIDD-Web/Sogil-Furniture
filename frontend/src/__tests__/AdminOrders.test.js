import React, { act } from "react";
import { createRoot } from "react-dom/client";

jest.mock(
  "@/lib/utils",
  () => jest.requireActual("../lib/utils"),
  { virtual: true }
);

import AdminOrders from "../pages/admin/AdminOrders";
import api from "../lib/api";
import { toast } from "sonner";
import axios from "axios";

// jsdom matchMedia polyfill
beforeAll(() => {
  window.matchMedia =
    window.matchMedia ||
    function () {
      return {
        matches: false,
        addListener: jest.fn(),
        removeListener: jest.fn(),
        addEventListener: jest.fn(),
        removeEventListener: jest.fn(),
        dispatchEvent: jest.fn(),
      };
    };
});

let mockSearchParams = new URLSearchParams();
const mockSetParams = jest.fn((newParams) => {
  mockSearchParams = new URLSearchParams(newParams);
});

jest.mock(
  "react-router-dom",
  () => ({
    useNavigate: () => jest.fn(),
    useSearchParams: () => [mockSearchParams, mockSetParams],
    Link: ({ children, to }) => <a href={to}>{children}</a>,
  }),
  { virtual: true }
);

jest.mock("../context/AuthContext", () => ({
  useAuth: () => ({
    user: {
      id: "admin_1",
      name: "Owner",
      role: "owner",
      permissions: { access_finance: true, manage_orders: true, modify_products: true },
    },
  }),
}));

jest.mock("sonner", () => ({
  toast: {
    success: jest.fn(),
    error: jest.fn(),
    info: jest.fn(),
    warning: jest.fn(),
  },
}));

jest.mock("../lib/api");

global.IS_REACT_ACT_ENVIRONMENT = true;

describe("Phase 1: AdminOrders Race Condition, Loading & Mobile Responsiveness", () => {
  let container = null;
  let root = null;

  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    jest.clearAllMocks();
    mockSearchParams = new URLSearchParams();

    api.get.mockImplementation((url) => {
      if (url === "/admin/overview") {
        return Promise.resolve({
          data: {
            total: 10,
            pesanan_masuk: 2,
            dikonfirmasi: 3,
            diproses: 2,
            siap: 1,
            selesai: 2,
            estimated_revenue_le: 5000,
          },
        });
      }
      return Promise.resolve({ data: [] });
    });
  });

  afterEach(() => {
    act(() => {
      if (root) root.unmount();
    });
    if (container) container.remove();
    container = null;
    root = null;
  });

  test("1. Solves race condition: stale response arriving late does NOT overwrite newer filter result", async () => {
    let resolveReq1, resolveReq2;
    const p1 = new Promise((resolve) => {
      resolveReq1 = resolve;
    });
    const p2 = new Promise((resolve) => {
      resolveReq2 = resolve;
    });

    let callCount = 0;
    api.get.mockImplementation((url, config) => {
      if (url === "/admin/overview") {
        return Promise.resolve({ data: {} });
      }
      if (url === "/admin/orders") {
        callCount++;
        if (callCount === 1) {
          // Request 1: slower, returns Order A
          return p1;
        } else if (callCount === 2) {
          // Request 2: faster, returns Order B
          return p2;
        }
      }
      return Promise.resolve({ data: [] });
    });

    // Mount initial
    await act(async () => {
      root.render(<AdminOrders />);
    });

    // Initial loading indicator is visible
    expect(container.querySelector('[data-testid="orders-loading"]')).toBeTruthy();

    // Trigger second request (e.g. user clicked tab "Diproses")
    mockSearchParams = new URLSearchParams("status=diproses");
    await act(async () => {
      root.render(<AdminOrders />);
    });

    // Now resolve Request 2 FIRST (returns Order B)
    await act(async () => {
      resolveReq2({
        data: [
          {
            _id: "ord_2",
            order_number: "SGF-20261101-002",
            customer_name: "Customer Terbaru",
            total_le: 1200,
            order_status: "diproses",
            payment_status: "dp",
            created_at: new Date().toISOString(),
            items: [{ product_name_snapshot: "Meja Mahasiswa" }],
          },
        ],
      });
    });

    // Verify UI shows Order B
    expect(container.textContent).toContain("SGF-20261101-002");
    expect(container.textContent).toContain("Customer Terbaru");

    // Now resolve the older Request 1 LATER (returns Order A)
    await act(async () => {
      resolveReq1({
        data: [
          {
            _id: "ord_1",
            order_number: "SGF-20261101-001",
            customer_name: "Customer Usang",
            total_le: 500,
            order_status: "dikonfirmasi",
            payment_status: "belum_dibayar",
            created_at: new Date().toISOString(),
            items: [{ product_name_snapshot: "Kursi Belajar" }],
          },
        ],
      });
    });

    // CRUCIAL ASSERTION: Stale request 1 MUST NOT overwrite the display!
    expect(container.textContent).toContain("SGF-20261101-002");
    expect(container.textContent).toContain("Customer Terbaru");
    expect(container.textContent).not.toContain("SGF-20261101-001");
    expect(container.textContent).not.toContain("Customer Usang");
  });

  test("2. Aborted / cancelled request does NOT trigger false error toast or error state", async () => {
    api.get.mockImplementation((url) => {
      if (url === "/admin/overview") return Promise.resolve({ data: {} });
      if (url === "/admin/orders") {
        const cancelErr = new axios.CanceledError("Request cancelled");
        return Promise.reject(cancelErr);
      }
      return Promise.resolve({ data: [] });
    });

    await act(async () => {
      root.render(<AdminOrders />);
    });

    // Toast error must NOT have been called for cancellation
    expect(toast.error).not.toHaveBeenCalled();
  });

  test("3. Real network error DOES trigger error toast and leaves loading false", async () => {
    api.get.mockImplementation((url) => {
      if (url === "/admin/overview") return Promise.resolve({ data: {} });
      if (url === "/admin/orders") {
        return Promise.reject({
          response: { data: { detail: "Server timeout atau koneksi putus" } },
        });
      }
      return Promise.resolve({ data: [] });
    });

    await act(async () => {
      root.render(<AdminOrders />);
    });

    expect(toast.error).toHaveBeenCalledWith("Server timeout atau koneksi putus");
    expect(container.querySelector('[data-testid="orders-loading"]')).toBeNull();
  });

  test("4. Renders mobile card view and search bar with responsive flex-wrap", async () => {
    api.get.mockImplementation((url) => {
      if (url === "/admin/overview") {
        return Promise.resolve({ data: { total: 1, pesanan_masuk: 1 } });
      }
      if (url === "/admin/orders") {
        return Promise.resolve({
          data: [
            {
              _id: "ord_mobile_1",
              order_number: "SGF-20261101-MOB",
              customer_name: "Ahmad Kairo",
              customer_phone: "+201012345678",
              total_le: 750,
              order_status: "pesanan_masuk",
              payment_status: "belum_dibayar",
              delivery_method: "delivery",
              delivery_zone_name: "Nasr City",
              created_at: new Date().toISOString(),
              items: [{ product_name_snapshot: "Rak Buku 3 Tingkat" }],
            },
          ],
        });
      }
      return Promise.resolve({ data: [] });
    });

    await act(async () => {
      root.render(<AdminOrders />);
    });

    // Mobile card exists with data-testid
    const mobileCard = container.querySelector('[data-testid="order-card-SGF-20261101-MOB"]');
    expect(mobileCard).toBeTruthy();
    expect(mobileCard.textContent).toContain("Ahmad Kairo");
    expect(mobileCard.textContent).toContain("+201012345678");
    expect(mobileCard.textContent).toContain("750 LE");
    expect(mobileCard.textContent).toContain("Nasr City");

    // Search bar container has flex-wrap for small viewports
    const searchContainer = container.querySelector('[data-testid="order-search-btn"]').parentElement;
    expect(searchContainer.className).toContain("flex-wrap");
  });
});
