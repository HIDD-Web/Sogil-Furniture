import React, { act } from "react";
import { createRoot } from "react-dom/client";

jest.mock(
  "@/lib/utils",
  () => jest.requireActual("../lib/utils"),
  { virtual: true }
);

import Home from "../pages/Home";
import api from "../lib/api";

jest.mock(
  "react-router-dom",
  () => ({
    useNavigate: () => jest.fn(),
    Link: ({ children, to }) => <a href={to}>{children}</a>,
  }),
  { virtual: true }
);

const mockT = (key) => {
  const dict = {
    "home.welcome": "Selamat datang di Sogil Furniture",
    "home.title": "Furniture Nyaman untuk Ruang Anda",
    "home.subtitle": "Katalog pilihan kami",
    "home.empty_title": "Produk belum tersedia",
    "home.empty_subtitle": "Silakan cek kembali nanti",
    "cat.rak": "Rak Buku",
    "cat.meja": "Meja Belajar",
  };
  return dict[key] || key;
};

jest.mock("../context/LanguageContext", () => ({
  useLang: () => ({
    t: mockT,
    lang: "id",
    dir: "ltr",
  }),
}));

jest.mock("../components/Logo", () => ({
  Logo: () => <div data-testid="mock-logo">LOGO</div>,
}));

jest.mock("../components/CategorySection", () => () => (
  <div data-testid="mock-category-section">CategorySection</div>
));

jest.mock("../components/HelpSheet", () => () => (
  <div data-testid="mock-help-sheet">HelpSheet</div>
));

jest.mock("../lib/api");

global.IS_REACT_ACT_ENVIRONMENT = true;

describe("Stage 1.1: Home Lifecycle and Splash Screen Deduplication", () => {
  let container = null;
  let root = null;

  const mockProducts = [
    { _id: "p1", name: "Rak Minimalis", category: "rak", active: true, price_le: 120 },
    { _id: "p2", name: "Meja Kayu", category: "meja", active: true, price_le: 200 },
  ];

  const mockCategories = [
    { key: "rak", name: "Rak", description: "Deskripsi rak" },
    { key: "meja", name: "Meja", description: "Deskripsi meja" },
  ];

  const mockStore = {
    exchange_rate_idr_per_le: 357,
    whatsapp_number: "+201234567890",
  };

  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    sessionStorage.clear();
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
    sessionStorage.clear();
  });

  test("1. Initial mount fetches products, store-info, categories exactly once when splash is enabled, and timer dismisses splash without duplicate fetch", async () => {
    jest.useFakeTimers();

    api.get.mockImplementation((url) => {
      if (url === "/products") return Promise.resolve({ data: mockProducts });
      if (url === "/store-info") return Promise.resolve({ data: mockStore });
      if (url === "/categories") return Promise.resolve({ data: mockCategories });
      return Promise.reject(new Error("Not found"));
    });

    await act(async () => {
      root.render(<Home />);
    });

    // Splash screen should be visible initially
    expect(container.querySelector("[data-testid='home-splash']")).not.toBeNull();
    expect(sessionStorage.getItem("sogil_splash_seen")).toBe("true");

    // Check API calls: exactly 1 call per endpoint
    const productsCalls = api.get.mock.calls.filter((c) => c[0] === "/products").length;
    const storeCalls = api.get.mock.calls.filter((c) => c[0] === "/store-info").length;
    const categoriesCalls = api.get.mock.calls.filter((c) => c[0] === "/categories").length;

    expect(productsCalls).toBe(1);
    expect(storeCalls).toBe(1);
    expect(categoriesCalls).toBe(1);

    // Fast-forward 1000ms timer to dismiss splash
    await act(async () => {
      jest.advanceTimersByTime(1000);
    });

    // Splash screen should now be gone, main content visible
    expect(container.querySelector("[data-testid='home-splash']")).toBeNull();
    expect(container.textContent).toContain("Furniture Nyaman untuk Ruang Anda");

    // CRITICAL: Verifying NO DUPLICATE FETCH occurred when showSplash changed to false!
    const productsCallsAfterSplash = api.get.mock.calls.filter((c) => c[0] === "/products").length;
    const storeCallsAfterSplash = api.get.mock.calls.filter((c) => c[0] === "/store-info").length;
    const categoriesCallsAfterSplash = api.get.mock.calls.filter((c) => c[0] === "/categories").length;

    expect(productsCallsAfterSplash).toBe(1);
    expect(storeCallsAfterSplash).toBe(1);
    expect(categoriesCallsAfterSplash).toBe(1);

    jest.useRealTimers();
  });

  test("2. When splash was already seen, mounts directly to home content and calls API endpoints once", async () => {
    sessionStorage.setItem("sogil_splash_seen", "true");

    api.get.mockImplementation((url) => {
      if (url === "/products") return Promise.resolve({ data: mockProducts });
      if (url === "/store-info") return Promise.resolve({ data: mockStore });
      if (url === "/categories") return Promise.resolve({ data: mockCategories });
      return Promise.reject(new Error("Not found"));
    });

    await act(async () => {
      root.render(<Home />);
    });

    // No splash screen
    expect(container.querySelector("[data-testid='home-splash']")).toBeNull();
    expect(container.textContent).toContain("Furniture Nyaman untuk Ruang Anda");

    const productsCalls = api.get.mock.calls.filter((c) => c[0] === "/products").length;
    expect(productsCalls).toBe(1);
  });

  test("3. Renders empty state when products array is empty", async () => {
    sessionStorage.setItem("sogil_splash_seen", "true");

    api.get.mockImplementation((url) => {
      if (url === "/products") return Promise.resolve({ data: [] });
      if (url === "/store-info") return Promise.resolve({ data: mockStore });
      if (url === "/categories") return Promise.resolve({ data: [] });
      return Promise.reject(new Error("Not found"));
    });

    await act(async () => {
      root.render(<Home />);
    });

    expect(container.querySelector("[data-testid='home-empty-state']")).not.toBeNull();
    expect(container.textContent).toContain("Produk belum tersedia");
  });

  test("4. Unmounting during splash screen cleans up timer safely", async () => {
    jest.useFakeTimers();

    api.get.mockImplementation(() => new Promise(() => {}));

    await act(async () => {
      root.render(<Home />);
    });

    expect(container.querySelector("[data-testid='home-splash']")).not.toBeNull();

    expect(() => {
      act(() => {
        root.unmount();
      });
    }).not.toThrow();

    jest.useRealTimers();
  });
});
