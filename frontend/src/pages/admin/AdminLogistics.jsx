import React, { useEffect, useState, useCallback, useMemo } from "react";
import { Link, useSearchParams } from "react-router-dom";
import api from "../../lib/api";
import { fmtLE, formatApiError } from "../../lib/format";
import { useAuth } from "../../context/AuthContext";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import {
  Truck,
  Package,
  Clock,
  Calendar,
  MapPin,
  Users,
  CheckCircle2,
  AlertCircle,
  AlertTriangle,
  Search,
  Filter,
  RotateCcw,
  ExternalLink,
  Phone,
  ShieldCheck,
  ShieldAlert,
  ShoppingBag,
  X,
  Car,
  FileText,
  Plus,
  CheckSquare,
  Square,
  ArrowRight,
  Trash2,
  Navigation,
  Info,
  Lock,
  XCircle,
  ChevronDown,
  ChevronUp,
  Loader2
} from "lucide-react";
import { toast } from "sonner";

export const getStopMapUrl = (stop) => {
  if (!stop) return null;
  // 1. Customer-provided Google Maps URL takes highest precedence
  if (stop.customer_maps_url && typeof stop.customer_maps_url === "string" && stop.customer_maps_url.trim()) {
    return stop.customer_maps_url.trim();
  }
  // 2. Stored full customer street address
  if (stop.customer_address && typeof stop.customer_address === "string" && stop.customer_address.trim()) {
    return `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(stop.customer_address.trim())}`;
  }
  // 3. Fallback only: delivery zone name
  if (stop.delivery_zone && typeof stop.delivery_zone === "string" && stop.delivery_zone.trim()) {
    return `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(stop.delivery_zone.trim())}`;
  }
  return null;
};

export const extractLocationFromMapsUrl = (rawUrl) => {
  if (!rawUrl || typeof rawUrl !== "string") return null;
  const trimmed = rawUrl.trim();
  if (!trimmed) return null;

  try {
    const urlStr = /^https?:\/\//i.test(trimmed) ? trimmed : `https://${trimmed}`;
    const u = new URL(urlStr);

    // 1. Supported query parameters: q, query, daddr, ll
    const q =
      u.searchParams.get("q") ||
      u.searchParams.get("query") ||
      u.searchParams.get("daddr") ||
      u.searchParams.get("ll");
    if (q && q.trim()) {
      return q.trim();
    }

    // 2. Coordinate paths such as /@latitude,longitude
    const coordMatch = trimmed.match(/@(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)/);
    if (coordMatch) {
      const lat = parseFloat(coordMatch[1]);
      const lng = parseFloat(coordMatch[2]);
      if (!Number.isNaN(lat) && !Number.isNaN(lng) && lat >= -90 && lat <= 90 && lng >= -180 && lng <= 180) {
        return `${coordMatch[1]},${coordMatch[2]}`;
      }
    }
  } catch {
    // Malformed URL - cannot be parsed reliably
  }

  return null;
};

export const buildGoogleMapsMultiStopUrl = (stops) => {
  if (!stops || stops.length === 0) return null;
  const validLocations = stops
    .map((s) => {
      // 1. First precedence: usable customer-provided Google Maps destination
      if (s.customer_maps_url && typeof s.customer_maps_url === "string") {
        const mapsDest = extractLocationFromMapsUrl(s.customer_maps_url);
        if (mapsDest) return mapsDest;
      }
      // 2. Second precedence: full customer street address
      if (s.customer_address && typeof s.customer_address === "string" && s.customer_address.trim()) {
        return s.customer_address.trim();
      }
      // 3. Third precedence (fallback only): delivery zone name
      if (s.delivery_zone && typeof s.delivery_zone === "string" && s.delivery_zone.trim()) {
        return s.delivery_zone.trim();
      }
      // Exclude stop from routing if no usable destination
      return null;
    })
    .filter(Boolean);

  if (validLocations.length === 0) return null;
  if (validLocations.length === 1) {
    return `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(validLocations[0])}`;
  }

  const destination = validLocations[validLocations.length - 1];
  const waypoints = validLocations.slice(0, -1).join("|");
  return `https://www.google.com/maps/dir/?api=1&destination=${encodeURIComponent(destination)}&waypoints=${encodeURIComponent(waypoints)}`;
};

