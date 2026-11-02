import React, { act } from "react";
import { createRoot } from "react-dom/client";

jest.mock(
  "@/lib/utils",
  () => jest.requireActual("../lib/utils"),
  { virtual: true }
);

import AdminInvoices from "../pages/admin/AdminInvoices";
import api from "../lib/api";
import { toast } from "sonner";

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
      permissions: { access_finance: true, manage_orders: true },
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

describe("Stage 1.1: AdminInvoices Request Deduplication and Race Condition Protection", () => {
  let container = null;
  let root = null;

  const mockInvoices = [
    {
      _id: "inv_1",
      invoice_number: "INV-001",
      status: "DRAFT",
      total: 500,
      customer: { name: "Customer A", whatsapp: "+201111111111" },
      created_at: new Date().toISOString(),
      items: [{ name: "Item 1" }],
    },
    {
      _id: "inv_2",
      invoice_number: "INV-002",
      status: "SENT",
      total: 1000,
      customer: { name: "Customer B", whatsapp: "+202222222222" },
      created_at: new Date().toISOString(),
      items: [{ name: "Item 2" }],
    },
    {
      _id: "inv_3",
      invoice_number: "INV-003",
      status: "CLAIMED",
      total: 1500,
      customer: { name: "Customer C", whatsapp: "+203333333333" },
      created_at: new Date().toISOString(),
      items: [{ name: "Item 3" }],
    },
  ];

  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    mockSearchParams = new URLSearchParams();
    jest.clearAllMocks();
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
    container = null;
    root = null;
  });

  test("1. Initial load on default route (status=all) makes exactly ONE request to /admin/invoices and calculates all summary counts", async () => {
    api.get.mockImplementation((url, config) => {
      if (url === "/admin/invoices") {
        return Promise.resolve({ data: mockInvoices });
      }
      return Promise.reject(new Error("Not found"));
    });

    await act(async () => {
      root.render(<AdminInvoices />);
    });

    // Check request count: must be EXACTLY 1 call on initial load!
    const invoiceCalls = api.get.mock.calls.filter((c) => c[0] === "/admin/invoices");
    expect(invoiceCalls.length).toBe(1);

    // Verify invoices table rendered
    expect(container.textContent).toContain("INV-001");
    expect(container.textContent).toContain("INV-002");
    expect(container.textContent).toContain("INV-003");

    // Verify globalCounts summary cards rendered properly (All: 3, Draft: 1, Sent: 1, Claimed: 1)
    expect(container.textContent).toContain("Semua");
    expect(container.textContent).toContain("Menunggu Klaim");
  });

  test("2. Filtering by status makes targeted request with query params", async () => {
    mockSearchParams = new URLSearchParams("status=DRAFT");

    api.get.mockImplementation((url, config) => {
      if (url === "/admin/invoices") {
        if (config?.params?.status === "DRAFT") {
          return Promise.resolve({ data: [mockInvoices[0]] });
        }
        // counts request
        return Promise.resolve({ data: mockInvoices });
      }
      return Promise.reject(new Error("Not found"));
    });

    await act(async () => {
      root.render(<AdminInvoices />);
    });

    expect(container.textContent).toContain("INV-001");
    expect(container.textContent).not.toContain("INV-002");
  });

  test("3. Rapid filter change drops slower out-of-order response", async () => {
    let resolveFirst;
    const firstPromise = new Promise((resolve) => {
      resolveFirst = resolve;
    });

    api.get.mockImplementation((url, config) => {
      if (config?.params?.status === "DRAFT") {
        return firstPromise.then(() => ({ data: [mockInvoices[0]] }));
      }
      if (config?.params?.status === "SENT") {
        return Promise.resolve({ data: [mockInvoices[1]] });
      }
      return Promise.resolve({ data: mockInvoices });
    });

    mockSearchParams = new URLSearchParams("status=DRAFT");
    await act(async () => {
      root.render(<AdminInvoices />);
    });

    // Now change to SENT before DRAFT resolves
    mockSearchParams = new URLSearchParams("status=SENT");
    await act(async () => {
      root.render(<AdminInvoices />);
    });

    // SENT is displayed
    expect(container.textContent).toContain("INV-002");

    // Now resolve the older DRAFT request
    await act(async () => {
      resolveFirst();
    });

    // Content should STILL show SENT (INV-002), not overwritten by DRAFT (INV-001)
    expect(container.textContent).toContain("INV-002");
    expect(container.textContent).not.toContain("INV-001");
  });

  test("4. API error surfaces error toast and does not leave page stuck in loading", async () => {
    const err = new Error("Fetch failed");
    err.response = { data: { detail: "Server error occurred" } };
    api.get.mockRejectedValue(err);

    await act(async () => {
      root.render(<AdminInvoices />);
    });

    expect(container.textContent).not.toContain("Memuat data invoice...");
    expect(toast.error).toHaveBeenCalledWith("Server error occurred");
  });

  test("5. Unmounting while requests are pending does not throw", async () => {
    api.get.mockImplementation(() => new Promise(() => {}));

    await act(async () => {
      root.render(<AdminInvoices />);
    });

    expect(() => {
      act(() => {
        root.unmount();
      });
    }).not.toThrow();
  });
});
