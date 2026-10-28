import React, { act } from "react";
import { createRoot } from "react-dom/client";

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

jest.mock(
  "@/lib/utils",
  () => jest.requireActual("../lib/utils"),
  { virtual: true }
);

let mockAuthContext = {
  user: {
    id: "admin_1",
    name: "Admin User",
    role: "owner",
    permissions: { access_finance: true, manage_orders: true, modify_products: true },
  },
  checked: true,
  logout: jest.fn(),
};

jest.mock("../context/AuthContext", () => ({
  useAuth: () => mockAuthContext,
}));

jest.mock(
  "react-router-dom",
  () => ({
    useNavigate: () => jest.fn(),
    useParams: () => ({}),
    useLocation: () => ({ pathname: "/admin/orders" }),
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
    Outlet: () => <div data-testid="admin-outlet">Outlet Content</div>,
    Navigate: ({ to }) => <div data-testid="navigate-mock" data-to={to}>Redirecting to {to}</div>,
  }),
  { virtual: true }
);

global.IS_REACT_ACT_ENVIRONMENT = true;

import api from "../lib/api";
jest.mock("../lib/api");

import AdminLayout from "../pages/admin/AdminLayout";

describe("AdminLayout - Component Mount & Navigation Tests", () => {
  let container = null;
  let root = null;

  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    jest.clearAllMocks();

    api.get.mockImplementation((url) => {
      if (url === "/store-info") {
        return Promise.resolve({
          data: {
            store_name: "Sogil Furniture",
            logo_url: "https://example.com/logo.png",
          },
        });
      }
      return Promise.resolve({ data: {} });
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
  });

  test("1. Renders AdminLayout without runtime errors when user is authenticated owner", async () => {
    mockAuthContext = {
      user: {
        id: "owner_1",
        name: "Owner Admin",
        role: "owner",
        permissions: { access_finance: true, manage_orders: true },
      },
      checked: true,
      logout: jest.fn(),
    };

    await act(async () => {
      root.render(<AdminLayout />);
    });

    const pendingPaymentLink = container.querySelector('a[href="/admin/pending-payments"]');
    expect(pendingPaymentLink).not.toBeNull();
    expect(pendingPaymentLink.textContent).toContain("Pending Payment");

    const wageSettingsLink = container.querySelector('a[href="/admin/wage-settings"]');
    expect(wageSettingsLink).not.toBeNull();
    expect(wageSettingsLink.textContent).toContain("Pengaturan Upah");
  });

  test("2. Pending Payment link is visible when user has access_finance permission", async () => {
    mockAuthContext = {
      user: {
        id: "finance_1",
        name: "Finance Officer",
        role: "staff",
        permissions: { access_finance: true, manage_orders: false },
      },
      checked: true,
      logout: jest.fn(),
    };

    await act(async () => {
      root.render(<AdminLayout />);
    });

    const pendingPaymentLink = container.querySelector('a[href="/admin/pending-payments"]');
    expect(pendingPaymentLink).not.toBeNull();
    expect(pendingPaymentLink.textContent).toContain("Pending Payment");

    const wageSettingsLink = container.querySelector('a[href="/admin/wage-settings"]');
    expect(wageSettingsLink).not.toBeNull();
    expect(wageSettingsLink.textContent).toContain("Pengaturan Upah");
  });

  test("3. Pending Payment link is hidden when user lacks finance or owner permission", async () => {
    mockAuthContext = {
      user: {
        id: "worker_1",
        name: "Regular Worker",
        role: "employee",
        permissions: { manage_orders: true, access_finance: false },
      },
      checked: true,
      logout: jest.fn(),
    };

    await act(async () => {
      root.render(<AdminLayout />);
    });

    const pendingPaymentLink = container.querySelector('a[href="/admin/pending-payments"]');
    expect(pendingPaymentLink).toBeNull();

    const wageSettingsLink = container.querySelector('a[href="/admin/wage-settings"]');
    expect(wageSettingsLink).toBeNull();
  });

  test("4. Displays loading state when auth is not checked or user is null", async () => {
    mockAuthContext = {
      user: null,
      checked: false,
      logout: jest.fn(),
    };

    await act(async () => {
      root.render(<AdminLayout />);
    });

    expect(container.textContent).toContain("Memuat...");
  });

  test("5. Redirects to /admin/login when user is unauthenticated (false)", async () => {
    mockAuthContext = {
      user: false,
      checked: true,
      logout: jest.fn(),
    };

    await act(async () => {
      root.render(<AdminLayout />);
    });

    const navMock = container.querySelector('[data-testid="navigate-mock"]');
    expect(navMock).not.toBeNull();
    expect(navMock.getAttribute("data-to")).toBe("/admin/login");
  });
});
