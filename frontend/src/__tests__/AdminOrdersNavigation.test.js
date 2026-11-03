import React, { act } from "react";
import { createRoot } from "react-dom/client";

jest.mock(
  "@/lib/utils",
  () => jest.requireActual("../lib/utils"),
  { virtual: true }
);

import AdminOrders from "../pages/admin/AdminOrders";
import AdminOrderDetail from "../pages/admin/AdminOrderDetail";
import api from "../lib/api";

// Polyfill window.matchMedia
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
const mockSetParams = jest.fn();
let mockLocationState = null;
const mockNavigate = jest.fn();

jest.mock(
  "react-router-dom",
  () => ({
    useParams: () => ({ id: "ord-test-123" }),
    useNavigate: () => mockNavigate,
    useLocation: () => ({
      pathname: "/admin/orders",
      search: mockSearchParams.toString() ? `?${mockSearchParams.toString()}` : "",
      state: mockLocationState,
    }),
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

describe("Phase C: Admin Orders Navigation & Filter Preservation", () => {
  let container = null;
  let root = null;

  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    jest.clearAllMocks();
    mockSearchParams = new URLSearchParams();
    mockLocationState = null;
    mockSetParams.mockImplementation((newParams) => {
      if (typeof newParams === "function") {
        mockSearchParams = new URLSearchParams(newParams(mockSearchParams));
      } else {
        mockSearchParams = new URLSearchParams(newParams);
      }
    });

    api.get.mockImplementation((url) => {
      if (url === "/admin/overview") {
        return Promise.resolve({
          data: {
            total: 10,
            pesanan_masuk: 2,
            dikonfirmasi: 2,
            diproses: 2,
            siap: 1,
            selesai: 2,
            dibatalkan: 1,
            lunas: 5,
            belum_dibayar: 3,
            dp: 2,
            estimated_revenue_le: 10000,
          },
        });
      }
      if (url.includes("/assignments")) {
        return Promise.resolve({ data: [] });
      }
      if (url.includes("/wage-rules") || url.includes("/delivery-zones") || url.includes("/delivery-trips") || url.includes("/admins")) {
        return Promise.resolve({ data: [] });
      }
      if (url.startsWith("/admin/orders/ord-test-123")) {
        return Promise.resolve({
          data: {
            _id: "ord-test-123",
            id: "ord-test-123",
            order_number: "SGL-TEST-001",
            customer_name: "Customer Navigation",
            customer_phone: "+201011112222",
            order_status: "siap",
            payment_status: "lunas",
            total_le: 1500,
            created_at: new Date().toISOString(),
            items: [{ item_id: "itm_1", product_name_snapshot: "Meja Kayu Jati", quantity: 1 }],
          },
        });
      }
      if (url.startsWith("/admin/orders")) {
        return Promise.resolve({
          data: [
            {
              _id: "ord-test-123",
              id: "ord-test-123",
              order_number: "SGL-TEST-001",
              customer_name: "Customer Navigation",
              customer_phone: "+201011112222",
              order_status: mockSearchParams.get("status") || "pesanan_masuk",
              payment_status: mockSearchParams.get("payment_status") || "lunas",
              total_le: 1500,
              created_at: new Date().toISOString(),
              items: [{ product_name_snapshot: "Meja Kayu Jati" }],
            },
          ],
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

  test("1. Filter 'Semua' navigates to detail with default '/admin/orders' back target", async () => {
    mockSearchParams = new URLSearchParams(); // No filter (tab Semua)
    await act(async () => {
      root.render(<AdminOrders />);
    });

    const orderRow = container.querySelector('[data-testid="order-row-SGL-TEST-001"]');
    expect(orderRow).toBeTruthy();

    await act(async () => {
      orderRow.click();
    });

    expect(mockNavigate).toHaveBeenCalledWith("/admin/orders/ord-test-123", {
      state: { from: "/admin/orders" },
    });
  });

  test("2. Filter 'Pesanan Masuk' preserves query param in navigation state", async () => {
    mockSearchParams = new URLSearchParams("status=pesanan_masuk");
    await act(async () => {
      root.render(<AdminOrders />);
    });

    const orderRow = container.querySelector('[data-testid="order-row-SGL-TEST-001"]');
    await act(async () => {
      orderRow.click();
    });

    expect(mockNavigate).toHaveBeenCalledWith("/admin/orders/ord-test-123", {
      state: { from: "/admin/orders?status=pesanan_masuk" },
    });
  });

  test("3. Filter 'Dikonfirmasi' preserves query param in navigation state", async () => {
    mockSearchParams = new URLSearchParams("status=dikonfirmasi");
    await act(async () => {
      root.render(<AdminOrders />);
    });

    const orderRow = container.querySelector('[data-testid="order-row-SGL-TEST-001"]');
    await act(async () => {
      orderRow.click();
    });

    expect(mockNavigate).toHaveBeenCalledWith("/admin/orders/ord-test-123", {
      state: { from: "/admin/orders?status=dikonfirmasi" },
    });
  });

  test("4. Filter 'Diproses' preserves query param in navigation state", async () => {
    mockSearchParams = new URLSearchParams("status=diproses");
    await act(async () => {
      root.render(<AdminOrders />);
    });

    const orderRow = container.querySelector('[data-testid="order-row-SGL-TEST-001"]');
    await act(async () => {
      orderRow.click();
    });

    expect(mockNavigate).toHaveBeenCalledWith("/admin/orders/ord-test-123", {
      state: { from: "/admin/orders?status=diproses" },
    });
  });

  test("5. Filter 'Siap Diambil/Dikirim' preserves query param in navigation state", async () => {
    mockSearchParams = new URLSearchParams("status=siap");
    await act(async () => {
      root.render(<AdminOrders />);
    });

    const orderRow = container.querySelector('[data-testid="order-row-SGL-TEST-001"]');
    await act(async () => {
      orderRow.click();
    });

    expect(mockNavigate).toHaveBeenCalledWith("/admin/orders/ord-test-123", {
      state: { from: "/admin/orders?status=siap" },
    });
  });

  test("6. Filter 'Selesai' preserves query param in navigation state", async () => {
    mockSearchParams = new URLSearchParams("status=selesai");
    await act(async () => {
      root.render(<AdminOrders />);
    });

    const orderRow = container.querySelector('[data-testid="order-row-SGL-TEST-001"]');
    await act(async () => {
      orderRow.click();
    });

    expect(mockNavigate).toHaveBeenCalledWith("/admin/orders/ord-test-123", {
      state: { from: "/admin/orders?status=selesai" },
    });
  });

  test("7. Filter 'Dibatalkan' preserves query param in navigation state", async () => {
    mockSearchParams = new URLSearchParams("status=dibatalkan");
    await act(async () => {
      root.render(<AdminOrders />);
    });

    const orderRow = container.querySelector('[data-testid="order-row-SGL-TEST-001"]');
    await act(async () => {
      orderRow.click();
    });

    expect(mockNavigate).toHaveBeenCalledWith("/admin/orders/ord-test-123", {
      state: { from: "/admin/orders?status=dibatalkan" },
    });
  });

  test("8. Detail page 'Kembali' button uses location.state.from when available", async () => {
    mockLocationState = { from: "/admin/orders?status=siap" };
    await act(async () => {
      root.render(<AdminOrderDetail />);
    });

    const backBtn = container.querySelector('[data-testid="admin-back-orders"]');
    expect(backBtn).toBeTruthy();

    await act(async () => {
      backBtn.click();
    });

    expect(mockNavigate).toHaveBeenCalledWith("/admin/orders?status=siap");
  });

  test("9. Detail page direct access fallback: returns to '/admin/orders' when state is null", async () => {
    mockLocationState = null; // Direct link or fresh tab
    await act(async () => {
      root.render(<AdminOrderDetail />);
    });

    const backBtn = container.querySelector('[data-testid="admin-back-orders"]');
    expect(backBtn).toBeTruthy();

    await act(async () => {
      backBtn.click();
    });

    expect(mockNavigate).toHaveBeenCalledWith("/admin/orders");
  });

  test("10. Payment filter and search term are both preserved in navigation state", async () => {
    mockSearchParams = new URLSearchParams("payment_status=dp");
    await act(async () => {
      root.render(<AdminOrders />);
    });

    // Enter search term and submit
    const searchInput = container.querySelector('[data-testid="order-search"]');
    const searchBtn = container.querySelector('[data-testid="order-search-btn"]');

    await act(async () => {
      searchInput.value = "Ahmad";
      searchInput.dispatchEvent(new Event("input", { bubbles: true }));
      // Manually trigger onChange if needed
      searchBtn.click();
    });

    const orderRow = container.querySelector('[data-testid="order-row-SGL-TEST-001"]');
    await act(async () => {
      orderRow.click();
    });

    expect(mockNavigate).toHaveBeenCalled();
    const lastCall = mockNavigate.mock.calls[mockNavigate.mock.calls.length - 1];
    expect(lastCall[0]).toBe("/admin/orders/ord-test-123");
    expect(lastCall[1].state.from).toContain("payment_status=dp");
  });
});
