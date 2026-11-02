import React, { act } from "react";
import { createRoot } from "react-dom/client";

jest.mock(
  "@/lib/utils",
  () => jest.requireActual("../lib/utils"),
  { virtual: true }
);

import Checkout from "../pages/Checkout";
import api from "../lib/api";
import { toast } from "sonner";

const mockNavigate = jest.fn();
const mockClear = jest.fn();

jest.mock(
  "react-router-dom",
  () => ({
    useNavigate: () => mockNavigate,
    Link: ({ children, to }) => <a href={to}>{children}</a>,
  }),
  { virtual: true }
);

const mockCartItem = {
  cartId: "c1",
  product_id: "prod_1",
  product: { id: "prod_1", name: "Meja Belajar", category: "meja" },
  quantity: 1,
  config: { size: "50x80", height: 75, finishing: "Natural" },
  breakdown: { subtotal: 200, requiresConfirm: false },
};

jest.mock("../context/CartContext", () => ({
  useCart: () => ({
    items: [mockCartItem],
    productSubtotal: 200,
    clear: mockClear,
    isInvoiceCart: false,
    activeInvoice: null,
  }),
}));

jest.mock("../context/LanguageContext", () => {
  const { translate } = require("../lib/i18n");
  return {
    useLang: () => ({
      t: (key) => translate("id", key),
      lang: "id",
      dir: "ltr",
    }),
  };
});