export default function AdminLogistics() {
  const { user } = useAuth();
  const isOwner = user?.role === "owner";
  const canManageOrders = Boolean(user?.permissions?.manage_orders || isOwner);

  const [searchParams, setSearchParams] = useSearchParams();
  const currentTab = searchParams.get("tab") === "trips" ? "trips" : "ready";

  // Data states
  const [readyOrders, setReadyOrders] = useState([]);
  const [loadingQueue, setLoadingQueue] = useState(true);
  const [queueError, setQueueError] = useState(null);

  const [trips, setTrips] = useState([]);
  const [loadingTrips, setLoadingTrips] = useState(true);
  const [tripsError, setTripsError] = useState(null);

  const [zones, setZones] = useState([]);
  const [workers, setWorkers] = useState([]);
  const [refreshing, setRefreshing] = useState(false);

  // Global KPI Metrics state (independent of list filters)
  const [globalMetrics, setGlobalMetrics] = useState({
    readyCount: 0,
    activeTripsCount: 0,
    completedTripsCount: 0
  });

  // Ready Queue Filter states
  const [searchInput, setSearchInput] = useState("");
  const [appliedSearch, setAppliedSearch] = useState("");
  const [selectedZone, setSelectedZone] = useState("");

  // Ready Queue Multi-Selection state
  const [selectedOrderIds, setSelectedOrderIds] = useState([]);

  // Trips Filter states
  const [statusFilter, setStatusFilter] = useState("all");
  const [dateFilter, setDateFilter] = useState("");

  // Modal 1: Create Trip State
  const [createModalOpen, setCreateModalOpen] = useState(false);
  const [submittingTrip, setSubmittingTrip] = useState(false);
  const [tripFormErrors, setTripFormErrors] = useState({});
  const [tripFormData, setTripFormData] = useState({
    scheduled_date: new Date().toISOString().slice(0, 10),
    departure_time: "09:00",
    trip_wage_rate_le: 50.0,
    helper_ids: [],
    vehicle_type: "rental", // "rental" | "internal"
    rental_provider: "",
    vehicle_plate_or_desc: "",
    driver_provided_by_rental: true,
    rental_driver_name: "",
    agreed_rental_cost_le: 350.0,
    agreement_reference: "",
    notes: ""
  });

  // Modal 2: Assign Orders to Trip State
  const [assignModalOpen, setAssignModalOpen] = useState(false);
  const [targetTripId, setTargetTripId] = useState("");
  const [assigningOrders, setAssigningOrders] = useState(false);
  const [conflictErrors, setConflictErrors] = useState([]);

  // Modal 3: Manage Trip Stops & Route State
  const [stopsModalOpen, setStopsModalOpen] = useState(false);
  const [activeTrip, setActiveTrip] = useState(null);
  const [loadingActiveTrip, setLoadingActiveTrip] = useState(false);

  // Release Confirmation Dialog State
  const [releaseConfirmOpen, setReleaseConfirmOpen] = useState(false);
  const [stopToRelease, setStopToRelease] = useState(null);
  const [releasing, setReleasing] = useState(false);

  // Dispatch Confirmation Modal State
  const [dispatchModalOpen, setDispatchModalOpen] = useState(false);
  const [tripToDispatch, setTripToDispatch] = useState(null);
  const [dispatching, setDispatching] = useState(false);
  const [dispatchError, setDispatchError] = useState(null);

  // Cancel Confirmation Modal State
  const [cancelModalOpen, setCancelModalOpen] = useState(false);
  const [tripToCancel, setTripToCancel] = useState(null);
  const [cancellationReason, setCancellationReason] = useState("");
  const [cancelling, setCancelling] = useState(false);
  const [cancelError, setCancelError] = useState(null);

  // Modal 4: Handover Confirmation State (Package 5)
  const [handoverModalOpen, setHandoverModalOpen] = useState(false);
  const [stopForHandover, setStopForHandover] = useState(null);
  const [recipientName, setRecipientName] = useState("");
  const [handoverNotes, setHandoverNotes] = useState("");
  const [helperConfirmed, setHelperConfirmed] = useState(false);
  const [isCustomWage, setIsCustomWage] = useState(false);
  const [customWageLe, setCustomWageLe] = useState("");
  const [confirmedUnusualAmount, setConfirmedUnusualAmount] = useState(false);
  const [overrideReason, setOverrideReason] = useState("");
  const [submittingHandover, setSubmittingHandover] = useState(false);
  const [handoverError, setHandoverError] = useState(null);

  // Failed Attempt & Retry Modal State (Package 6)
  const [failAttemptModalOpen, setFailAttemptModalOpen] = useState(false);
  const [stopForFailAttempt, setStopForFailAttempt] = useState(null);
  const [failureReason, setFailureReason] = useState("");
  const [failureNotes, setFailureNotes] = useState("");
  const [submittingFailAttempt, setSubmittingFailAttempt] = useState(false);
  const [failAttemptError, setFailAttemptError] = useState(null);
  const [retryingStopId, setRetryingStopId] = useState(null);
  const [expandedAttemptsStopIds, setExpandedAttemptsStopIds] = useState({});

  // Modal 5: Trip Completion Confirmation State (Package 7B)
  const [completeModalOpen, setCompleteModalOpen] = useState(false);
  const [tripToComplete, setTripToComplete] = useState(null);
  const [completionNotes, setCompletionNotes] = useState("");
  const [completing, setCompleting] = useState(false);
  const [completeError, setCompleteError] = useState(null);

  // Tab switcher
  const handleTabChange = (tabKey) => {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      if (tabKey === "trips") {
        next.set("tab", "trips");
      } else {
        next.delete("tab");
      }
      return next;
    });
  };

  // 1. Fetch Delivery Zones
  const loadZones = useCallback(async () => {
    try {
      const res = await api.get("/delivery-zones");
      if (Array.isArray(res.data)) {
        setZones(res.data);
      }
    } catch {
      // Non-critical
    }
  }, []);

  // 2. Fetch Available Workers (Helpers)
  const loadWorkers = useCallback(async () => {
    try {
      const res = await api.get("/admin/workers");
      if (Array.isArray(res.data)) {
        setWorkers(res.data);
      }
    } catch {
      // Non-critical
    }
  }, []);

  // 3. Fetch Global KPI Metrics (independent of tab filters)
  const loadGlobalMetrics = useCallback(async () => {
    try {
      const [queueRes, tripsRes] = await Promise.all([
        api.get("/admin/delivery-trips/unassigned-orders", { params: { limit: 500 } }),
        api.get("/admin/delivery-trips", { params: { limit: 500 } })
      ]);
      const queueList = Array.isArray(queueRes.data) ? queueRes.data : [];
      const tripsList = Array.isArray(tripsRes.data) ? tripsRes.data : [];
      const readyCount = queueList.length;
      const activeTripsCount = tripsList.filter(
        (t) => t.status === "scheduled" || t.status === "in_transit"
      ).length;
      const completedTripsCount = tripsList.filter((t) => t.status === "completed").length;
      setGlobalMetrics({ readyCount, activeTripsCount, completedTripsCount });
    } catch {
      // Fallback
    }
  }, []);

  // 4. Fetch Ready Queue (Unassigned Orders)
  const loadReadyQueue = useCallback(async (qParam, zoneParam) => {
    setLoadingQueue(true);
    setQueueError(null);
    try {
      const params = { limit: 100 };
      if (qParam && qParam.trim()) {
        params.q = qParam.trim();
      }
      if (zoneParam && zoneParam.trim()) {
        params.delivery_zone_id = zoneParam.trim();
      }
      const res = await api.get("/admin/delivery-trips/unassigned-orders", { params });
      setReadyOrders(Array.isArray(res.data) ? res.data : []);
    } catch (err) {
      const msg = formatApiError(err?.response?.data?.detail || err?.message);
      setQueueError(msg);
      toast.error(`Gagal memuat antrean kirim: ${msg}`);
    } finally {
      setLoadingQueue(false);
    }
  }, []);

  // 5. Fetch Delivery Trips
  const loadTrips = useCallback(async (stParam, dateParam) => {
    setLoadingTrips(true);
    setTripsError(null);
    try {
      const params = { limit: 100 };
      if (stParam && stParam !== "all") {
        params.status = stParam;
      }
      if (dateParam && dateParam.trim()) {
        params.scheduled_date = dateParam.trim();
      }
      const res = await api.get("/admin/delivery-trips", { params });
      setTrips(Array.isArray(res.data) ? res.data : []);
    } catch (err) {
      const msg = formatApiError(err?.response?.data?.detail || err?.message);
      setTripsError(msg);
      toast.error(`Gagal memuat trip armada: ${msg}`);
    } finally {
      setLoadingTrips(false);
    }
  }, []);

  // Manual refresh all
  const handleRefreshAll = async () => {
    setRefreshing(true);
    try {
      await Promise.all([
        loadReadyQueue(appliedSearch, selectedZone),
        loadTrips(statusFilter, dateFilter),
        loadGlobalMetrics()
      ]);
      toast.success("Data logistik berhasil diperbarui");
    } finally {
      setRefreshing(false);
    }
  };

  // Initial load
  useEffect(() => {
    if (canManageOrders) {
      loadZones();
      loadWorkers();
      loadGlobalMetrics();
      loadReadyQueue(appliedSearch, selectedZone);
      loadTrips(statusFilter, dateFilter);
    }
  }, [canManageOrders, loadZones, loadWorkers, loadGlobalMetrics, loadReadyQueue, loadTrips, appliedSearch, selectedZone, statusFilter, dateFilter]);

  // Handle Search in Ready Queue
  const handleSearchSubmit = (e) => {
    e.preventDefault();
    setAppliedSearch(searchInput.trim());
  };

  const handleClearSearch = () => {
    setSearchInput("");
    setAppliedSearch("");
  };

  // Ready Queue Multi-Selection Helpers
  const handleToggleSelectOrder = (orderId) => {
    setSelectedOrderIds((prev) =>
      prev.includes(orderId) ? prev.filter((id) => id !== orderId) : [...prev, orderId]
    );
  };

  const handleSelectAllOrders = () => {
    if (selectedOrderIds.length === readyOrders.length) {
      setSelectedOrderIds([]);
    } else {
      setSelectedOrderIds(readyOrders.map((o) => o.id));
    }
  };

  // Trip Creation Form Handlers
  const handleOpenCreateModal = () => {
    setTripFormData({
      scheduled_date: new Date().toISOString().slice(0, 10),
      departure_time: "09:00",
      trip_wage_rate_le: 50.0,
      helper_ids: [],
      vehicle_type: "rental",
      rental_provider: "",
      vehicle_plate_or_desc: "",
      driver_provided_by_rental: true,
      rental_driver_name: "",
      agreed_rental_cost_le: 350.0,
      agreement_reference: "",
      notes: ""
    });
    setTripFormErrors({});
    setCreateModalOpen(true);
  };

  const handleToggleHelper = (workerId) => {
    setTripFormData((prev) => {
      const exists = prev.helper_ids.includes(workerId);
      return {
        ...prev,
        helper_ids: exists
          ? prev.helper_ids.filter((id) => id !== workerId)
          : [...prev.helper_ids, workerId]
      };
    });
  };

  const handleCreateTripSubmit = async (e) => {
    e.preventDefault();
    const errors = {};

    if (!tripFormData.scheduled_date) {
      errors.scheduled_date = "Tanggal keberangkatan wajib diisi";
    }

    if (tripFormData.vehicle_type === "rental") {
      if (!tripFormData.rental_provider || tripFormData.rental_provider.trim().length < 2) {
        errors.rental_provider = "Nama vendor rental minimal 2 karakter";
      }
      if (!tripFormData.vehicle_plate_or_desc || tripFormData.vehicle_plate_or_desc.trim().length < 2) {
        errors.vehicle_plate_or_desc = "Plat nomor atau deskripsi armada minimal 2 karakter";
      }
      if (!tripFormData.rental_driver_name || tripFormData.rental_driver_name.trim().length < 2) {
        errors.rental_driver_name = "Nama sopir minimal 2 karakter";
      }
    } else {
      // Internal vehicle
      if (!tripFormData.vehicle_plate_or_desc || tripFormData.vehicle_plate_or_desc.trim().length < 2) {
        errors.vehicle_plate_or_desc = "Plat nomor atau nama armada toko minimal 2 karakter";
      }
      if (!tripFormData.rental_driver_name || tripFormData.rental_driver_name.trim().length < 2) {
        errors.rental_driver_name = "Nama pengemudi internal minimal 2 karakter";
      }
    }

    if (Object.keys(errors).length > 0) {
      setTripFormErrors(errors);
      return;
    }

    setSubmittingTrip(true);
    setTripFormErrors({});

    try {
      const isRental = tripFormData.vehicle_type === "rental";
      const payload = {
        scheduled_date: tripFormData.scheduled_date.trim(),
        departure_time: tripFormData.departure_time ? tripFormData.departure_time.trim() : null,
        trip_wage_rate_le: Number(tripFormData.trip_wage_rate_le) || 0.0,
        helper_ids: tripFormData.helper_ids,
        vehicle_rental: {
          is_rented: isRental,
          rental_provider: isRental ? tripFormData.rental_provider.trim() : "Armada Toko",
          vehicle_plate_or_desc: tripFormData.vehicle_plate_or_desc.trim(),
          driver_provided_by_rental: isRental ? Boolean(tripFormData.driver_provided_by_rental) : false,
          rental_driver_name: tripFormData.rental_driver_name.trim(),
          agreed_rental_cost_le: isRental ? Number(tripFormData.agreed_rental_cost_le) || 0.0 : 0.0,
          agreement_reference: isRental && tripFormData.agreement_reference ? tripFormData.agreement_reference.trim() : null,
          notes: tripFormData.notes ? tripFormData.notes.trim() : null
        },
        notes: tripFormData.notes ? tripFormData.notes.trim() : null
      };

      const res = await api.post("/admin/delivery-trips", payload);
      toast.success(`Trip ${res.data.trip_number || ""} berhasil dibuat!`);
      setCreateModalOpen(false);

      // Refresh list & metrics
      await Promise.all([
        loadTrips(statusFilter, dateFilter),
        loadGlobalMetrics()
      ]);

      // If user had selected orders, suggest assigning them
      if (selectedOrderIds.length > 0) {
        setTargetTripId(res.data.id || res.data._id);
        setAssignModalOpen(true);
      }
    } catch (err) {
      const detail = formatApiError(err?.response?.data?.detail || err?.message);
      toast.error(`Gagal membuat trip: ${detail}`);
    } finally {
      setSubmittingTrip(false);
    }
  };

  // Order Assignment Execution (with Concurrency Conflict Handling)
  const handleExecuteAssignOrders = async () => {
    if (!targetTripId) {
      toast.error("Pilih trip tujuan terlebih dahulu");
      return;
    }
    if (selectedOrderIds.length === 0) {
      toast.error("Pilih minimal 1 pesanan untuk ditugaskan");
      return;
    }

    setAssigningOrders(true);
    setConflictErrors([]);
    const conflicts = [];
    let successCount = 0;

    for (const orderId of selectedOrderIds) {
      const orderObj = readyOrders.find((o) => o.id === orderId);
      const orderNum = orderObj?.order_number || `#${orderId.slice(-6)}`;
      try {
        await api.post(`/admin/delivery-trips/${targetTripId}/stops`, {
          order_id: orderId
        });
        successCount++;
      } catch (err) {
        const status = err?.response?.status;
        const detail = formatApiError(err?.response?.data?.detail || err?.message);
        if (status === 409) {
          conflicts.push(`Pesanan ${orderNum}: ${detail}`);
        } else {
          conflicts.push(`Pesanan ${orderNum}: Gagal (${detail})`);
        }
      }
    }

    // Refresh datasets immediately to clear stale records
    await Promise.all([
      loadReadyQueue(appliedSearch, selectedZone),
      loadTrips(statusFilter, dateFilter),
      loadGlobalMetrics()
    ]);

    // If active trip modal is open, refresh it
    if (activeTrip && (activeTrip.id === targetTripId || activeTrip._id === targetTripId)) {
      try {
        const res = await api.get(`/admin/delivery-trips/${targetTripId}`);
        setActiveTrip(res.data);
      } catch {
        // Non-critical
      }
    }

    setAssigningOrders(false);
    setAssignModalOpen(false);
    setSelectedOrderIds([]);

    if (conflicts.length > 0) {
      setConflictErrors(conflicts);
      if (successCount > 0) {
        toast.warning(
          `${successCount} pesanan berhasil ditugaskan, tetapi ${conflicts.length} pesanan mengalami konflik konkurensi/status.`
        );
      } else {
        toast.error(`Gagal menugaskan pesanan: ${conflicts[0]}`);
      }
    } else {
      toast.success(`Berhasil menugaskan ${successCount} pesanan ke trip!`);
    }
  };

  // Open Manage Stops Modal for a Trip
  const handleOpenStopsModal = async (trip) => {
    setActiveTrip(trip);
    setStopsModalOpen(true);
    setLoadingActiveTrip(true);
    try {
      const res = await api.get(`/admin/delivery-trips/${trip.id || trip._id}`);
      setActiveTrip(res.data);
    } catch (err) {
      const detail = formatApiError(err?.response?.data?.detail || err?.message);
      toast.error(`Gagal memuat detail stop trip: ${detail}`);
    } finally {
      setLoadingActiveTrip(false);
    }
  };

  // Order Release Execution
  const handleConfirmReleaseStop = async () => {
    if (!activeTrip || !stopToRelease) return;
    setReleasing(true);
    const tripId = activeTrip.id || activeTrip._id;
    const orderId = stopToRelease.order_id;

    try {
      const res = await api.delete(`/admin/delivery-trips/${tripId}/stops/${orderId}`);
      toast.success(
        `Pesanan ${stopToRelease.order_number || ""} berhasil dilepas dari trip dan kembali ke antrean siap kirim.`
      );
      setActiveTrip(res.data);
      setReleaseConfirmOpen(false);
      setStopToRelease(null);

      // Refresh data
      await Promise.all([
        loadReadyQueue(appliedSearch, selectedZone),
        loadTrips(statusFilter, dateFilter),
        loadGlobalMetrics()
      ]);
    } catch (err) {
      const detail = formatApiError(err?.response?.data?.detail || err?.message);
      toast.error(`Gagal melepaskan pesanan: ${detail}`);
    } finally {
      setReleasing(false);
    }
  };

  // Open Dispatch Modal
  const handleOpenDispatchModal = (trip) => {
    setTripToDispatch(trip);
    setDispatchError(null);
    setDispatchModalOpen(true);
  };

  // Dispatch Execution
  const handleConfirmDispatch = async () => {
    if (!tripToDispatch) return;
    setDispatching(true);
    setDispatchError(null);
    const tripId = tripToDispatch.id || tripToDispatch._id;

    try {
      // If trip is in draft status, backend VALID_TRIP_TRANSITIONS requires transitioning draft -> scheduled first
      if (tripToDispatch.status === "draft") {
        await api.patch(`/admin/delivery-trips/${tripId}/status`, {
          target_status: "scheduled"
        });
      }

      const res = await api.patch(`/admin/delivery-trips/${tripId}/status`, {
        target_status: "in_transit"
      });

      toast.success(
        `Armada ${tripToDispatch.trip_number} berhasil diberangkatkan! Snapshot kebijakan upah telah dikunci.`
      );
      setDispatchModalOpen(false);
      setTripToDispatch(null);

      // Refresh authoritative data
      await Promise.all([
        loadReadyQueue(appliedSearch, selectedZone),
        loadTrips(statusFilter, dateFilter),
        loadGlobalMetrics()
      ]);

      if (stopsModalOpen && activeTrip && (activeTrip.id === tripId || activeTrip._id === tripId)) {
        setActiveTrip(res.data);
      }
    } catch (err) {
      const detail = err.response?.data?.detail || err.message || "Gagal memberangkatkan armada";
      setDispatchError(detail);
      if (err.response?.status === 422) {
        toast.error(`Gagal Dispatch (Batas Upah): ${detail}`);
      } else {
        toast.error(`Gagal Dispatch: ${detail}`);
      }
    } finally {
      setDispatching(false);
    }
  };

  // Open Cancel Modal
  const handleOpenCancelModal = (trip) => {
    setTripToCancel(trip);
    setCancellationReason("");
    setCancelError(null);
    setCancelModalOpen(true);
  };

  // Cancel Trip Execution
  const handleConfirmCancel = async () => {
    if (!tripToCancel) return;
    const reason = cancellationReason.trim();
    if (reason.length < 5) {
      setCancelError("Alasan pembatalan wajib diisi (minimal 5 karakter).");
      return;
    }

    setCancelling(true);
    setCancelError(null);
    const tripId = tripToCancel.id || tripToCancel._id;

    try {
      const res = await api.post(`/admin/delivery-trips/${tripId}/cancel`, {
        reason
      });

      toast.success(
        `Trip ${tripToCancel.trip_number} berhasil dibatalkan. Pesanan telah dikembalikan ke Antrean Siap Kirim.`
      );
      setCancelModalOpen(false);
      setTripToCancel(null);

      // Refresh authoritative data
      await Promise.all([
        loadReadyQueue(appliedSearch, selectedZone),
        loadTrips(statusFilter, dateFilter),
        loadGlobalMetrics()
      ]);

      if (stopsModalOpen && activeTrip && (activeTrip.id === tripId || activeTrip._id === tripId)) {
        setActiveTrip(res.data);
      }
    } catch (err) {
      const detail = err.response?.data?.detail || err.message || "Gagal membatalkan trip";
      setCancelError(detail);
      if (err.response?.status === 409) {
        toast.error(`Tidak Dapat Dibatalkan: ${detail}`);
      } else {
        toast.error(`Gagal Membatalkan Trip: ${detail}`);
      }
    } finally {
      setCancelling(false);
    }
  };

  // Trip Completion Eligibility Checker (Package 7B)
  const isTripEligibleForCompletion = (trip) => {
    if (!trip) return false;
    if (trip.status !== "in_transit" && trip.status !== "partially_completed") return false;
    const stops = Array.isArray(trip.stops) ? trip.stops : [];
    const deliveredCount = stops.filter((s) => s.outcome === "delivered").length;
    const activeCount = stops.filter((s) => s.outcome === "pending" || s.outcome === "out_for_delivery").length;
    return deliveredCount >= 1 && activeCount === 0;
  };

  // Open Complete Modal (Package 7B)
  const handleOpenCompleteModal = (trip) => {
    setTripToComplete(trip);
    setCompletionNotes("");
    setCompleteError(null);
    setCompleteModalOpen(true);
  };

  // Confirm Complete Trip Execution (Package 7B)
  const handleConfirmCompleteTrip = async () => {
    if (!tripToComplete) return;

    setCompleting(true);
    setCompleteError(null);
    const tripId = tripToComplete.id || tripToComplete._id;

    try {
      const payload = {};
      if (completionNotes && completionNotes.trim()) {
        payload.notes = completionNotes.trim();
      }

      const res = await api.post(`/admin/delivery-trips/${tripId}/complete`, payload);

      const isPartial = Boolean(res.data?.is_partially_completed);
      const successMsg = isPartial
        ? `Trip ${tripToComplete.trip_number} selesai (sebagian). Pesanan yang gagal telah dikembalikan ke Antrean Siap Kirim.`
        : `Trip ${tripToComplete.trip_number} berhasil diselesaikan sepenuhnya!`;

      toast.success(successMsg);
      setCompleteModalOpen(false);
      setTripToComplete(null);

      // Refresh authoritative data
      await Promise.all([
        loadReadyQueue(appliedSearch, selectedZone),
        loadTrips(statusFilter, dateFilter),
        loadGlobalMetrics()
      ]);

      if (stopsModalOpen && activeTrip && (activeTrip.id === tripId || activeTrip._id === tripId)) {
        setActiveTrip(res.data);
      }
    } catch (err) {
      const detail = err.response?.data?.detail || err.message || "Gagal menyelesaikan trip";
      setCompleteError(detail);
      if (err.response?.status === 409) {
        toast.error(`Tidak Dapat Diselesaikan: ${detail}`);
      } else if (err.response?.status === 422) {
        toast.error(`Validasi Gagal: ${detail}`);
      } else if (err.response?.status === 503) {
        toast.error(`Layanan Tidak Tersedia: ${detail}`);
      } else {
        toast.error(`Gagal Menyelesaikan Trip: ${detail}`);
      }
      if (err.response?.status === 409) {
        loadTrips(statusFilter, dateFilter);
        if (stopsModalOpen && activeTrip) {
          api.get(`/admin/delivery-trips/${tripId}`).then((r) => setActiveTrip(r.data)).catch(() => {});
        }
      }
    } finally {
      setCompleting(false);
    }
  };

  // Open Handover Modal (Package 5)
  const handleOpenHandoverModal = (stop) => {
    if (stop.outcome !== "out_for_delivery") return;
    setStopForHandover(stop);
    setRecipientName(stop.customer_name || "");
    setHandoverNotes("");
    setHelperConfirmed(false);
    setIsCustomWage(false);
    setCustomWageLe("");
    setConfirmedUnusualAmount(false);
    setOverrideReason("");
    setHandoverError(null);
    setHandoverModalOpen(true);
  };

  // Handover Execution (Package 5)
  const handleConfirmHandover = async () => {
    if (!activeTrip || !stopForHandover) return;
    const tripId = activeTrip.id || activeTrip._id;
    const orderId = stopForHandover.order_id;
    const rName = recipientName.trim();

    if (!rName) {
      setHandoverError("Nama penerima wajib diisi.");
      return;
    }
    if (!helperConfirmed) {
      setHandoverError("Konfirmasi serah terima fisik oleh helper wajib dicentang.");
      return;
    }

    const threshold = activeTrip?.rate_policy_snapshot?.unusual_amount_threshold_le || 100;
    const hardCap = activeTrip?.rate_policy_snapshot?.max_cap_at_dispatch_le || 500;
    const payload = {
      recipient_name: rName,
      handover_notes: handoverNotes.trim() || null,
      helper_confirmed: helperConfirmed,
    };

    if (isCustomWage && customWageLe !== "" && !isNaN(Number(customWageLe))) {
      const cWage = Number(customWageLe);
      if (cWage < 0) {
        setHandoverError("Nominal upah tidak boleh negatif.");
        return;
      }
      if (cWage > hardCap) {
        setHandoverError(
          `Nominal upah (${cWage} LE) melebihi batas maksimum keras (${hardCap} LE). Konfirmasi dan alasan tidak dapat melewati batas keras.`
        );
        return;
      }
      payload.custom_wage_le = cWage;
      if (cWage > threshold) {
        if (!confirmedUnusualAmount) {
          setHandoverError(
            `Nominal upah (${cWage} LE) melebihi batas konfirmasi (${threshold} LE). Konfirmasi diperlukan.`
          );
          return;
        }
        if (!overrideReason.trim() || overrideReason.trim().length < 5) {
          setHandoverError("Alasan override upah di atas batas konfirmasi wajib diisi minimal 5 karakter.");
          return;
        }
        payload.confirmed_unusual_amount = true;
        payload.override_reason = overrideReason.trim();
      }
    }

    setSubmittingHandover(true);
    setHandoverError(null);

    try {
      const res = await api.post(`/admin/delivery-trips/${tripId}/stops/${orderId}/deliver`, payload);
      toast.success(
        `Pesanan ${stopForHandover.order_number || stopForHandover.order_id} berhasil diserahterimakan! Snapshot upah dan pendapatan telah dikunci.`
      );
      setHandoverModalOpen(false);
      setStopForHandover(null);

      // Refresh authoritative data
      if (res.data?.trip) {
        setActiveTrip(res.data.trip);
      } else {
        try {
          const tripRes = await api.get(`/admin/delivery-trips/${tripId}`);
          setActiveTrip(tripRes.data);
        } catch {
          // Non-critical
        }
      }

      await Promise.all([
        loadReadyQueue(appliedSearch, selectedZone),
        loadTrips(statusFilter, dateFilter),
        loadGlobalMetrics()
      ]);
    } catch (err) {
      const detail = err.response?.data?.detail || err.message || "Gagal mencatat serah terima pesanan";
      setHandoverError(detail);
      if (err.response?.status === 409) {
        toast.error(`Konflik Serah Terima: ${detail}`);
      } else if (err.response?.status === 422) {
        toast.error(`Validasi Upah / Data Gagal: ${detail}`);
      } else {
        toast.error(`Gagal Serah Terima: ${detail}`);
      }
    } finally {
      setSubmittingHandover(false);
    }
  };

  const handleOpenFailAttemptModal = (stop) => {
    setStopForFailAttempt(stop);
    setFailureReason("");
    setFailureNotes("");
    setFailAttemptError(null);
    setFailAttemptModalOpen(true);
  };

  const handleConfirmFailAttempt = async () => {
    if (!stopForFailAttempt || !activeTrip) return;
    const tripId = activeTrip._id || activeTrip.id;
    const orderId = stopForFailAttempt.order_id;
    const reasonClean = failureReason.trim();

    if (reasonClean.length < 3) {
      setFailAttemptError("Alasan kegagalan pengantaran wajib diisi (minimal 3 karakter).");
      return;
    }

    const payload = {
      outcome: "failed",
      failure_reason: reasonClean,
      notes: failureNotes.trim() || null,
    };

    setSubmittingFailAttempt(true);
    setFailAttemptError(null);

    try {
      const res = await api.post(`/admin/delivery-trips/${tripId}/stops/${orderId}/record-attempt`, payload);
      toast.success(
        `Percobaan pengantaran pesanan ${stopForFailAttempt.order_number || stopForFailAttempt.order_id} berhasil dicatat sebagai gagal / ditunda.`
      );
      setFailAttemptModalOpen(false);
      setStopForFailAttempt(null);
      setFailureReason("");
      setFailureNotes("");

      // Refresh authoritative active trip
      if (res.data) {
        setActiveTrip(res.data);
      } else {
        try {
          const tripRes = await api.get(`/admin/delivery-trips/${tripId}`);
          setActiveTrip(tripRes.data);
        } catch {
          // Non-critical
        }
      }

      await Promise.all([
        loadReadyQueue(appliedSearch, selectedZone),
        loadTrips(statusFilter, dateFilter),
        loadGlobalMetrics()
      ]);
    } catch (err) {
      const detail = err.response?.data?.detail || err.message || "Gagal mencatat kegagalan pengantaran";
      setFailAttemptError(detail);
      if (err.response?.status === 409) {
        toast.error(`Konflik Percobaan Pengantaran: ${detail}`);
      } else if (err.response?.status === 422) {
        toast.error(`Validasi Gagal Pengantaran: ${detail}`);
      } else {
        toast.error(`Gagal Mencatat Percobaan: ${detail}`);
      }
    } finally {
      setSubmittingFailAttempt(false);
    }
  };

  const handleExecuteRetry = async (stop) => {
    if (!stop || !activeTrip) return;
    const tripId = activeTrip._id || activeTrip.id;
    const orderId = stop.order_id;

    setRetryingStopId(orderId);

    try {
      const res = await api.post(`/admin/delivery-trips/${tripId}/stops/${orderId}/record-attempt`, {
        outcome: "out_for_delivery"
      });
      toast.success(
        `Pesanan ${stop.order_number || stop.order_id} siap dicoba kembali (Dalam Perjalanan).`
      );

      // Refresh authoritative active trip
      if (res.data) {
        setActiveTrip(res.data);
      } else {
        try {
          const tripRes = await api.get(`/admin/delivery-trips/${tripId}`);
          setActiveTrip(tripRes.data);
        } catch {
          // Non-critical
        }
      }

      await Promise.all([
        loadReadyQueue(appliedSearch, selectedZone),
        loadTrips(statusFilter, dateFilter),
        loadGlobalMetrics()
      ]);
    } catch (err) {
      const detail = err.response?.data?.detail || err.message || "Gagal mengubah status untuk coba lagi";
      if (err.response?.status === 409) {
        toast.error(`Konflik Coba Lagi: ${detail}`);
      } else {
        toast.error(`Gagal Coba Lagi: ${detail}`);
      }
    } finally {
      setRetryingStopId(null);
    }
  };

  const toggleExpandAttempts = (orderId) => {
    setExpandedAttemptsStopIds((prev) => ({
      ...prev,
      [orderId]: !prev[orderId]
    }));
  };

  // Eligible trips for assignment (draft or scheduled)
  const assignableTrips = useMemo(() => {
    return trips.filter((t) => t.status === "draft" || t.status === "scheduled");
  }, [trips]);

  // RBAC Access Guard
  if (!canManageOrders) {
    return (
      <div data-testid="access-restricted" className="rounded-2xl border border-red-200 bg-red-50 p-6 text-center text-red-700">
        <ShieldAlert size={40} className="mx-auto mb-2 text-red-500" />
        <h2 className="text-lg font-bold">Akses Terbatas</h2>
        <p className="text-sm">Halaman ini hanya dapat diakses oleh Dispatcher atau Administrator Pesanan.</p>
      </div>
    );
  }

  return (
    <div data-testid="admin-logistics-page" className="max-w-7xl space-y-6 pb-16">
      {/* 1. Header & Quick Actions */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between border-b border-[#E5DCC5] pb-4">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="font-heading text-2xl font-bold text-[#2C1E16]">
              Logistik & Dispatcher Armada
            </h1>
            {isOwner ? (
              <span className="inline-flex items-center gap-1 rounded-full bg-emerald-100 px-2.5 py-0.5 text-xs font-semibold text-emerald-800">
                <ShieldCheck size={12} /> Owner
              </span>
            ) : (
              <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2.5 py-0.5 text-xs font-semibold text-amber-800">
                <Truck size={12} /> Dispatcher
              </span>
            )}
          </div>
          <p className="text-xs sm:text-sm text-[#8B7355] mt-1">
            Monitoring antrean pesanan siap kirim, penyusunan trip armada, dan tracking stop pengiriman.
          </p>
        </div>

        <div className="flex items-center gap-2 flex-wrap">
          <Button
            size="sm"
            onClick={handleOpenCreateModal}
            data-testid="btn-create-trip"
            className="rounded-xl bg-[#8B5A2B] hover:bg-[#724a23] text-white text-xs h-9 px-3.5 shadow-xs"
          >
            <Plus size={15} className="mr-1.5" />
            Buat Trip Baru
          </Button>

          <Button
            variant="outline"
            size="sm"
            onClick={handleRefreshAll}
            disabled={refreshing || loadingQueue || loadingTrips}
            data-testid="btn-refresh"
            className="rounded-xl border-[#E5DCC5] text-xs h-9 px-3 text-[#5C4A3D] hover:bg-[#EFE6D5]"
          >
            <RotateCcw size={14} className={`mr-1.5 ${refreshing ? "animate-spin" : ""}`} />
            Segarkan
          </Button>
        </div>
      </div>

      {/* 2. Top Summary Metric Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        {/* Ready Queue Card */}
        <div
          data-testid="stat-ready-queue"
          onClick={() => handleTabChange("ready")}
          className={`cursor-pointer rounded-2xl border p-4 transition-all ${
            currentTab === "ready"
              ? "border-[#8B5A2B] bg-[#FAF5EE] ring-1 ring-[#8B5A2B] shadow-xs"
              : "border-[#E5DCC5] bg-white hover:bg-[#FBF9F4]"
          }`}
        >
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-[#8B7355]">Antrean Siap Kirim</span>
            <div className="p-2 rounded-xl bg-amber-50 text-amber-700">
              <Package size={16} />
            </div>
          </div>
          <div className="mt-2 font-heading text-2xl font-bold text-[#8B5A2B]">
            {loadingQueue ? "..." : globalMetrics.readyCount}
          </div>
          <p className="text-[11px] text-[#8B7355] mt-0.5">Pesanan siap dialokasikan ke armada</p>
        </div>

        {/* Active Trips Card */}
        <div
          data-testid="stat-active-trips"
          onClick={() => handleTabChange("trips")}
          className={`cursor-pointer rounded-2xl border p-4 transition-all ${
            currentTab === "trips"
              ? "border-[#8B5A2B] bg-[#FAF5EE] ring-1 ring-[#8B5A2B] shadow-xs"
              : "border-[#E5DCC5] bg-white hover:bg-[#FBF9F4]"
          }`}
        >
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-[#8B7355]">Trip Aktif</span>
            <div className="p-2 rounded-xl bg-blue-50 text-blue-700">
              <Truck size={16} />
            </div>
          </div>
          <div className="mt-2 font-heading text-2xl font-bold text-blue-800">
            {loadingTrips ? "..." : globalMetrics.activeTripsCount}
          </div>
          <p className="text-[11px] text-[#8B7355] mt-0.5">Dalam perjalanan & terjadwal</p>
        </div>

        {/* Completed Trips Card */}
        <div
          data-testid="stat-completed-trips"
          onClick={() => handleTabChange("trips")}
          className={`cursor-pointer rounded-2xl border p-4 transition-all ${
            currentTab === "trips" && statusFilter === "completed"
              ? "border-[#8B5A2B] bg-[#FAF5EE] ring-1 ring-[#8B5A2B] shadow-xs"
              : "border-[#E5DCC5] bg-white hover:bg-[#FBF9F4]"
          }`}
        >
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-[#8B7355]">Trip Selesai</span>
            <div className="p-2 rounded-xl bg-emerald-50 text-emerald-700">
              <CheckCircle2 size={16} />
            </div>
          </div>
          <div className="mt-2 font-heading text-2xl font-bold text-emerald-800">
            {loadingTrips ? "..." : globalMetrics.completedTripsCount}
          </div>
          <p className="text-[11px] text-[#8B7355] mt-0.5">Pengiriman sukses terlaksana</p>
        </div>
      </div>

      {/* 3. Segmented Navigation Tabs */}
      <div className="flex items-center gap-2 border-b border-[#E5DCC5] pb-2">
        <button
          onClick={() => handleTabChange("ready")}
          data-testid="tab-ready-queue"
          className={`flex items-center gap-2 px-4 py-2 text-sm font-semibold rounded-xl transition-all ${
            currentTab === "ready"
              ? "bg-[#8B5A2B] text-white shadow-xs"
              : "text-[#5C4A3D] hover:bg-[#EFE6D5] bg-white"
          }`}
        >
          <Package size={16} />
          Antrean Siap Kirim
          <span
            className={`ml-1 text-xs px-2 py-0.5 rounded-full font-mono ${
              currentTab === "ready" ? "bg-[#704822] text-white" : "bg-stone-100 text-stone-700"
            }`}
          >
            {readyOrders.length}
          </span>
        </button>

        <button
          onClick={() => handleTabChange("trips")}
          data-testid="tab-trips-list"
          className={`flex items-center gap-2 px-4 py-2 text-sm font-semibold rounded-xl transition-all ${
            currentTab === "trips"
              ? "bg-[#8B5A2B] text-white shadow-xs"
              : "text-[#5C4A3D] hover:bg-[#EFE6D5] bg-white"
          }`}
        >
          <Truck size={16} />
          Daftar Trip Armada
          <span
            className={`ml-1 text-xs px-2 py-0.5 rounded-full font-mono ${
              currentTab === "trips" ? "bg-[#704822] text-white" : "bg-stone-100 text-stone-700"
            }`}
          >
            {trips.length}
          </span>
        </button>
      </div>

      {/* 4. Tab 1: Antrean Siap Kirim (Ready Queue) */}
      {currentTab === "ready" && (
        <div className="space-y-4">
          {/* Conflict Error Callout Banner if any */}
          {conflictErrors.length > 0 && (
            <div className="rounded-2xl border border-amber-300 bg-amber-50 p-4 text-xs text-amber-900 space-y-1">
              <div className="font-semibold flex items-center gap-1.5">
                <AlertTriangle size={15} className="text-amber-600" />
                Sebagian pesanan mengalami konflik status / telah diklaim proses lain:
              </div>
              <ul className="list-disc list-inside space-y-0.5 pl-2 text-amber-800">
                {conflictErrors.map((errText, idx) => (
                  <li key={idx}>{errText}</li>
                ))}
              </ul>
              <div className="pt-1 text-[11px] text-amber-700">
                Data antrean telah diperbarui secara otomatis.
              </div>
            </div>
          )}

          {/* Search, Zone Filter & Batch Action Bar */}
          <div className="rounded-2xl border border-[#E5DCC5] bg-white p-4 shadow-2xs space-y-3">
            <div className="flex flex-col md:flex-row gap-3">
              {/* Search Form */}
              <form onSubmit={handleSearchSubmit} className="flex-1 flex gap-2">
                <div className="relative flex-1">
                  <Search size={16} className="absolute left-3 top-2.5 text-[#8B7355]" />
                  <Input
                    type="text"
                    placeholder="Cari nomor pesanan, pelanggan, telepon, alamat..."
                    value={searchInput}
                    onChange={(e) => setSearchInput(e.target.value)}
                    data-testid="ready-queue-search"
                    className="pl-9 h-10 rounded-xl border-[#E5DCC5] text-xs text-[#2C1E16] placeholder:text-[#8B7355]"
                  />
                  {searchInput && (
                    <button
                      type="button"
                      onClick={handleClearSearch}
                      className="absolute right-2.5 top-2.5 text-[#8B7355] hover:text-[#2C1E16]"
                    >
                      <X size={15} />
                    </button>
                  )}
                </div>
                <Button
                  type="submit"
                  size="sm"
                  className="rounded-xl bg-[#8B5A2B] hover:bg-[#724a23] text-white text-xs h-10 px-4"
                >
                  Cari
                </Button>
              </form>

              {/* Delivery Zone Filter */}
              <div className="w-full md:w-64">
                <select
                  value={selectedZone}
                  onChange={(e) => setSelectedZone(e.target.value)}
                  data-testid="ready-queue-zone-filter"
                  className="w-full h-10 rounded-xl border border-[#E5DCC5] bg-white px-3 text-xs text-[#2C1E16] focus:outline-hidden focus:ring-1 focus:ring-[#8B5A2B]"
                >
                  <option value="">Semua Zona Pengiriman</option>
                  {zones.map((z) => (
                    <option key={z.id || z._id} value={z.id || z._id}>
                      {z.name} {z.fee_le ? `(${fmtLE(z.fee_le)} LE)` : ""}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            {/* Selection & Batch Action Row */}
            {readyOrders.length > 0 && (
              <div className="flex items-center justify-between border-t border-[#F1EBE0] pt-3 flex-wrap gap-2">
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={handleSelectAllOrders}
                    data-testid="btn-select-all"
                    className="inline-flex items-center gap-1.5 text-xs font-semibold text-[#5C4A3D] hover:text-[#8B5A2B]"
                  >
                    {selectedOrderIds.length === readyOrders.length ? (
                      <CheckSquare size={16} className="text-[#8B5A2B]" />
                    ) : (
                      <Square size={16} className="text-stone-400" />
                    )}
                    <span>
                      {selectedOrderIds.length === readyOrders.length
                        ? "Batalkan Pilihan Semua"
                        : `Pilih Semua (${readyOrders.length})`}
                    </span>
                  </button>

                  {selectedOrderIds.length > 0 && (
                    <span className="text-xs text-[#8B7355] font-medium">
                      • {selectedOrderIds.length} pesanan terpilih
                    </span>
                  )}
                </div>

                {selectedOrderIds.length > 0 && (
                  <Button
                    size="sm"
                    onClick={() => {
                      if (assignableTrips.length === 0) {
                        toast.error(
                          "Belum ada trip aktif berstatus Draft atau Dijadwalkan. Buat trip baru terlebih dahulu."
                        );
                        handleOpenCreateModal();
                        return;
                      }
                      setTargetTripId(assignableTrips[0]?.id || assignableTrips[0]?._id || "");
                      setAssignModalOpen(true);
                    }}
                    data-testid="btn-assign-selected"
                    className="rounded-xl bg-[#8B5A2B] hover:bg-[#724a23] text-white text-xs h-8 px-3 shadow-xs"
                  >
                    <Truck size={14} className="mr-1.5" />
                    Tugaskan {selectedOrderIds.length} Pesanan ke Trip
                  </Button>
                )}
              </div>
            )}
          </div>

          {/* Queue State Views */}
          {loadingQueue ? (
            <div className="rounded-2xl border border-[#E5DCC5] bg-white p-12 text-center text-sm text-[#8B7355]">
              <RotateCcw size={24} className="mx-auto mb-2 animate-spin text-[#8B5A2B]" />
              Memuat antrean pesanan siap kirim...
            </div>
          ) : queueError ? (
            <div className="rounded-2xl border border-red-200 bg-red-50 p-6 text-center text-red-700">
              <AlertTriangle size={32} className="mx-auto mb-2 text-red-500" />
              <p className="font-semibold text-sm">Gagal memuat antrean pengiriman</p>
              <p className="text-xs text-red-600 mt-1">{queueError}</p>
              <Button
                size="sm"
                variant="outline"
                onClick={() => loadReadyQueue(appliedSearch, selectedZone)}
                className="mt-3 rounded-xl border-red-300 bg-white text-xs text-red-700 hover:bg-red-100"
              >
                Coba Lagi
              </Button>
            </div>
          ) : readyOrders.length === 0 ? (
            <div className="rounded-2xl border border-dashed border-[#E5DCC5] bg-white p-12 text-center">
              <Package size={40} className="mx-auto text-[#8B7355]/50 mb-3" />
              <h3 className="text-sm font-semibold text-[#2C1E16]">
                Tidak ada pesanan dalam antrean siap kirim
              </h3>
              <p className="mt-1 text-xs text-[#8B7355] max-w-md mx-auto">
                {appliedSearch || selectedZone
                  ? "Tidak ada pesanan yang sesuai dengan kata kunci atau filter zona yang dipilih."
                  : "Semua pesanan siap telah dialokasikan ke trip aktif atau belum ada pesanan baru berstatus 'siap'."}
              </p>
            </div>
          ) : (
            <div className="space-y-3">
              {readyOrders.map((order) => {
                const isSelected = selectedOrderIds.includes(order.id);
                return (
                  <div
                    key={order.id}
                    data-testid={`order-card-${order.order_number || order.id}`}
                    className={`rounded-2xl border bg-white p-4 sm:p-5 shadow-2xs hover:shadow-xs transition-all ${
                      isSelected ? "border-[#8B5A2B] bg-[#FAF5EE]/40 ring-1 ring-[#8B5A2B]" : "border-[#E5DCC5]"
                    }`}
                  >
                    <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2 border-b border-[#F1EBE0] pb-3">
                      <div className="flex items-center gap-2.5 flex-wrap">
                        <button
                          type="button"
                          onClick={() => handleToggleSelectOrder(order.id)}
                          data-testid={`checkbox-order-${order.order_number || order.id}`}
                          className="text-[#8B5A2B] hover:text-[#724a23]"
                        >
                          {isSelected ? (
                            <CheckSquare size={18} className="text-[#8B5A2B]" />
                          ) : (
                            <Square size={18} className="text-stone-300 hover:text-stone-500" />
                          )}
                        </button>

                        <Link
                          to={`/admin/orders/${order.id}`}
                          className="font-mono text-sm font-bold text-[#8B5A2B] hover:underline"
                        >
                          {order.order_number || `#${order.id.slice(-6)}`}
                        </Link>
                        <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 border border-emerald-200 px-2 py-0.5 text-[11px] font-medium text-emerald-800">
                          <CheckCircle2 size={11} /> Siap Kirim
                        </span>
                        <span className="inline-flex items-center gap-1 rounded-full bg-amber-50 border border-amber-200 px-2 py-0.5 text-[11px] font-medium text-amber-800">
                          Belum Masuk Trip
                        </span>
                        {order.delivery_logistics_status === "delivery_failed" && (
                          <span
                            data-testid={`badge-retry-${order.order_number || order.id}`}
                            className="inline-flex items-center gap-1 rounded-full bg-amber-100 border border-amber-300 px-2 py-0.5 text-[11px] font-semibold text-amber-900"
                          >
                            <RotateCcw size={11} className="text-amber-700 shrink-0" />
                            Pengantaran Ulang
                          </span>
                        )}
                      </div>

                      <div className="text-right text-[11px] text-[#8B7355]">
                        {order.created_at
                          ? new Date(order.created_at).toLocaleString("id-ID", {
                              dateStyle: "medium",
                              timeStyle: "short"
                            })
                          : "-"}
                      </div>
                    </div>

                    {/* Order Details Body */}
                    <div className="grid grid-cols-1 md:grid-cols-3 gap-4 pt-3">
                      {/* Customer Info */}
                      <div className="space-y-1">
                        <div className="text-xs font-semibold text-[#2C1E16]">
                          {order.customer_name}
                        </div>
                        {order.customer_phone && (
                          <div className="flex items-center gap-1 text-xs text-[#5C4A3D]">
                            <Phone size={12} className="text-[#8B7355] shrink-0" />
                            <a href={`tel:${order.customer_phone}`} className="hover:underline">
                              {order.customer_phone}
                            </a>
                          </div>
                        )}
                        {order.customer_address && (
                          <div className="flex items-start gap-1 text-xs text-[#5C4A3D] mt-1">
                            <MapPin size={12} className="text-[#8B7355] shrink-0 mt-0.5" />
                            <span className="line-clamp-2">{order.customer_address}</span>
                          </div>
                        )}
                        {order.customer_maps_url && (
                          <div className="pt-1">
                            <a
                              href={order.customer_maps_url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="inline-flex items-center gap-1 text-xs font-medium text-blue-600 hover:text-blue-800 hover:underline"
                            >
                              <ExternalLink size={12} /> Buka Google Maps
                            </a>
                          </div>
                        )}
                      </div>

                      {/* Items Summary */}
                      <div className="space-y-1">
                        <div className="flex items-center gap-1 text-xs font-medium text-[#8B7355]">
                          <ShoppingBag size={12} />
                          <span>Barang ({order.total_items_count || 0} unit)</span>
                        </div>
                        <div className="space-y-1 max-h-24 overflow-y-auto">
                          {Array.isArray(order.items_summary) && order.items_summary.length > 0 ? (
                            order.items_summary.map((it, idx) => (
                              <div key={idx} className="text-xs text-[#2C1E16]">
                                <span className="font-semibold">{it.quantity}x</span> {it.name}
                              </div>
                            ))
                          ) : (
                            <div className="text-xs text-[#8B7355] italic">Detail barang tidak tersedia</div>
                          )}
                        </div>
                      </div>

                      {/* Delivery & Pricing Info */}
                      <div className="space-y-1 text-right md:border-l md:border-[#F1EBE0] md:pl-4">
                        <div className="text-xs text-[#8B7355]">
                          Zona:{" "}
                          <span className="font-medium text-[#2C1E16]">
                            {order.delivery_zone_name || "Tanpa Zona"}
                          </span>
                        </div>
                        <div className="text-xs text-[#8B7355]">
                          Ongkir:{" "}
                          <span className="font-medium text-[#2C1E16]">
                            {fmtLE(order.delivery_fee_le)} LE
                          </span>
                        </div>
                        <div className="pt-1 text-sm font-bold text-[#8B5A2B]">
                          Total: {fmtLE(order.total_le)} LE
                        </div>
                      </div>
                    </div>

                    {/* Notes callout if any */}
                    {order.notes && (
                      <div className="mt-3 rounded-xl bg-[#FAF5EE] border border-[#E5DCC5] p-2.5 text-xs text-[#5C4A3D] flex items-start gap-1.5">
                        <FileText size={14} className="text-[#8B5A2B] shrink-0 mt-0.5" />
                        <div>
                          <span className="font-semibold text-[#8B5A2B]">Catatan: </span>
                          {order.notes}
                        </div>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* 5. Tab 2: Daftar Trip Armada (Trip List) */}
      {currentTab === "trips" && (
        <div className="space-y-4">
          {/* Status Filters & Date Bar */}
          <div className="rounded-2xl border border-[#E5DCC5] bg-white p-4 shadow-2xs space-y-3">
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-3">
              {/* Status Chips */}
              <div className="flex flex-wrap gap-1.5" data-testid="trip-status-filter">
                {[
                  { key: "all", label: "Semua Status" },
                  { key: "draft", label: "Draft" },
                  { key: "scheduled", label: "Dijadwalkan" },
                  { key: "in_transit", label: "Sedang Jalan" },
                  { key: "completed", label: "Selesai" },
                  { key: "cancelled", label: "Dibatalkan" }
                ].map((tab) => {
                  const isActive = statusFilter === tab.key;
                  return (
                    <button
                      key={tab.key}
                      onClick={() => setStatusFilter(tab.key)}
                      className={`px-3 py-1.5 text-xs font-semibold rounded-xl transition-all ${
                        isActive
                          ? "bg-[#8B5A2B] text-white shadow-2xs"
                          : "text-[#5C4A3D] hover:bg-[#EFE6D5] bg-[#F9F6F0]"
                      }`}
                    >
                      {tab.label}
                    </button>
                  );
                })}
              </div>

              {/* Date Filter */}
              <div className="flex items-center gap-2">
                <Calendar size={14} className="text-[#8B7355] shrink-0" />
                <Input
                  type="date"
                  value={dateFilter}
                  onChange={(e) => setDateFilter(e.target.value)}
                  className="h-9 text-xs rounded-xl border-[#E5DCC5] w-40"
                />
                {dateFilter && (
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setDateFilter("")}
                    className="h-8 text-xs text-[#8B5A2B] px-2"
                  >
                    Reset
                  </Button>
                )}
              </div>
            </div>
          </div>

          {/* Trips Content */}
          {loadingTrips ? (
            <div className="rounded-2xl border border-[#E5DCC5] bg-white p-12 text-center text-sm text-[#8B7355]">
              <RotateCcw size={24} className="mx-auto mb-2 animate-spin text-[#8B5A2B]" />
              Memuat data trip armada pengiriman...
            </div>
          ) : tripsError ? (
            <div className="rounded-2xl border border-red-200 bg-red-50 p-6 text-center text-red-700">
              <AlertTriangle size={32} className="mx-auto mb-2 text-red-500" />
              <p className="font-semibold text-sm">Gagal memuat daftar trip</p>
              <p className="text-xs text-red-600 mt-1">{tripsError}</p>
              <Button
                size="sm"
                variant="outline"
                onClick={() => loadTrips(statusFilter, dateFilter)}
                className="mt-3 rounded-xl border-red-300 bg-white text-xs text-red-700 hover:bg-red-100"
              >
                Coba Lagi
              </Button>
            </div>
          ) : trips.length === 0 ? (
            <div className="rounded-2xl border border-dashed border-[#E5DCC5] bg-white p-12 text-center">
              <Truck size={40} className="mx-auto text-[#8B7355]/50 mb-3" />
              <h3 className="text-sm font-semibold text-[#2C1E16]">
                Belum ada trip pengiriman
              </h3>
              <p className="mt-1 text-xs text-[#8B7355] max-w-md mx-auto">
                {statusFilter !== "all" || dateFilter
                  ? "Tidak ada trip yang sesuai dengan filter status atau tanggal yang dipilih."
                  : "Belum ada trip yang dibuat. Klik tombol di bawah untuk membuat trip baru."}
              </p>
              <Button
                size="sm"
                onClick={handleOpenCreateModal}
                className="mt-4 rounded-xl bg-[#8B5A2B] hover:bg-[#724a23] text-white text-xs"
              >
                <Plus size={14} className="mr-1.5" />
                Buat Trip Baru
              </Button>
            </div>
          ) : (
            <div className="space-y-3">
              {trips.map((trip) => {
                const stopsCount = trip.stops_count || (trip.stops ? trip.stops.length : 0);
                const deliveredCount = trip.delivered_stops_count || 0;
                const failedCount = trip.failed_stops_count || 0;
                const progressPct = stopsCount > 0 ? Math.round((deliveredCount / stopsCount) * 100) : 0;

                // Status configuration
                let badgeClass = "bg-stone-100 text-stone-700 border-stone-200";
                let statusLabel = trip.status;
                if (trip.status === "draft") {
                  badgeClass = "bg-stone-100 text-stone-700 border-stone-300";
                  statusLabel = "Draft";
                } else if (trip.status === "scheduled") {
                  badgeClass = "bg-amber-100 text-amber-800 border-amber-300";
                  statusLabel = "Dijadwalkan";
                } else if (trip.status === "in_transit") {
                  badgeClass = "bg-blue-100 text-blue-800 border-blue-300 animate-pulse";
                  statusLabel = "Sedang Jalan";
                } else if (trip.status === "completed") {
                  badgeClass = "bg-emerald-100 text-emerald-800 border-emerald-300";
                  statusLabel = "Selesai";
                } else if (trip.status === "cancelled") {
                  badgeClass = "bg-rose-100 text-rose-800 border-rose-300";
                  statusLabel = "Dibatalkan";
                }

                const rental = trip.vehicle_rental;
                const isRental = Boolean(rental?.is_rental);

                return (
                  <div
                    key={trip.id}
                    data-testid={`trip-card-${trip.trip_number || trip.id}`}
                    className="rounded-2xl border border-[#E5DCC5] bg-white p-4 sm:p-5 shadow-2xs hover:shadow-xs transition-shadow"
                  >
                    {/* Header */}
                    <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2 border-b border-[#F1EBE0] pb-3">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="font-mono text-base font-bold text-[#8B5A2B]">
                          {trip.trip_number}
                        </span>
                        <span
                          className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-xs font-semibold ${badgeClass}`}
                        >
                          {statusLabel}
                        </span>
                        {trip.status === "completed" && trip.is_partially_completed && (
                          <span
                            data-testid={`badge-partial-${trip.trip_number || trip.id}`}
                            className="inline-flex items-center gap-1 rounded-full border border-amber-300 bg-amber-50 px-2 py-0.5 text-[11px] font-semibold text-amber-800"
                          >
                            Selesai Sebagian
                          </span>
                        )}
                        {trip.scheduled_date && (
                          <span className="inline-flex items-center gap-1 text-xs text-[#5C4A3D]">
                            <Calendar size={13} className="text-[#8B7355]" />
                            {trip.scheduled_date}
                            {trip.departure_time && ` ${trip.departure_time}`}
                          </span>
                        )}
                      </div>

                      {/* Stop Progress summary & Action button */}
                      <div className="flex items-center gap-2 justify-between sm:justify-end">
                        <div className="text-right">
                          <div className="text-xs font-semibold text-[#2C1E16]">
                            Progress Stop: {deliveredCount} / {stopsCount} Selesai ({progressPct}%)
                          </div>
                          {failedCount > 0 && (
                            <div className="text-[11px] font-semibold text-rose-600">
                              {failedCount} stop tertunda / gagal kirim
                            </div>
                          )}
                        </div>

                        <div className="flex items-center gap-2 flex-wrap">
                          {canManageOrders && (trip.status === "draft" || trip.status === "scheduled") && (
                            <Button
                              size="sm"
                              onClick={() => handleOpenDispatchModal(trip)}
                              data-testid={`btn-dispatch-trip-${trip.trip_number || trip.id}`}
                              className="rounded-xl bg-[#8B5A2B] hover:bg-[#6F4420] text-white text-xs h-8 px-3 shadow-xs"
                            >
                              <Truck size={13} className="mr-1" />
                              Dispatch Armada
                            </Button>
                          )}

                          {canManageOrders && isTripEligibleForCompletion(trip) && (
                            <Button
                              size="sm"
                              onClick={() => handleOpenCompleteModal(trip)}
                              data-testid={`btn-complete-trip-${trip.trip_number || trip.id}`}
                              className="rounded-xl bg-emerald-700 hover:bg-emerald-800 text-white text-xs h-8 px-3 shadow-xs"
                            >
                              <CheckCircle2 size={13} className="mr-1" />
                              Selesaikan Trip
                            </Button>
                          )}

                          {canManageOrders &&
                            trip.status !== "cancelled" &&
                            trip.status !== "completed" &&
                            (!trip.delivered_stops_count || trip.delivered_stops_count === 0) && (
                              <Button
                                size="sm"
                                variant="ghost"
                                onClick={() => handleOpenCancelModal(trip)}
                                data-testid={`btn-cancel-trip-${trip.trip_number || trip.id}`}
                                className="rounded-xl border border-rose-200 text-rose-600 hover:text-rose-700 hover:bg-rose-50 text-xs h-8 px-2.5"
                              >
                                <XCircle size={13} className="mr-1" />
                                Batalkan
                              </Button>
                            )}

                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => handleOpenStopsModal(trip)}
                            data-testid={`btn-manage-stops-${trip.trip_number || trip.id}`}
                            className="rounded-xl border-[#8B5A2B] text-xs h-8 px-3 text-[#8B5A2B] hover:bg-[#FAF5EE]"
                          >
                            <Navigation size={13} className="mr-1" />
                            Kelola Stop & Rute
                          </Button>
                        </div>
                      </div>
                    </div>

                    {/* Progress Bar */}
                    <div className="mt-2.5 h-1.5 w-full bg-stone-100 rounded-full overflow-hidden">
                      <div
                        className={`h-full transition-all duration-300 ${
                          trip.status === "completed"
                            ? "bg-emerald-600"
                            : failedCount > 0
                            ? "bg-amber-500"
                            : "bg-[#8B5A2B]"
                        }`}
                        style={{ width: `${progressPct}%` }}
                      />
                    </div>

                    {/* Details Grid */}
                    <div className="grid grid-cols-1 md:grid-cols-3 gap-4 pt-3 mt-1">
                      {/* Vehicle & Rental Info */}
                      <div className="space-y-1">
                        <div className="text-xs font-semibold text-[#8B7355] flex items-center gap-1">
                          <Car size={13} />
                          <span>Armada & Kendaraan</span>
                        </div>
                        {isRental ? (
                          <div className="text-xs text-[#2C1E16] space-y-0.5">
                            <span className="inline-block rounded-md bg-stone-100 px-1.5 py-0.5 text-[10px] font-medium text-stone-700 mr-1">
                              Rental
                            </span>
                            <span className="font-semibold">{rental?.rental_provider || rental?.rental_vendor_name || "Vendor Rental"}</span>
                            {(rental?.vehicle_plate_or_desc || rental?.vehicle_plate_number) && (
                              <div className="font-mono text-stone-600 text-[11px]">
                                Plat: {rental.vehicle_plate_or_desc || rental.vehicle_plate_number}
                              </div>
                            )}
                            {rental?.rental_driver_name && (
                              <div className="text-stone-600 text-[11px]">
                                Driver: {rental.rental_driver_name}
                              </div>
                            )}
                            <div className="text-xs font-medium text-[#8B5A2B] pt-0.5">
                              Biaya Sewa: {fmtLE(rental?.cost_obligation?.agreed_rental_cost_le || rental?.agreed_rental_cost_le || 0)} LE
                            </div>
                          </div>
                        ) : (
                          <div className="text-xs text-[#2C1E16] space-y-0.5">
                            <span className="inline-block rounded-md bg-stone-100 px-1.5 py-0.5 text-[10px] font-medium text-stone-700 mr-1">
                              Internal
                            </span>
                            <span className="font-semibold">{rental?.vehicle_plate_or_desc || "Armada Toko"}</span>
                            {rental?.rental_driver_name && (
                              <div className="text-stone-600 text-[11px]">
                                Driver: {rental.rental_driver_name}
                              </div>
                            )}
                          </div>
                        )}
                      </div>

                      {/* Helpers Info */}
                      <div className="space-y-1">
                        <div className="text-xs font-semibold text-[#8B7355] flex items-center gap-1">
                          <Users size={13} />
                          <span>Helper Bertugas</span>
                        </div>
                        {Array.isArray(trip.helpers) && trip.helpers.length > 0 ? (
                          <div className="space-y-0.5">
                            {trip.helpers.map((h, hIdx) => (
                              <div key={hIdx} className="text-xs text-[#2C1E16] flex items-center gap-1">
                                <span className="w-1.5 h-1.5 rounded-full bg-[#8B5A2B] inline-block" />
                                <span className="font-medium">{h.helper_name || `Helper #${hIdx + 1}`}</span>
                                {h.helper_phone && (
                                  <span className="text-[11px] text-[#8B7355]">({h.helper_phone})</span>
                                )}
                              </div>
                            ))}
                          </div>
                        ) : (
                          <div className="text-xs text-[#8B7355] italic">Belum ada helper ditugaskan</div>
                        )}
                      </div>

                      {/* Wage Rate Policy Snapshot */}
                      <div className="space-y-1 md:text-right">
                        <div className="text-xs font-semibold text-[#8B7355] flex items-center gap-1 md:justify-end">
                          <Clock size={13} />
                          <span>Snapshot Kebijakan Upah</span>
                        </div>
                        {trip.rate_policy_snapshot ? (
                          <div className="text-xs text-[#2C1E16] space-y-0.5">
                            <span className="inline-block rounded-md bg-emerald-50 border border-emerald-200 px-1.5 py-0.5 text-[10px] font-medium text-emerald-800">
                              Tersnapshot V{trip.rate_policy_snapshot.policy_version || 1}
                            </span>
                            <div className="font-semibold text-[#8B5A2B]">
                              Tarif: {fmtLE(trip.rate_policy_snapshot.effective_rate_le || trip.rate_policy_snapshot.base_wage_per_order_le)} LE / pesanan
                            </div>
                            <div className="text-[10px] text-[#8B7355]">
                              {trip.rate_policy_snapshot.rounding_policy || "piastre_round_half_up"}
                            </div>
                          </div>
                        ) : (
                          <div className="text-xs text-[#2C1E16] space-y-0.5">
                            <div className="text-[11px] text-[#8B7355]">
                              Rencana Tarif:{" "}
                              <span className="font-semibold text-[#2C1E16]">
                                {fmtLE(trip.trip_wage_rate_le || 50)} LE / pesanan
                              </span>
                            </div>
                            <div className="text-[10px] text-[#8B7355] italic">
                              Snapshot permanen akan terkunci saat dispatch
                            </div>
                          </div>
                        )}
                      </div>
                    </div>

                    {/* Trip Notes if present */}
                    {trip.notes && (
                      <div className="mt-3 rounded-xl bg-[#FAF5EE] border border-[#E5DCC5] p-2.5 text-xs text-[#5C4A3D]">
                        <span className="font-semibold text-[#8B5A2B]">Catatan Trip: </span>
                        {trip.notes}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* ========================================================================= */}
      {/* MODAL 1: Buat Trip Baru (Create Trip Modal) */}
      {/* ========================================================================= */}
      {createModalOpen && (
        <div
          data-testid="modal-create-trip"
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4 backdrop-blur-xs"
        >
          <div className="w-full max-w-2xl max-h-[90vh] overflow-y-auto rounded-3xl border border-[#E5DCC5] bg-white p-6 shadow-xl space-y-5">
            <div className="flex items-center justify-between border-b border-[#F1EBE0] pb-3">
              <div className="flex items-center gap-2">
                <Truck size={20} className="text-[#8B5A2B]" />
                <h2 className="font-heading text-lg font-bold text-[#2C1E16]">
                  Buat Trip Armada Pengiriman Baru
                </h2>
              </div>
              <button
                type="button"
                onClick={() => setCreateModalOpen(false)}
                className="text-[#8B7355] hover:text-[#2C1E16]"
              >
                <X size={20} />
              </button>
            </div>

            <form onSubmit={handleCreateTripSubmit} className="space-y-4">
              {/* Jadwal Keberangkatan */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-semibold text-[#2C1E16] mb-1">
                    Tanggal Jadwal <span className="text-red-500">*</span>
                  </label>
                  <Input
                    type="date"
                    required
                    data-testid="input-scheduled-date"
                    value={tripFormData.scheduled_date}
                    onChange={(e) =>
                      setTripFormData({ ...tripFormData, scheduled_date: e.target.value })
                    }
                    className="h-10 text-xs rounded-xl border-[#E5DCC5]"
                  />
                  {tripFormErrors.scheduled_date && (
                    <p className="text-[11px] text-red-500 mt-0.5">{tripFormErrors.scheduled_date}</p>
                  )}
                </div>

                <div>
                  <label className="block text-xs font-semibold text-[#2C1E16] mb-1">
                    Perkiraan Jam Keberangkatan
                  </label>
                  <Input
                    type="time"
                    data-testid="input-departure-time"
                    value={tripFormData.departure_time}
                    onChange={(e) =>
                      setTripFormData({ ...tripFormData, departure_time: e.target.value })
                    }
                    className="h-10 text-xs rounded-xl border-[#E5DCC5]"
                  />
                </div>
              </div>

              {/* Pemilihan Kendaraan */}
              <div className="rounded-2xl border border-[#E5DCC5] p-4 bg-[#FAF5EE]/40 space-y-3">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-bold text-[#2C1E16]">Jenis Armada Kendaraan</span>
                  <div className="flex items-center gap-1.5">
                    <button
                      type="button"
                      data-testid="btn-vehicle-rental"
                      onClick={() => setTripFormData({ ...tripFormData, vehicle_type: "rental" })}
                      className={`px-3 py-1 text-xs font-semibold rounded-lg transition-all ${
                        tripFormData.vehicle_type === "rental"
                          ? "bg-[#8B5A2B] text-white shadow-2xs"
                          : "bg-white text-[#5C4A3D] border border-[#E5DCC5]"
                      }`}
                    >
                      Kendaraan Rental
                    </button>
                    <button
                      type="button"
                      data-testid="btn-vehicle-internal"
                      onClick={() => setTripFormData({ ...tripFormData, vehicle_type: "internal" })}
                      className={`px-3 py-1 text-xs font-semibold rounded-lg transition-all ${
                        tripFormData.vehicle_type === "internal"
                          ? "bg-[#8B5A2B] text-white shadow-2xs"
                          : "bg-white text-[#5C4A3D] border border-[#E5DCC5]"
                      }`}
                    >
                      Armada Toko / Sendiri
                    </button>
                  </div>
                </div>

                {tripFormData.vehicle_type === "rental" ? (
                  <div className="space-y-3 pt-1">
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                      <div>
                        <label className="block text-[11px] font-semibold text-[#5C4A3D] mb-1">
                          Nama Vendor Rental <span className="text-red-500">*</span>
                        </label>
                        <Input
                          type="text"
                          placeholder="cth. Rental Al-Barakah"
                          data-testid="input-rental-provider"
                          value={tripFormData.rental_provider}
                          onChange={(e) =>
                            setTripFormData({ ...tripFormData, rental_provider: e.target.value })
                          }
                          className="h-9 text-xs rounded-xl border-[#E5DCC5]"
                        />
                        {tripFormErrors.rental_provider && (
                          <p className="text-[10px] text-red-500 mt-0.5">
                            {tripFormErrors.rental_provider}
                          </p>
                        )}
                      </div>

                      <div>
                        <label className="block text-[11px] font-semibold text-[#5C4A3D] mb-1">
                          Plat Nomor / Jenis Mobil <span className="text-red-500">*</span>
                        </label>
                        <Input
                          type="text"
                          placeholder="cth. B 1234 CD (Pickup Box)"
                          data-testid="input-rental-plate"
                          value={tripFormData.vehicle_plate_or_desc}
                          onChange={(e) =>
                            setTripFormData({ ...tripFormData, vehicle_plate_or_desc: e.target.value })
                          }
                          className="h-9 text-xs rounded-xl border-[#E5DCC5]"
                        />
                        {tripFormErrors.vehicle_plate_or_desc && (
                          <p className="text-[10px] text-red-500 mt-0.5">
                            {tripFormErrors.vehicle_plate_or_desc}
                          </p>
                        )}
                      </div>
                    </div>

                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                      <div>
                        <label className="block text-[11px] font-semibold text-[#5C4A3D] mb-1">
                          Nama Sopir Rental <span className="text-red-500">*</span>
                        </label>
                        <Input
                          type="text"
                          placeholder="cth. Mahmoud Driver"
                          data-testid="input-rental-driver"
                          value={tripFormData.rental_driver_name}
                          onChange={(e) =>
                            setTripFormData({ ...tripFormData, rental_driver_name: e.target.value })
                          }
                          className="h-9 text-xs rounded-xl border-[#E5DCC5]"
                        />
                        {tripFormErrors.rental_driver_name && (
                          <p className="text-[10px] text-red-500 mt-0.5">
                            {tripFormErrors.rental_driver_name}
                          </p>
                        )}
                      </div>

                      <div>
                        <label className="block text-[11px] font-semibold text-[#5C4A3D] mb-1">
                          Biaya Sewa Armada Disepakati (LE) <span className="text-red-500">*</span>
                        </label>
                        <Input
                          type="number"
                          min="0"
                          step="1"
                          data-testid="input-rental-cost"
                          value={tripFormData.agreed_rental_cost_le}
                          onChange={(e) =>
                            setTripFormData({
                              ...tripFormData,
                              agreed_rental_cost_le: e.target.value
                            })
                          }
                          className="h-9 text-xs rounded-xl border-[#E5DCC5]"
                        />
                      </div>
                    </div>

                    <div>
                      <label className="block text-[11px] font-semibold text-[#5C4A3D] mb-1">
                        No. Referensi Kwitansi / Kontrak (Opsional)
                      </label>
                      <Input
                        type="text"
                        placeholder="cth. KWT-RENTAL-2026-10"
                        value={tripFormData.agreement_reference}
                        onChange={(e) =>
                          setTripFormData({ ...tripFormData, agreement_reference: e.target.value })
                        }
                        className="h-9 text-xs rounded-xl border-[#E5DCC5]"
                      />
                    </div>
                  </div>
                ) : (
                  <div className="space-y-3 pt-1">
                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                      <div>
                        <label className="block text-[11px] font-semibold text-[#5C4A3D] mb-1">
                          Plat / Nama Armada Toko <span className="text-red-500">*</span>
                        </label>
                        <Input
                          type="text"
                          placeholder="cth. Pickup Toko - B 9876 XYZ"
                          data-testid="input-internal-plate"
                          value={tripFormData.vehicle_plate_or_desc}
                          onChange={(e) =>
                            setTripFormData({ ...tripFormData, vehicle_plate_or_desc: e.target.value })
                          }
                          className="h-9 text-xs rounded-xl border-[#E5DCC5]"
                        />
                        {tripFormErrors.vehicle_plate_or_desc && (
                          <p className="text-[10px] text-red-500 mt-0.5">
                            {tripFormErrors.vehicle_plate_or_desc}
                          </p>
                        )}
                      </div>

                      <div>
                        <label className="block text-[11px] font-semibold text-[#5C4A3D] mb-1">
                          Nama Pengemudi Internal <span className="text-red-500">*</span>
                        </label>
                        <Input
                          type="text"
                          placeholder="cth. Ahmad Driver Toko"
                          data-testid="input-internal-driver"
                          value={tripFormData.rental_driver_name}
                          onChange={(e) =>
                            setTripFormData({ ...tripFormData, rental_driver_name: e.target.value })
                          }
                          className="h-9 text-xs rounded-xl border-[#E5DCC5]"
                        />
                        {tripFormErrors.rental_driver_name && (
                          <p className="text-[10px] text-red-500 mt-0.5">
                            {tripFormErrors.rental_driver_name}
                          </p>
                        )}
                      </div>
                    </div>
                    <p className="text-[11px] text-[#8B7355] italic">
                      Armada toko tidak mencatat kewajiban utang sewa eksternal (biaya sewa = 0 LE).
                    </p>
                  </div>
                )}
              </div>

              {/* Penugasan Helper */}
              <div>
                <div className="flex items-center justify-between mb-1.5">
                  <label className="text-xs font-semibold text-[#2C1E16]">
                    Pilih Helper Bertugas ({tripFormData.helper_ids.length} dipilih)
                  </label>
                  <span className="text-[11px] text-[#8B7355]">Dari daftar akun tim internal</span>
                </div>

                <div
                  data-testid="helper-selection-list"
                  className="max-h-36 overflow-y-auto rounded-xl border border-[#E5DCC5] p-2 space-y-1 bg-stone-50/50"
                >
                  {workers.length === 0 ? (
                    <div className="text-xs text-[#8B7355] py-2 text-center">
                      Tidak ada pekerja aktif ditemukan.
                    </div>
                  ) : (
                    workers.map((w) => {
                      const isChecked = tripFormData.helper_ids.includes(w.id);
                      return (
                        <label
                          key={w.id}
                          className={`flex items-center justify-between p-2 rounded-lg cursor-pointer transition-colors text-xs ${
                            isChecked ? "bg-[#FAF5EE] border border-[#8B5A2B]/30" : "hover:bg-white"
                          }`}
                        >
                          <div className="flex items-center gap-2">
                            <input
                              type="checkbox"
                              checked={isChecked}
                              onChange={() => handleToggleHelper(w.id)}
                              className="accent-[#8B5A2B] rounded-sm"
                            />
                            <span className="font-semibold text-[#2C1E16]">{w.name}</span>
                          </div>
                          <span className="text-[10px] text-[#8B7355] font-mono capitalize">
                            {w.role || "worker"}
                          </span>
                        </label>
                      );
                    })
                  )}
                </div>
              </div>

              {/* Tarif Upah Helper per Pesanan Berhasil */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-semibold text-[#2C1E16] mb-1">
                    Rencana Tarif Upah per Pesanan (LE)
                  </label>
                  <Input
                    type="number"
                    min="0"
                    step="1"
                    data-testid="input-trip-wage-rate"
                    value={tripFormData.trip_wage_rate_le}
                    onChange={(e) =>
                      setTripFormData({ ...tripFormData, trip_wage_rate_le: e.target.value })
                    }
                    className="h-10 text-xs rounded-xl border-[#E5DCC5]"
                  />
                  <p className="text-[10px] text-[#8B7355] mt-1">
                    Snapshot kebijakan upah akan terkunci permanen saat dispatch armada.
                  </p>
                </div>

                <div>
                  <label className="block text-xs font-semibold text-[#2C1E16] mb-1">
                    Catatan Trip (Opsional)
                  </label>
                  <Input
                    type="text"
                    placeholder="cth. Rute prioritas daerah Maadi"
                    value={tripFormData.notes}
                    onChange={(e) => setTripFormData({ ...tripFormData, notes: e.target.value })}
                    className="h-10 text-xs rounded-xl border-[#E5DCC5]"
                  />
                </div>
              </div>

              {/* Action Buttons */}
              <div className="flex items-center justify-end gap-2 border-t border-[#F1EBE0] pt-4">
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => setCreateModalOpen(false)}
                  className="rounded-xl border-[#E5DCC5] text-xs h-10 px-4"
                >
                  Batal
                </Button>
                <Button
                  type="submit"
                  disabled={submittingTrip}
                  data-testid="btn-submit-create-trip"
                  className="rounded-xl bg-[#8B5A2B] hover:bg-[#724a23] text-white text-xs h-10 px-5 shadow-xs"
                >
                  {submittingTrip ? "Menyimpan..." : "Simpan & Buat Trip"}
                </Button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {/* MODAL 2: Penugasan Pesanan ke Trip (Assign Orders Modal) */}
      {/* ========================================================================= */}
      {assignModalOpen && (
        <div
          data-testid="modal-assign-orders"
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4 backdrop-blur-xs"
        >
          <div className="w-full max-w-lg rounded-3xl border border-[#E5DCC5] bg-white p-6 shadow-xl space-y-4">
            <div className="flex items-center justify-between border-b border-[#F1EBE0] pb-3">
              <div className="flex items-center gap-2">
                <Truck size={18} className="text-[#8B5A2B]" />
                <h3 className="font-heading text-base font-bold text-[#2C1E16]">
                  Tugaskan Pesanan ke Trip Armada
                </h3>
              </div>
              <button
                type="button"
                onClick={() => setAssignModalOpen(false)}
                className="text-[#8B7355] hover:text-[#2C1E16]"
              >
                <X size={18} />
              </button>
            </div>

            <div className="text-xs text-[#5C4A3D]">
              Anda memilih{" "}
              <span className="font-bold text-[#8B5A2B]">{selectedOrderIds.length} pesanan</span> dari
              Antrean Siap Kirim untuk ditugaskan:
            </div>

            {/* List of Available Active Trips */}
            <div>
              <label className="block text-xs font-semibold text-[#2C1E16] mb-1.5">
                Pilih Trip Armada Tujuan <span className="text-red-500">*</span>
              </label>
              <div
                data-testid="trip-select-options"
                className="max-h-48 overflow-y-auto rounded-xl border border-[#E5DCC5] p-2 space-y-1.5"
              >
                {assignableTrips.length === 0 ? (
                  <div className="text-xs text-[#8B7355] p-3 text-center">
                    Tidak ada trip berstatus Draft atau Dijadwalkan.
                  </div>
                ) : (
                  assignableTrips.map((t) => {
                    const isTarget = targetTripId === (t.id || t._id);
                    return (
                      <div
                        key={t.id || t._id}
                        onClick={() => setTargetTripId(t.id || t._id)}
                        className={`p-3 rounded-xl border cursor-pointer transition-all text-xs ${
                          isTarget
                            ? "border-[#8B5A2B] bg-[#FAF5EE] ring-1 ring-[#8B5A2B]"
                            : "border-[#E5DCC5] hover:bg-[#FBF9F4]"
                        }`}
                      >
                        <div className="flex items-center justify-between">
                          <span className="font-mono font-bold text-[#8B5A2B]">{t.trip_number}</span>
                          <span className="capitalize text-[10px] px-2 py-0.5 rounded-full bg-stone-100 font-semibold text-stone-700">
                            {t.status}
                          </span>
                        </div>
                        <div className="flex items-center justify-between mt-1 text-[11px] text-[#8B7355]">
                          <span>
                            {t.scheduled_date} {t.departure_time || ""}
                          </span>
                          <span>
                            {t.stops_count || (t.stops ? t.stops.length : 0)} stop saat ini
                          </span>
                        </div>
                      </div>
                    );
                  })
                )}
              </div>
            </div>

            <div className="rounded-xl bg-amber-50 border border-amber-200 p-2.5 text-[11px] text-amber-800 flex items-start gap-1.5">
              <Info size={14} className="text-amber-600 shrink-0 mt-0.5" />
              <span>
                Penugasan dilakukan secara atomik. Jika pesanan sedang diklaim proses lain, sistem
                akan menolak (HTTP 409) dan memperbarui antrean secara otomatis.
              </span>
            </div>

            <div className="flex items-center justify-end gap-2 border-t border-[#F1EBE0] pt-3">
              <Button
                type="button"
                variant="outline"
                onClick={() => setAssignModalOpen(false)}
                className="rounded-xl border-[#E5DCC5] text-xs h-9 px-4"
              >
                Batal
              </Button>
              <Button
                type="button"
                disabled={assigningOrders || !targetTripId || assignableTrips.length === 0}
                onClick={handleExecuteAssignOrders}
                data-testid="btn-confirm-assign-orders"
                className="rounded-xl bg-[#8B5A2B] hover:bg-[#724a23] text-white text-xs h-9 px-5 shadow-xs"
              >
                {assigningOrders ? "Memproses Penugasan..." : "Konfirmasi & Tugaskan"}
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {/* MODAL 3: Kelola Trip Stops & Rute (Manage Stops & Route Modal) */}
      {/* ========================================================================= */}
      {stopsModalOpen && activeTrip && (
        <div
          data-testid="modal-manage-stops"
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4 backdrop-blur-xs"
        >
          <div className="w-full max-w-3xl max-h-[90vh] overflow-y-auto rounded-3xl border border-[#E5DCC5] bg-white p-6 shadow-xl space-y-4">
            <div className="flex items-center justify-between border-b border-[#F1EBE0] pb-3">
              <div>
                <div className="flex items-center gap-2 flex-wrap">
                  <h3 className="font-heading text-lg font-bold text-[#2C1E16]">
                    Stop & Rute Pengiriman: {activeTrip.trip_number}
                  </h3>
                  <span className="capitalize text-[10px] px-2 py-0.5 rounded-full bg-stone-100 font-semibold text-stone-700">
                    {activeTrip.status}
                  </span>
                  {activeTrip.status === "completed" && activeTrip.is_partially_completed && (
                    <span
                      data-testid="badge-partial-modal"
                      className="inline-flex items-center gap-1 rounded-full border border-amber-300 bg-amber-50 px-2 py-0.5 text-[10px] font-semibold text-amber-800"
                    >
                      Selesai Sebagian
                    </span>
                  )}
                </div>
                <p className="text-xs text-[#8B7355] mt-0.5">
                  Jadwal: {activeTrip.scheduled_date} {activeTrip.departure_time || ""} • Total{" "}
                  {activeTrip.stops ? activeTrip.stops.length : 0} Stop
                </p>
              </div>

              <button
                type="button"
                onClick={() => setStopsModalOpen(false)}
                className="text-[#8B7355] hover:text-[#2C1E16]"
              >
                <X size={20} />
              </button>
            </div>

            {/* Google Maps Multi-Stop Route Bar */}
            {activeTrip.stops && activeTrip.stops.length > 0 && (
              <div className="rounded-2xl border border-blue-200 bg-blue-50/60 p-3.5 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
                <div className="space-y-0.5">
                  <div className="text-xs font-bold text-blue-900 flex items-center gap-1.5">
                    <Navigation size={14} className="text-blue-700" />
                    <span>Rute Google Maps Armada (V1 Directions)</span>
                  </div>
                  <p className="text-[11px] text-blue-700">
                    Buka arah jalan rute multi-stop berdasarkan urutan destinasi pelanggan.
                  </p>
                </div>

                {buildGoogleMapsMultiStopUrl(activeTrip.stops) && (
                  <a
                    href={buildGoogleMapsMultiStopUrl(activeTrip.stops)}
                    target="_blank"
                    rel="noopener noreferrer"
                    data-testid="btn-open-multi-stop-maps"
                    className="inline-flex items-center justify-center gap-1.5 rounded-xl bg-blue-600 hover:bg-blue-700 text-white text-xs font-semibold px-4 py-2 shadow-2xs shrink-0"
                  >
                    <ExternalLink size={13} />
                    Buka Rute Lengkap
                  </a>
                )}
              </div>
            )}

            {/* Stops List */}
            {loadingActiveTrip ? (
              <div className="py-12 text-center text-sm text-[#8B7355]">
                <RotateCcw size={20} className="mx-auto mb-2 animate-spin text-[#8B5A2B]" />
                Memuat daftar stop trip...
              </div>
            ) : !activeTrip.stops || activeTrip.stops.length === 0 ? (
              <div className="rounded-2xl border border-dashed border-[#E5DCC5] p-8 text-center space-y-2">
                <MapPin size={32} className="mx-auto text-[#8B7355]/50" />
                <p className="text-xs font-semibold text-[#2C1E16]">
                  Belum ada pesanan / stop yang ditugaskan ke trip ini.
                </p>
                <p className="text-[11px] text-[#8B7355]">
                  Pilih pesanan dari tab Antrean Siap Kirim untuk menambahkan stop.
                </p>
              </div>
            ) : (
              <div className="space-y-2.5">
                {activeTrip.stops.map((stop, idx) => {
                  const isDelivered = stop.outcome === "delivered";
                  const canRelease =
                    (activeTrip.status === "draft" || activeTrip.status === "scheduled") &&
                    !isDelivered;

                  let outcomeBadge = "bg-stone-100 text-stone-700";
                  let outcomeLabel = stop.outcome || "pending";
                  if (stop.outcome === "pending") {
                    outcomeBadge = "bg-amber-50 text-amber-800 border border-amber-200";
                    outcomeLabel = "Menunggu";
                  } else if (stop.outcome === "out_for_delivery") {
                    outcomeBadge = "bg-blue-50 text-blue-800 border border-blue-200";
                    outcomeLabel = "Dalam Perjalanan";
                  } else if (stop.outcome === "delivered") {
                    outcomeBadge = "bg-emerald-50 text-emerald-800 border border-emerald-200";
                    outcomeLabel = "Terkirim";
                  } else if (stop.outcome === "failed") {
                    outcomeBadge = "bg-rose-50 text-rose-800 border border-rose-200";
                    outcomeLabel = "Gagal / Ditunda";
                  } else if (stop.outcome === "failed_closed") {
                    outcomeBadge = "bg-stone-100 text-stone-700 border border-stone-300";
                    outcomeLabel = "Gagal (Ditutup)";
                  }

                  const singleMapUrl = getStopMapUrl(stop);

                  return (
                    <div
                      key={stop.stop_id || idx}
                      data-testid={`stop-item-${stop.order_number || stop.order_id}`}
                      className="rounded-xl border border-[#E5DCC5] bg-white p-3.5 flex flex-col gap-2 shadow-2xs hover:shadow-xs transition-shadow"
                    >
                      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
                        <div className="flex items-start gap-3">
                          <div className="w-7 h-7 rounded-lg bg-[#FAF5EE] border border-[#E5DCC5] flex items-center justify-center font-bold text-xs text-[#8B5A2B] shrink-0 mt-0.5">
                            #{stop.sequence || idx + 1}
                          </div>
                          <div className="space-y-0.5">
                            <div className="flex items-center gap-2 flex-wrap">
                              <span className="font-mono text-xs font-bold text-[#2C1E16]">
                                {stop.order_number || `#${stop.order_id.slice(-6)}`}
                              </span>
                              <span
                                className={`text-[10px] px-2 py-0.5 rounded-full font-semibold ${outcomeBadge}`}
                              >
                                {outcomeLabel}
                              </span>
                              {stop.attempts?.length > 0 && (
                                <button
                                  type="button"
                                  onClick={() => toggleExpandAttempts(stop.order_id)}
                                  data-testid={`btn-toggle-attempts-${stop.order_number || stop.order_id}`}
                                  className="text-[10px] text-amber-800 bg-amber-50 hover:bg-amber-100 border border-amber-200 px-2 py-0.5 rounded-full font-medium inline-flex items-center gap-1 cursor-pointer transition-colors"
                                  title="Lihat riwayat percobaan pengantaran"
                                >
                                  <span>{stop.attempts.length} Percobaan</span>
                                  {expandedAttemptsStopIds[stop.order_id] ? (
                                    <ChevronUp size={11} />
                                  ) : (
                                    <ChevronDown size={11} />
                                  )}
                                </button>
                              )}
                            </div>
                            <div className="text-xs text-[#2C1E16] font-medium">
                              {stop.customer_name}
                              {stop.customer_phone && (
                                <span className="text-[#8B7355] font-normal ml-1.5">
                                  ({stop.customer_phone})
                                </span>
                              )}
                            </div>
                            {stop.customer_address && (
                              <div className="text-[11px] text-[#5C4A3D] flex items-center gap-1 line-clamp-1">
                                <MapPin size={11} className="text-[#8B7355] shrink-0" /> {stop.customer_address}
                              </div>
                            )}
                            {stop.delivery_zone && (
                              <div className="text-[10px] text-[#8B7355]">
                                Zona: {stop.delivery_zone}
                              </div>
                            )}
                            {stop.outcome === "failed" && stop.failure_reason && (
                              <div className="text-[11px] text-rose-700 font-medium">
                                Gagal: {stop.failure_reason}
                              </div>
                            )}
                          </div>
                        </div>

                        {/* Stop Actions */}
                        <div className="flex items-center gap-2 self-end sm:self-center flex-wrap">
                          {singleMapUrl && (
                            <a
                              href={singleMapUrl}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="inline-flex items-center gap-1 text-[11px] font-medium text-blue-600 hover:underline px-2 py-1 rounded-lg hover:bg-blue-50"
                            >
                              <ExternalLink size={12} /> Map
                            </a>
                          )}

                          {canManageOrders && stop.outcome === "out_for_delivery" && (
                            <>
                              <Button
                                size="sm"
                                onClick={() => handleOpenHandoverModal(stop)}
                                data-testid={`btn-handover-stop-${stop.order_number || stop.order_id}`}
                                className="h-8 text-xs bg-emerald-600 hover:bg-emerald-700 text-white px-2.5 rounded-lg shadow-xs"
                              >
                                <CheckCircle2 size={13} className="mr-1" />
                                Serah Terima
                              </Button>
                              <Button
                                size="sm"
                                variant="outline"
                                onClick={() => handleOpenFailAttemptModal(stop)}
                                data-testid={`btn-fail-stop-${stop.order_number || stop.order_id}`}
                                className="h-8 text-xs border-rose-300 text-rose-700 hover:bg-rose-50 px-2.5 rounded-lg"
                              >
                                <XCircle size={13} className="mr-1 text-rose-600" />
                                Catat Gagal
                              </Button>
                            </>
                          )}

                          {canManageOrders && stop.outcome === "failed" && (
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={() => handleExecuteRetry(stop)}
                              data-testid={`btn-retry-stop-${stop.order_number || stop.order_id}`}
                              disabled={retryingStopId === stop.order_id}
                              className="h-8 text-xs border-blue-300 text-blue-700 hover:bg-blue-50 px-2.5 rounded-lg font-medium"
                            >
                              {retryingStopId === stop.order_id ? (
                                <>
                                  <Loader2 size={13} className="mr-1 animate-spin" />
                                  Memproses...
                                </>
                              ) : (
                                <>
                                  <RotateCcw size={13} className="mr-1 text-blue-600" />
                                  Coba Lagi
                                </>
                              )}
                            </Button>
                          )}

                          {stop.outcome === "delivered" && (
                            <span className="text-[11px] text-emerald-700 font-medium bg-emerald-50 border border-emerald-200 px-2 py-1 rounded-lg inline-flex items-center gap-1">
                              <CheckCircle2 size={12} /> Selesai
                            </span>
                          )}

                          {canRelease && (
                            <Button
                              size="sm"
                              variant="ghost"
                              onClick={() => {
                                setStopToRelease(stop);
                                setReleaseConfirmOpen(true);
                              }}
                              data-testid={`btn-release-stop-${stop.order_number || stop.order_id}`}
                              className="h-8 text-xs text-rose-600 hover:text-rose-700 hover:bg-rose-50 px-2.5 rounded-lg"
                            >
                              <Trash2 size={13} className="mr-1" />
                              Lepas
                            </Button>
                          )}
                        </div>
                      </div>

                      {/* Expandable Attempt History Card */}
                      {expandedAttemptsStopIds[stop.order_id] && stop.attempts?.length > 0 && (
                        <div
                          data-testid={`attempt-history-${stop.order_number || stop.order_id}`}
                          className="w-full mt-2 pt-2 border-t border-[#F1EBE0] space-y-2"
                        >
                          <div className="text-[11px] font-bold text-[#2C1E16] flex items-center justify-between">
                            <span>Riwayat Percobaan Pengantaran ({stop.attempts.length})</span>
                            <span className="text-[10px] text-[#8B7355] font-normal">Urutan kronologis</span>
                          </div>
                          <div className="space-y-1.5">
                            {stop.attempts.map((att, attIdx) => (
                              <div
                                key={att.attempt_number || attIdx}
                                data-testid={`attempt-entry-${stop.order_number || stop.order_id}-${att.attempt_number || attIdx + 1}`}
                                className="rounded-lg bg-[#FAF5EE] border border-[#E5DCC5] p-2 text-xs text-[#2C1E16] space-y-1"
                              >
                                <div className="flex items-center justify-between gap-2 flex-wrap">
                                  <span className="font-bold text-[#8B5A2B]">
                                    Percobaan #{att.attempt_number || attIdx + 1}
                                  </span>
                                  <span className="text-[10px] text-[#8B7355]">
                                    {att.attempted_at ? new Date(att.attempted_at).toLocaleString("id-ID", { dateStyle: "medium", timeStyle: "short" }) : "-"}
                                  </span>
                                </div>
                                <div className="text-rose-700 font-medium">
                                  Alasan: {att.failure_reason}
                                </div>
                                {att.notes && (
                                  <div className="text-[#5C4A3D] text-[11px] italic">
                                    Catatan: {att.notes}
                                  </div>
                                )}
                                <div className="text-[10px] text-[#8B7355]">
                                  Dicatat oleh: {att.recorded_by_name || "Petugas"}
                                </div>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}

            <div className="flex items-center justify-between border-t border-[#F1EBE0] pt-3">
              {canManageOrders && isTripEligibleForCompletion(activeTrip) ? (
                <Button
                  type="button"
                  onClick={() => handleOpenCompleteModal(activeTrip)}
                  data-testid="btn-complete-trip-modal"
                  className="rounded-xl bg-emerald-700 hover:bg-emerald-800 text-white text-xs h-9 px-4 shadow-xs"
                >
                  <CheckCircle2 size={14} className="mr-1.5" />
                  Selesaikan Trip
                </Button>
              ) : (
                <div />
              )}
              <Button
                type="button"
                variant="outline"
                onClick={() => setStopsModalOpen(false)}
                className="rounded-xl border-[#E5DCC5] text-xs h-9 px-4"
              >
                Tutup
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {/* RELEASE CONFIRMATION DIALOG */}
      {/* ========================================================================= */}
      {releaseConfirmOpen && stopToRelease && (
        <div
          data-testid="dialog-confirm-release"
          className="fixed inset-0 z-60 flex items-center justify-center bg-black/50 p-4 backdrop-blur-xs"
        >
          <div className="w-full max-w-md rounded-3xl border border-[#E5DCC5] bg-white p-6 shadow-xl space-y-4">
            <div className="flex items-center gap-2 text-rose-600">
              <AlertTriangle size={22} />
              <h4 className="font-heading text-base font-bold text-[#2C1E16]">
                Konfirmasi Lepas Pesanan
              </h4>
            </div>

            <p className="text-xs text-[#5C4A3D]">
              Apakah Anda yakin ingin melepaskan pesanan{" "}
              <span className="font-mono font-bold text-[#8B5A2B]">
                {stopToRelease.order_number || stopToRelease.order_id}
              </span>{" "}
              dari trip ini?
            </p>
            <p className="text-[11px] text-[#8B7355]">
              Pesanan akan otomatis dilepaskan secara atomik dan kembali ke Antrean Siap Kirim untuk
              dapat dialokasikan ke trip lainnya.
            </p>

            <div className="flex items-center justify-end gap-2 border-t border-[#F1EBE0] pt-3">
              <Button
                type="button"
                variant="outline"
                disabled={releasing}
                onClick={() => {
                  setReleaseConfirmOpen(false);
                  setStopToRelease(null);
                }}
                className="rounded-xl border-[#E5DCC5] text-xs h-9 px-4"
              >
                Batal
              </Button>
              <Button
                type="button"
                disabled={releasing}
                onClick={handleConfirmReleaseStop}
                data-testid="btn-confirm-release-submit"
                className="rounded-xl bg-rose-600 hover:bg-rose-700 text-white text-xs h-9 px-4 shadow-xs"
              >
                {releasing ? "Melepaskan..." : "Ya, Lepas Pesanan"}
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {/* DISPATCH CONFIRMATION DIALOG */}
      {/* ========================================================================= */}
      {dispatchModalOpen && tripToDispatch && (
        <div
          data-testid="modal-confirm-dispatch"
          className="fixed inset-0 z-60 flex items-center justify-center bg-black/50 p-4 backdrop-blur-xs"
        >
          <div className="w-full max-w-lg rounded-3xl border border-[#E5DCC5] bg-white p-6 shadow-xl space-y-4">
            <div className="flex items-center gap-2.5 text-[#8B5A2B]">
              <Truck size={24} />
              <div>
                <h3 className="font-heading text-base font-bold text-[#2C1E16]">
                  Konfirmasi Dispatch Armada Pengiriman
                </h3>
                <p className="text-xs text-[#8B7355] font-mono">
                  {tripToDispatch.trip_number}
                </p>
              </div>
            </div>

            <div className="rounded-2xl bg-[#FAF5EE] border border-[#E5DCC5] p-3.5 space-y-2 text-xs text-[#2C1E16]">
              <div className="flex justify-between">
                <span className="text-[#8B7355]">Jadwal Keberangkatan:</span>
                <span className="font-semibold">{tripToDispatch.scheduled_date} {tripToDispatch.departure_time || ""}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-[#8B7355]">Jumlah Stop:</span>
                <span className="font-semibold font-mono">{tripToDispatch.stops_count || tripToDispatch.stops?.length || 0} Lokasi</span>
              </div>
              <div className="flex justify-between">
                <span className="text-[#8B7355]">Rencana Tarif Upah Helper:</span>
                <span className="font-bold text-[#8B5A2B]">
                  {fmtLE(tripToDispatch.trip_wage_rate_le || 50)} LE / pesanan
                </span>
              </div>
              {Array.isArray(tripToDispatch.helpers) && tripToDispatch.helpers.length > 0 && (
                <div className="pt-1 border-t border-[#E5DCC5]/60">
                  <span className="text-[#8B7355] block mb-1">Helper Bertugas:</span>
                  <div className="flex flex-wrap gap-1.5">
                    {tripToDispatch.helpers.map((h, i) => (
                      <span key={i} className="rounded-md bg-white border border-[#E5DCC5] px-2 py-0.5 text-[11px] font-medium text-[#2C1E16]">
                        {h.helper_name || `Helper #${i+1}`}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>

            <div className="rounded-xl bg-amber-50 border border-amber-200 p-3 text-xs text-amber-900 flex items-start gap-2.5">
              <Lock size={16} className="text-amber-700 shrink-0 mt-0.5" />
              <div className="space-y-1">
                <p className="font-bold">Penting: Snapshot Kebijakan Upah Dikunci Permanen</p>
                <p className="text-[11px] text-amber-800">
                  Saat armada diberangkatkan (in_transit), tarif upah helper akan dikunci secara imutabel. Seluruh stop pending akan beralih status menjadi out_for_delivery.
                </p>
              </div>
            </div>

            {dispatchError && (
              <div
                data-testid="dispatch-error-alert"
                className="rounded-xl bg-rose-50 border border-rose-200 p-3 text-xs text-rose-800 flex items-start gap-2"
              >
                <AlertCircle size={15} className="text-rose-600 shrink-0 mt-0.5" />
                <div>
                  <span className="font-bold">Gagal Dispatch (Batas Upah): </span>
                  <span>{dispatchError}</span>
                </div>
              </div>
            )}

            <div className="flex items-center justify-end gap-2 border-t border-[#F1EBE0] pt-3">
              <Button
                type="button"
                variant="outline"
                disabled={dispatching}
                onClick={() => {
                  setDispatchModalOpen(false);
                  setTripToDispatch(null);
                  setDispatchError(null);
                }}
                data-testid="btn-cancel-dispatch"
                className="rounded-xl border-[#E5DCC5] text-xs h-9 px-4"
              >
                Batal
              </Button>
              <Button
                type="button"
                disabled={dispatching}
                onClick={handleConfirmDispatch}
                data-testid="btn-confirm-dispatch-submit"
                className="rounded-xl bg-[#8B5A2B] hover:bg-[#6F4420] text-white text-xs h-9 px-4 shadow-xs"
              >
                {dispatching ? "Memberangkatkan..." : "Berangkatkan Sekarang"}
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {/* CANCEL TRIP CONFIRMATION DIALOG */}
      {/* ========================================================================= */}
      {cancelModalOpen && tripToCancel && (
        <div
          data-testid="modal-confirm-cancel"
          className="fixed inset-0 z-60 flex items-center justify-center bg-black/50 p-4 backdrop-blur-xs"
        >
          <div className="w-full max-w-md rounded-3xl border border-[#E5DCC5] bg-white p-6 shadow-xl space-y-4">
            <div className="flex items-center gap-2.5 text-rose-600">
              <AlertTriangle size={24} />
              <div>
                <h3 className="font-heading text-base font-bold text-[#2C1E16]">
                  Konfirmasi Pembatalan Trip Pengiriman
                </h3>
                <p className="text-xs text-[#8B7355] font-mono">
                  {tripToCancel.trip_number}
                </p>
              </div>
            </div>

            <p className="text-xs text-[#5C4A3D]">
              Apakah Anda yakin ingin membatalkan trip ini?
            </p>

            <div className="rounded-xl bg-[#FAF5EE] border border-[#E5DCC5] p-3 text-xs text-[#5C4A3D] space-y-1">
              <div className="font-semibold text-[#8B5A2B]">Dampak Pembatalan:</div>
              <p className="text-[11px] text-[#8B7355]">
                Seluruh pesanan yang belum selesai ({tripToCancel.stops_count || tripToCancel.stops?.length || 0} pesanan) akan otomatis dilepaskan secara atomik dan kembali ke Antrean Siap Kirim.
              </p>
            </div>

            <div className="space-y-1.5">
              <label className="block text-xs font-semibold text-[#2C1E16]">
                Alasan Pembatalan <span className="text-rose-500">*</span>
              </label>
              <textarea
                data-testid="input-cancel-reason"
                rows={3}
                value={cancellationReason}
                onChange={(e) => {
                  setCancellationReason(e.target.value);
                  if (cancelError) setCancelError(null);
                }}
                placeholder="Masukkan alasan pembatalan trip (minimal 5 karakter)..."
                className="w-full rounded-xl border border-[#E5DCC5] p-2.5 text-xs text-[#2C1E16] focus:border-[#8B5A2B] focus:outline-hidden"
              />
              <div className="text-[10px] text-[#8B7355] flex justify-between">
                <span>Wajib diisi minimal 5 karakter</span>
                <span>{cancellationReason.trim().length} karakter</span>
              </div>
            </div>

            {cancelError && (
              <div
                data-testid="cancel-error-alert"
                className="rounded-xl bg-rose-50 border border-rose-200 p-2.5 text-xs text-rose-800 flex items-start gap-2"
              >
                <AlertCircle size={14} className="text-rose-600 shrink-0 mt-0.5" />
                <span>{cancelError}</span>
              </div>
            )}

            <div className="flex items-center justify-end gap-2 border-t border-[#F1EBE0] pt-3">
              <Button
                type="button"
                variant="outline"
                disabled={cancelling}
                onClick={() => {
                  setCancelModalOpen(false);
                  setTripToCancel(null);
                  setCancelError(null);
                }}
                data-testid="btn-dismiss-cancel"
                className="rounded-xl border-[#E5DCC5] text-xs h-9 px-4"
              >
                Batal
              </Button>
              <Button
                type="button"
                disabled={cancelling || cancellationReason.trim().length < 5}
                onClick={handleConfirmCancel}
                data-testid="btn-confirm-cancel-submit"
                className="rounded-xl bg-rose-600 hover:bg-rose-700 text-white text-xs h-9 px-4 shadow-xs"
              >
                {cancelling ? "Membatalkan..." : "Ya, Batalkan Trip"}
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {/* HANDOVER CONFIRMATION DIALOG (Package 5) */}
      {/* ========================================================================= */}
      {handoverModalOpen && stopForHandover && activeTrip && (() => {
        const plannedRate =
          activeTrip.rate_policy_snapshot?.applied_rate_le ||
          activeTrip.trip_wage_rate_le ||
          50;
        const threshold =
          activeTrip.rate_policy_snapshot?.unusual_amount_threshold_le || 100;
        const hardCap =
          activeTrip.rate_policy_snapshot?.max_cap_at_dispatch_le || 500;
        const cWageNum = Number(customWageLe);
        const isOverHardCap =
          isCustomWage &&
          customWageLe !== "" &&
          !isNaN(cWageNum) &&
          cWageNum > hardCap;
        const isUnusual =
          isCustomWage &&
          customWageLe !== "" &&
          !isNaN(cWageNum) &&
          cWageNum > threshold &&
          !isOverHardCap;
        const canSubmit =
          !submittingHandover &&
          recipientName.trim().length > 0 &&
          helperConfirmed &&
          (!isCustomWage ||
            (customWageLe !== "" &&
              !isNaN(cWageNum) &&
              cWageNum >= 0 &&
              !isOverHardCap &&
              (!isUnusual ||
                (confirmedUnusualAmount && overrideReason.trim().length >= 5))));

        return (
          <div
            data-testid="modal-confirm-handover"
            className="fixed inset-0 z-70 flex items-center justify-center bg-black/50 p-4 backdrop-blur-xs overflow-y-auto"
          >
            <div className="w-full max-w-lg rounded-3xl border border-[#E5DCC5] bg-white p-6 shadow-xl space-y-4 my-8">
              <div className="flex items-center gap-2.5 text-emerald-700">
                <CheckCircle2 size={24} />
                <div>
                  <h3 className="font-heading text-base font-bold text-[#2C1E16]">
                    Konfirmasi Serah Terima Pesanan
                  </h3>
                  <p className="text-xs text-[#8B7355] font-mono">
                    {stopForHandover.order_number || stopForHandover.order_id} — Trip {activeTrip.trip_number}
                  </p>
                </div>
              </div>

              {/* Order & Recipient Context Card */}
              <div className="rounded-2xl bg-[#FAF5EE] border border-[#E5DCC5] p-3.5 space-y-1.5 text-xs text-[#2C1E16]">
                <div className="flex justify-between">
                  <span className="text-[#8B7355]">Pelanggan:</span>
                  <span className="font-semibold">{stopForHandover.customer_name}</span>
                </div>
                {stopForHandover.customer_phone && (
                  <div className="flex justify-between">
                    <span className="text-[#8B7355]">Telepon:</span>
                    <span>{stopForHandover.customer_phone}</span>
                  </div>
                )}
                {stopForHandover.customer_address && (
                  <div className="flex justify-between items-start gap-2">
                    <span className="text-[#8B7355] shrink-0">Alamat:</span>
                    <span className="text-right text-[11px] text-[#5C4A3D] line-clamp-2">
                      {stopForHandover.customer_address}
                    </span>
                  </div>
                )}
                <div className="flex justify-between pt-1 border-t border-[#E5DCC5]/60">
                  <span className="text-[#8B7355]">Rencana Tarif Upah Helper:</span>
                  <span className="font-bold text-[#8B5A2B]">
                    {fmtLE(plannedRate)} LE / pesanan
                  </span>
                </div>
              </div>

              {/* Handover Form */}
              <div className="space-y-3">
                {/* Recipient Name (Required) */}
                <div className="space-y-1">
                  <label className="block text-xs font-semibold text-[#2C1E16]">
                    Nama Penerima di Lokasi <span className="text-rose-500">*</span>
                  </label>
                  <Input
                    data-testid="input-handover-recipient"
                    value={recipientName}
                    onChange={(e) => {
                      setRecipientName(e.target.value);
                      if (handoverError) setHandoverError(null);
                    }}
                    placeholder="Masukkan nama terang penerima mebel..."
                    className="h-9 rounded-xl border-[#E5DCC5] text-xs text-[#2C1E16]"
                  />
                </div>

                {/* Handover Notes (Optional) */}
                <div className="space-y-1">
                  <label className="block text-xs font-semibold text-[#2C1E16]">
                    Catatan Serah Terima (Opsional)
                  </label>
                  <textarea
                    data-testid="input-handover-notes"
                    rows={2}
                    value={handoverNotes}
                    onChange={(e) => setHandoverNotes(e.target.value)}
                    placeholder="Contoh: Diterima rapi di lantai 2, dicek lengkap..."
                    className="w-full rounded-xl border border-[#E5DCC5] p-2.5 text-xs text-[#2C1E16] focus:border-[#8B5A2B] focus:outline-hidden"
                  />
                </div>

                {/* Helper Confirmation Checkbox (Required, Explicit action) */}
                <div className="rounded-xl border border-emerald-200 bg-emerald-50/50 p-3 flex items-start gap-2.5">
                  <input
                    type="checkbox"
                    id="helper-confirmed-check"
                    data-testid="checkbox-helper-confirmed"
                    checked={helperConfirmed}
                    onChange={(e) => {
                      setHelperConfirmed(e.target.checked);
                      if (handoverError) setHandoverError(null);
                    }}
                    className="mt-0.5 h-4 w-4 rounded-sm border-emerald-300 text-emerald-600 focus:ring-emerald-500 cursor-pointer"
                  />
                  <label
                    htmlFor="helper-confirmed-check"
                    className="text-xs font-medium text-emerald-950 cursor-pointer select-none"
                  >
                    Saya mengonfirmasi bahwa mebel telah diserahterimakan secara fisik oleh helper kepada pelanggan di lokasi. <span className="text-rose-500">*</span>
                  </label>
                </div>

                {/* Wage Override Section */}
                <div className="rounded-xl border border-[#E5DCC5] p-3 space-y-2.5">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <input
                        type="checkbox"
                        id="toggle-custom-wage-check"
                        data-testid="toggle-custom-wage"
                        checked={isCustomWage}
                        onChange={(e) => {
                          setIsCustomWage(e.target.checked);
                          if (!e.target.checked) {
                            setCustomWageLe("");
                            setConfirmedUnusualAmount(false);
                            setOverrideReason("");
                          }
                          if (handoverError) setHandoverError(null);
                        }}
                        className="h-4 w-4 rounded-sm border-[#8B5A2B] text-[#8B5A2B] focus:ring-[#8B5A2B] cursor-pointer"
                      />
                      <label
                        htmlFor="toggle-custom-wage-check"
                        className="text-xs font-semibold text-[#2C1E16] cursor-pointer select-none"
                      >
                        Sesuaikan Nominal Upah (Override)
                      </label>
                    </div>
                    <span className="text-[11px] text-[#8B7355]">
                      Standar: {fmtLE(plannedRate)} LE
                    </span>
                  </div>

                  {isCustomWage && (
                    <div className="space-y-2.5 pt-1 border-t border-[#F1EBE0]">
                      <div className="space-y-1">
                        <label className="block text-[11px] font-medium text-[#5C4A3D]">
                          Total Upah Helper untuk Pesanan Ini (LE) <span className="text-rose-500">*</span>
                        </label>
                        <Input
                          type="number"
                          step="0.01"
                          min="0"
                          data-testid="input-custom-wage"
                          value={customWageLe}
                          onChange={(e) => {
                            setCustomWageLe(e.target.value);
                            if (handoverError) setHandoverError(null);
                          }}
                          placeholder={`Nominal upah dalam LE (misal: ${plannedRate})`}
                          className="h-8.5 rounded-xl border-[#E5DCC5] text-xs text-[#2C1E16]"
                        />
                      </div>

                      {/* Hard Cap Warning (> hardCap LE) */}
                      {isOverHardCap && (
                        <div
                          data-testid="hard-cap-warning"
                          className="rounded-xl bg-rose-50 border border-rose-300 p-3 space-y-1.5 text-xs text-rose-950"
                        >
                          <div className="flex items-start gap-2">
                            <AlertTriangle size={16} className="text-rose-600 shrink-0 mt-0.5" />
                            <div>
                              <p className="font-bold">
                                Nominal upah ({customWageLe} LE) melebihi batas maksimum keras ({hardCap} LE).
                              </p>
                              <p className="mt-0.5 text-[11px] text-rose-800">
                                Pengajuan ini otomatis ditolak oleh backend. Konfirmasi dan alasan tertulis tidak dapat melewati batas keras.
                              </p>
                            </div>
                          </div>
                        </div>
                      )}

                      {/* Unusual Amount Warning & Confirmation (> threshold and <= hardCap) */}
                      {isUnusual && (
                        <div
                          data-testid="unusual-amount-warning"
                          className="rounded-xl bg-amber-50 border border-amber-200 p-3 space-y-2 text-xs text-amber-900"
                        >
                          <div className="flex items-start gap-2">
                            <AlertTriangle size={15} className="text-amber-700 shrink-0 mt-0.5" />
                            <p className="font-semibold">
                              Nominal upah ({customWageLe} LE) melebihi batas konfirmasi ({threshold} LE).
                            </p>
                          </div>

                          <div className="flex items-start gap-2 pt-1 border-t border-amber-200/60">
                            <input
                              type="checkbox"
                              id="confirm-unusual-check"
                              data-testid="checkbox-confirm-unusual-amount"
                              checked={confirmedUnusualAmount}
                              onChange={(e) => {
                                setConfirmedUnusualAmount(e.target.checked);
                                if (handoverError) setHandoverError(null);
                              }}
                              className="mt-0.5 h-3.5 w-3.5 rounded-sm border-amber-400 text-amber-600 focus:ring-amber-500 cursor-pointer"
                            />
                            <label
                              htmlFor="confirm-unusual-check"
                              className="text-[11px] font-medium cursor-pointer select-none"
                            >
                              Saya mengonfirmasi kebenaran nominal upah di atas batas normal. <span className="text-rose-500">*</span>
                            </label>
                          </div>

                          <div className="space-y-1">
                            <label className="block text-[11px] font-semibold text-[#2C1E16]">
                              Alasan Penyesuaian Upah <span className="text-rose-500">*</span>
                            </label>
                            <textarea
                              data-testid="input-override-reason"
                              rows={2}
                              value={overrideReason}
                              onChange={(e) => {
                                setOverrideReason(e.target.value);
                                if (handoverError) setHandoverError(null);
                              }}
                              placeholder="Wajib diisi minimal 5 karakter (contoh: Naik lantai 5 tanpa lift)..."
                              className="w-full rounded-xl border border-amber-200 bg-white p-2 text-xs text-[#2C1E16] focus:border-amber-500 focus:outline-hidden"
                            />
                            <div className="text-[10px] text-amber-800 text-right">
                              {overrideReason.trim().length} / 5 karakter minimum
                            </div>
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </div>

              {/* Error Alert */}
              {handoverError && (
                <div
                  data-testid="handover-error-alert"
                  className="rounded-xl bg-rose-50 border border-rose-200 p-3 text-xs text-rose-800 flex items-start gap-2"
                >
                  <AlertCircle size={15} className="text-rose-600 shrink-0 mt-0.5" />
                  <div>
                    <span className="font-bold">Gagal Serah Terima: </span>
                    <span>{handoverError}</span>
                  </div>
                </div>
              )}

              {/* Modal Actions */}
              <div className="flex items-center justify-end gap-2 border-t border-[#F1EBE0] pt-3">
                <Button
                  type="button"
                  variant="outline"
                  disabled={submittingHandover}
                  onClick={() => {
                    setHandoverModalOpen(false);
                    setStopForHandover(null);
                    setHandoverError(null);
                  }}
                  data-testid="btn-cancel-handover"
                  className="rounded-xl border-[#E5DCC5] text-xs h-9 px-4"
                >
                  Batal
                </Button>
                <Button
                  type="button"
                  disabled={!canSubmit}
                  onClick={handleConfirmHandover}
                  data-testid="btn-confirm-handover-submit"
                  className="rounded-xl bg-emerald-600 hover:bg-emerald-700 text-white text-xs h-9 px-4 shadow-xs"
                >
                  {submittingHandover ? "Memproses..." : "Konfirmasi & Serahkan Pesanan"}
                </Button>
              </div>
            </div>
          </div>
        );
      })()}

      {/* 9. Failed Attempt Modal (Package 6) */}
      {failAttemptModalOpen && stopForFailAttempt && activeTrip && (
        <div
          data-testid="modal-record-fail-attempt"
          className="fixed inset-0 z-70 flex items-center justify-center bg-black/50 p-4 backdrop-blur-xs overflow-y-auto"
        >
          <div className="w-full max-w-lg rounded-3xl border border-[#E5DCC5] bg-white p-6 shadow-xl space-y-4 my-8">
            <div className="flex items-center gap-2.5 text-rose-700">
              <XCircle size={24} />
              <div>
                <h3 className="font-heading text-base font-bold text-[#2C1E16]">
                  Catat Percobaan Pengantaran Gagal
                </h3>
                <p className="text-xs text-[#8B7355] font-mono">
                  {stopForFailAttempt.order_number || stopForFailAttempt.order_id} — Trip {activeTrip.trip_number}
                </p>
              </div>
            </div>

            <div className="space-y-3.5 text-xs">
              {/* Destination & Recipient Info */}
              <div className="rounded-2xl bg-[#FAF5EE] border border-[#E5DCC5] p-3.5 space-y-1.5">
                <div className="flex justify-between items-center text-[#8B7355]">
                  <span>Penerima:</span>
                  <span className="font-semibold text-[#2C1E16]">
                    {stopForFailAttempt.customer_name}
                  </span>
                </div>
                {stopForFailAttempt.customer_phone && (
                  <div className="flex justify-between items-center text-[#8B7355]">
                    <span>Nomor Telepon:</span>
                    <span className="font-mono text-[#2C1E16]">
                      {stopForFailAttempt.customer_phone}
                    </span>
                  </div>
                )}
                {stopForFailAttempt.customer_address && (
                  <div className="flex justify-between items-start text-[#8B7355] gap-2">
                    <span className="shrink-0">Alamat:</span>
                    <span className="text-right text-[#2C1E16] font-medium">
                      {stopForFailAttempt.customer_address}
                    </span>
                  </div>
                )}
                <div className="flex justify-between items-center text-[#8B7355] border-t border-[#E5DCC5]/50 pt-1.5">
                  <span>Percobaan Sebelumnya:</span>
                  <span className="font-bold text-[#8B5A2B]">
                    {stopForFailAttempt.attempts?.length || stopForFailAttempt.attempt_count || 0} kali
                  </span>
                </div>
              </div>

              {/* Quick Reasons */}
              <div className="space-y-1.5">
                <label className="block text-xs font-semibold text-[#2C1E16]">
                  Pilih Alasan Cepat:
                </label>
                <div className="flex flex-wrap gap-1.5">
                  {[
                    "Penerima tidak dapat dihubungi",
                    "Penerima tidak ada di tempat / Rumah kosong",
                    "Alamat tidak ditemukan / salah alamat",
                    "Akses jalan ditutup / tidak dapat dilalui",
                    "Pesanan ditolak penerima"
                  ].map((qReason) => (
                    <button
                      key={qReason}
                      type="button"
                      onClick={() => {
                        setFailureReason(qReason);
                        if (failAttemptError) setFailAttemptError(null);
                      }}
                      className={`text-[11px] px-2.5 py-1 rounded-lg border transition-colors cursor-pointer ${
                        failureReason === qReason
                          ? "bg-rose-100 border-rose-300 text-rose-900 font-semibold"
                          : "bg-[#FAF5EE] border-[#E5DCC5] text-[#5C4A3D] hover:bg-rose-50"
                      }`}
                    >
                      {qReason}
                    </button>
                  ))}
                </div>
              </div>

              {/* Failure Reason Input */}
              <div className="space-y-1">
                <label className="block text-xs font-semibold text-[#2C1E16]">
                  Alasan Kegagalan Pengantaran <span className="text-rose-600">*</span>
                </label>
                <Input
                  data-testid="input-failure-reason"
                  placeholder="Misal: Penerima di luar kota, tidak ada orang di rumah"
                  value={failureReason}
                  onChange={(e) => {
                    setFailureReason(e.target.value);
                    if (failAttemptError) setFailAttemptError(null);
                  }}
                  className="h-9 text-xs border-[#E5DCC5] rounded-xl"
                />
                <div className="flex items-center justify-between text-[10px] text-[#8B7355]">
                  <span>Wajib diisi minimal 3 karakter non-spasi.</span>
                  <span>{failureReason.trim().length} / 3 min</span>
                </div>
              </div>

              {/* Failure Notes Input */}
              <div className="space-y-1">
                <label className="block text-xs font-semibold text-[#2C1E16]">
                  Catatan Tambahan (Opsional)
                </label>
                <textarea
                  data-testid="input-failure-notes"
                  rows={2}
                  value={failureNotes}
                  onChange={(e) => setFailureNotes(e.target.value)}
                  placeholder="Misal: Sudah titip pesan ke satpam atau koordinasi dengan customer service..."
                  className="w-full text-xs border border-[#E5DCC5] rounded-xl p-2.5 bg-white text-[#2C1E16] focus:outline-hidden focus:ring-1 focus:ring-[#8B5A2B]"
                />
              </div>

              {/* Zero Wage & Zero Finance Policy Notice */}
              <div className="rounded-xl bg-amber-50 border border-amber-200 p-3 text-xs text-amber-900 space-y-1">
                <p className="font-semibold flex items-center gap-1.5">
                  <Info size={14} className="text-amber-700 shrink-0" />
                  Ketentuan Upah & Finansial:
                </p>
                <p className="text-[11px] text-amber-800">
                  Pencatatan kegagalan pengantaran <strong>tidak menimbulkan kewajiban upah helper</strong> dan <strong>tidak memicu beban finansial</strong>. Stop dapat dicoba kembali (*Retry*) atau dijadwalkan ulang.
                </p>
              </div>

              {/* Error Alert */}
              {failAttemptError && (
                <div
                  data-testid="fail-attempt-error-alert"
                  className="rounded-xl bg-rose-50 border border-rose-200 p-3 text-xs text-rose-800 flex items-start gap-2"
                >
                  <AlertCircle size={15} className="text-rose-600 shrink-0 mt-0.5" />
                  <div>
                    <span className="font-bold">Gagal Mencatat Percobaan: </span>
                    <span>{failAttemptError}</span>
                  </div>
                </div>
              )}
            </div>

            {/* Modal Actions */}
            <div className="flex items-center justify-end gap-2 border-t border-[#F1EBE0] pt-3">
              <Button
                type="button"
                variant="outline"
                disabled={submittingFailAttempt}
                onClick={() => {
                  setFailAttemptModalOpen(false);
                  setStopForFailAttempt(null);
                  setFailAttemptError(null);
                }}
                data-testid="btn-cancel-fail-attempt"
                className="rounded-xl border-[#E5DCC5] text-xs h-9 px-4"
              >
                Batal
              </Button>
              <Button
                type="button"
                disabled={submittingFailAttempt || failureReason.trim().length < 3}
                onClick={handleConfirmFailAttempt}
                data-testid="btn-submit-fail-attempt"
                className="rounded-xl bg-rose-600 hover:bg-rose-700 text-white text-xs h-9 px-4 font-semibold shadow-xs"
              >
                {submittingFailAttempt ? (
                  <>
                    <Loader2 size={13} className="mr-1.5 animate-spin" />
                    Menyimpan...
                  </>
                ) : (
                  <>
                    <XCircle size={13} className="mr-1.5" />
                    Simpan Kegagalan
                  </>
                )}
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* ========================================================================= */}
      {/* MODAL 5: KONFIRMASI PENYELESAIAN TRIP (PACKAGE 7B) */}
      {/* ========================================================================= */}
      {completeModalOpen && tripToComplete && (() => {
        const stops = Array.isArray(tripToComplete.stops) ? tripToComplete.stops : [];
        const deliveredStops = stops.filter((s) => s.outcome === "delivered");
        const failedStops = stops.filter((s) => s.outcome === "failed" || s.outcome === "failed_closed");

        return (
          <div
            data-testid="modal-complete-trip"
            className="fixed inset-0 z-60 flex items-center justify-center bg-black/50 p-4 backdrop-blur-xs"
          >
            <div className="w-full max-w-lg rounded-3xl border border-[#E5DCC5] bg-white p-6 shadow-xl space-y-4">
              <div className="flex items-center gap-2.5 text-emerald-700">
                <CheckCircle2 size={24} />
                <div>
                  <h3 className="font-heading text-base font-bold text-[#2C1E16]">
                    Konfirmasi Penyelesaian Trip
                  </h3>
                  <p className="text-xs text-[#8B7355] font-mono">
                    {tripToComplete.trip_number}
                  </p>
                </div>
              </div>

              {/* Summary Box */}
              <div
                data-testid="complete-trip-summary"
                className="rounded-2xl bg-[#FAF5EE] border border-[#E5DCC5] p-3.5 space-y-2 text-xs text-[#2C1E16]"
              >
                <div className="flex justify-between items-center">
                  <span className="text-[#8B7355]">Total Stop pada Trip:</span>
                  <span className="font-bold font-mono text-[#2C1E16]">{stops.length} Lokasi</span>
                </div>
                <div className="flex justify-between items-center">
                  <span className="text-emerald-700 font-medium">Berhasil Diserahterimakan (Delivered):</span>
                  <span
                    data-testid="complete-summary-delivered-count"
                    className="font-bold font-mono text-emerald-800 bg-emerald-50 px-2 py-0.5 rounded-md border border-emerald-200"
                  >
                    {deliveredStops.length} Stop
                  </span>
                </div>
                <div className="flex justify-between items-center">
                  <span className="text-rose-700 font-medium">Gagal / Ditunda (Failed):</span>
                  <span
                    data-testid="complete-summary-failed-count"
                    className={`font-bold font-mono px-2 py-0.5 rounded-md border ${
                      failedStops.length > 0
                        ? "text-rose-800 bg-rose-50 border-rose-200"
                        : "text-stone-600 bg-stone-50 border-stone-200"
                    }`}
                  >
                    {failedStops.length} Stop
                  </span>
                </div>
              </div>

              {/* Warning/Explanatory Notice */}
              {failedStops.length > 0 ? (
                <div
                  data-testid="complete-trip-failed-warning"
                  className="rounded-2xl border border-amber-300 bg-amber-50/70 p-3.5 text-xs text-amber-900 space-y-1"
                >
                  <div className="font-bold flex items-center gap-1.5 text-amber-800">
                    <AlertTriangle size={15} className="shrink-0 text-amber-700" />
                    <span>Perhatian: Trip Diselesaikan Sebagian ({failedStops.length} Stop Gagal)</span>
                  </div>
                  <p className="text-[11px] leading-relaxed text-amber-900/90">
                    Sebanyak <span className="font-bold">{failedStops.length} pesanan</span> yang gagal diantar akan ditutup statusnya pada trip ini (<code className="font-mono text-[10px] bg-amber-100 px-1 rounded">failed_closed</code>), dan pesanannya akan <span className="font-semibold underline">otomatis dilepaskan kembali ke Antrean Siap Kirim</span> agar dapat dijadwalkan ulang pada trip berikutnya.
                  </p>
                </div>
              ) : (
                <div
                  data-testid="complete-trip-success-notice"
                  className="rounded-2xl border border-emerald-200 bg-emerald-50/60 p-3 text-xs text-emerald-900 flex items-center gap-2"
                >
                  <CheckCircle2 size={16} className="text-emerald-700 shrink-0" />
                  <span>Semua stop berhasil diserahterimakan. Seluruh pesanan telah berstatus selesai dengan pengakuan pendapatan yang terkunci.</span>
                </div>
              )}

              {/* Completion Notes Input */}
              <div>
                <label className="block text-xs font-semibold text-[#2C1E16] mb-1">
                  Catatan Penyelesaian Trip (Opsional)
                </label>
                <textarea
                  data-testid="input-complete-notes"
                  rows={2}
                  value={completionNotes}
                  onChange={(e) => setCompletionNotes(e.target.value)}
                  placeholder="Catatan kepulangan armada, kondisi serah terima, dsb."
                  disabled={completing}
                  className="w-full text-xs rounded-xl border border-[#E5DCC5] p-2.5 text-[#2C1E16] focus:border-[#8B5A2B] focus:ring-1 focus:ring-[#8B5A2B] outline-none"
                />
              </div>

              {/* Error Message */}
              {completeError && (
                <div
                  data-testid="complete-error-message"
                  className="rounded-xl border border-rose-300 bg-rose-50 p-2.5 text-xs text-rose-800 font-medium"
                >
                  {completeError}
                </div>
              )}

              {/* Action Buttons */}
              <div className="flex items-center justify-end gap-2 border-t border-[#F1EBE0] pt-3">
                <Button
                  type="button"
                  variant="outline"
                  disabled={completing}
                  onClick={() => {
                    setCompleteModalOpen(false);
                    setTripToComplete(null);
                  }}
                  data-testid="btn-cancel-complete"
                  className="rounded-xl border-[#E5DCC5] text-xs h-9 px-4"
                >
                  Batal
                </Button>
                <Button
                  type="button"
                  disabled={completing}
                  onClick={handleConfirmCompleteTrip}
                  data-testid="btn-confirm-complete-submit"
                  className="rounded-xl bg-emerald-700 hover:bg-emerald-800 text-white text-xs h-9 px-4 shadow-xs"
                >
                  {completing ? (
                    <>
                      <Loader2 size={13} className="mr-1.5 animate-spin" />
                      Menyelesaikan...
                    </>
                  ) : (
                    <>
                      <CheckCircle2 size={14} className="mr-1.5" />
                      Konfirmasi Selesai
                    </>
                  )}
                </Button>
              </div>
            </div>
          </div>
        );
      })()}
    </div>
  );
}
