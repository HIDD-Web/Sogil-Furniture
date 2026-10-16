import React, { act } from "react";
import { createRoot } from "react-dom/client";

jest.mock(
  "@/lib/utils",
  () => jest.requireActual("../lib/utils"),
  { virtual: true }
);

let mockSearchParams = new URLSearchParams();
const mockSetSearchParams = jest.fn((updater) => {
  if (typeof updater === "function") {
    mockSearchParams = updater(mockSearchParams);
  } else {
    mockSearchParams = new URLSearchParams(updater);
  }
});

jest.mock(
  "react-router-dom",
  () => ({
    useSearchParams: () => [mockSearchParams, mockSetSearchParams],
    useNavigate: () => jest.fn(),
    Link: ({ children, to, ...props }) => (
      <a href={to} {...props}>
        {children}
      </a>
    ),
  }),
  { virtual: true }
);

let mockCurrentUser = {
  role: "owner",
  permissions: { manage_orders: true },
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

import { toast } from "sonner";
import api from "../lib/api";
jest.mock("../lib/api");

import AdminLogistics from "../pages/admin/AdminLogistics";

describe("AdminLogistics - Phase 3.F.4.2B Package 2 Suite", () => {
  let container = null;
  let root = null;

  const mockZones = [
    { id: "zone_nasr", name: "Nasr City", fee_le: 40.0 },
    { id: "zone_maadi", name: "Maadi", fee_le: 60.0 },
  ];

  const mockUnassignedOrders = [
    {
      id: "ord_101",
      order_number: "ORD-20261015-001",
      customer_name: "Youssef Ibrahim",
      customer_phone: "+201012345678",
      customer_address: "Street 9, Maadi, Cairo",
      customer_maps_url: "https://maps.google.com/?q=Maadi+Street+9",
      delivery_method: "delivery",
      delivery_zone_id: "zone_maadi",
      delivery_zone_name: "Maadi",
      delivery_fee_le: 60.0,
      total_le: 2400.0,
      order_status: "siap",
      delivery_logistics_status: "unassigned",
      notes: "Hubungi sebelum tiba, lantai 3",
      total_items_count: 3,
      items_summary: [
        { name: "Meja Belajar Kayu", quantity: 1 },
        { name: "Kursi Ergonomis", quantity: 2 },
      ],
      created_at: "2026-10-15T09:00:00Z",
      updated_at: "2026-10-15T09:30:00Z",
    },
    {
      id: "ord_102",
      order_number: "ORD-20261015-002",
      customer_name: "Fatima El-Sayed",
      customer_phone: "+201098765432",
      customer_address: "Abbas El-Akkad, Nasr City",
      customer_maps_url: "",
      delivery_method: "delivery",
      delivery_zone_id: "zone_nasr",
      delivery_zone_name: "Nasr City",
      delivery_fee_le: 40.0,
      total_le: 1800.0,
      order_status: "siap",
      delivery_logistics_status: "unassigned",
      notes: "",
      total_items_count: 1,
      items_summary: [{ name: "Lemari 2 Pintu", quantity: 1 }],
      created_at: "2026-10-15T09:15:00Z",
      updated_at: "2026-10-15T09:35:00Z",
    },
  ];

  const mockTrips = [
    {
      id: "trip_001",
      trip_number: "TRIP-20261015-001",
      status: "in_transit",
      scheduled_date: "2026-10-15",
      departure_time: "10:00",
      trip_wage_rate_le: 50.0,
      helpers: [
        { helper_id: "h_1", helper_name: "Ahmed Helper", helper_phone: "01001" },
        { helper_id: "h_2", helper_name: "Mahmoud Helper", helper_phone: "01002" },
      ],
      vehicle_rental: {
        is_rental: true,
        rental_vendor_name: "Armada Cairo Rent",
        vehicle_plate_number: "C-1234-EG",
        rental_driver_name: "Sameh Driver",
        cost_obligation: { agreed_rental_cost_le: 350.0 },
      },
      rate_policy_snapshot: {
        policy_version: 1,
        effective_rate_le: 50.0,
        base_wage_per_order_le: 50.0,
        rounding_policy: "piastre_round_half_up",
      },
      stops: [
        {
          stop_id: "stp_1",
          sequence: 1,
          order_id: "ord_101",
          order_number: "ORD-20261015-001",
          customer_name: "Youssef Ibrahim",
          delivery_zone: "Maadi",
          outcome: "pending",
        },
      ],
      stops_count: 4,
      delivered_stops_count: 2,
      failed_stops_count: 0,
      notes: "Rute prioritas Nasr City",
    },
    {
      id: "trip_002",
      trip_number: "TRIP-20261015-002",
      status: "completed",
      scheduled_date: "2026-10-15",
      departure_time: "08:00",
      trip_wage_rate_le: 50.0,
      helpers: [{ helper_id: "h_1", helper_name: "Ahmed Helper" }],
      vehicle_rental: {
        is_rental: false,
      },
      rate_policy_snapshot: {
        policy_version: 1,
        effective_rate_le: 50.0,
      },
      stops: [],
      stops_count: 2,
      delivered_stops_count: 2,
      failed_stops_count: 0,
      notes: "Selesai tepat waktu",
    },
    {
      id: "trip_003",
      trip_number: "TRIP-20261015-003",
      status: "scheduled",
      scheduled_date: "2026-10-15",
      departure_time: "11:00",
      trip_wage_rate_le: 50.0,
      helpers: [{ helper_id: "h_1", helper_name: "Ahmed Helper" }],
      vehicle_rental: {
        is_rental: false,
        vehicle_plate_or_desc: "Armada Toko",
        rental_driver_name: "Ahmad Toko",
      },
      rate_policy_snapshot: null,
      stops: [
        {
          stop_id: "stp_1",
          sequence: 1,
          order_id: "ord_101",
          order_number: "ORD-20261015-001",
          customer_name: "Youssef Ibrahim",
          customer_phone: "+201012345678",
          customer_address: "Street 9, Maadi, Cairo",
          customer_maps_url: "https://maps.google.com/?q=Maadi+Street+9",
          delivery_zone: "Maadi",
          outcome: "pending",
        },
        {
          stop_id: "stp_2",
          sequence: 2,
          order_id: "ord_102",
          order_number: "ORD-20261015-002",
          customer_name: "Fatima El-Sayed",
          customer_phone: "+201098765432",
          customer_address: "Abbas El-Akkad, Nasr City",
          customer_maps_url: "",
          delivery_zone: "Nasr City",
          outcome: "pending",
        },
      ],
      stops_count: 2,
      delivered_stops_count: 0,
      failed_stops_count: 0,
      notes: "Trip terjadwal",
    },
  ];

  const mockWorkers = [
    { id: "w_1", name: "Ahmed Helper", role: "helper" },
    { id: "w_2", name: "Mahmoud Helper", role: "helper" },
  ];

  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);

    mockSearchParams = new URLSearchParams();
    mockCurrentUser = {
      role: "owner",
      permissions: { manage_orders: true },
    };

    api.get.mockReset();
    api.post.mockReset();
    api.delete.mockReset();
    api.patch.mockReset();
    toast.success.mockReset();
    toast.error.mockReset();

    api.get.mockImplementation((url) => {
      if (url === "/delivery-zones") {
        return Promise.resolve({ data: mockZones });
      }
      if (url === "/admin/workers") {
        return Promise.resolve({ data: mockWorkers });
      }
      if (url === "/admin/delivery-trips/unassigned-orders") {
        return Promise.resolve({ data: mockUnassignedOrders });
      }
      if (url === "/admin/delivery-trips") {
        return Promise.resolve({ data: mockTrips });
      }
      if (url === "/admin/delivery-trips/trip_003") {
        return Promise.resolve({ data: mockTrips[2] });
      }
      if (url.startsWith("/admin/delivery-trips/")) {
        return Promise.resolve({ data: mockTrips[0] });
      }
      return Promise.reject(new Error(`Unhandled GET url: ${url}`));
    });
  });

  afterEach(async () => {
    if (root) {
      await act(async () => {
        root.unmount();
      });
    }
    if (container && container.parentNode) {
      container.parentNode.removeChild(container);
    }
  });

  test("1. Blocks access for unauthorized staff lacking manage_orders permission", async () => {
    mockCurrentUser = {
      role: "staff",
      permissions: { manage_orders: false },
    };

    await act(async () => {
      root.render(<AdminLogistics />);
    });

    expect(container.querySelector('[data-testid="access-restricted"]')).not.toBeNull();
    expect(container.textContent).toContain("Akses Terbatas");
    expect(container.textContent).toContain("hanya dapat diakses oleh Dispatcher");
    expect(api.get).not.toHaveBeenCalled();
  });

  test("2. Mounts successfully for authorized user, loads metrics, zones, and ready queue", async () => {
    await act(async () => {
      root.render(<AdminLogistics />);
    });

    expect(container.querySelector('[data-testid="admin-logistics-page"]')).not.toBeNull();
    expect(container.textContent).toContain("Logistik & Dispatcher Armada");

    // Check summary metric cards
    expect(container.querySelector('[data-testid="stat-ready-queue"]')).not.toBeNull();
    expect(container.querySelector('[data-testid="stat-ready-queue"]').textContent).toContain("2");
    expect(container.querySelector('[data-testid="stat-active-trips"]').textContent).toContain("2");
    expect(container.querySelector('[data-testid="stat-completed-trips"]').textContent).toContain("1");

    // Check orders rendered in Ready Queue
    expect(container.querySelector('[data-testid="order-card-ORD-20261015-001"]')).not.toBeNull();
    expect(container.textContent).toContain("Youssef Ibrahim");
    expect(container.textContent).toContain("Street 9, Maadi, Cairo");
    expect(container.textContent).toContain("2.400 LE");
    expect(container.textContent).toContain("Meja Belajar Kayu");
    expect(container.textContent).toContain("Catatan: Hubungi sebelum tiba");

    // Check Google Maps external link
    const mapsLink = container.querySelector('a[href="https://maps.google.com/?q=Maadi+Street+9"]');
    expect(mapsLink).not.toBeNull();
    expect(mapsLink.getAttribute("target")).toBe("_blank");
    expect(mapsLink.getAttribute("rel")).toBe("noopener noreferrer");
    expect(mapsLink.textContent).toContain("Buka Google Maps");
  });

  test("3. Handles empty Ready Queue state gracefully", async () => {
    api.get.mockImplementation((url) => {
      if (url === "/delivery-zones") return Promise.resolve({ data: [] });
      if (url === "/admin/delivery-trips/unassigned-orders") return Promise.resolve({ data: [] });
      if (url === "/admin/delivery-trips") return Promise.resolve({ data: [] });
      return Promise.reject(new Error("Unknown"));
    });

    await act(async () => {
      root.render(<AdminLogistics />);
    });

    expect(container.textContent).toContain("Tidak ada pesanan dalam antrean siap kirim");
  });

  test("4. Handles Ready Queue fetch error with retry capability", async () => {
    api.get.mockImplementation((url) => {
      if (url === "/delivery-zones") return Promise.resolve({ data: [] });
      if (url === "/admin/delivery-trips/unassigned-orders") {
        return Promise.reject({ response: { data: { detail: "Database connection failed" } } });
      }
      if (url === "/admin/delivery-trips") return Promise.resolve({ data: [] });
      return Promise.reject(new Error("Unknown"));
    });

    await act(async () => {
      root.render(<AdminLogistics />);
    });

    expect(container.textContent).toContain("Gagal memuat antrean pengiriman");
    expect(container.textContent).toContain("Database connection failed");
    expect(container.textContent).toContain("Coba Lagi");
  });

  test("5. Ready Queue searches and filters by query and zone", async () => {
    await act(async () => {
      root.render(<AdminLogistics />);
    });

    const searchInput = container.querySelector('[data-testid="ready-queue-search"]');
    const form = searchInput.closest("form");

    await act(async () => {
      const nativeInputSetter = Object.getOwnPropertyDescriptor(
        window.HTMLInputElement.prototype,
        "value"
      ).set;
      nativeInputSetter.call(searchInput, "Maadi");
      searchInput.dispatchEvent(new Event("input", { bubbles: true }));
    });

    await act(async () => {
      form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    });

    expect(api.get).toHaveBeenCalledWith(
      "/admin/delivery-trips/unassigned-orders",
      expect.objectContaining({ params: expect.objectContaining({ q: "Maadi" }) })
    );

    const zoneSelect = container.querySelector('[data-testid="ready-queue-zone-filter"]');
    await act(async () => {
      const nativeSelectSetter = Object.getOwnPropertyDescriptor(
        window.HTMLSelectElement.prototype,
        "value"
      ).set;
      nativeSelectSetter.call(zoneSelect, "zone_nasr");
      zoneSelect.dispatchEvent(new Event("change", { bubbles: true }));
    });

    expect(api.get).toHaveBeenCalledWith(
      "/admin/delivery-trips/unassigned-orders",
      expect.objectContaining({ params: expect.objectContaining({ delivery_zone_id: "zone_nasr" }) })
    );
  });

  test("6. Switches to Trip List tab and displays trips with rental, helpers, progress and snapshot rate", async () => {
    mockSearchParams = new URLSearchParams("tab=trips");

    await act(async () => {
      root.render(<AdminLogistics />);
    });

    expect(container.querySelector('[data-testid="trip-card-TRIP-20261015-001"]')).not.toBeNull();
    expect(container.textContent).toContain("TRIP-20261015-001");
    expect(container.textContent).toContain("Sedang Jalan");
    expect(container.textContent).toContain("Armada Cairo Rent");
    expect(container.textContent).toContain("Plat: C-1234-EG");
    expect(container.textContent).toContain("Driver: Sameh Driver");
    expect(container.textContent).toContain("Biaya Sewa: 350 LE");
    expect(container.textContent).toContain("Ahmed Helper");
    expect(container.textContent).toContain("Mahmoud Helper");
    expect(container.textContent).toContain("Progress Stop: 2 / 4 Selesai (50%)");
    expect(container.textContent).toContain("Tersnapshot V1");
    expect(container.textContent).toContain("Tarif: 50 LE / pesanan");

    // Internal vehicle trip check
    expect(container.querySelector('[data-testid="trip-card-TRIP-20261015-002"]')).not.toBeNull();
    expect(container.textContent).toContain("Armada Toko");
    expect(container.textContent).toContain("Selesai");
  });

  test("7. Status filter on Trip List calls API with selected status", async () => {
    mockSearchParams = new URLSearchParams("tab=trips");

    await act(async () => {
      root.render(<AdminLogistics />);
    });

    const statusGroup = container.querySelector('[data-testid="trip-status-filter"]');
    const scheduledBtn = Array.from(statusGroup.querySelectorAll("button")).find(
      (b) => b.textContent.trim() === "Dijadwalkan"
    );

    await act(async () => {
      scheduledBtn.click();
    });

    expect(api.get).toHaveBeenCalledWith(
      "/admin/delivery-trips",
      expect.objectContaining({ params: expect.objectContaining({ status: "scheduled" }) })
    );
  });

  test("8. Refresh button re-fetches both Ready Queue and Trips", async () => {
    await act(async () => {
      root.render(<AdminLogistics />);
    });

    const refreshBtn = container.querySelector('[data-testid="btn-refresh"]');
    expect(refreshBtn).not.toBeNull();

    await act(async () => {
      refreshBtn.click();
    });

    expect(api.get).toHaveBeenCalledWith("/admin/delivery-trips/unassigned-orders", expect.any(Object));
    expect(api.get).toHaveBeenCalledWith("/admin/delivery-trips", expect.any(Object));
  });

  test("9. Does not render Google Maps link if customer_maps_url is empty", async () => {
    await act(async () => {
      root.render(<AdminLogistics />);
    });

    const card2 = container.querySelector('[data-testid="order-card-ORD-20261015-002"]');
    expect(card2).not.toBeNull();
    expect(card2.querySelector('a[href^="https://maps.google.com"]')).toBeNull();
  });

  test("10. Handles trips fetch error with retry button", async () => {
    mockSearchParams = new URLSearchParams("tab=trips");
    api.get.mockImplementation((url) => {
      if (url === "/delivery-zones") return Promise.resolve({ data: [] });
      if (url === "/admin/workers") return Promise.resolve({ data: [] });
      if (url === "/admin/delivery-trips/unassigned-orders") return Promise.resolve({ data: [] });
      if (url === "/admin/delivery-trips") {
        return Promise.reject({ response: { data: { detail: "Failed to fetch trips" } } });
      }
      return Promise.reject(new Error("Unknown"));
    });

    await act(async () => {
      root.render(<AdminLogistics />);
    });

    expect(container.textContent).toContain("Gagal memuat daftar trip");
    expect(container.textContent).toContain("Failed to fetch trips");
    expect(container.textContent).toContain("Coba Lagi");
  });

  test("11. Renders trip with failed stops warning and unsnapshotted draft rate", async () => {
    mockSearchParams = new URLSearchParams("tab=trips");
    const tripWithWarning = [
      {
        id: "trip_003",
        trip_number: "TRIP-20261015-003",
        status: "draft",
        scheduled_date: "2026-10-16",
        departure_time: "14:00",
        trip_wage_rate_le: 45.0,
        helpers: [],
        vehicle_rental: null,
        rate_policy_snapshot: null,
        stops_count: 5,
        delivered_stops_count: 3,
        failed_stops_count: 2,
        notes: "Ada kendala alamat",
      },
    ];

    api.get.mockImplementation((url) => {
      if (url === "/delivery-zones") return Promise.resolve({ data: [] });
      if (url === "/admin/workers") return Promise.resolve({ data: [] });
      if (url === "/admin/delivery-trips/unassigned-orders") return Promise.resolve({ data: [] });
      if (url === "/admin/delivery-trips") return Promise.resolve({ data: tripWithWarning });
      return Promise.reject(new Error("Unknown"));
    });

    await act(async () => {
      root.render(<AdminLogistics />);
    });

    expect(container.textContent).toContain("TRIP-20261015-003");
    expect(container.textContent).toContain("Draft");
    expect(container.textContent).toContain("2 stop tertunda / gagal kirim");
    expect(container.textContent).toContain("Belum ada helper ditugaskan");
    expect(container.textContent).toContain("Rencana Tarif: 45 LE / pesanan");
    expect(container.textContent).toContain("Snapshot permanen akan terkunci saat dispatch");
  });

  test("12. Date filter on Trip List updates scheduled_date parameter", async () => {
    mockSearchParams = new URLSearchParams("tab=trips");

    await act(async () => {
      root.render(<AdminLogistics />);
    });

    const dateInput = container.querySelector('input[type="date"]');
    expect(dateInput).not.toBeNull();

    await act(async () => {
      const nativeInputSetter = Object.getOwnPropertyDescriptor(
        window.HTMLInputElement.prototype,
        "value"
      ).set;
      nativeInputSetter.call(dateInput, "2026-10-18");
      dateInput.dispatchEvent(new Event("input", { bubbles: true }));
      dateInput.dispatchEvent(new Event("change", { bubbles: true }));
    });

    expect(api.get).toHaveBeenCalledWith(
      "/admin/delivery-trips",
      expect.objectContaining({ params: expect.objectContaining({ scheduled_date: "2026-10-18" }) })
    );
  });

  test("13. Trip Creation modal opens, validates rental fields, and submits POST /admin/delivery-trips", async () => {
    api.post.mockResolvedValueOnce({
      data: {
        id: "trip_new",
        trip_number: "TRIP-20261015-099",
        status: "draft",
        stops: []
      }
    });

    await act(async () => {
      root.render(<AdminLogistics />);
    });

    const createBtn = container.querySelector('[data-testid="btn-create-trip"]');
    expect(createBtn).not.toBeNull();

    await act(async () => {
      createBtn.click();
    });

    const modal = container.querySelector('[data-testid="modal-create-trip"]');
    expect(modal).not.toBeNull();

    // Fill in rental fields
    const providerInput = container.querySelector('[data-testid="input-rental-provider"]');
    const plateInput = container.querySelector('[data-testid="input-rental-plate"]');
    const driverInput = container.querySelector('[data-testid="input-rental-driver"]');

    const nativeInputSetter = Object.getOwnPropertyDescriptor(
      window.HTMLInputElement.prototype,
      "value"
    ).set;

    await act(async () => {
      nativeInputSetter.call(providerInput, "Rental Nile Cairo");
      providerInput.dispatchEvent(new Event("input", { bubbles: true }));

      nativeInputSetter.call(plateInput, "CA-9988");
      plateInput.dispatchEvent(new Event("input", { bubbles: true }));

      nativeInputSetter.call(driverInput, "Tariq Driver");
      driverInput.dispatchEvent(new Event("input", { bubbles: true }));
    });

    const submitBtn = container.querySelector('[data-testid="btn-submit-create-trip"]');
    await act(async () => {
      submitBtn.click();
    });

    expect(api.post).toHaveBeenCalledWith(
      "/admin/delivery-trips",
      expect.objectContaining({
        scheduled_date: expect.any(String),
        trip_wage_rate_le: 50,
        vehicle_rental: expect.objectContaining({
          is_rented: true,
          rental_provider: "Rental Nile Cairo",
          vehicle_plate_or_desc: "CA-9988",
          rental_driver_name: "Tariq Driver",
          agreed_rental_cost_le: 350
        })
      })
    );
  });

  test("14. Trip Creation supports internal vehicle type", async () => {
    api.post.mockResolvedValueOnce({
      data: {
        id: "trip_internal",
        trip_number: "TRIP-20261015-100",
        status: "draft"
      }
    });

    await act(async () => {
      root.render(<AdminLogistics />);
    });

    await act(async () => {
      container.querySelector('[data-testid="btn-create-trip"]').click();
    });

    const internalBtn = container.querySelector('[data-testid="btn-vehicle-internal"]');
    await act(async () => {
      internalBtn.click();
    });

    const plateInput = container.querySelector('[data-testid="input-internal-plate"]');
    const driverInput = container.querySelector('[data-testid="input-internal-driver"]');

    const nativeInputSetter = Object.getOwnPropertyDescriptor(
      window.HTMLInputElement.prototype,
      "value"
    ).set;

    await act(async () => {
      nativeInputSetter.call(plateInput, "Pickup Toko Sogil 01");
      plateInput.dispatchEvent(new Event("input", { bubbles: true }));

      nativeInputSetter.call(driverInput, "Karim Supir Toko");
      driverInput.dispatchEvent(new Event("input", { bubbles: true }));
    });

    await act(async () => {
      container.querySelector('[data-testid="btn-submit-create-trip"]').click();
    });

    expect(api.post).toHaveBeenCalledWith(
      "/admin/delivery-trips",
      expect.objectContaining({
        vehicle_rental: expect.objectContaining({
          is_rented: false,
          rental_provider: "Armada Toko",
          vehicle_plate_or_desc: "Pickup Toko Sogil 01",
          rental_driver_name: "Karim Supir Toko",
          agreed_rental_cost_le: 0
        })
      })
    );
  });

  test("15. Multi-order selection in Ready Queue toggles selection and opens assignment modal", async () => {
    await act(async () => {
      root.render(<AdminLogistics />);
    });

    const chk1 = container.querySelector('[data-testid="checkbox-order-ORD-20261015-001"]');
    const chk2 = container.querySelector('[data-testid="checkbox-order-ORD-20261015-002"]');

    await act(async () => {
      chk1.click();
      chk2.click();
    });

    const assignBtn = container.querySelector('[data-testid="btn-assign-selected"]');
    expect(assignBtn).not.toBeNull();
    expect(assignBtn.textContent).toContain("2 Pesanan");

    await act(async () => {
      assignBtn.click();
    });

    const modal = container.querySelector('[data-testid="modal-assign-orders"]');
    expect(modal).not.toBeNull();
    expect(modal.textContent).toContain("2 pesanan");
  });

  test("16. Multi-order assignment executes POST /admin/delivery-trips/{trip_id}/stops for selected orders", async () => {
    api.post.mockResolvedValue({ data: { ok: true } });

    await act(async () => {
      root.render(<AdminLogistics />);
    });

    // Select order 1
    await act(async () => {
      container.querySelector('[data-testid="checkbox-order-ORD-20261015-001"]').click();
    });

    await act(async () => {
      container.querySelector('[data-testid="btn-assign-selected"]').click();
    });

    const confirmBtn = container.querySelector('[data-testid="btn-confirm-assign-orders"]');
    expect(confirmBtn).not.toBeNull();

    await act(async () => {
      confirmBtn.click();
    });

    expect(api.post).toHaveBeenCalledWith(
      "/admin/delivery-trips/trip_003/stops",
      { order_id: "ord_101" }
    );
  });

  test("17. Concurrency conflict (HTTP 409) during order assignment shows warning and auto-refreshes", async () => {
    api.post.mockRejectedValueOnce({
      response: {
        status: 409,
        data: { detail: "Konflik penugasan: pesanan telah diklaim proses lain." }
      }
    });

    await act(async () => {
      root.render(<AdminLogistics />);
    });

    await act(async () => {
      container.querySelector('[data-testid="checkbox-order-ORD-20261015-001"]').click();
    });

    await act(async () => {
      container.querySelector('[data-testid="btn-assign-selected"]').click();
    });

    await act(async () => {
      container.querySelector('[data-testid="btn-confirm-assign-orders"]').click();
    });

    // Verifies auto-refresh was dispatched
    expect(api.get).toHaveBeenCalledWith(
      "/admin/delivery-trips/unassigned-orders",
      expect.any(Object)
    );
  });

  test("18. Manage Stops modal displays stops and Google Maps multi-stop route link", async () => {
    mockSearchParams = new URLSearchParams("tab=trips");

    await act(async () => {
      root.render(<AdminLogistics />);
    });

    const manageBtn = container.querySelector('[data-testid="btn-manage-stops-TRIP-20261015-003"]');
    expect(manageBtn).not.toBeNull();

    await act(async () => {
      manageBtn.click();
    });

    const modal = container.querySelector('[data-testid="modal-manage-stops"]');
    expect(modal).not.toBeNull();
    expect(modal.textContent).toContain("Stop & Rute Pengiriman: TRIP-20261015-003");

    // Check multi-stop route link
    const multiMapsBtn = container.querySelector('[data-testid="btn-open-multi-stop-maps"]');
    expect(multiMapsBtn).not.toBeNull();
    const href = multiMapsBtn.getAttribute("href");
    expect(href).toContain("google.com/maps/dir");
    expect(href).toContain("destination=Abbas%20El-Akkad%2C%20Nasr%20City");
    expect(href).toContain("waypoints=Maadi%20Street%209");
    expect(multiMapsBtn.getAttribute("target")).toBe("_blank");
  });

  test("19. Release stop opens confirmation dialog and executes DELETE /admin/delivery-trips/{trip_id}/stops/{order_id}", async () => {
    mockSearchParams = new URLSearchParams("tab=trips");
    api.delete.mockResolvedValueOnce({
      data: {
        ...mockTrips[2],
        stops: []
      }
    });

    await act(async () => {
      root.render(<AdminLogistics />);
    });

    await act(async () => {
      container.querySelector('[data-testid="btn-manage-stops-TRIP-20261015-003"]').click();
    });

    const releaseBtn = container.querySelector('[data-testid="btn-release-stop-ORD-20261015-001"]');
    expect(releaseBtn).not.toBeNull();

    await act(async () => {
      releaseBtn.click();
    });

    const dialog = container.querySelector('[data-testid="dialog-confirm-release"]');
    expect(dialog).not.toBeNull();
    expect(dialog.textContent).toContain("Konfirmasi Lepas Pesanan");

    const confirmReleaseBtn = container.querySelector('[data-testid="btn-confirm-release-submit"]');
    await act(async () => {
      confirmReleaseBtn.click();
    });

    expect(api.delete).toHaveBeenCalledWith("/admin/delivery-trips/trip_003/stops/ord_101");
  });

  test("20. getStopMapUrl gives highest precedence to customer_maps_url when present", () => {
    const { getStopMapUrl } = require("../pages/admin/AdminLogistics");
    const stopWithMapUrl = {
      customer_maps_url: "https://maps.app.goo.gl/xyz123",
      customer_address: "Street 9, Maadi, Cairo",
      delivery_zone: "Maadi",
    };
    expect(getStopMapUrl(stopWithMapUrl)).toBe("https://maps.app.goo.gl/xyz123");

    const stopWithTrimmedMapUrl = {
      customer_maps_url: "   https://maps.google.com/?q=Cairo+Festival+City   ",
      customer_address: "New Cairo",
      delivery_zone: "New Cairo",
    };
    expect(getStopMapUrl(stopWithTrimmedMapUrl)).toBe("https://maps.google.com/?q=Cairo+Festival+City");
  });

  test("21. getStopMapUrl uses stored customer_address when customer_maps_url is absent", () => {
    const { getStopMapUrl } = require("../pages/admin/AdminLogistics");
    const stopWithAddressOnly = {
      customer_maps_url: "",
      customer_address: "Abbas El-Akkad, Nasr City",
      delivery_zone: "Nasr City",
    };
    expect(getStopMapUrl(stopWithAddressOnly)).toBe(
      "https://www.google.com/maps/search/?api=1&query=Abbas%20El-Akkad%2C%20Nasr%20City"
    );

    const stopWithNullMapUrl = {
      customer_maps_url: null,
      customer_address: "Street 9, Maadi, Cairo",
      delivery_zone: "Maadi",
    };
    expect(getStopMapUrl(stopWithNullMapUrl)).toBe(
      "https://www.google.com/maps/search/?api=1&query=Street%209%2C%20Maadi%2C%20Cairo"
    );
  });

  test("22. getStopMapUrl uses delivery_zone strictly as fallback when both Maps URL and address are missing", () => {
    const { getStopMapUrl } = require("../pages/admin/AdminLogistics");
    const stopWithZoneOnly = {
      customer_maps_url: "",
      customer_address: null,
      delivery_zone: "Heliopolis",
    };
    expect(getStopMapUrl(stopWithZoneOnly)).toBe(
      "https://www.google.com/maps/search/?api=1&query=Heliopolis"
    );
  });

  test("23. getStopMapUrl returns null when customer_maps_url, customer_address, and delivery_zone are all missing", () => {
    const { getStopMapUrl } = require("../pages/admin/AdminLogistics");
    expect(getStopMapUrl(null)).toBeNull();
    expect(getStopMapUrl({})).toBeNull();
    expect(
      getStopMapUrl({
        customer_maps_url: "   ",
        customer_address: "",
        delivery_zone: null,
      })
    ).toBeNull();
  });

  test("24. extractLocationFromMapsUrl safely parses q, query, daddr, ll, and /@lat,lng coordinates", () => {
    const { extractLocationFromMapsUrl } = require("../pages/admin/AdminLogistics");
    expect(extractLocationFromMapsUrl(null)).toBeNull();
    expect(extractLocationFromMapsUrl("")).toBeNull();
    expect(extractLocationFromMapsUrl("   ")).toBeNull();

    // q param
    expect(
      extractLocationFromMapsUrl("https://maps.google.com/?q=30.0588,31.3456")
    ).toBe("30.0588,31.3456");

    // query param
    expect(
      extractLocationFromMapsUrl("https://www.google.com/maps/search/?api=1&query=Street%209%2C%20Maadi")
    ).toBe("Street 9, Maadi");

    // daddr param
    expect(
      extractLocationFromMapsUrl("https://maps.google.com/maps?daddr=Abbas+El-Akkad,+Nasr+City")
    ).toBe("Abbas El-Akkad, Nasr City");

    // ll param
    expect(
      extractLocationFromMapsUrl("https://maps.google.com/?ll=30.0444,31.2357")
    ).toBe("30.0444,31.2357");

    // /@latitude,longitude coordinate path
    expect(
      extractLocationFromMapsUrl("https://www.google.com/maps/@30.044420,31.235712,17z")
    ).toBe("30.044420,31.235712");

    expect(
      extractLocationFromMapsUrl("https://www.google.com/maps/place/Cafe/@30.044420,31.235712,17z/data=...")
    ).toBe("30.044420,31.235712");

    // Unparseable / shortlink / arbitrary text safely returns null
    expect(extractLocationFromMapsUrl("https://maps.app.goo.gl/shortlink123")).toBeNull();
    expect(extractLocationFromMapsUrl("https://www.google.com/maps/place/")).toBeNull();
    expect(extractLocationFromMapsUrl("not a valid url")).toBeNull();
    expect(extractLocationFromMapsUrl("https://www.google.com/maps/@999.0,999.0")).toBeNull();
  });

  test("25. buildGoogleMapsMultiStopUrl gives first precedence to usable customer_maps_url over address", () => {
    const { buildGoogleMapsMultiStopUrl } = require("../pages/admin/AdminLogistics");
    const stops = [
      {
        customer_maps_url: "https://maps.google.com/?q=30.0123,31.2345",
        customer_address: "General Maadi Address",
        delivery_zone: "Maadi",
      },
      {
        customer_maps_url: "https://www.google.com/maps/@30.0500,31.3500,16z",
        customer_address: "General Nasr City Address",
        delivery_zone: "Nasr City",
      },
    ];
    const url = buildGoogleMapsMultiStopUrl(stops);
    expect(url).toContain("destination=30.0500%2C31.3500");
    expect(url).toContain("waypoints=30.0123%2C31.2345");
  });

  test("26. buildGoogleMapsMultiStopUrl falls back to customer_address when customer_maps_url is unparseable", () => {
    const { buildGoogleMapsMultiStopUrl } = require("../pages/admin/AdminLogistics");
    const stops = [
      {
        customer_maps_url: "https://maps.app.goo.gl/shortlink123",
        customer_address: "Street 9, Maadi, Cairo",
        delivery_zone: "Maadi",
      },
      {
        customer_maps_url: "not-a-valid-url",
        customer_address: "Abbas El-Akkad, Nasr City",
        delivery_zone: "Nasr City",
      },
    ];
    const url = buildGoogleMapsMultiStopUrl(stops);
    expect(url).toContain("destination=Abbas%20El-Akkad%2C%20Nasr%20City");
    expect(url).toContain("waypoints=Street%209%2C%20Maadi%2C%20Cairo");
  });

  test("27. buildGoogleMapsMultiStopUrl falls back to delivery_zone when customer_maps_url and address are missing", () => {
    const { buildGoogleMapsMultiStopUrl } = require("../pages/admin/AdminLogistics");
    const stops = [
      {
        customer_maps_url: "",
        customer_address: null,
        delivery_zone: "Maadi",
      },
      {
        customer_maps_url: null,
        customer_address: "   ",
        delivery_zone: "Nasr City",
      },
    ];
    const url = buildGoogleMapsMultiStopUrl(stops);
    expect(url).toContain("destination=Nasr%20City");
    expect(url).toContain("waypoints=Maadi");
  });

  test("28. buildGoogleMapsMultiStopUrl returns null when all destinations are missing or invalid", () => {
    const { buildGoogleMapsMultiStopUrl } = require("../pages/admin/AdminLogistics");
    expect(buildGoogleMapsMultiStopUrl([])).toBeNull();
    expect(buildGoogleMapsMultiStopUrl(null)).toBeNull();
    expect(buildGoogleMapsMultiStopUrl(undefined)).toBeNull();

    const emptyStops = [
      { customer_maps_url: "", customer_address: "", delivery_zone: "" },
      { customer_maps_url: "   ", customer_address: null, delivery_zone: null },
    ];
    expect(buildGoogleMapsMultiStopUrl(emptyStops)).toBeNull();
  });

  test("29. buildGoogleMapsMultiStopUrl preserves stop ordering, URL encoding, and handles omitted invalid stops", () => {
    const { buildGoogleMapsMultiStopUrl } = require("../pages/admin/AdminLogistics");

    // Single valid stop returns search query URL
    const singleStop = [{ customer_address: "Abbas El-Akkad, Nasr City" }];
    expect(buildGoogleMapsMultiStopUrl(singleStop)).toBe(
      "https://www.google.com/maps/search/?api=1&query=Abbas%20El-Akkad%2C%20Nasr%20City"
    );

    // Stop 2 is completely empty and should be safely omitted without breaking ordering of stop 1 and stop 3
    const stopsWithGap = [
      {
        customer_address: "Street 9, Maadi, Cairo",
        delivery_zone: "Maadi",
      },
      {
        customer_maps_url: "",
        customer_address: "",
        delivery_zone: "",
      },
      {
        customer_address: "Abbas El-Akkad, Nasr City",
        delivery_zone: "Nasr City",
      },
    ];
    const url = buildGoogleMapsMultiStopUrl(stopsWithGap);
    expect(url).toBe(
      "https://www.google.com/maps/dir/?api=1&destination=Abbas%20El-Akkad%2C%20Nasr%20City&waypoints=Street%209%2C%20Maadi%2C%20Cairo"
    );
  });

  test("30. Dispatch confirmation modal displays planned rate and permanent snapshot warning", async () => {
    mockSearchParams = new URLSearchParams("tab=trips");

    await act(async () => {
      root.render(<AdminLogistics />);
    });

    const dispatchBtn = container.querySelector(
      '[data-testid="btn-dispatch-trip-TRIP-20261015-003"]'
    );
    expect(dispatchBtn).not.toBeNull();

    await act(async () => {
      dispatchBtn.click();
    });

    const modal = container.querySelector('[data-testid="modal-confirm-dispatch"]');
    expect(modal).not.toBeNull();
    expect(modal.textContent).toContain("Konfirmasi Dispatch Armada Pengiriman");
    expect(modal.textContent).toContain("50 LE");
    expect(modal.textContent).toContain("Penting: Snapshot Kebijakan Upah Dikunci Permanen");

    // Close modal
    const cancelBtn = container.querySelector('[data-testid="btn-cancel-dispatch"]');
    await act(async () => {
      cancelBtn.click();
    });

    expect(container.querySelector('[data-testid="modal-confirm-dispatch"]')).toBeNull();
    expect(api.patch).not.toHaveBeenCalled();
  });

  test("31. Dispatch fails closed with HTTP 422 error display when wage cap is missing/invalid", async () => {
    mockSearchParams = new URLSearchParams("tab=trips");
    const failClosedDetail =
      "Batas atas upah pengiriman (cap) belum ditetapkan oleh Owner. Penetapan tarif dan dispatch trip terkunci (Fail-Closed).";

    api.patch.mockRejectedValueOnce({
      response: {
        status: 422,
        data: { detail: failClosedDetail },
      },
    });

    await act(async () => {
      root.render(<AdminLogistics />);
    });

    await act(async () => {
      container
        .querySelector('[data-testid="btn-dispatch-trip-TRIP-20261015-003"]')
        .click();
    });

    const submitBtn = container.querySelector(
      '[data-testid="btn-confirm-dispatch-submit"]'
    );
    await act(async () => {
      submitBtn.click();
    });

    // Modal stays open and displays error alert
    const errorAlert = container.querySelector('[data-testid="dispatch-error-alert"]');
    expect(errorAlert).not.toBeNull();
    expect(errorAlert.textContent).toContain(failClosedDetail);

    // Modal is still present
    expect(container.querySelector('[data-testid="modal-confirm-dispatch"]')).not.toBeNull();
  });

  test("32. Successful dispatch calls PATCH /status with in_transit and displays locked snapshot", async () => {
    mockSearchParams = new URLSearchParams("tab=trips");
    const dispatchedTrip = {
      ...mockTrips[2],
      status: "in_transit",
      rate_policy_snapshot: {
        policy_version: 1,
        effective_rate_le: 50.0,
        applied_rate_le: 50.0,
        max_cap_at_dispatch_le: 100.0,
        locked_at: "2026-10-15T12:00:00Z",
        rounding_policy: "piastre_round_half_up",
      },
    };

    api.patch.mockResolvedValueOnce({
      data: dispatchedTrip,
    });

    await act(async () => {
      root.render(<AdminLogistics />);
    });

    await act(async () => {
      container
        .querySelector('[data-testid="btn-dispatch-trip-TRIP-20261015-003"]')
        .click();
    });

    await act(async () => {
      container
        .querySelector('[data-testid="btn-confirm-dispatch-submit"]')
        .click();
    });

    expect(api.patch).toHaveBeenCalledWith(
      "/admin/delivery-trips/trip_003/status",
      { target_status: "in_transit" }
    );

    // Modal closes
    expect(container.querySelector('[data-testid="modal-confirm-dispatch"]')).toBeNull();
  });

  test("33. Cancel modal requires non-empty reason of at least 5 characters (3 and 4 chars disabled)", async () => {
    mockSearchParams = new URLSearchParams("tab=trips");

    await act(async () => {
      root.render(<AdminLogistics />);
    });

    const cancelBtn = container.querySelector(
      '[data-testid="btn-cancel-trip-TRIP-20261015-003"]'
    );
    expect(cancelBtn).not.toBeNull();

    await act(async () => {
      cancelBtn.click();
    });

    const modal = container.querySelector('[data-testid="modal-confirm-cancel"]');
    expect(modal).not.toBeNull();
    expect(modal.textContent).toContain("Konfirmasi Pembatalan Trip Pengiriman");

    const submitBtn = container.querySelector(
      '[data-testid="btn-confirm-cancel-submit"]'
    );
    // Initially disabled because reason is empty
    expect(submitBtn.disabled).toBe(true);

    const reasonInput = container.querySelector(
      '[data-testid="input-cancel-reason"]'
    );

    const setInputValue = async (val) => {
      await act(async () => {
        const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
          window.HTMLTextAreaElement.prototype,
          "value"
        ).set;
        nativeInputValueSetter.call(reasonInput, val);
        reasonInput.dispatchEvent(new Event("change", { bubbles: true }));
      });
    };

    // 2 characters -> disabled
    await setInputValue("no");
    expect(submitBtn.disabled).toBe(true);

    // 3 characters ("Ban", or trimmed "  abc  ") -> cannot be submitted (disabled)
    await setInputValue("Ban");
    expect(submitBtn.disabled).toBe(true);
    await setInputValue("  abc  ");
    expect(submitBtn.disabled).toBe(true);

    // 4 characters ("Rusa", or trimmed " 1234 ") -> cannot be submitted (disabled)
    await setInputValue("Rusa");
    expect(submitBtn.disabled).toBe(true);
    await setInputValue(" 1234 ");
    expect(submitBtn.disabled).toBe(true);

    // 5 trimmed characters ("Rusak") -> can be submitted (enabled)
    await setInputValue("Rusak");
    expect(submitBtn.disabled).toBe(false);

    // Whitespace with 5 trimmed characters ("  Rusak  ") -> can be submitted (enabled)
    await setInputValue("  Rusak  ");
    expect(submitBtn.disabled).toBe(false);

    // >5 trimmed characters -> can be submitted (enabled)
    await setInputValue("  Armada rental mogok  ");
    expect(submitBtn.disabled).toBe(false);
  });

  test("34. Successful cancellation calls POST /cancel and refreshes ready queue", async () => {
    mockSearchParams = new URLSearchParams("tab=trips");
    const cancelledTrip = {
      ...mockTrips[2],
      status: "cancelled",
    };

    api.post.mockResolvedValueOnce({
      data: cancelledTrip,
    });

    await act(async () => {
      root.render(<AdminLogistics />);
    });

    await act(async () => {
      container
        .querySelector('[data-testid="btn-cancel-trip-TRIP-20261015-003"]')
        .click();
    });

    const reasonInput = container.querySelector(
      '[data-testid="input-cancel-reason"]'
    );
    await act(async () => {
      const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
        window.HTMLTextAreaElement.prototype,
        "value"
      ).set;
      nativeInputValueSetter.call(reasonInput, "Kendala armada darurat");
      reasonInput.dispatchEvent(new Event("change", { bubbles: true }));
    });

    await act(async () => {
      container
        .querySelector('[data-testid="btn-confirm-cancel-submit"]')
        .click();
    });

    expect(api.post).toHaveBeenCalledWith(
      "/admin/delivery-trips/trip_003/cancel",
      { reason: "Kendala armada darurat" }
    );

    // Modal closes
    expect(container.querySelector('[data-testid="modal-confirm-cancel"]')).toBeNull();

    // Verifies queue & trips refresh
    expect(api.get).toHaveBeenCalledWith(
      "/admin/delivery-trips/unassigned-orders",
      expect.any(Object)
    );
  });

  test("35. Trips with delivered stops do not show Cancel button", async () => {
    mockSearchParams = new URLSearchParams("tab=trips");

    await act(async () => {
      root.render(<AdminLogistics />);
    });

    // trip_001 has delivered_stops_count: 2 -> Cancel button must be absent
    const trip1CancelBtn = container.querySelector(
      '[data-testid="btn-cancel-trip-TRIP-20261015-001"]'
    );
    expect(trip1CancelBtn).toBeNull();

    // trip_002 is completed -> Cancel button must be absent
    const trip2CancelBtn = container.querySelector(
      '[data-testid="btn-cancel-trip-TRIP-20261015-002"]'
    );
    expect(trip2CancelBtn).toBeNull();
  });

  test("36. Backend HTTP 409 rejection displays error without client-side state mutation", async () => {
    mockSearchParams = new URLSearchParams("tab=trips");
    api.post.mockRejectedValueOnce({
      response: {
        status: 409,
        data: {
          detail:
            "Trip tidak dapat dibatalkan karena memuat pesanan yang telah diserahterimakan (delivered).",
        },
      },
    });

    await act(async () => {
      root.render(<AdminLogistics />);
    });

    await act(async () => {
      container
        .querySelector('[data-testid="btn-cancel-trip-TRIP-20261015-003"]')
        .click();
    });

    const reasonInput = container.querySelector(
      '[data-testid="input-cancel-reason"]'
    );
    await act(async () => {
      const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
        window.HTMLTextAreaElement.prototype,
        "value"
      ).set;
      nativeInputValueSetter.call(reasonInput, "Pembatalan tertolak");
      reasonInput.dispatchEvent(new Event("change", { bubbles: true }));
    });

    await act(async () => {
      container
        .querySelector('[data-testid="btn-confirm-cancel-submit"]')
        .click();
    });

    // Modal stays open showing error alert
    const errorAlert = container.querySelector('[data-testid="cancel-error-alert"]');
    expect(errorAlert).not.toBeNull();
    expect(errorAlert.textContent).toContain("Trip tidak dapat dibatalkan");
  });

  test("37. Dispatching a draft trip executes scheduled PATCH before in_transit PATCH", async () => {
    mockSearchParams = new URLSearchParams("tab=trips");
    const draftTrip = {
      ...mockTrips[2],
      id: "trip_draft_001",
      trip_number: "TRIP-20261015-DRAFT",
      status: "draft",
    };

    api.get.mockImplementation((url) => {
      if (url === "/delivery-zones") return Promise.resolve({ data: mockZones });
      if (url === "/admin/workers") return Promise.resolve({ data: mockWorkers });
      if (url === "/admin/delivery-trips/unassigned-orders") {
        return Promise.resolve({ data: mockUnassignedOrders });
      }
      if (url === "/admin/delivery-trips/trip_draft_001") {
        return Promise.resolve({ data: draftTrip });
      }
      if (url.startsWith("/admin/delivery-trips")) {
        return Promise.resolve({ data: [draftTrip] });
      }
      return Promise.reject(new Error(`Unhandled GET url: ${url}`));
    });

    const patchCallSequence = [];
    api.patch.mockImplementation((url, body) => {
      patchCallSequence.push({ url, body });
      if (body.target_status === "scheduled") {
        return Promise.resolve({ data: { ...draftTrip, status: "scheduled" } });
      }
      if (body.target_status === "in_transit") {
        return Promise.resolve({ data: { ...draftTrip, status: "in_transit" } });
      }
      return Promise.resolve({ data: {} });
    });

    await act(async () => {
      root.render(<AdminLogistics />);
    });

    const dispatchBtn = container.querySelector(
      '[data-testid="btn-dispatch-trip-TRIP-20261015-DRAFT"]'
    );
    expect(dispatchBtn).not.toBeNull();

    await act(async () => {
      dispatchBtn.click();
    });

    const submitBtn = container.querySelector(
      '[data-testid="btn-confirm-dispatch-submit"]'
    );
    expect(submitBtn).not.toBeNull();

    await act(async () => {
      submitBtn.click();
    });

    // Assert that scheduled PATCH completed before in_transit PATCH
    expect(patchCallSequence).toHaveLength(2);
    expect(patchCallSequence[0]).toEqual({
      url: "/admin/delivery-trips/trip_draft_001/status",
      body: { target_status: "scheduled" },
    });
    expect(patchCallSequence[1]).toEqual({
      url: "/admin/delivery-trips/trip_draft_001/status",
      body: { target_status: "in_transit" },
    });

    // Modal closes and success notification is triggered
    expect(container.querySelector('[data-testid="modal-confirm-dispatch"]')).toBeNull();
    expect(toast.success).toHaveBeenCalledWith(
      expect.stringContaining("Armada TRIP-20261015-DRAFT berhasil diberangkatkan")
    );
  });

  test("38. Failure in scheduled PATCH or in_transit PATCH aborts dispatch without false success or optimistic mutation", async () => {
    mockSearchParams = new URLSearchParams("tab=trips");
    const draftTrip = {
      ...mockTrips[2],
      id: "trip_draft_002",
      trip_number: "TRIP-20261015-DRAFT2",
      status: "draft",
    };

    api.get.mockImplementation((url) => {
      if (url === "/delivery-zones") return Promise.resolve({ data: mockZones });
      if (url === "/admin/workers") return Promise.resolve({ data: mockWorkers });
      if (url === "/admin/delivery-trips/unassigned-orders") {
        return Promise.resolve({ data: mockUnassignedOrders });
      }
      if (url === "/admin/delivery-trips/trip_draft_002") {
        return Promise.resolve({ data: draftTrip });
      }
      if (url.startsWith("/admin/delivery-trips")) {
        return Promise.resolve({ data: [draftTrip] });
      }
      return Promise.reject(new Error(`Unhandled GET url: ${url}`));
    });

    // Case 1: First PATCH (scheduled) fails
    api.patch.mockRejectedValueOnce({
      response: { status: 400, data: { detail: "Transisi draft ke scheduled gagal" } },
    });

    await act(async () => {
      root.render(<AdminLogistics />);
    });

    await act(async () => {
      container
        .querySelector('[data-testid="btn-dispatch-trip-TRIP-20261015-DRAFT2"]')
        .click();
    });

    await act(async () => {
      container
        .querySelector('[data-testid="btn-confirm-dispatch-submit"]')
        .click();
    });

    // in_transit PATCH was NOT called
    expect(api.patch).toHaveBeenCalledTimes(1);
    expect(api.patch).toHaveBeenCalledWith(
      "/admin/delivery-trips/trip_draft_002/status",
      { target_status: "scheduled" }
    );

    // No false success notification
    expect(toast.success).not.toHaveBeenCalled();
    expect(toast.error).toHaveBeenCalledWith(
      expect.stringContaining("Transisi draft ke scheduled gagal")
    );

    // Modal stays open showing error alert, no optimistic state mutation
    const modal = container.querySelector('[data-testid="modal-confirm-dispatch"]');
    expect(modal).not.toBeNull();
    const errorAlert = container.querySelector('[data-testid="dispatch-error-alert"]');
    expect(errorAlert).not.toBeNull();
    expect(errorAlert.textContent).toContain("Transisi draft ke scheduled gagal");

    // Close modal
    await act(async () => {
      container.querySelector('[data-testid="btn-cancel-dispatch"]').click();
    });

    // Case 2: First PATCH (scheduled) succeeds, but second PATCH (in_transit) fails
    api.patch.mockReset();
    toast.success.mockReset();
    toast.error.mockReset();

    api.patch
      .mockResolvedValueOnce({ data: { ...draftTrip, status: "scheduled" } })
      .mockRejectedValueOnce({
        response: {
          status: 422,
          data: {
            detail: "Batas atas upah pengiriman (cap) belum ditetapkan oleh Owner.",
          },
        },
      });

    await act(async () => {
      container
        .querySelector('[data-testid="btn-dispatch-trip-TRIP-20261015-DRAFT2"]')
        .click();
    });

    await act(async () => {
      container
        .querySelector('[data-testid="btn-confirm-dispatch-submit"]')
        .click();
    });

    // Both were attempted in order
    expect(api.patch).toHaveBeenCalledTimes(2);

    // No false success notification
    expect(toast.success).not.toHaveBeenCalled();
    expect(toast.error).toHaveBeenCalledWith(
      expect.stringContaining("Batas atas upah pengiriman (cap) belum ditetapkan oleh Owner")
    );

    // Modal stays open showing error alert, no optimistic state mutation
    expect(container.querySelector('[data-testid="modal-confirm-dispatch"]')).not.toBeNull();
    const errorAlert2 = container.querySelector('[data-testid="dispatch-error-alert"]');
    expect(errorAlert2).not.toBeNull();
    expect(errorAlert2.textContent).toContain("Batas atas upah pengiriman (cap) belum ditetapkan oleh Owner");
  });

  // =========================================================================
  // Phase 3.F.4.3 Package 5: Handover UI & Wage Accrual Integration Tests
  // =========================================================================

  test("39. Handover button is available only for eligible stops with outcome out_for_delivery", async () => {
    mockSearchParams = new URLSearchParams("tab=trips");
    const testTrip = {
      ...mockTrips[0],
      id: "trip_transit_001",
      trip_number: "TRIP-20261015-TRANSIT1",
      status: "in_transit",
      stops: [
        {
          stop_id: "stp_active",
          sequence: 1,
          order_id: "ord_active",
          order_number: "ORD-ACTIVE",
          customer_name: "Customer Active",
          outcome: "out_for_delivery",
        },
        {
          stop_id: "stp_pending",
          sequence: 2,
          order_id: "ord_pending",
          order_number: "ORD-PENDING",
          customer_name: "Customer Pending",
          outcome: "pending",
        },
        {
          stop_id: "stp_delivered",
          sequence: 3,
          order_id: "ord_delivered",
          order_number: "ORD-DELIVERED",
          customer_name: "Customer Delivered",
          outcome: "delivered",
        },
      ],
      stops_count: 3,
      delivered_stops_count: 1,
    };

    api.get.mockImplementation((url) => {
      if (url === "/delivery-zones") return Promise.resolve({ data: mockZones });
      if (url === "/admin/workers") return Promise.resolve({ data: mockWorkers });
      if (url === "/admin/delivery-trips/unassigned-orders") {
        return Promise.resolve({ data: mockUnassignedOrders });
      }
      if (url === "/admin/delivery-trips/trip_transit_001") {
        return Promise.resolve({ data: testTrip });
      }
      if (url.startsWith("/admin/delivery-trips")) {
        return Promise.resolve({ data: [testTrip] });
      }
      return Promise.reject(new Error(`Unhandled GET url: ${url}`));
    });

    await act(async () => {
      root.render(<AdminLogistics />);
    });

    // Open Manage Stops modal for this trip
    await act(async () => {
      container
        .querySelector('[data-testid="btn-manage-stops-TRIP-20261015-TRANSIT1"]')
        .click();
    });

    // Stop 1 (out_for_delivery) has Serah Terima button
    const activeBtn = container.querySelector('[data-testid="btn-handover-stop-ORD-ACTIVE"]');
    expect(activeBtn).not.toBeNull();
    expect(activeBtn.textContent).toContain("Serah Terima");

    // Stop 2 (pending) does NOT have Serah Terima button
    const pendingBtn = container.querySelector('[data-testid="btn-handover-stop-ORD-PENDING"]');
    expect(pendingBtn).toBeNull();

    // Stop 3 (delivered) does NOT have Serah Terima button, but shows Selesai badge
    const deliveredBtn = container.querySelector('[data-testid="btn-handover-stop-ORD-DELIVERED"]');
    expect(deliveredBtn).toBeNull();
    const deliveredStop = container.querySelector('[data-testid="stop-item-ORD-DELIVERED"]');
    expect(deliveredStop.textContent).toContain("Selesai");
  });

  test("40. Handover modal requires recipient name and explicit helper confirmation before submission", async () => {
    mockSearchParams = new URLSearchParams("tab=trips");
    const testTrip = {
      ...mockTrips[0],
      id: "trip_transit_002",
      trip_number: "TRIP-20261015-TRANSIT2",
      status: "in_transit",
      rate_policy_snapshot: {
        applied_rate_le: 65.0,
        unusual_amount_threshold_le: 500.0,
      },
      stops: [
        {
          stop_id: "stp_101",
          order_id: "ord_101",
          order_number: "ORD-20261015-001",
          customer_name: "Youssef Ibrahim",
          customer_phone: "+201012345678",
          customer_address: "Street 9, Maadi, Cairo",
          outcome: "out_for_delivery",
        },
      ],
      stops_count: 1,
    };

    api.get.mockImplementation((url) => {
      if (url === "/delivery-zones") return Promise.resolve({ data: mockZones });
      if (url === "/admin/workers") return Promise.resolve({ data: mockWorkers });
      if (url === "/admin/delivery-trips/unassigned-orders") {
        return Promise.resolve({ data: mockUnassignedOrders });
      }
      if (url === "/admin/delivery-trips/trip_transit_002") {
        return Promise.resolve({ data: testTrip });
      }
      if (url.startsWith("/admin/delivery-trips")) {
        return Promise.resolve({ data: [testTrip] });
      }
      return Promise.reject(new Error(`Unhandled GET url: ${url}`));
    });

    await act(async () => {
      root.render(<AdminLogistics />);
    });

    await act(async () => {
      container
        .querySelector('[data-testid="btn-manage-stops-TRIP-20261015-TRANSIT2"]')
        .click();
    });

    // Click Serah Terima
    await act(async () => {
      container
        .querySelector('[data-testid="btn-handover-stop-ORD-20261015-001"]')
        .click();
    });

    const modal = container.querySelector('[data-testid="modal-confirm-handover"]');
    expect(modal).not.toBeNull();
    expect(modal.textContent).toContain("Konfirmasi Serah Terima Pesanan");
    expect(modal.textContent).toContain("65 LE"); // Displays planned rate from snapshot

    const recipientInput = container.querySelector('[data-testid="input-handover-recipient"]');
    const helperCheck = container.querySelector('[data-testid="checkbox-helper-confirmed"]');
    const submitBtn = container.querySelector('[data-testid="btn-confirm-handover-submit"]');

    // Helper checkbox must start unchecked
    expect(helperCheck.checked).toBe(false);
    // Submit button is disabled because helper is not confirmed
    expect(submitBtn.disabled).toBe(true);

    // Set recipient name empty -> still disabled
    await act(async () => {
      const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
      nativeSetter.call(recipientInput, "");
      recipientInput.dispatchEvent(new Event("change", { bubbles: true }));
    });
    expect(submitBtn.disabled).toBe(true);

    // Fill recipient name -> still disabled because helper is not confirmed
    await act(async () => {
      const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
      nativeSetter.call(recipientInput, "Youssef Ibrahim");
      recipientInput.dispatchEvent(new Event("change", { bubbles: true }));
    });
    expect(submitBtn.disabled).toBe(true);

    // Explicitly check helper confirmation -> enabled!
    await act(async () => {
      helperCheck.click();
    });
    expect(helperCheck.checked).toBe(true);
    expect(submitBtn.disabled).toBe(false);

    // Uncheck helper confirmation -> disabled again
    await act(async () => {
      helperCheck.click();
    });
    expect(helperCheck.checked).toBe(false);
    expect(submitBtn.disabled).toBe(true);

    // Close modal
    await act(async () => {
      container.querySelector('[data-testid="btn-cancel-handover"]').click();
    });
    expect(container.querySelector('[data-testid="modal-confirm-handover"]')).toBeNull();
  });

  test("41. Successful handover submits payload with recipient and helper confirmation, then refreshes data", async () => {
    mockSearchParams = new URLSearchParams("tab=trips");
    const testTrip = {
      ...mockTrips[0],
      id: "trip_transit_003",
      trip_number: "TRIP-20261015-TRANSIT3",
      status: "in_transit",
      rate_policy_snapshot: { applied_rate_le: 50.0 },
      stops: [
        {
          stop_id: "stp_101",
          order_id: "ord_101",
          order_number: "ORD-20261015-001",
          customer_name: "Youssef Ibrahim",
          outcome: "out_for_delivery",
        },
      ],
      stops_count: 1,
    };

    api.get.mockImplementation((url) => {
      if (url === "/delivery-zones") return Promise.resolve({ data: mockZones });
      if (url === "/admin/workers") return Promise.resolve({ data: mockWorkers });
      if (url === "/admin/delivery-trips/unassigned-orders") {
        return Promise.resolve({ data: mockUnassignedOrders });
      }
      if (url === "/admin/delivery-trips/trip_transit_003") {
        return Promise.resolve({ data: testTrip });
      }
      if (url.startsWith("/admin/delivery-trips")) {
        return Promise.resolve({ data: [testTrip] });
      }
      return Promise.reject(new Error(`Unhandled GET url: ${url}`));
    });

    api.post.mockResolvedValueOnce({
      data: {
        ok: true,
        trip: {
          ...testTrip,
          stops: [
            {
              ...testTrip.stops[0],
              outcome: "delivered",
              recipient_name: "Ahmed Penerima",
              helper_confirmed: true,
            },
          ],
        },
      },
    });

    await act(async () => {
      root.render(<AdminLogistics />);
    });

    await act(async () => {
      container
        .querySelector('[data-testid="btn-manage-stops-TRIP-20261015-TRANSIT3"]')
        .click();
    });

    await act(async () => {
      container
        .querySelector('[data-testid="btn-handover-stop-ORD-20261015-001"]')
        .click();
    });

    const recipientInput = container.querySelector('[data-testid="input-handover-recipient"]');
    const notesInput = container.querySelector('[data-testid="input-handover-notes"]');
    const helperCheck = container.querySelector('[data-testid="checkbox-helper-confirmed"]');

    await act(async () => {
      const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
      nativeSetter.call(recipientInput, "Ahmed Penerima");
      recipientInput.dispatchEvent(new Event("change", { bubbles: true }));

      const nativeAreaSetter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, "value").set;
      nativeAreaSetter.call(notesInput, "Diterima rapi di lantai dasar");
      notesInput.dispatchEvent(new Event("change", { bubbles: true }));

      helperCheck.click();
    });

    await act(async () => {
      container.querySelector('[data-testid="btn-confirm-handover-submit"]').click();
    });

    expect(api.post).toHaveBeenCalledWith(
      "/admin/delivery-trips/trip_transit_003/stops/ord_101/deliver",
      {
        recipient_name: "Ahmed Penerima",
        handover_notes: "Diterima rapi di lantai dasar",
        helper_confirmed: true,
      }
    );

    // Modal closes & success toast fired
    expect(container.querySelector('[data-testid="modal-confirm-handover"]')).toBeNull();
    expect(toast.success).toHaveBeenCalledWith(
      expect.stringContaining("berhasil diserahterimakan")
    );

    // Authoritative reload triggered
    expect(api.get).toHaveBeenCalledWith(
      "/admin/delivery-trips/unassigned-orders",
      expect.any(Object)
    );
  });

  test("42. Unusual wage override above 500 LE threshold requires explicit confirmation and >= 5 char reason", async () => {
    mockSearchParams = new URLSearchParams("tab=trips");
    const testTrip = {
      ...mockTrips[0],
      id: "trip_transit_004",
      trip_number: "TRIP-20261015-TRANSIT4",
      status: "in_transit",
      rate_policy_snapshot: { applied_rate_le: 50.0, unusual_amount_threshold_le: 100.0, max_cap_at_dispatch_le: 500.0 },
      stops: [
        {
          stop_id: "stp_101",
          order_id: "ord_101",
          order_number: "ORD-20261015-001",
          customer_name: "Youssef Ibrahim",
          outcome: "out_for_delivery",
        },
      ],
      stops_count: 1,
    };

    api.get.mockImplementation((url) => {
      if (url === "/delivery-zones") return Promise.resolve({ data: mockZones });
      if (url === "/admin/workers") return Promise.resolve({ data: mockWorkers });
      if (url === "/admin/delivery-trips/unassigned-orders") {
        return Promise.resolve({ data: mockUnassignedOrders });
      }
      if (url === "/admin/delivery-trips/trip_transit_004") {
        return Promise.resolve({ data: testTrip });
      }
      if (url.startsWith("/admin/delivery-trips")) {
        return Promise.resolve({ data: [testTrip] });
      }
      return Promise.reject(new Error(`Unhandled GET url: ${url}`));
    });

    api.post.mockResolvedValueOnce({
      data: { ok: true, trip: testTrip },
    });

    await act(async () => {
      root.render(<AdminLogistics />);
    });

    await act(async () => {
      container
        .querySelector('[data-testid="btn-manage-stops-TRIP-20261015-TRANSIT4"]')
        .click();
    });

    await act(async () => {
      container
        .querySelector('[data-testid="btn-handover-stop-ORD-20261015-001"]')
        .click();
    });

    const recipientInput = container.querySelector('[data-testid="input-handover-recipient"]');
    const helperCheck = container.querySelector('[data-testid="checkbox-helper-confirmed"]');
    const customWageToggle = container.querySelector('[data-testid="toggle-custom-wage"]');
    const submitBtn = container.querySelector('[data-testid="btn-confirm-handover-submit"]');

    await act(async () => {
      const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
      nativeSetter.call(recipientInput, "Fatima");
      recipientInput.dispatchEvent(new Event("change", { bubbles: true }));

      helperCheck.click();
      customWageToggle.click();
    });

    // Enter 250 LE (> 100 LE threshold, <= 500 LE hard cap)
    const customWageInput = container.querySelector('[data-testid="input-custom-wage"]');
    await act(async () => {
      const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
      nativeSetter.call(customWageInput, "250");
      customWageInput.dispatchEvent(new Event("change", { bubbles: true }));
    });

    // Warning alert is visible
    expect(container.querySelector('[data-testid="unusual-amount-warning"]')).not.toBeNull();
    // Submit button disabled because unconfirmed
    expect(submitBtn.disabled).toBe(true);

    const unusualCheck = container.querySelector('[data-testid="checkbox-confirm-unusual-amount"]');
    const reasonInput = container.querySelector('[data-testid="input-override-reason"]');

    // Check unusual amount confirmation, but reason still empty -> disabled
    await act(async () => {
      unusualCheck.click();
    });
    expect(submitBtn.disabled).toBe(true);

    // Reason with < 5 characters -> disabled
    await act(async () => {
      const nativeAreaSetter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, "value").set;
      nativeAreaSetter.call(reasonInput, "L5");
      reasonInput.dispatchEvent(new Event("change", { bubbles: true }));
    });
    expect(submitBtn.disabled).toBe(true);

    // Reason >= 5 characters -> enabled!
    await act(async () => {
      const nativeAreaSetter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, "value").set;
      nativeAreaSetter.call(reasonInput, "Lantai 5 tanpa lift");
      reasonInput.dispatchEvent(new Event("change", { bubbles: true }));
    });
    expect(submitBtn.disabled).toBe(false);

    // Submit
    await act(async () => {
      submitBtn.click();
    });

    expect(api.post).toHaveBeenCalledWith(
      "/admin/delivery-trips/trip_transit_004/stops/ord_101/deliver",
      {
        recipient_name: "Fatima",
        handover_notes: null,
        helper_confirmed: true,
        custom_wage_le: 250,
        confirmed_unusual_amount: true,
        override_reason: "Lantai 5 tanpa lift",
      }
    );
  });

  test("42b. Unusual wage override above 500 LE hard cap displays rejection alert and keeps submit disabled", async () => {
    mockSearchParams = new URLSearchParams("tab=trips");
    const testTrip = {
      ...mockTrips[0],
      id: "trip_transit_004b",
      trip_number: "TRIP-20261015-TRANSIT4B",
      status: "in_transit",
      rate_policy_snapshot: {
        applied_rate_le: 50.0,
        unusual_amount_threshold_le: 100.0,
        max_cap_at_dispatch_le: 500.0,
      },
      stops: [
        {
          stop_id: "stp_101b",
          order_id: "ord_101b",
          order_number: "ORD-20261015-001B",
          customer_name: "Youssef Ibrahim",
          outcome: "out_for_delivery",
        },
      ],
      stops_count: 1,
    };

    api.get.mockImplementation((url) => {
      if (url === "/delivery-zones") return Promise.resolve({ data: mockZones });
      if (url === "/admin/workers") return Promise.resolve({ data: mockWorkers });
      if (url === "/admin/delivery-trips/unassigned-orders") {
        return Promise.resolve({ data: mockUnassignedOrders });
      }
      if (url === "/admin/delivery-trips/trip_transit_004b") {
        return Promise.resolve({ data: testTrip });
      }
      if (url.startsWith("/admin/delivery-trips")) {
        return Promise.resolve({ data: [testTrip] });
      }
      return Promise.reject(new Error(`Unhandled GET url: ${url}`));
    });

    await act(async () => {
      root.render(<AdminLogistics />);
    });

    await act(async () => {
      container
        .querySelector('[data-testid="btn-manage-stops-TRIP-20261015-TRANSIT4B"]')
        .click();
    });

    await act(async () => {
      container
        .querySelector('[data-testid="btn-handover-stop-ORD-20261015-001B"]')
        .click();
    });

    const recipientInput = container.querySelector('[data-testid="input-handover-recipient"]');
    const helperCheck = container.querySelector('[data-testid="checkbox-helper-confirmed"]');
    const customWageToggle = container.querySelector('[data-testid="toggle-custom-wage"]');
    const submitBtn = container.querySelector('[data-testid="btn-confirm-handover-submit"]');

    await act(async () => {
      const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
      nativeSetter.call(recipientInput, "Fatima");
      recipientInput.dispatchEvent(new Event("change", { bubbles: true }));

      helperCheck.click();
      customWageToggle.click();
    });

    // Enter 600 LE (> 500 LE hard cap)
    const customWageInput = container.querySelector('[data-testid="input-custom-wage"]');
    await act(async () => {
      const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
      nativeSetter.call(customWageInput, "600");
      customWageInput.dispatchEvent(new Event("change", { bubbles: true }));
    });

    // Hard cap rejection alert is visible
    expect(container.querySelector('[data-testid="hard-cap-warning"]')).not.toBeNull();
    // Submit button permanently disabled
    expect(submitBtn.disabled).toBe(true);
  });

  test("43. Handover failure (HTTP 409/422/network) displays error alert without false success or optimistic mutation", async () => {
    mockSearchParams = new URLSearchParams("tab=trips");
    const testTrip = {
      ...mockTrips[0],
      id: "trip_transit_005",
      trip_number: "TRIP-20261015-TRANSIT5",
      status: "in_transit",
      rate_policy_snapshot: { applied_rate_le: 50.0 },
      stops: [
        {
          stop_id: "stp_101",
          order_id: "ord_101",
          order_number: "ORD-20261015-001",
          customer_name: "Youssef Ibrahim",
          outcome: "out_for_delivery",
        },
      ],
      stops_count: 1,
    };

    api.get.mockImplementation((url) => {
      if (url === "/delivery-zones") return Promise.resolve({ data: mockZones });
      if (url === "/admin/workers") return Promise.resolve({ data: mockWorkers });
      if (url === "/admin/delivery-trips/unassigned-orders") {
        return Promise.resolve({ data: mockUnassignedOrders });
      }
      if (url === "/admin/delivery-trips/trip_transit_005") {
        return Promise.resolve({ data: testTrip });
      }
      if (url.startsWith("/admin/delivery-trips")) {
        return Promise.resolve({ data: [testTrip] });
      }
      return Promise.reject(new Error(`Unhandled GET url: ${url}`));
    });

    // Case 1: Backend rejects with HTTP 409
    api.post.mockRejectedValueOnce({
      response: {
        status: 409,
        data: { detail: "Konflik transaksi: stop telah dimodifikasi proses lain" },
      },
    });

    await act(async () => {
      root.render(<AdminLogistics />);
    });

    await act(async () => {
      container
        .querySelector('[data-testid="btn-manage-stops-TRIP-20261015-TRANSIT5"]')
        .click();
    });

    await act(async () => {
      container
        .querySelector('[data-testid="btn-handover-stop-ORD-20261015-001"]')
        .click();
    });

    const recipientInput = container.querySelector('[data-testid="input-handover-recipient"]');
    const helperCheck = container.querySelector('[data-testid="checkbox-helper-confirmed"]');

    await act(async () => {
      const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
      nativeSetter.call(recipientInput, "Penerima Gagal");
      recipientInput.dispatchEvent(new Event("change", { bubbles: true }));
      helperCheck.click();
    });

    await act(async () => {
      container.querySelector('[data-testid="btn-confirm-handover-submit"]').click();
    });

    // Error alert is rendered inside the modal
    const errorAlert = container.querySelector('[data-testid="handover-error-alert"]');
    expect(errorAlert).not.toBeNull();
    expect(errorAlert.textContent).toContain("Konflik transaksi");

    // Modal is still open
    expect(container.querySelector('[data-testid="modal-confirm-handover"]')).not.toBeNull();

    // No false success toast
    expect(toast.success).not.toHaveBeenCalled();
    expect(toast.error).toHaveBeenCalledWith(
      expect.stringContaining("Konflik Serah Terima")
    );
  });

  test("44. Stop in out_for_delivery displays Catat Gagal button, opening modal with recipient info and quick reasons", async () => {
    mockSearchParams = new URLSearchParams("tab=trips");
    const testTrip = {
      ...mockTrips[0],
      id: "trip_pkg6_01",
      trip_number: "TRIP-20261015-PKG6-01",
      status: "in_transit",
      stops: [
        {
          stop_id: "stp_601",
          order_id: "ord_601",
          order_number: "ORD-PKG6-001",
          customer_name: "Farah Hassan",
          customer_phone: "+201234567890",
          customer_address: "Zamalek, Cairo",
          outcome: "out_for_delivery",
          attempts: [],
        },
      ],
      stops_count: 1,
    };

    api.get.mockImplementation((url) => {
      if (url === "/delivery-zones") return Promise.resolve({ data: mockZones });
      if (url === "/admin/workers") return Promise.resolve({ data: mockWorkers });
      if (url === "/admin/delivery-trips/unassigned-orders") {
        return Promise.resolve({ data: mockUnassignedOrders });
      }
      if (url === "/admin/delivery-trips/trip_pkg6_01") {
        return Promise.resolve({ data: testTrip });
      }
      if (url.startsWith("/admin/delivery-trips")) {
        return Promise.resolve({ data: [testTrip] });
      }
      return Promise.reject(new Error(`Unhandled GET url: ${url}`));
    });

    await act(async () => {
      root.render(<AdminLogistics />);
    });

    await act(async () => {
      container
        .querySelector('[data-testid="btn-manage-stops-TRIP-20261015-PKG6-01"]')
        .click();
    });

    // Check Catat Gagal button is rendered on out_for_delivery stop
    const failBtn = container.querySelector('[data-testid="btn-fail-stop-ORD-PKG6-001"]');
    expect(failBtn).not.toBeNull();
    expect(failBtn.textContent).toContain("Catat Gagal");

    // Click Catat Gagal
    await act(async () => {
      failBtn.click();
    });

    // Modal opens
    const modal = container.querySelector('[data-testid="modal-record-fail-attempt"]');
    expect(modal).not.toBeNull();
    expect(modal.textContent).toContain("Catat Percobaan Pengantaran Gagal");
    expect(modal.textContent).toContain("Farah Hassan");
    expect(modal.textContent).toContain("Zamalek, Cairo");
    expect(modal.textContent).toContain("tidak menimbulkan kewajiban upah helper");

    // Quick reasons are rendered
    expect(modal.textContent).toContain("Penerima tidak dapat dihubungi");
    expect(modal.textContent).toContain("Rumah kosong");
  });

  test("45. Failed attempt modal enforces minimum 3 characters non-whitespace reason before submission can proceed", async () => {
    mockSearchParams = new URLSearchParams("tab=trips");
    const testTrip = {
      ...mockTrips[0],
      id: "trip_pkg6_02",
      trip_number: "TRIP-20261015-PKG6-02",
      status: "in_transit",
      stops: [
        {
          stop_id: "stp_602",
          order_id: "ord_602",
          order_number: "ORD-PKG6-002",
          customer_name: "Mahmoud Aly",
          customer_phone: "+201112223344",
          customer_address: "Dokki, Giza",
          outcome: "out_for_delivery",
          attempts: [],
        },
      ],
      stops_count: 1,
    };

    api.get.mockImplementation((url) => {
      if (url === "/delivery-zones") return Promise.resolve({ data: mockZones });
      if (url === "/admin/workers") return Promise.resolve({ data: mockWorkers });
      if (url === "/admin/delivery-trips/unassigned-orders") {
        return Promise.resolve({ data: mockUnassignedOrders });
      }
      if (url === "/admin/delivery-trips/trip_pkg6_02") {
        return Promise.resolve({ data: testTrip });
      }
      if (url.startsWith("/admin/delivery-trips")) {
        return Promise.resolve({ data: [testTrip] });
      }
      return Promise.reject(new Error(`Unhandled GET url: ${url}`));
    });

    api.post.mockResolvedValue({
      data: {
        ...testTrip,
        stops: [
          {
            ...testTrip.stops[0],
            outcome: "failed",
            failure_reason: "Penerima tidak ada di tempat / Rumah kosong",
            attempt_count: 1,
            attempts: [
              {
                attempt_number: 1,
                outcome: "failed",
                failure_reason: "Penerima tidak ada di tempat / Rumah kosong",
                notes: "Pintu pagar terkunci gembok",
                recorded_by_name: "Dispatcher Siti",
                attempted_at: "2026-10-15T12:00:00Z",
              },
            ],
          },
        ],
      },
    });

    await act(async () => {
      root.render(<AdminLogistics />);
    });

    await act(async () => {
      container
        .querySelector('[data-testid="btn-manage-stops-TRIP-20261015-PKG6-02"]')
        .click();
    });

    await act(async () => {
      container.querySelector('[data-testid="btn-fail-stop-ORD-PKG6-002"]').click();
    });

    const submitBtn = container.querySelector('[data-testid="btn-submit-fail-attempt"]');
    const reasonInput = container.querySelector('[data-testid="input-failure-reason"]');
    const notesInput = container.querySelector('[data-testid="input-failure-notes"]');
    const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
    const nativeTextareaSetter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, "value").set;

    // Disabled initially (empty reason)
    expect(submitBtn.disabled).toBe(true);

    // Whitespace only: disabled
    await act(async () => {
      nativeSetter.call(reasonInput, "   ");
      reasonInput.dispatchEvent(new Event("change", { bubbles: true }));
    });
    expect(submitBtn.disabled).toBe(true);

    // 2 characters only: disabled
    await act(async () => {
      nativeSetter.call(reasonInput, "ab");
      reasonInput.dispatchEvent(new Event("change", { bubbles: true }));
    });
    expect(submitBtn.disabled).toBe(true);

    // Select quick reason: enabled
    const quickBtn = Array.from(container.querySelectorAll("button")).find((b) =>
      b.textContent.includes("Rumah kosong")
    );
    expect(quickBtn).not.toBeNull();
    await act(async () => {
      quickBtn.click();
    });
    expect(submitBtn.disabled).toBe(false);

    // Fill notes
    await act(async () => {
      nativeTextareaSetter.call(notesInput, "Pintu pagar terkunci gembok");
      notesInput.dispatchEvent(new Event("change", { bubbles: true }));
    });

    // Submit
    await act(async () => {
      submitBtn.click();
    });

    expect(api.post).toHaveBeenCalledWith(
      "/admin/delivery-trips/trip_pkg6_02/stops/ord_602/record-attempt",
      expect.objectContaining({
        outcome: "failed",
        failure_reason: expect.stringContaining("Rumah kosong"),
        notes: "Pintu pagar terkunci gembok",
      })
    );

    // Modal is closed on success
    expect(container.querySelector('[data-testid="modal-record-fail-attempt"]')).toBeNull();
    expect(toast.success).toHaveBeenCalledWith(
      expect.stringContaining("berhasil dicatat sebagai gagal")
    );
  });

  test("46. Stop in failed state displays Coba Lagi (Retry) button and triggers transition to out_for_delivery", async () => {
    mockSearchParams = new URLSearchParams("tab=trips");
    const testTrip = {
      ...mockTrips[0],
      id: "trip_pkg6_03",
      trip_number: "TRIP-20261015-PKG6-03",
      status: "in_transit",
      stops: [
        {
          stop_id: "stp_603",
          order_id: "ord_603",
          order_number: "ORD-PKG6-003",
          customer_name: "Kareem Tarek",
          outcome: "failed",
          failure_reason: "Alamat tidak ditemukan",
          attempt_count: 1,
          attempts: [
            {
              attempt_number: 1,
              outcome: "failed",
              failure_reason: "Alamat tidak ditemukan",
              recorded_by_name: "Dispatcher Siti",
            },
          ],
        },
      ],
      stops_count: 1,
    };

    api.get.mockImplementation((url) => {
      if (url === "/delivery-zones") return Promise.resolve({ data: mockZones });
      if (url === "/admin/workers") return Promise.resolve({ data: mockWorkers });
      if (url === "/admin/delivery-trips/unassigned-orders") {
        return Promise.resolve({ data: mockUnassignedOrders });
      }
      if (url === "/admin/delivery-trips/trip_pkg6_03") {
        return Promise.resolve({ data: testTrip });
      }
      if (url.startsWith("/admin/delivery-trips")) {
        return Promise.resolve({ data: [testTrip] });
      }
      return Promise.reject(new Error(`Unhandled GET url: ${url}`));
    });

    api.post.mockResolvedValue({
      data: {
        ...testTrip,
        stops: [
          {
            ...testTrip.stops[0],
            outcome: "out_for_delivery",
          },
        ],
      },
    });

    await act(async () => {
      root.render(<AdminLogistics />);
    });

    await act(async () => {
      container
        .querySelector('[data-testid="btn-manage-stops-TRIP-20261015-PKG6-03"]')
        .click();
    });

    // In failed state: Coba Lagi is visible, Serah Terima and Catat Gagal are not
    const retryBtn = container.querySelector('[data-testid="btn-retry-stop-ORD-PKG6-003"]');
    expect(retryBtn).not.toBeNull();
    expect(retryBtn.textContent).toContain("Coba Lagi");
    expect(container.querySelector('[data-testid="btn-handover-stop-ORD-PKG6-003"]')).toBeNull();
    expect(container.querySelector('[data-testid="btn-fail-stop-ORD-PKG6-003"]')).toBeNull();

    // Click Coba Lagi
    await act(async () => {
      retryBtn.click();
    });

    expect(api.post).toHaveBeenCalledWith(
      "/admin/delivery-trips/trip_pkg6_03/stops/ord_603/record-attempt",
      { outcome: "out_for_delivery" }
    );
    expect(toast.success).toHaveBeenCalledWith(
      expect.stringContaining("siap dicoba kembali")
    );
  });

  test("47. Delivery attempt history toggle renders chronologically ordered attempts with numbers, timestamps, reasons, notes, and recorder names", async () => {
    mockSearchParams = new URLSearchParams("tab=trips");
    const testTrip = {
      ...mockTrips[0],
      id: "trip_pkg6_04",
      trip_number: "TRIP-20261015-PKG6-04",
      status: "in_transit",
      stops: [
        {
          stop_id: "stp_604",
          order_id: "ord_604",
          order_number: "ORD-PKG6-004",
          customer_name: "Nadia Fathy",
          outcome: "failed",
          failure_reason: "Akses jalan ditutup",
          attempt_count: 2,
          attempts: [
            {
              attempt_number: 1,
              outcome: "failed",
              failure_reason: "Penerima tidak dapat dihubungi",
              notes: "WhatsApp tidak aktif",
              recorded_by_name: "Dispatcher Doni",
              attempted_at: "2026-10-15T09:30:00Z",
            },
            {
              attempt_number: 2,
              outcome: "failed",
              failure_reason: "Akses jalan ditutup warga",
              notes: "Ada hajatan warga",
              recorded_by_name: "Dispatcher Siti",
              attempted_at: "2026-10-15T14:15:00Z",
            },
          ],
        },
      ],
      stops_count: 1,
    };

    api.get.mockImplementation((url) => {
      if (url === "/delivery-zones") return Promise.resolve({ data: mockZones });
      if (url === "/admin/workers") return Promise.resolve({ data: mockWorkers });
      if (url === "/admin/delivery-trips/unassigned-orders") {
        return Promise.resolve({ data: mockUnassignedOrders });
      }
      if (url === "/admin/delivery-trips/trip_pkg6_04") {
        return Promise.resolve({ data: testTrip });
      }
      if (url.startsWith("/admin/delivery-trips")) {
        return Promise.resolve({ data: [testTrip] });
      }
      return Promise.reject(new Error(`Unhandled GET url: ${url}`));
    });

    await act(async () => {
      root.render(<AdminLogistics />);
    });

    await act(async () => {
      container
        .querySelector('[data-testid="btn-manage-stops-TRIP-20261015-PKG6-04"]')
        .click();
    });

    // Check attempts badge button is rendered showing "2 Percobaan"
    const toggleBtn = container.querySelector('[data-testid="btn-toggle-attempts-ORD-PKG6-004"]');
    expect(toggleBtn).not.toBeNull();
    expect(toggleBtn.textContent).toContain("2 Percobaan");

    // History is initially collapsed
    expect(container.querySelector('[data-testid="attempt-history-ORD-PKG6-004"]')).toBeNull();

    // Click to expand
    await act(async () => {
      toggleBtn.click();
    });

    const historyCard = container.querySelector('[data-testid="attempt-history-ORD-PKG6-004"]');
    expect(historyCard).not.toBeNull();
    expect(historyCard.textContent).toContain("Riwayat Percobaan Pengantaran (2)");

    // Attempt 1 entry
    const entry1 = container.querySelector('[data-testid="attempt-entry-ORD-PKG6-004-1"]');
    expect(entry1).not.toBeNull();
    expect(entry1.textContent).toContain("Percobaan #1");
    expect(entry1.textContent).toContain("Penerima tidak dapat dihubungi");
    expect(entry1.textContent).toContain("WhatsApp tidak aktif");
    expect(entry1.textContent).toContain("Dispatcher Doni");

    // Attempt 2 entry
    const entry2 = container.querySelector('[data-testid="attempt-entry-ORD-PKG6-004-2"]');
    expect(entry2).not.toBeNull();
    expect(entry2.textContent).toContain("Percobaan #2");
    expect(entry2.textContent).toContain("Akses jalan ditutup warga");
    expect(entry2.textContent).toContain("Ada hajatan warga");
    expect(entry2.textContent).toContain("Dispatcher Siti");

    // Click toggle again collapses history
    await act(async () => {
      toggleBtn.click();
    });
    expect(container.querySelector('[data-testid="attempt-history-ORD-PKG6-004"]')).toBeNull();
  });

  test("48. Backend error on recording failure preserves user inputs and displays error alert without false success", async () => {
    mockSearchParams = new URLSearchParams("tab=trips");
    const testTrip = {
      ...mockTrips[0],
      id: "trip_pkg6_05",
      trip_number: "TRIP-20261015-PKG6-05",
      status: "in_transit",
      stops: [
        {
          stop_id: "stp_605",
          order_id: "ord_605",
          order_number: "ORD-PKG6-005",
          customer_name: "Ahmed Samir",
          outcome: "out_for_delivery",
          attempts: [],
        },
      ],
      stops_count: 1,
    };

    api.get.mockImplementation((url) => {
      if (url === "/delivery-zones") return Promise.resolve({ data: mockZones });
      if (url === "/admin/workers") return Promise.resolve({ data: mockWorkers });
      if (url === "/admin/delivery-trips/unassigned-orders") {
        return Promise.resolve({ data: mockUnassignedOrders });
      }
      if (url === "/admin/delivery-trips/trip_pkg6_05") {
        return Promise.resolve({ data: testTrip });
      }
      if (url.startsWith("/admin/delivery-trips")) {
        return Promise.resolve({ data: [testTrip] });
      }
      return Promise.reject(new Error(`Unhandled GET url: ${url}`));
    });

    api.post.mockRejectedValue({
      response: {
        status: 409,
        data: { detail: "Konflik pengantaran: stop telah diubah oleh helper lain." },
      },
    });

    await act(async () => {
      root.render(<AdminLogistics />);
    });

    await act(async () => {
      container
        .querySelector('[data-testid="btn-manage-stops-TRIP-20261015-PKG6-05"]')
        .click();
    });

    await act(async () => {
      container.querySelector('[data-testid="btn-fail-stop-ORD-PKG6-005"]').click();
    });

    const reasonInput = container.querySelector('[data-testid="input-failure-reason"]');
    const notesInput = container.querySelector('[data-testid="input-failure-notes"]');
    const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
    const nativeTextareaSetter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, "value").set;

    await act(async () => {
      nativeSetter.call(reasonInput, "Rumah kosong dan lampu padam");
      reasonInput.dispatchEvent(new Event("change", { bubbles: true }));
      nativeTextareaSetter.call(notesInput, "Catatan penting pengemudi");
      notesInput.dispatchEvent(new Event("change", { bubbles: true }));
    });

    await act(async () => {
      container.querySelector('[data-testid="btn-submit-fail-attempt"]').click();
    });

    // Error alert is displayed inside modal
    const errorAlert = container.querySelector('[data-testid="fail-attempt-error-alert"]');
    expect(errorAlert).not.toBeNull();
    expect(errorAlert.textContent).toContain("Konflik pengantaran: stop telah diubah oleh helper lain.");

    // Modal remains open
    expect(container.querySelector('[data-testid="modal-record-fail-attempt"]')).not.toBeNull();

    // User inputs are preserved
    expect(container.querySelector('[data-testid="input-failure-reason"]').value).toBe(
      "Rumah kosong dan lampu padam"
    );
    expect(container.querySelector('[data-testid="input-failure-notes"]').value).toBe(
      "Catatan penting pengemudi"
    );

    // No false success toast
    expect(toast.success).not.toHaveBeenCalled();
    expect(toast.error).toHaveBeenCalledWith(
      expect.stringContaining("Konflik Percobaan Pengantaran")
    );
  });

  // =========================================================================
  // Phase 3.F.4.3 Package 7B: Frontend Trip Completion UI & Final Order Release
  // =========================================================================

  test("49. Selesaikan Trip button visibility enforces strict backend eligibility rules", async () => {
    mockSearchParams = new URLSearchParams("tab=trips");

    const tripEligible = {
      ...mockTrips[0],
      id: "trip_el_1",
      trip_number: "TRIP-ELIGIBLE",
      status: "in_transit",
      stops: [
        { stop_id: "s1", order_id: "o1", outcome: "delivered" },
        { stop_id: "s2", order_id: "o2", outcome: "failed" },
      ],
      stops_count: 2,
    };
    const tripActive = {
      ...mockTrips[0],
      id: "trip_act_1",
      trip_number: "TRIP-ACTIVE",
      status: "in_transit",
      stops: [
        { stop_id: "s3", order_id: "o3", outcome: "delivered" },
        { stop_id: "s4", order_id: "o4", outcome: "out_for_delivery" },
      ],
      stops_count: 2,
    };
    const tripNoDeliv = {
      ...mockTrips[0],
      id: "trip_no_deliv",
      trip_number: "TRIP-NO-DELIV",
      status: "in_transit",
      stops: [
        { stop_id: "s5", order_id: "o5", outcome: "failed" },
      ],
      stops_count: 1,
    };
    const tripCompleted = {
      ...mockTrips[0],
      id: "trip_comp_1",
      trip_number: "TRIP-COMPLETED",
      status: "completed",
      stops: [
        { stop_id: "s6", order_id: "o6", outcome: "delivered" },
      ],
      stops_count: 1,
    };

    api.get.mockImplementation((url) => {
      if (url === "/delivery-zones") return Promise.resolve({ data: mockZones });
      if (url === "/admin/workers") return Promise.resolve({ data: mockWorkers });
      if (url === "/admin/delivery-trips/unassigned-orders") {
        return Promise.resolve({ data: mockUnassignedOrders });
      }
      if (url.startsWith("/admin/delivery-trips")) {
        return Promise.resolve({
          data: [tripEligible, tripActive, tripNoDeliv, tripCompleted],
        });
      }
      return Promise.reject(new Error(`Unhandled GET url: ${url}`));
    });

    await act(async () => {
      root.render(<AdminLogistics />);
    });

    // 1. Eligible trip has Selesaikan Trip button visible
    expect(
      container.querySelector('[data-testid="btn-complete-trip-TRIP-ELIGIBLE"]')
    ).not.toBeNull();

    // 2. Trip with active stops (out_for_delivery) does NOT show Selesaikan Trip button
    expect(
      container.querySelector('[data-testid="btn-complete-trip-TRIP-ACTIVE"]')
    ).toBeNull();

    // 3. Trip with 0 delivered stops does NOT show Selesaikan Trip button
    expect(
      container.querySelector('[data-testid="btn-complete-trip-TRIP-NO-DELIV"]')
    ).toBeNull();

    // 4. Already completed trip does NOT show Selesaikan Trip button
    expect(
      container.querySelector('[data-testid="btn-complete-trip-TRIP-COMPLETED"]')
    ).toBeNull();
  });

  test("50. Trip completion confirmation modal displays trip summary and explains failed stops release", async () => {
    mockSearchParams = new URLSearchParams("tab=trips");

    const tripWithFailed = {
      ...mockTrips[0],
      id: "trip_pkg7_01",
      trip_number: "TRIP-PKG7-01",
      status: "in_transit",
      stops: [
        { stop_id: "stp_1", order_id: "ord_1", outcome: "delivered" },
        { stop_id: "stp_2", order_id: "ord_2", outcome: "failed" },
      ],
      stops_count: 2,
    };

    api.get.mockImplementation((url) => {
      if (url === "/delivery-zones") return Promise.resolve({ data: mockZones });
      if (url === "/admin/workers") return Promise.resolve({ data: mockWorkers });
      if (url === "/admin/delivery-trips/unassigned-orders") {
        return Promise.resolve({ data: mockUnassignedOrders });
      }
      if (url.startsWith("/admin/delivery-trips")) {
        return Promise.resolve({ data: [tripWithFailed] });
      }
      return Promise.reject(new Error(`Unhandled GET url: ${url}`));
    });

    await act(async () => {
      root.render(<AdminLogistics />);
    });

    // Click Selesaikan Trip
    await act(async () => {
      container
        .querySelector('[data-testid="btn-complete-trip-TRIP-PKG7-01"]')
        .click();
    });

    // Modal is opened
    const modal = container.querySelector('[data-testid="modal-complete-trip"]');
    expect(modal).not.toBeNull();
    expect(modal.textContent).toContain("TRIP-PKG7-01");

    // Summary counts
    const deliveredCount = container.querySelector(
      '[data-testid="complete-summary-delivered-count"]'
    );
    expect(deliveredCount.textContent).toContain("1 Stop");

    const failedCount = container.querySelector(
      '[data-testid="complete-summary-failed-count"]'
    );
    expect(failedCount.textContent).toContain("1 Stop");

    // Warning notice for failed stops is present
    const warning = container.querySelector(
      '[data-testid="complete-trip-failed-warning"]'
    );
    expect(warning).not.toBeNull();
    expect(warning.textContent).toContain("dilepaskan kembali ke Antrean Siap Kirim");
    expect(warning.textContent).toContain("failed_closed");
  });

  test("51. Modal cancellation closes modal without issuing an API call", async () => {
    mockSearchParams = new URLSearchParams("tab=trips");

    const trip = {
      ...mockTrips[0],
      id: "trip_pkg7_cancel",
      trip_number: "TRIP-PKG7-CANCEL",
      status: "in_transit",
      stops: [
        { stop_id: "stp_1", order_id: "ord_1", outcome: "delivered" },
      ],
      stops_count: 1,
    };

    api.get.mockImplementation((url) => {
      if (url === "/delivery-zones") return Promise.resolve({ data: mockZones });
      if (url === "/admin/workers") return Promise.resolve({ data: mockWorkers });
      if (url === "/admin/delivery-trips/unassigned-orders") {
        return Promise.resolve({ data: mockUnassignedOrders });
      }
      if (url.startsWith("/admin/delivery-trips")) {
        return Promise.resolve({ data: [trip] });
      }
      return Promise.reject(new Error(`Unhandled GET url: ${url}`));
    });

    await act(async () => {
      root.render(<AdminLogistics />);
    });

    await act(async () => {
      container
        .querySelector('[data-testid="btn-complete-trip-TRIP-PKG7-CANCEL"]')
        .click();
    });

    expect(container.querySelector('[data-testid="modal-complete-trip"]')).not.toBeNull();

    // Click Batal
    await act(async () => {
      container.querySelector('[data-testid="btn-cancel-complete"]').click();
    });

    expect(container.querySelector('[data-testid="modal-complete-trip"]')).toBeNull();
    expect(api.post).not.toHaveBeenCalled();
  });

  test("52. Submitting completion calls POST /admin/delivery-trips/{trip_id}/complete with optional notes and refreshes state", async () => {
    mockSearchParams = new URLSearchParams("tab=trips");

    const testTrip = {
      ...mockTrips[0],
      id: "trip_pkg7_02",
      trip_number: "TRIP-PKG7-02",
      status: "in_transit",
      stops: [
        { stop_id: "stp_1", order_id: "ord_1", outcome: "delivered" },
        { stop_id: "stp_2", order_id: "ord_2", outcome: "delivered" },
      ],
      stops_count: 2,
    };

    api.get.mockImplementation((url) => {
      if (url === "/delivery-zones") return Promise.resolve({ data: mockZones });
      if (url === "/admin/workers") return Promise.resolve({ data: mockWorkers });
      if (url === "/admin/delivery-trips/unassigned-orders") {
        return Promise.resolve({ data: mockUnassignedOrders });
      }
      if (url.startsWith("/admin/delivery-trips")) {
        return Promise.resolve({ data: [testTrip] });
      }
      return Promise.reject(new Error(`Unhandled GET url: ${url}`));
    });

    api.post.mockResolvedValueOnce({
      data: {
        ...testTrip,
        status: "completed",
        is_partially_completed: false,
        delivered_stops_count: 2,
        failed_stops_count: 0,
        completion_notes: "Semua barang telah sampai dengan selamat",
      },
    });

    await act(async () => {
      root.render(<AdminLogistics />);
    });

    await act(async () => {
      container
        .querySelector('[data-testid="btn-complete-trip-TRIP-PKG7-02"]')
        .click();
    });

    // Enter notes
    const notesInput = container.querySelector('[data-testid="input-complete-notes"]');
    const nativeSetter = Object.getOwnPropertyDescriptor(
      window.HTMLTextAreaElement.prototype,
      "value"
    ).set;

    await act(async () => {
      nativeSetter.call(notesInput, "Semua barang telah sampai dengan selamat");
      notesInput.dispatchEvent(new Event("change", { bubbles: true }));
    });

    // Submit
    await act(async () => {
      container
        .querySelector('[data-testid="btn-confirm-complete-submit"]')
        .click();
    });

    // Correct endpoint and payload
    expect(api.post).toHaveBeenCalledWith(
      "/admin/delivery-trips/trip_pkg7_02/complete",
      { notes: "Semua barang telah sampai dengan selamat" }
    );

    // Modal closed
    expect(container.querySelector('[data-testid="modal-complete-trip"]')).toBeNull();

    // Success notification
    expect(toast.success).toHaveBeenCalledWith(
      expect.stringContaining("TRIP-PKG7-02 berhasil diselesaikan sepenuhnya")
    );
  });

  test("53. Duplicate submit prevention disables button and shows loading state during submission", async () => {
    mockSearchParams = new URLSearchParams("tab=trips");

    const testTrip = {
      ...mockTrips[0],
      id: "trip_pkg7_dup",
      trip_number: "TRIP-PKG7-DUP",
      status: "in_transit",
      stops: [
        { stop_id: "stp_1", order_id: "ord_1", outcome: "delivered" },
      ],
      stops_count: 1,
    };

    api.get.mockImplementation((url) => {
      if (url === "/delivery-zones") return Promise.resolve({ data: mockZones });
      if (url === "/admin/workers") return Promise.resolve({ data: mockWorkers });
      if (url === "/admin/delivery-trips/unassigned-orders") {
        return Promise.resolve({ data: mockUnassignedOrders });
      }
      if (url.startsWith("/admin/delivery-trips")) {
        return Promise.resolve({ data: [testTrip] });
      }
      return Promise.reject(new Error(`Unhandled GET url: ${url}`));
    });

    // Never resolving promise to simulate ongoing request
    let resolvePost;
    api.post.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolvePost = resolve;
        })
    );

    await act(async () => {
      root.render(<AdminLogistics />);
    });

    await act(async () => {
      container
        .querySelector('[data-testid="btn-complete-trip-TRIP-PKG7-DUP"]')
        .click();
    });

    const submitBtn = container.querySelector(
      '[data-testid="btn-confirm-complete-submit"]'
    );

    await act(async () => {
      submitBtn.click();
    });

    // Button should be disabled and show loading label
    expect(submitBtn.disabled).toBe(true);
    expect(submitBtn.textContent).toContain("Menyelesaikan...");

    // Clean up
    await act(async () => {
      resolvePost({
        data: { ...testTrip, status: "completed" },
      });
    });
  });

  test("54. Partial-completion badge is displayed on trip card and stops modal for partially completed trips", async () => {
    mockSearchParams = new URLSearchParams("tab=trips");

    const partialTrip = {
      ...mockTrips[0],
      id: "trip_pkg7_part",
      trip_number: "TRIP-PKG7-PARTIAL",
      status: "completed",
      is_partially_completed: true,
      delivered_stops_count: 1,
      failed_stops_count: 1,
      stops: [
        { stop_id: "s1", order_id: "o1", outcome: "delivered" },
        { stop_id: "s2", order_id: "o2", outcome: "failed_closed" },
      ],
      stops_count: 2,
    };

    api.get.mockImplementation((url) => {
      if (url === "/delivery-zones") return Promise.resolve({ data: mockZones });
      if (url === "/admin/workers") return Promise.resolve({ data: mockWorkers });
      if (url === "/admin/delivery-trips/unassigned-orders") {
        return Promise.resolve({ data: mockUnassignedOrders });
      }
      if (url === "/admin/delivery-trips/trip_pkg7_part") {
        return Promise.resolve({ data: partialTrip });
      }
      if (url.startsWith("/admin/delivery-trips")) {
        return Promise.resolve({ data: [partialTrip] });
      }
      return Promise.reject(new Error(`Unhandled GET url: ${url}`));
    });

    await act(async () => {
      root.render(<AdminLogistics />);
    });

    // 1. Badge on trip card
    const cardBadge = container.querySelector(
      '[data-testid="badge-partial-TRIP-PKG7-PARTIAL"]'
    );
    expect(cardBadge).not.toBeNull();
    expect(cardBadge.textContent).toContain("Selesai Sebagian");

    // 2. Open stops modal
    await act(async () => {
      container
        .querySelector('[data-testid="btn-manage-stops-TRIP-PKG7-PARTIAL"]')
        .click();
    });

    // Badge in modal header
    const modalBadge = container.querySelector('[data-testid="badge-partial-modal"]');
    expect(modalBadge).not.toBeNull();
    expect(modalBadge.textContent).toContain("Selesai Sebagian");
  });

  test("55. HTTP 409 error handling displays server error detail, preserves modal input, and prevents false success", async () => {
    mockSearchParams = new URLSearchParams("tab=trips");

    const testTrip = {
      ...mockTrips[0],
      id: "trip_pkg7_err",
      trip_number: "TRIP-PKG7-ERR",
      status: "in_transit",
      stops: [
        { stop_id: "stp_1", order_id: "ord_1", outcome: "delivered" },
      ],
      stops_count: 1,
    };

    api.get.mockImplementation((url) => {
      if (url === "/delivery-zones") return Promise.resolve({ data: mockZones });
      if (url === "/admin/workers") return Promise.resolve({ data: mockWorkers });
      if (url === "/admin/delivery-trips/unassigned-orders") {
        return Promise.resolve({ data: mockUnassignedOrders });
      }
      if (url.startsWith("/admin/delivery-trips")) {
        return Promise.resolve({ data: [testTrip] });
      }
      return Promise.reject(new Error(`Unhandled GET url: ${url}`));
    });

    api.post.mockRejectedValueOnce({
      response: {
        status: 409,
        data: {
          detail: "Trip tidak memiliki stop yang berhasil diserahterimakan (delivered).",
        },
      },
    });

    await act(async () => {
      root.render(<AdminLogistics />);
    });

    await act(async () => {
      container
        .querySelector('[data-testid="btn-complete-trip-TRIP-PKG7-ERR"]')
        .click();
    });

    // Enter notes
    const notesInput = container.querySelector('[data-testid="input-complete-notes"]');
    const nativeSetter = Object.getOwnPropertyDescriptor(
      window.HTMLTextAreaElement.prototype,
      "value"
    ).set;

    await act(async () => {
      nativeSetter.call(notesInput, "Catatan yang tidak boleh hilang");
      notesInput.dispatchEvent(new Event("change", { bubbles: true }));
    });

    // Submit
    await act(async () => {
      container
        .querySelector('[data-testid="btn-confirm-complete-submit"]')
        .click();
    });

    // Error alert is displayed inside modal
    const errorAlert = container.querySelector(
      '[data-testid="complete-error-message"]'
    );
    expect(errorAlert).not.toBeNull();
    expect(errorAlert.textContent).toContain(
      "Trip tidak memiliki stop yang berhasil diserahterimakan"
    );

    // Modal remains open
    expect(container.querySelector('[data-testid="modal-complete-trip"]')).not.toBeNull();

    // Notes preserved
    expect(container.querySelector('[data-testid="input-complete-notes"]').value).toBe(
      "Catatan yang tidak boleh hilang"
    );

    // No false success
    expect(toast.success).not.toHaveBeenCalled();
    expect(toast.error).toHaveBeenCalledWith(
      expect.stringContaining("Tidak Dapat Diselesaikan")
    );
  });

  test("56. Manage stops modal provides Selesaikan Trip button for eligible trips", async () => {
    mockSearchParams = new URLSearchParams("tab=trips");

    const testTrip = {
      ...mockTrips[0],
      id: "trip_pkg7_stops_modal",
      trip_number: "TRIP-PKG7-MODAL",
      status: "in_transit",
      stops: [
        { stop_id: "stp_1", order_id: "ord_1", outcome: "delivered" },
        { stop_id: "stp_2", order_id: "ord_2", outcome: "failed" },
      ],
      stops_count: 2,
    };

    api.get.mockImplementation((url) => {
      if (url === "/delivery-zones") return Promise.resolve({ data: mockZones });
      if (url === "/admin/workers") return Promise.resolve({ data: mockWorkers });
      if (url === "/admin/delivery-trips/unassigned-orders") {
        return Promise.resolve({ data: mockUnassignedOrders });
      }
      if (url === "/admin/delivery-trips/trip_pkg7_stops_modal") {
        return Promise.resolve({ data: testTrip });
      }
      if (url.startsWith("/admin/delivery-trips")) {
        return Promise.resolve({ data: [testTrip] });
      }
      return Promise.reject(new Error(`Unhandled GET url: ${url}`));
    });

    await act(async () => {
      root.render(<AdminLogistics />);
    });

    // Open stops modal
    await act(async () => {
      container
        .querySelector('[data-testid="btn-manage-stops-TRIP-PKG7-MODAL"]')
        .click();
    });

    // Selesaikan Trip button inside modal is visible
    const modalCompleteBtn = container.querySelector(
      '[data-testid="btn-complete-trip-modal"]'
    );
    expect(modalCompleteBtn).not.toBeNull();

    // Click it to trigger complete confirmation modal
    await act(async () => {
      modalCompleteBtn.click();
    });

    expect(container.querySelector('[data-testid="modal-complete-trip"]')).not.toBeNull();
  });

  // -------------------------------------------------------------------------
  // Phase 3.F.4.3 Package 8.1 - Ready Queue Retry Badge Tests
  // -------------------------------------------------------------------------

  test("Test 57: Order with delivery_logistics_status === 'delivery_failed' renders 'Pengantaran Ulang' badge in ready queue", async () => {
    const mockOrdersWithRetry = [
      {
        id: "ord_retry_1",
        order_number: "ORD-RETRY-001",
        customer_name: "Customer Retry",
        customer_phone: "+201011112222",
        customer_address: "Nasr City, Cairo",
        delivery_method: "delivery",
        total_le: 1800.0,
        order_status: "siap",
        delivery_logistics_status: "delivery_failed",
        total_items_count: 1,
        items_summary: [{ name: "Lemari 2 Pintu", quantity: 1 }],
        created_at: "2026-10-15T08:00:00Z",
      },
      {
        id: "ord_normal_1",
        order_number: "ORD-NORMAL-001",
        customer_name: "Customer Normal",
        customer_phone: "+201033334444",
        customer_address: "Maadi, Cairo",
        delivery_method: "delivery",
        total_le: 900.0,
        order_status: "siap",
        delivery_logistics_status: "unassigned",
        total_items_count: 1,
        items_summary: [{ name: "Kursi Makan", quantity: 1 }],
        created_at: "2026-10-15T09:00:00Z",
      },
    ];

    api.get.mockImplementation((url) => {
      if (url === "/delivery-zones") return Promise.resolve({ data: mockZones });
      if (url === "/admin/workers") return Promise.resolve({ data: mockWorkers });
      if (url.startsWith("/admin/delivery-trips/unassigned-orders")) {
        return Promise.resolve({ data: mockOrdersWithRetry });
      }
      if (url.startsWith("/admin/delivery-trips")) {
        return Promise.resolve({ data: [] });
      }
      return Promise.reject(new Error(`Unhandled GET url: ${url}`));
    });

    await act(async () => {
      root.render(<AdminLogistics />);
    });

    // Retry badge must be rendered for ord_retry_1
    const retryBadge = container.querySelector('[data-testid="badge-retry-ORD-RETRY-001"]');
    expect(retryBadge).not.toBeNull();
    expect(retryBadge.textContent).toContain("Pengantaran Ulang");

    // Normal order must NOT have retry badge
    const normalBadge = container.querySelector('[data-testid="badge-retry-ORD-NORMAL-001"]');
    expect(normalBadge).toBeNull();
  });

  test("Test 58: Unrelated or standard orders do not display 'Pengantaran Ulang' badge", async () => {
    const standardOrders = [
      {
        id: "ord_std_1",
        order_number: "ORD-STD-001",
        customer_name: "Standard Order",
        customer_phone: "+201055556666",
        customer_address: "Zamalek, Cairo",
        delivery_method: "delivery",
        total_le: 1500.0,
        order_status: "siap",
        delivery_logistics_status: "unassigned",
        total_items_count: 1,
        items_summary: [{ name: "Meja Kopi", quantity: 1 }],
        created_at: "2026-10-15T10:00:00Z",
      },
    ];

    api.get.mockImplementation((url) => {
      if (url === "/delivery-zones") return Promise.resolve({ data: mockZones });
      if (url === "/admin/workers") return Promise.resolve({ data: mockWorkers });
      if (url.startsWith("/admin/delivery-trips/unassigned-orders")) {
        return Promise.resolve({ data: standardOrders });
      }
      if (url.startsWith("/admin/delivery-trips")) {
        return Promise.resolve({ data: [] });
      }
      return Promise.reject(new Error(`Unhandled GET url: ${url}`));
    });

    await act(async () => {
      root.render(<AdminLogistics />);
    });

    const anyRetryBadge = container.querySelector('[data-testid^="badge-retry-"]');
    expect(anyRetryBadge).toBeNull();
    expect(container.textContent).not.toContain("Pengantaran Ulang");
  });

  test("Test 59: Re-queued orders with 'Pengantaran Ulang' can be selected and assigned to trip normally", async () => {
    const mockOrdersWithRetry = [
      {
        id: "ord_retry_2",
        order_number: "ORD-RETRY-002",
        customer_name: "Customer Retry Two",
        customer_phone: "+201077778888",
        customer_address: "Dokki, Giza",
        delivery_method: "delivery",
        total_le: 2200.0,
        order_status: "siap",
        delivery_logistics_status: "delivery_failed",
        total_items_count: 1,
        items_summary: [{ name: "Sofa Minimalis", quantity: 1 }],
        created_at: "2026-10-15T08:30:00Z",
      },
    ];

    const draftTrip = {
      _id: "trip_draft_target",
      id: "trip_draft_target",
      trip_number: "TRP-20261015-DRAFT",
      status: "draft",
      scheduled_date: "2026-10-15",
      stops: [],
      stops_count: 0,
      helpers: [{ helper_id: "w_1", helper_name: "Ali Hassan" }],
    };

    api.get.mockImplementation((url) => {
      if (url === "/delivery-zones") return Promise.resolve({ data: mockZones });
      if (url === "/admin/workers") return Promise.resolve({ data: mockWorkers });
      if (url.startsWith("/admin/delivery-trips/unassigned-orders")) {
        return Promise.resolve({ data: mockOrdersWithRetry });
      }
      if (url.startsWith("/admin/delivery-trips")) {
        return Promise.resolve({ data: [draftTrip] });
      }
      return Promise.reject(new Error(`Unhandled GET url: ${url}`));
    });

    api.post.mockImplementation((url) => {
      if (url === "/admin/delivery-trips/trip_draft_target/stops") {
        return Promise.resolve({ data: { ok: true } });
      }
      return Promise.reject(new Error(`Unhandled POST url: ${url}`));
    });

    await act(async () => {
      root.render(<AdminLogistics />);
    });

    // Checkbox is clickable
    const checkbox = container.querySelector('[data-testid="checkbox-order-ORD-RETRY-002"]');
    expect(checkbox).not.toBeNull();
    await act(async () => {
      checkbox.click();
    });

    // Action bar appears
    const assignBtn = container.querySelector('[data-testid="btn-assign-selected"]');
    expect(assignBtn).not.toBeNull();
    await act(async () => {
      assignBtn.click();
    });

    // Modal to choose trip opens
    expect(container.querySelector('[data-testid="modal-assign-orders"]')).not.toBeNull();

    // Select draft trip option
    const tripOption = container.querySelector('[data-testid="trip-select-options"] > div');
    expect(tripOption).not.toBeNull();
    await act(async () => {
      tripOption.click();
    });

    // Submit assignment
    const confirmAssignBtn = container.querySelector('[data-testid="btn-confirm-assign-orders"]');
    await act(async () => {
      confirmAssignBtn.click();
    });

    expect(api.post).toHaveBeenCalledWith(
      "/admin/delivery-trips/trip_draft_target/stops",
      { order_id: "ord_retry_2" }
    );
  });
});


