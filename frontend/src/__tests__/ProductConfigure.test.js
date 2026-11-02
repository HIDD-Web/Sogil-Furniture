import React, { act } from "react";
import { createRoot } from "react-dom/client";

jest.mock(
  "@/lib/utils",
  () => jest.requireActual("../lib/utils"),
  { virtual: true }
);

import ProductConfigure from "../pages/ProductConfigure";
import api from "../lib/api";
import { toast } from "sonner";

let mockSlug = "rak-buku-minimalis";
let mockSearchParams = new URLSearchParams();
const mockNavigate = jest.fn();

jest.mock(
  "react-router-dom",
  () => ({
    useParams: () => ({ slug: mockSlug }),
    useNavigate: () => mockNavigate,
    useSearchParams: () => [mockSearchParams],
    Link: ({ children, to }) => <a href={to}>{children}</a>,
  }),
  { virtual: true }
);

const mockT = (key) => {
  const dict = {
    "cat.memuat": "Memuat...",
    "err.product_not_found": "Produk tidak ditemukan",
    "prod.back_catalog": "Kembali ke katalog",
    "cfg.kembali_produk": "Kembali ke Katalog",
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

jest.mock("../context/CartContext", () => ({
  useCart: () => ({
    addItem: jest.fn(),
    items: [],
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

describe("Stage 1.1: ProductConfigure Safe Fetch & Error Handling", () => {
  let container = null;
  let root = null;

  const mockProduct = {
    _id: "p1",
    name: "Rak Buku Minimalis",
    slug: "rak-buku-minimalis",
    category: "rak",
    configurable: true,
    pricing: {
      price_model: "base",
      base_price: 150,
      lengths: ["100 cm"],
      levels: [3],
      finishing_rates: { Natural: 0 },
    },
    images: ["/uploads/rak1.jpg"],
  };

  const mockStore = {
    exchange_rate_idr_per_le: 357,
    whatsapp_number: "+201234567890",
  };

  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    mockSlug = "rak-buku-minimalis";
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

  test("1. Initial fetch success renders product configuration UI and pricing", async () => {
    api.get.mockImplementation((url) => {
      if (url.startsWith("/products/")) {
        return Promise.resolve({ data: mockProduct });
      }
      if (url === "/store-info") {
        return Promise.resolve({ data: mockStore });
      }
      return Promise.reject(new Error("Not found"));
    });

    await act(async () => {
      root.render(<ProductConfigure />);
    });

    expect(container.textContent).toContain("Rak Buku Minimalis");
    expect(container.querySelector("[data-testid='product-loading']")).toBeNull();
    expect(container.querySelector("[data-testid='product-error-state']")).toBeNull();
  });

  test("2. Initial fetch 404 (not found) renders error state, no infinite loading, and back to catalog CTA", async () => {
    const error404 = new Error("Product not found");
    error404.response = { status: 404, data: { detail: "Product not found" } };

    api.get.mockImplementation((url) => {
      if (url.startsWith("/products/")) {
        return Promise.reject(error404);
      }
      return Promise.resolve({ data: mockStore });
    });

    await act(async () => {
      root.render(<ProductConfigure />);
    });

    // Should NOT be stuck in loading
    expect(container.querySelector("[data-testid='product-loading']")).toBeNull();

    // Should display not-found error state
    const errorState = container.querySelector("[data-testid='product-error-state']");
    expect(errorState).not.toBeNull();
    expect(errorState.textContent).toContain("Produk tidak ditemukan");

    // CTA back to catalog should be present
    const backBtn = container.querySelector("[data-testid='product-back-catalog-btn']");
    expect(backBtn).not.toBeNull();
    expect(backBtn.textContent).toContain("Kembali ke katalog");

    // No retry button on 404
    expect(container.querySelector("[data-testid='product-retry-btn']")).toBeNull();

    // Clicking back to catalog navigates to /katalog
    act(() => {
      backBtn.click();
    });
    expect(mockNavigate).toHaveBeenCalledWith("/katalog");
  });

  test("3. Network failure or server 500 renders error state with Coba Lagi retry button", async () => {
    const networkError = new Error("Network Error");
    networkError.response = { status: 500, data: { detail: "Internal Server Error" } };

    api.get.mockImplementation((url) => {
      if (url.startsWith("/products/")) {
        return Promise.reject(networkError);
      }
      return Promise.resolve({ data: mockStore });
    });

    await act(async () => {
      root.render(<ProductConfigure />);
    });

    expect(container.querySelector("[data-testid='product-loading']")).toBeNull();

    const errorState = container.querySelector("[data-testid='product-error-state']");
    expect(errorState).not.toBeNull();
    expect(errorState.textContent).toContain("Gagal Memuat Produk");

    const retryBtn = container.querySelector("[data-testid='product-retry-btn']");
    expect(retryBtn).not.toBeNull();
    expect(retryBtn.textContent).toContain("Coba Lagi");
  });

  test("4. Clicking Coba Lagi performs a new request and displays product upon recovery", async () => {
    let callCount = 0;
    api.get.mockImplementation((url) => {
      if (url.startsWith("/products/")) {
        callCount++;
        if (callCount === 1) {
          const err = new Error("Network failed");
          err.response = { status: 503, data: { detail: "Service Unavailable" } };
          return Promise.reject(err);
        }
        return Promise.resolve({ data: mockProduct });
      }
      return Promise.resolve({ data: mockStore });
    });

    await act(async () => {
      root.render(<ProductConfigure />);
    });

    // In error state initially
    const retryBtn = container.querySelector("[data-testid='product-retry-btn']");
    expect(retryBtn).not.toBeNull();

    // Click retry
    await act(async () => {
      retryBtn.click();
    });

    // Successfully recovered
    expect(container.textContent).toContain("Rak Buku Minimalis");
    expect(container.querySelector("[data-testid='product-error-state']")).toBeNull();
  });

  test("5. Slower response from previous slug does not overwrite newer slug response", async () => {
    let resolveFirst;
    const firstPromise = new Promise((resolve) => {
      resolveFirst = resolve;
    });

    const product1 = { ...mockProduct, name: "Product First" };
    const product2 = { ...mockProduct, name: "Product Second", slug: "product-second" };

    api.get.mockImplementation((url) => {
      if (url === "/products/rak-buku-minimalis") {
        return firstPromise.then(() => ({ data: product1 }));
      }
      if (url === "/products/product-second") {
        return Promise.resolve({ data: product2 });
      }
      return Promise.resolve({ data: mockStore });
    });

    await act(async () => {
      root.render(<ProductConfigure />);
    });

    // Still loading first product
    expect(container.querySelector("[data-testid='product-loading']")).not.toBeNull();

    // Change slug to product-second
    mockSlug = "product-second";
    await act(async () => {
      root.render(<ProductConfigure />);
    });

    // Second product resolved immediately
    expect(container.textContent).toContain("Product Second");

    // Now resolve first slug response
    await act(async () => {
      resolveFirst();
    });

    // Still displays second product (first response dropped by requestId check)
    expect(container.textContent).toContain("Product Second");
    expect(container.textContent).not.toContain("Product First");
  });

  test("6. Component unmounting during pending request does not throw", async () => {
    api.get.mockImplementation(() => new Promise(() => {}));

    await act(async () => {
      root.render(<ProductConfigure />);
    });

    expect(container.querySelector("[data-testid='product-loading']")).not.toBeNull();

    // Unmount while pending
    expect(() => {
      act(() => {
        root.unmount();
      });
    }).not.toThrow();
  });
});