jest.mock("../context/CustomerContext", () => ({
  useCustomer: () => ({
    customer: null,
    checked: true,
    customerLoading: false,
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

jest.mock("../lib/api", () => {
  const actual = jest.requireActual("../lib/api");
  return {
    __esModule: true,
    default: {
      get: jest.fn(),
      post: jest.fn(),
    },
    API_BASE: "http://localhost:8000/api",
    imgUrl: actual.imgUrl,
  };
});

global.IS_REACT_ACT_ENVIRONMENT = true;

const setInputValue = (input, value) => {
  const nativeSetter = Object.getOwnPropertyDescriptor(
    window.HTMLInputElement.prototype,
    "value"
  )?.set;
  if (nativeSetter) {
    nativeSetter.call(input, value);
  } else {
    input.value = value;
  }
  input.dispatchEvent(new Event("input", { bubbles: true }));
};

const setTextareaValue = (textarea, value) => {
  const nativeSetter = Object.getOwnPropertyDescriptor(
    window.HTMLTextAreaElement.prototype,
    "value"
  )?.set;
  if (nativeSetter) {
    nativeSetter.call(textarea, value);
  } else {
    textarea.value = value;
  }
  textarea.dispatchEvent(new Event("input", { bubbles: true }));
};

describe("Stage 2: Checkout, Address, Delivery Maps & Building Photo", () => {
  let container = null;
  let root = null;

  const mockZones = [
    { id: "z1", name: "Madinat Nasr", fee_le: 50, active: true },
    { id: "z2", name: "Maadi", fee_le: 70, active: true },
  ];

  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    jest.clearAllMocks();

    api.get.mockImplementation((url) => {
      if (url === "/delivery-zones") return Promise.resolve({ data: mockZones });
      if (url === "/store-info") return Promise.resolve({ data: { exchange_rate_idr_per_le: 357 } });
      return Promise.reject(new Error("Not found"));
    });
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

  test("1. Renders 'No WhatsApp' label and Cairo address placeholder & helper text", async () => {
    await act(async () => {
      root.render(<Checkout />);
    });

    // Check label "No WhatsApp"
    expect(container.textContent).toContain("No WhatsApp");

    // Check Address input placeholder and helper
    const addressInput = container.querySelector("[data-testid='input-address']");
    expect(addressInput).not.toBeNull();
    expect(addressInput.getAttribute("placeholder")).toContain("No. Imarah, jalan, area/distrik, lantai, no. syaqqoh");
    expect(container.textContent).toContain("Sebutkan no. imarah, jalan, distrik/area, lantai, & no. syaqqoh");

    // Check Building Photo section presence
    expect(container.querySelector("[data-testid='section-building-photo']")).not.toBeNull();
    expect(container.textContent).toContain("Foto Gedung / Imarah");
    expect(container.textContent).toContain("(Opsional)");
  });

  test("2. Delivery checkout is blocked when Google Maps link is missing", async () => {
    await act(async () => {
      root.render(<Checkout />);
    });

    // Select delivery
    const deliveryBtn = container.querySelector("[data-testid='delivery-delivery']");
    await act(async () => {
      deliveryBtn.click();
    });

    // Select zone
    const zoneBtn = container.querySelector("[data-testid='zone-z1']");
    await act(async () => {
      zoneBtn.click();
    });

    // Fill customer name, phone, address, payment
    const nameInput = container.querySelector("[data-testid='input-name']");
    const phoneInput = container.querySelector("[data-testid='input-phone']");
    const addressInput = container.querySelector("[data-testid='input-address']");
    const payCashBtn = container.querySelector("[data-testid='pay-cash']");

    await act(async () => {
      setInputValue(nameInput, "Ahmad Customer");
      setInputValue(phoneInput, "+201234567890");
      setTextareaValue(addressInput, "Imarah 10, Jl. Al-Tayaran, Madinat Nasr, Lt. 2");
      payCashBtn.click();
    });

    // Submit without Maps link
    const submitBtn = container.querySelector("[data-testid='submit-order']");
    await act(async () => {
      submitBtn.click();
    });

    expect(toast.error).toHaveBeenCalledWith("Link Google Maps lokasi pengiriman wajib diisi untuk pesanan delivery.");
    expect(api.post).not.toHaveBeenCalled();
  });

  test("3. Pickup checkout succeeds without Maps link", async () => {
    api.post.mockResolvedValueOnce({
      data: {
        id: "order_123",
        order_number: "SGF-20261101-001",
        total_le: 200,
      },
    });

    await act(async () => {
      root.render(<Checkout />);
    });

    // Select pickup
    const pickupBtn = container.querySelector("[data-testid='delivery-pickup']");
    await act(async () => {
      pickupBtn.click();
    });

    // Fill customer details
    const nameInput = container.querySelector("[data-testid='input-name']");
    const phoneInput = container.querySelector("[data-testid='input-phone']");
    const addressInput = container.querySelector("[data-testid='input-address']");
    const payCashBtn = container.querySelector("[data-testid='pay-cash']");

    await act(async () => {
      setInputValue(nameInput, "Budi Customer");
      setInputValue(phoneInput, "+201112223334");
      setTextareaValue(addressInput, "Hay El Asher, Cairo");
      payCashBtn.click();
    });

    // Submit with empty maps link
    const submitBtn = container.querySelector("[data-testid='submit-order']");
    await act(async () => {
      submitBtn.click();
    });

    // Should call /orders with delivery_method: "pickup" and customer_maps_url: ""
    expect(api.post).toHaveBeenCalledWith(
      "/orders",
      expect.objectContaining({
        delivery_method: "pickup",
        customer_maps_url: "",
        building_photo_url: null,
      })
    );
    expect(mockNavigate).toHaveBeenCalledWith("/pesanan/order_123", expect.any(Object));
  });

  test("4. Building photo upload validates file format and size", async () => {
    await act(async () => {
      root.render(<Checkout />);
    });

    const fileInput = container.querySelector("[data-testid='input-building-photo']");

    // Invalid format (e.g. text/plain or pdf)
    const invalidFile = new File(["dummy"], "contract.pdf", { type: "application/pdf" });
    await act(async () => {
      Object.defineProperty(fileInput, "files", { value: [invalidFile], configurable: true });
      fileInput.dispatchEvent(new Event("change", { bubbles: true }));
    });
    expect(toast.error).toHaveBeenCalledWith("Format gambar tidak didukung. Gunakan JPG, PNG, atau WebP.");

    // Excessive size (> 10MB)
    const largeFile = new File([new ArrayBuffer(11 * 1024 * 1024)], "huge.jpg", { type: "image/jpeg" });
    await act(async () => {
      Object.defineProperty(fileInput, "files", { value: [largeFile], configurable: true });
      fileInput.dispatchEvent(new Event("change", { bubbles: true }));
    });
    expect(toast.error).toHaveBeenCalledWith("Ukuran foto gedung melebihi batas 10MB.");
  });

  test("5. Valid building photo upload uploads to R2 and includes URL in order payload", async () => {
    api.post.mockImplementation((url) => {
      if (url === "/upload-building-photo") {
        return Promise.resolve({
          data: {
            path: "sogil-furniture/building-photos/test_uuid.jpg",
            url: "/api/files/sogil-furniture/building-photos/test_uuid.jpg",
          },
        });
      }
      if (url === "/orders") {
        return Promise.resolve({
          data: { id: "ord_with_photo", order_number: "SGF-PHOTO-001" },
        });
      }
      return Promise.reject(new Error("Not found"));
    });

    await act(async () => {
      root.render(<Checkout />);
    });

    // Upload a valid image
    const validFile = new File(["fake_image_bytes"], "building_facade.jpg", { type: "image/jpeg" });
    const fileInput = container.querySelector("[data-testid='input-building-photo']");

    await act(async () => {
      Object.defineProperty(fileInput, "files", { value: [validFile], configurable: true });
      fileInput.dispatchEvent(new Event("change", { bubbles: true }));
    });

    // Verify upload called and preview rendered
    expect(api.post).toHaveBeenCalledWith("/upload-building-photo", expect.any(FormData), expect.any(Object));
    expect(toast.success).toHaveBeenCalledWith("Foto gedung berhasil diunggah.");
    expect(container.querySelector("[data-testid='building-photo-preview']")).not.toBeNull();

    // Now fill required checkout fields and submit (pickup)
    const pickupBtn = container.querySelector("[data-testid='delivery-pickup']");
    const nameInput = container.querySelector("[data-testid='input-name']");
    const phoneInput = container.querySelector("[data-testid='input-phone']");
    const addressInput = container.querySelector("[data-testid='input-address']");
    const payCashBtn = container.querySelector("[data-testid='pay-cash']");
    const submitBtn = container.querySelector("[data-testid='submit-order']");

    await act(async () => {
      pickupBtn.click();
      setInputValue(nameInput, "Citra Customer");
      setInputValue(phoneInput, "+201234567890");
      setTextareaValue(addressInput, "Imarah 5, Abbasia, Cairo");
      payCashBtn.click();
      submitBtn.click();
    });

    // Verify building_photo_url passed in orderPayload
    expect(api.post).toHaveBeenCalledWith(
      "/orders",
      expect.objectContaining({
        building_photo_url: "/api/files/sogil-furniture/building-photos/test_uuid.jpg",
      })
    );
  });

  test("6. Removing building photo clears preview and resets state", async () => {
    api.post.mockResolvedValueOnce({
      data: {
        path: "sogil-furniture/building-photos/test_uuid.jpg",
        url: "/api/files/sogil-furniture/building-photos/test_uuid.jpg",
      },
    });

    await act(async () => {
      root.render(<Checkout />);
    });

    const validFile = new File(["fake_image_bytes"], "entrance.jpg", { type: "image/jpeg" });
    const fileInput = container.querySelector("[data-testid='input-building-photo']");

    await act(async () => {
      Object.defineProperty(fileInput, "files", { value: [validFile] });
      fileInput.dispatchEvent(new Event("change", { bubbles: true }));
    });

    // Verify preview is visible
    expect(container.querySelector("[data-testid='building-photo-preview']")).not.toBeNull();

    // Click remove button
    const removeBtn = container.querySelector("[data-testid='btn-remove-building-photo']");
    await act(async () => {
      removeBtn.click();
    });

    // Preview should be removed, input re-rendered
    expect(container.querySelector("[data-testid='building-photo-preview']")).toBeNull();
    expect(container.querySelector("[data-testid='input-building-photo']")).not.toBeNull();
    expect(toast.info).toHaveBeenCalledWith("Foto gedung dihapus.");
  });
});
