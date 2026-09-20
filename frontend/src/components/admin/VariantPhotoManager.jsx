import React, { useState, useRef, useMemo } from "react";
import { imgUrl } from "../../lib/api";
import { CATEGORY_PRICELISTS } from "../../lib/constants";
import { Button } from "../ui/button";
import { Badge } from "../ui/badge";
import { Input } from "../ui/input";
import { Label } from "../ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../ui/select";
import {
  Upload,
  Trash2,
  Plus,
  ArrowLeft,
  ArrowRight,
  Search,
  CheckCircle2,
  Clock,
  Layers,
  Sparkles,
  ChevronDown,
  ChevronUp,
  Image as ImageIcon,
} from "lucide-react";
import { toast } from "sonner";

/**
 * Helper to generate predefined combinations based on category rules
 */
export function getProductCombinations(product) {
  if (!product) return [];
  const cat = product.category;
  const pr = product.pricing || {};

  // 1. Rak & shelf-like products
  if (cat === "rak" || ((pr.lengths || pr.levels) && !pr.groups)) {
    const lengths = pr.lengths || ["60", "80", "120"];
    const levels = pr.levels || ["2", "3", "4", "5", "6", "7"];
    const types = (pr.types || ["B", "A"]).filter((t) => t === "B" || t === "A");
    const combos = [];
    lengths.forEach((len) => {
      levels.forEach((lvl) => {
        types.forEach((typ) => {
          combos.push({
            id: `${len}_${lvl}_${typ}`,
            title: `Rak ${len} cm · ${lvl} Tingkat · Tipe ${typ}`,
            shortTitle: `${len}cm • ${lvl} Tkt • Tipe ${typ}`,
            attributes: { length: String(len), level: String(lvl), type: String(typ), finishing: "Natural" },
            filterValues: { length: String(len), level: String(lvl), type: String(typ) },
          });
        });
      });
    });
    return combos;
  }

  // 2. Meja: Standar (Ukuran × Tinggi) + Khusus Finishing Lapis HPL
  if (cat === "meja") {
    const sizes = pr.sizes || ["40x80", "50x80"];
    const heights = pr.heights || ["30", "75"];
    const combos = [];

    // 2a. Standar (Natural)
    sizes.forEach((sz) => {
      heights.forEach((h) => {
        const hLabel = h === "30" ? "30 cm (Lesehan)" : h === "75" ? "75 cm (Kursi)" : `${h} cm`;
        combos.push({
          id: `${sz}_${h}`,
          title: `Meja ${sz} cm · Tinggi ${hLabel}`,
          shortTitle: `${sz} • T.${h}cm`,
          attributes: { size: String(sz), height: String(h), finishing: "Natural" },
          filterValues: { size: String(sz), height: String(h), finishing: "Natural" },
        });
      });
    });

    // 2b. Khusus Finishing Lapis HPL
    sizes.forEach((sz) => {
      heights.forEach((h) => {
        const hLabel = h === "30" ? "30 cm (Lesehan)" : h === "75" ? "75 cm (Kursi)" : `${h} cm`;
        combos.push({
          id: `${sz}_${h}_hpl`,
          title: `Meja ${sz} cm · Tinggi ${hLabel} · Lapis HPL`,
          shortTitle: `${sz} • T.${h}cm • HPL`,
          attributes: { size: String(sz), height: String(h), finishing: "Lapis HPL" },
          filterValues: { size: String(sz), height: String(h), finishing: "Lapis HPL" },
        });
      });
    });

    return combos;
  }

  // 3. Meja Rak
  if (cat === "meja_rak") {
    if (Array.isArray(pr.groups) && pr.groups.length > 0) {
      const sizeGroup = pr.groups.find((g) => g.key === "size")?.options || ["Meja 40x80 cm", "Meja 50x80 cm"];
      const levelsGroup = pr.groups.find((g) => g.key === "levels")?.options || ["2 Tingkat", "3 Tingkat", "4 Tingkat", "5 Tingkat"];
      const heightGroup = pr.groups.find((g) => g.key === "height")?.options || ["30 cm (Lesehan)", "75 cm (Kursi)"];
      const combos = [];
      sizeGroup.forEach((sz) => {
        levelsGroup.forEach((lvl) => {
          heightGroup.forEach((h) => {
            combos.push({
              id: `${sz}__${lvl}__${h}`,
              title: `${sz} · ${lvl} · ${h}`,
              shortTitle: `${sz} • ${lvl} • ${h}`,
              attributes: { size: String(sz), levels: String(lvl), height: String(h), finishing: "Natural" },
              filterValues: { size: String(sz), levels: String(lvl), height: String(h) },
            });
          });
        });
      });
      return combos;
    }
  }

  // 4. Papan Tulis
  if (cat === "papan_tulis") {
    const mounts = pr.groups?.find((g) => g.key === "mount")?.options || ["Gantung", "+ Kaki 150 cm"];
    const sizes = pr.groups?.find((g) => g.key === "size")?.options || [
      "30x50 cm",
      "40x60 cm",
      "50x70 cm",
      "80x60 cm",
      "120x60 cm",
      "120x80 cm",
      "180x80 cm",
      "180x120 cm",
      "240x120 cm",
    ];
    const combos = [];
    mounts.forEach((m) => {
      sizes.forEach((s) => {
        if (m === "+ Kaki 150 cm" && (s === "30x50 cm" || s === "40x60 cm" || s === "50x70 cm")) {
          return;
        }
        combos.push({
          id: `${m}_${s}`,
          title: `Papan Tulis ${m} · ${s}`,
          shortTitle: `${m} • ${s}`,
          attributes: { mount: String(m), size: String(s) },
          filterValues: { mount: String(m), size: String(s) },
        });
      });
    });
    return combos;
  }

  // 5. BlackBoard
  if (cat === "blockboard") {
    const options = pr.groups?.find((g) => g.key === "pilihan")?.options || [
      "Gantung 80x60 cm",
      "Gantung 80x120 cm",
      "Gantung 200x60 cm",
      "Stand 2 Muka (Papan 60x80 + Stand 60x120)",
    ];
    return options.map((opt) => ({
      id: opt,
      title: `BlackBoard ${opt}`,
      shortTitle: opt,
      attributes: { pilihan: String(opt) },
      filterValues: { pilihan: String(opt) },
    }));
  }

  // 6. Custom Showcase
  if (cat === "custom") {
    const designOpts = pr.groups?.find((g) => g.key === "desain")?.options || Object.keys(pr.design_details || {});
    const set = new Set(designOpts);
    (product.photos || []).forEach((ph) => {
      if (ph.attributes?.desain) set.add(ph.attributes.desain);
    });
    return Array.from(set).map((desain) => {
      const details = pr.design_details?.[desain];
      const basePrice = pr.base_prices?.[desain] || 0;
      return {
        id: desain,
        title: desain,
        shortTitle: desain,
        subtitle: Array.isArray(details) ? details.join(" • ") : (details || ""),
        price: basePrice,
        attributes: { desain: String(desain) },
        filterValues: { desain: String(desain) },
        isCustom: true,
      };
    });
  }

  // 7. Dynamic cartesian for any other product with groups
  if (Array.isArray(pr.groups) && pr.groups.length > 0) {
    const primaryGroups = pr.groups.filter((g) => g.key !== "finishing");
    const activeGroups = primaryGroups.length > 0 ? primaryGroups : pr.groups;

    const cartesian = (groups) => {
      return groups.reduce(
        (acc, g) => {
          const opts = g.options || [];
          if (opts.length === 0) return acc;
          const res = [];
          acc.forEach((combo) => {
            opts.forEach((opt) => {
              res.push({ ...combo, [g.key]: opt });
            });
          });
          return res;
        },
        [{}]
      );
    };

    const combos = cartesian(activeGroups);
    return combos.map((cfg) => {
      const title = Object.values(cfg).join(" · ");
      const id = Object.entries(cfg)
        .map(([k, v]) => `${k}:${v}`)
        .join("__");
      return {
        id,
        title: `${product.name} ${title}`,
        shortTitle: title,
        attributes: cfg,
        filterValues: cfg,
      };
    });
  }

  return [];
}

export function findPhotoForCombo(photos, comboAttributes) {
  if (!Array.isArray(photos)) return null;
  return (
    photos.find((ph) => {
      const attr = ph?.attributes || {};
      return Object.entries(comboAttributes).every(([k, v]) => {
        if (v == null || v === "") return true;
        if (k === "finishing") {
          const isTargetHpl = v === "Lapis HPL" || v === "Premium";
          const isAttrHpl = attr.finishing === "Lapis HPL" || attr.finishing === "Premium";
          if (isTargetHpl) return isAttrHpl;
          // Target is Natural/standard: photo must NOT be HPL
          return !isAttrHpl;
        }
        return String(attr[k]) === String(v);
      });
    }) || null
  );
}

export function hasAnyPhoto(ph) {
  if (!ph) return false;
  return Boolean(
    ph.main_url ||
    ph.front_url ||
    ph.side_url ||
    (Array.isArray(ph.images) && ph.images.length > 0 && ph.images[0])
  );
}

export default function VariantPhotoManager({
  product,
  photos = [],
  onUpdatePhotos,
  uploadTo,
  pricing = {},
  onUpdatePricing,
}) {
  const fileInputs = useRef({});
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("all"); // 'all' | 'has_photo' | 'no_photo'
  const [filterValues, setFilterValues] = useState({});
  const [showAddCustomModal, setShowAddCustomModal] = useState(false);
  const [newCustomDesign, setNewCustomDesign] = useState({
    title: "",
    spesifikasi: "",
    price: "",
  });

  const category = product?.category;
  const priceListFallback = CATEGORY_PRICELISTS[category] || "";

  // 1. Generate combinations
  const combinations = useMemo(() => {
    return getProductCombinations(product);
  }, [product]);

  const [showUnmapped, setShowUnmapped] = useState(combinations.length === 0);

  // 2. Compute filter options
  const filterKeys = useMemo(() => {
    if (category === "rak") {
      return [
        { key: "length", label: "Panjang", options: ["60", "80", "120"], suffix: " cm" },
        { key: "level", label: "Tingkat", options: ["2", "3", "4", "5", "6", "7"], suffix: " Tingkat" },
        { key: "type", label: "Tipe", options: ["B", "A"], prefix: "Tipe " },
      ];
    }
    if (category === "meja") {
      return [
        { key: "size", label: "Ukuran", options: ["40x80", "50x80"], suffix: " cm" },
        { key: "height", label: "Tinggi", options: ["30", "75"], formatter: (h) => (h === "30" ? "30 cm (Lesehan)" : "75 cm (Kursi)") },
        { key: "finishing", label: "Model / Finishing", options: ["Natural", "Lapis HPL"], formatter: (f) => (f === "Natural" ? "Standar Kayu" : "Lapis HPL") },
      ];
    }
    if (category === "meja_rak") {
      return [
        { key: "size", label: "Ukuran Meja", options: ["Meja 40x80 cm", "Meja 50x80 cm"] },
        { key: "levels", label: "Jumlah Tingkat", options: ["2 Tingkat", "3 Tingkat", "4 Tingkat", "5 Tingkat"] },
        { key: "height", label: "Tinggi Meja", options: ["30 cm (Lesehan)", "75 cm (Kursi)"] },
      ];
    }
    if (category === "papan_tulis") {
      return [
        { key: "mount", label: "Pemasangan", options: ["Gantung", "+ Kaki 150 cm"] },
        { key: "size", label: "Ukuran", options: [
          "30x50 cm",
          "40x60 cm",
          "50x70 cm",
          "80x60 cm",
          "120x60 cm",
          "120x80 cm",
          "180x80 cm",
          "180x120 cm",
          "240x120 cm"
        ] },
      ];
    }
    return [];
  }, [category]);

  // 3. Stats calculation
  const stats = useMemo(() => {
    let filled = 0;
    combinations.forEach((combo) => {
      const ph = findPhotoForCombo(photos, combo.attributes);
      if (hasAnyPhoto(ph)) filled++;
    });
    const total = combinations.length;
    const percentage = total > 0 ? Math.round((filled / total) * 100) : 0;
    return { filled, total, percentage };
  }, [combinations, photos]);

  // 4. Filter combinations
  const filteredCombinations = useMemo(() => {
    return combinations.filter((combo) => {
      const ph = findPhotoForCombo(photos, combo.attributes);
      const hasPhoto = hasAnyPhoto(ph);

      // Status filter
      if (statusFilter === "has_photo" && !hasPhoto) return false;
      if (statusFilter === "no_photo" && hasPhoto) return false;

      // Dropdown filters
      for (const [key, val] of Object.entries(filterValues)) {
        if (val && val !== "all") {
          if (String(combo.attributes[key]) !== String(val)) return false;
        }
      }

      // Text search
      if (search.trim()) {
        const q = search.toLowerCase();
        const matchTitle = combo.title.toLowerCase().includes(q);
        const matchSub = (combo.subtitle || "").toLowerCase().includes(q);
        const matchAttrs = Object.values(combo.attributes).some((v) =>
          String(v).toLowerCase().includes(q)
        );
        if (!matchTitle && !matchSub && !matchAttrs) return false;
      }

      return true;
    });
  }, [combinations, photos, statusFilter, filterValues, search]);

  // 5. Unmapped photos
  const unmappedPhotos = useMemo(() => {
    return (photos || []).filter((ph) => {
      const attr = ph?.attributes || {};
      return !combinations.some((combo) => {
        return Object.entries(combo.attributes).every(
          ([k, v]) => String(attr[k]) === String(v)
        );
      });
    });
  }, [photos, combinations]);

  // Action: Upload to specific slot
  const handleUploadSlot = (combo, slot, file) => {
    uploadTo(file, (url) => {
      const next = [...photos];
      const idx = next.findIndex((ph) => {
        const attr = ph?.attributes || {};
        return Object.entries(combo.attributes).every(
          ([k, v]) => String(attr[k]) === String(v)
        );
      });

      if (idx >= 0) {
        next[idx] = {
          ...next[idx],
          [slot]: url,
        };
      } else {
        const newPh = {
          id: "ph_" + Date.now() + "_" + Math.random().toString(36).substring(2, 6),
          attributes: { ...combo.attributes },
          main_url: slot === "main_url" ? url : "",
          front_url: slot === "front_url" ? url : "",
          side_url: slot === "side_url" ? url : "",
          images: [],
        };
        next.push(newPh);
      }
      onUpdatePhotos(next);
      toast.success("Foto berhasil diunggah!");
    });
  };

  // Action: Delete a slot
  const handleDeleteSlot = (combo, slot) => {
    const next = [...photos];
    const idx = next.findIndex((ph) => {
      const attr = ph?.attributes || {};
      return Object.entries(combo.attributes).every(
        ([k, v]) => String(attr[k]) === String(v)
      );
    });

    if (idx >= 0) {
      const target = { ...next[idx], [slot]: "" };
      const hasContent =
        target.main_url ||
        target.front_url ||
        target.side_url ||
        (Array.isArray(target.images) && target.images.length > 0);

      if (!hasContent) {
        next.splice(idx, 1);
      } else {
        next[idx] = target;
      }
      onUpdatePhotos(next);
      toast.success("Foto dihapus");
    }
  };

  // Action: Swap slots (reorder Foto 1, Foto 2, Foto 3)
  const handleMoveSlot = (combo, fromIdx, dir) => {
    const slots = ["main_url", "front_url", "side_url"];
    const toIdx = fromIdx + dir;
    if (toIdx < 0 || toIdx >= slots.length) return;
    const fromSlot = slots[fromIdx];
    const toSlot = slots[toIdx];

    const next = [...photos];
    const idx = next.findIndex((ph) => {
      const attr = ph?.attributes || {};
      return Object.entries(combo.attributes).every(
        ([k, v]) => String(attr[k]) === String(v)
      );
    });

    if (idx >= 0) {
      const ph = { ...next[idx] };
      const temp = ph[fromSlot] || "";
      ph[fromSlot] = ph[toSlot] || "";
      ph[toSlot] = temp;
      next[idx] = ph;
      onUpdatePhotos(next);
    }
  };

  // Action: Add extra photo
  const handleAddExtraPhoto = (combo, file) => {
    uploadTo(file, (url) => {
      const next = [...photos];
      const idx = next.findIndex((ph) => {
        const attr = ph?.attributes || {};
        return Object.entries(combo.attributes).every(
          ([k, v]) => String(attr[k]) === String(v)
        );
      });

      if (idx >= 0) {
        const imgs = Array.isArray(next[idx].images) ? [...next[idx].images] : [];
        imgs.push(url);
        next[idx] = { ...next[idx], images: imgs };
      } else {
        const newPh = {
          id: "ph_" + Date.now() + "_" + Math.random().toString(36).substring(2, 6),
          attributes: { ...combo.attributes },
          main_url: "",
          front_url: "",
          side_url: "",
          images: [url],
        };
        next.push(newPh);
      }
      onUpdatePhotos(next);
      toast.success("Foto tambahan ditambahkan!");
    });
  };

  // Action: Delete extra photo
  const handleDeleteExtraPhoto = (combo, imgIdx) => {
    const next = [...photos];
    const idx = next.findIndex((ph) => {
      const attr = ph?.attributes || {};
      return Object.entries(combo.attributes).every(
        ([k, v]) => String(attr[k]) === String(v)
      );
    });

    if (idx >= 0) {
      const imgs = (next[idx].images || []).filter((_, i) => i !== imgIdx);
      const target = { ...next[idx], images: imgs };
      const hasContent =
        target.main_url ||
        target.front_url ||
        target.side_url ||
        imgs.length > 0;

      if (!hasContent) {
        next.splice(idx, 1);
      } else {
        next[idx] = target;
      }
      onUpdatePhotos(next);
    }
  };

  // Action: Add new custom showcase design
  const handleCreateCustomDesign = () => {
    const title = newCustomDesign.title.trim();
    if (!title) {
      toast.error("Nama desain wajib diisi");
      return;
    }

    const next = [...photos];
    const newPh = {
      id: "ph_" + Date.now(),
      attributes: {
        desain: title,
        spesifikasi: newCustomDesign.spesifikasi.trim(),
        price: Number(newCustomDesign.price) || 0,
      },
      main_url: "",
      front_url: "",
      side_url: "",
      images: [],
    };
    next.push(newPh);
    onUpdatePhotos(next);

    // If pricing updater available, add to pricing.groups and details
    if (onUpdatePricing && pricing) {
      const pr = { ...pricing };
      if (Array.isArray(pr.groups) && pr.groups.length > 0) {
        const dGroup = pr.groups.find((g) => g.key === "desain");
        if (dGroup && !dGroup.options.includes(title)) {
          dGroup.options = [...dGroup.options, title];
        }
      }
      if (Number(newCustomDesign.price) > 0) {
        pr.base_prices = { ...(pr.base_prices || {}), [title]: Number(newCustomDesign.price) };
      }
      if (newCustomDesign.spesifikasi) {
        pr.design_details = {
          ...(pr.design_details || {}),
          [title]: [newCustomDesign.spesifikasi.trim()],
        };
      }
      onUpdatePricing(pr);
    }

    setNewCustomDesign({ title: "", spesifikasi: "", price: "" });
    setShowAddCustomModal(false);
    toast.success("Desain custom baru berhasil ditambahkan! Silakan unggah foto di kartunya.");
  };

  return (
    <div className="space-y-4">
      {/* Header & Progress Stats */}
      <div className="rounded-2xl border border-[#E5DCC5] bg-gradient-to-br from-[#FAF8F5] to-white p-4 shadow-xs">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
          <div>
            <div className="flex items-center gap-2">
              <Layers size={18} className="text-[#8B5A2B]" />
              <h2 className="font-heading text-base font-bold text-[#2C1E16]">
                Foto Produk per Pilihan Varian
              </h2>
            </div>
            <p className="mt-1 text-xs text-[#8B7355]">
              Atur dan unggah foto langsung pada tiap kombinasi pilihan yang telah ditetapkan.
              Varian tanpa foto otomatis menampilkan foto Price List resmi.
            </p>
          </div>

          {category === "custom" && (
            <Button
              onClick={() => setShowAddCustomModal(true)}
              className="rounded-xl bg-[#8B5A2B] text-xs font-semibold hover:bg-[#6B4423]"
            >
              <Plus size={14} className="mr-1.5" /> Tambah Desain Custom
            </Button>
          )}
        </div>

        {/* Progress bar */}
        {combinations.length > 0 && (
          <div className="mt-3.5 pt-3 border-t border-[#F1EBE0]">
            <div className="flex items-center justify-between text-xs mb-1.5">
              <span className="font-medium text-[#2C1E16]">
                Kesiapan Foto:{" "}
                <strong className="text-[#8B5A2B]">
                  {stats.filled} dari {stats.total} varian
                </strong>{" "}
                terisi foto asli ({stats.percentage}%)
              </span>
              <span className="text-[11px] text-[#8B7355]">
                {stats.total - stats.filled} varian pakai Price List
              </span>
            </div>
            <div className="h-2 w-full overflow-hidden rounded-full bg-[#EFE9DF]">
              <div
                className="h-full bg-gradient-to-r from-[#8B5A2B] to-[#B37B47] transition-all duration-300 rounded-full"
                style={{ width: `${stats.percentage}%` }}
              />
            </div>
          </div>
        )}
      </div>

      {/* Filter & Search Toolbar */}
      <div className="rounded-2xl border border-[#E5DCC5] bg-white p-3.5 space-y-3 shadow-xs">
        <div className="flex flex-col sm:flex-row gap-2">
          {/* Search input */}
          <div className="relative flex-1">
            <Search
              size={15}
              className="absolute left-3 top-1/2 -translate-y-1/2 text-[#8B7355]"
            />
            <Input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Cari varian... (misal: 60, 4 tingkat, tipe a, gantung)"
              className="pl-9 h-9 text-xs bg-[#FAF8F5] border-[#E5DCC5] rounded-xl"
            />
          </div>

          {/* Status Tabs */}
          <div className="inline-flex rounded-xl border border-[#E5DCC5] bg-[#FAF8F5] p-0.5 text-xs">
            <button
              type="button"
              onClick={() => setStatusFilter("all")}
              className={`rounded-lg px-2.5 py-1 text-xs font-medium transition-colors ${
                statusFilter === "all"
                  ? "bg-white text-[#2C1E16] shadow-xs"
                  : "text-[#8B7355] hover:text-[#2C1E16]"
              }`}
            >
              Semua ({combinations.length})
            </button>
            <button
              type="button"
              onClick={() => setStatusFilter("has_photo")}
              className={`rounded-lg px-2.5 py-1 text-xs font-medium transition-colors ${
                statusFilter === "has_photo"
                  ? "bg-white text-green-700 shadow-xs"
                  : "text-[#8B7355] hover:text-green-700"
              }`}
            >
              ✓ Ada Foto ({stats.filled})
            </button>
            <button
              type="button"
              onClick={() => setStatusFilter("no_photo")}
              className={`rounded-lg px-2.5 py-1 text-xs font-medium transition-colors ${
                statusFilter === "no_photo"
                  ? "bg-white text-amber-700 shadow-xs"
                  : "text-[#8B7355] hover:text-amber-700"
              }`}
            >
              ⏳ Belum ({stats.total - stats.filled})
            </button>
          </div>
        </div>

        {/* Dynamic Attribute Filters */}
        {filterKeys.length > 0 && (
          <div className="flex flex-wrap items-center gap-2 pt-1 border-t border-[#F1EBE0]">
            <span className="text-[11px] font-medium text-[#8B7355] mr-1">Filter:</span>
            {filterKeys.map((fk) => (
              <div key={fk.key} className="flex items-center gap-1">
                <Select
                  value={filterValues[fk.key] || "all"}
                  onValueChange={(val) =>
                    setFilterValues((prev) => ({ ...prev, [fk.key]: val }))
                  }
                >
                  <SelectTrigger className="h-8 w-auto min-w-[110px] text-xs bg-[#FAF8F5] border-[#E5DCC5] rounded-lg">
                    <SelectValue placeholder={`Semua ${fk.label}`} />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">Semua {fk.label}</SelectItem>
                    {fk.options.map((opt) => (
                      <SelectItem key={opt} value={opt}>
                        {fk.formatter
                          ? fk.formatter(opt)
                          : `${fk.prefix || ""}${opt}${fk.suffix || ""}`}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            ))}

            {/* Reset Filters button if any active */}
            {(Object.values(filterValues).some((v) => v && v !== "all") || search) && (
              <Button
                variant="ghost"
                onClick={() => {
                  setFilterValues({});
                  setSearch("");
                }}
                className="h-8 text-[11px] text-[#8B5A2B] hover:bg-[#FAF8F5] px-2 rounded-lg"
              >
                Reset Filter
              </Button>
            )}
          </div>
        )}
      </div>

      {/* Modal Tambah Desain Custom */}
      {showAddCustomModal && (
        <div className="rounded-2xl border border-[#8B5A2B]/40 bg-[#FAF5EE] p-4 space-y-3 shadow-sm">
          <div className="flex items-center justify-between">
            <h3 className="font-heading text-sm font-bold text-[#2C1E16] flex items-center gap-1.5">
              <Sparkles size={16} className="text-[#8B5A2B]" /> Tambah Desain Koleksi Custom Baru
            </h3>
            <button
              onClick={() => setShowAddCustomModal(false)}
              className="text-xs text-[#8B7355] hover:text-[#2C1E16]"
            >
              Tutup ✕
            </button>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <Label className="text-xs font-medium mb-1 block">Nama Desain</Label>
              <Input
                value={newCustomDesign.title}
                onChange={(e) =>
                  setNewCustomDesign((prev) => ({ ...prev, title: e.target.value }))
                }
                placeholder="Contoh: Meja Bar Industrial"
                className="bg-white text-xs h-9"
              />
            </div>
            <div>
              <Label className="text-xs font-medium mb-1 block">Estimasi Harga (LE)</Label>
              <Input
                type="number"
                value={newCustomDesign.price}
                onChange={(e) =>
                  setNewCustomDesign((prev) => ({ ...prev, price: e.target.value }))
                }
                placeholder="Contoh: 2400"
                className="bg-white text-xs h-9"
              />
            </div>
            <div className="sm:col-span-2">
              <Label className="text-xs font-medium mb-1 block">
                Keterangan / Spesifikasi
              </Label>
              <Input
                value={newCustomDesign.spesifikasi}
                onChange={(e) =>
                  setNewCustomDesign((prev) => ({ ...prev, spesifikasi: e.target.value }))
                }
                placeholder="Contoh: Ukuran 160x50x105 cm, Kayu Mahoni, Kaki Besi Hollow"
                className="bg-white text-xs h-9"
              />
            </div>
          </div>
          <div className="flex justify-end gap-2 pt-1">
            <Button
              variant="outline"
              size="sm"
              onClick={() => setShowAddCustomModal(false)}
              className="text-xs rounded-xl"
            >
              Batal
            </Button>
            <Button
              size="sm"
              onClick={handleCreateCustomDesign}
              className="bg-[#8B5A2B] hover:bg-[#6B4423] text-xs font-semibold rounded-xl"
            >
              Tambahkan Desain
            </Button>
          </div>
        </div>
      )}

      {/* Combinations Grid / List */}
      <div className="space-y-3">
        {filteredCombinations.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-[#E5DCC5] bg-[#FAF8F5] p-8 text-center">
            <Layers size={24} className="mx-auto text-[#8B7355] opacity-50 mb-2" />
            <p className="text-sm font-medium text-[#2C1E16]">
              {combinations.length === 0
                ? "Belum ada matriks varian yang ditetapkan untuk produk ini."
                : "Tidak ada varian yang cocok dengan filter"}
            </p>
            <p className="text-xs text-[#8B7355] mt-1">
              {combinations.length === 0
                ? "Anda dapat menambahkan foto secara mandiri pada bagian di bawah."
                : "Coba ubah kata kunci pencarian atau reset filter."}
            </p>
            {combinations.length === 0 && (
              <Button
                variant="outline"
                onClick={() => {
                  const newPh = {
                    id: "ph_" + Date.now(),
                    attributes: {},
                    main_url: "",
                    front_url: "",
                    side_url: "",
                    images: [],
                  };
                  onUpdatePhotos([...photos, newPh]);
                  setShowUnmapped(true);
                }}
                className="mt-3 rounded-xl border-[#8B5A2B] text-xs text-[#8B5A2B]"
              >
                <Plus size={14} className="mr-1" /> Tambah Foto Bebas
              </Button>
            )}
          </div>
        ) : (
          filteredCombinations.map((combo) => {
            const ph = findPhotoForCombo(photos, combo.attributes);
            const hasPhoto = hasAnyPhoto(ph);

            return (
              <div
                key={combo.id}
                className={`rounded-2xl border p-4 transition-all duration-200 ${
                  hasPhoto
                    ? "border-[#D6E6D5] bg-white shadow-xs"
                    : "border-[#EFE5D5] bg-[#FAF8F5]"
                }`}
                data-testid={`variant-card-${combo.id}`}
              >
                {/* Card Header */}
                <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2 pb-3 border-b border-[#F1EBE0]">
                  <div className="space-y-0.5">
                    <div className="flex items-center gap-2">
                      <h3 className="font-heading text-sm sm:text-base font-bold text-[#2C1E16]">
                        {combo.title}
                      </h3>
                      {hasPhoto ? (
                        <Badge
                          variant="outline"
                          className="border-green-300 bg-green-50 px-2 py-0.5 text-[10px] font-semibold text-green-700"
                        >
                          <CheckCircle2 size={11} className="mr-1" />
                          Foto Terpasang
                        </Badge>
                      ) : (
                        <Badge
                          variant="outline"
                          className="border-amber-300 bg-amber-50 px-2 py-0.5 text-[10px] font-medium text-amber-800"
                        >
                          <Clock size={11} className="mr-1" />
                          Menampilkan Price List
                        </Badge>
                      )}
                    </div>

                    {combo.subtitle && (
                      <p className="text-xs text-[#5C4A3D] line-clamp-1">{combo.subtitle}</p>
                    )}
                  </div>

                  {/* Fallback preview indicator if no photo */}
                  {!hasPhoto && priceListFallback && (
                    <div className="flex items-center gap-1.5 self-start sm:self-auto rounded-lg bg-white border border-[#E5DCC5] px-2 py-1 text-[11px] text-[#8B7355]">
                      <div className="h-5 w-5 overflow-hidden rounded border border-[#E5DCC5]">
                        <img
                          src={imgUrl(priceListFallback)}
                          alt="Price List"
                          className="h-full w-full object-cover"
                        />
                      </div>
                      <span>Pakai Price List Resmi</span>
                    </div>
                  )}
                </div>

                {/* 3 Main Photo Slots */}
                <div className="mt-3 grid grid-cols-1 sm:grid-cols-3 gap-3">
                  {[
                    { slot: "main_url", label: "Foto 1 (Utama)", testId: "main" },
                    { slot: "front_url", label: "Foto 2 (Tampak Depan)", testId: "front" },
                    { slot: "side_url", label: "Foto 3 (Tampak Samping)", testId: "side" },
                  ].map(({ slot, label }, slotIdx) => {
                    const url = ph ? ph[slot] : "";
                    const inputKey = `${combo.id}_${slot}`;

                    return (
                      <div
                        key={slot}
                        className="flex flex-col rounded-xl border border-[#E5DCC5] bg-white p-2.5 shadow-2xs"
                      >
                        <div className="flex items-center justify-between mb-1.5">
                          <span className="text-[11px] font-semibold text-[#2C1E16]">
                            {label}
                          </span>
                          {url && (
                            <div className="flex items-center gap-0.5">
                              <button
                                type="button"
                                title="Geser ke kiri"
                                disabled={slotIdx === 0}
                                onClick={() => handleMoveSlot(combo, slotIdx, -1)}
                                className="rounded p-0.5 text-[#8B7355] hover:text-[#2C1E16] disabled:opacity-30"
                              >
                                <ArrowLeft size={12} />
                              </button>
                              <button
                                type="button"
                                title="Geser ke kanan"
                                disabled={slotIdx === 2}
                                onClick={() => handleMoveSlot(combo, slotIdx, 1)}
                                className="rounded p-0.5 text-[#8B7355] hover:text-[#2C1E16] disabled:opacity-30"
                              >
                                <ArrowRight size={12} />
                              </button>
                              <button
                                type="button"
                                title="Hapus foto slot ini"
                                onClick={() => handleDeleteSlot(combo, slot)}
                                className="rounded p-0.5 text-red-500 hover:text-red-700 ml-0.5"
                              >
                                <Trash2 size={12} />
                              </button>
                            </div>
                          )}
                        </div>

                        {/* Image preview or placeholder */}
                        <div className="relative aspect-4/3 overflow-hidden rounded-lg border border-[#F1EBE0] bg-[#FAF8F5] flex items-center justify-center">
                          {url ? (
                            <img
                              src={imgUrl(url)}
                              alt=""
                              className="h-full w-full object-cover"
                            />
                          ) : (
                            <div className="flex flex-col items-center justify-center p-2 text-center text-[#8B7355]">
                              <ImageIcon size={20} className="opacity-40 mb-1" />
                              <span className="text-[10px] leading-tight">
                                {slotIdx === 0 ? "Foto Belum Ada" : "Opsional"}
                              </span>
                              {slotIdx === 0 && priceListFallback && (
                                <span className="text-[9px] text-[#A89887] mt-0.5">
                                  (Fallback: Price List)
                                </span>
                              )}
                            </div>
                          )}
                        </div>

                        {/* Hidden file input */}
                        <input
                          type="file"
                          accept="image/*"
                          hidden
                          ref={(el) => (fileInputs.current[inputKey] = el)}
                          onChange={(e) => {
                            if (e.target.files && e.target.files[0]) {
                              handleUploadSlot(combo, slot, e.target.files[0]);
                              e.target.value = "";
                            }
                          }}
                        />

                        {/* Upload / Replace button */}
                        <button
                          type="button"
                          onClick={() => fileInputs.current[inputKey]?.click()}
                          className={`mt-2 flex items-center justify-center gap-1 rounded-lg py-1.5 text-xs font-medium transition-colors ${
                            url
                              ? "border border-[#E5DCC5] bg-[#FAF8F5] text-[#8B5A2B] hover:bg-[#F0EAE1]"
                              : "border border-dashed border-[#8B5A2B] bg-white text-[#8B5A2B] hover:bg-[#FAF5EE]"
                          }`}
                        >
                          <Upload size={12} />
                          {url ? "Ganti Foto" : "Unggah Foto"}
                        </button>
                      </div>
                    );
                  })}
                </div>

                {/* Extra Photos row */}
                <div className="mt-3 pt-2.5 border-t border-[#F1EBE0]">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-[11px] font-semibold text-[#8B7355]">
                      Foto Tambahan ({ph?.images?.length || 0})
                    </span>
                    <button
                      type="button"
                      onClick={() => fileInputs.current[`${combo.id}_add`]?.click()}
                      className="inline-flex items-center gap-1 text-[11px] font-medium text-[#8B5A2B] hover:underline"
                    >
                      <Plus size={12} /> Tambah Foto Tambahan
                    </button>
                  </div>

                  <input
                    type="file"
                    accept="image/*"
                    hidden
                    ref={(el) => (fileInputs.current[`${combo.id}_add`] = el)}
                    onChange={(e) => {
                      if (e.target.files && e.target.files[0]) {
                        handleAddExtraPhoto(combo, e.target.files[0]);
                        e.target.value = "";
                      }
                    }}
                  />

                  <div className="flex flex-wrap items-center gap-2">
                    {(ph?.images || []).map((img, imgIdx) => (
                      <div key={imgIdx} className="relative group">
                        <div className="h-14 w-14 overflow-hidden rounded-lg border border-[#E5DCC5] bg-white shadow-2xs">
                          <img
                            src={imgUrl(img)}
                            alt=""
                            className="h-full w-full object-cover"
                          />
                        </div>
                        <button
                          type="button"
                          onClick={() => handleDeleteExtraPhoto(combo, imgIdx)}
                          className="absolute -top-1.5 -right-1.5 flex h-4 w-4 items-center justify-center rounded-full bg-red-500 text-white text-[10px] shadow hover:bg-red-600"
                        >
                          ×
                        </button>
                      </div>
                    ))}

                    <button
                      type="button"
                      onClick={() => fileInputs.current[`${combo.id}_add`]?.click()}
                      className="flex h-14 w-14 items-center justify-center rounded-lg border-2 border-dashed border-[#E5DCC5] text-[#8B7355] hover:border-[#8B5A2B] hover:text-[#8B5A2B] transition-colors"
                      title="Tambah foto tambahan"
                    >
                      <Plus size={16} />
                    </button>
                  </div>
                </div>
              </div>
            );
          })
        )}
      </div>

      {/* Collapsible Section for Unmapped / Custom Legacy Photos */}
      {unmappedPhotos.length > 0 && (
        <div className="rounded-2xl border border-[#E5DCC5] bg-white p-4 shadow-xs mt-4">
          <button
            type="button"
            onClick={() => setShowUnmapped(!showUnmapped)}
            className="flex w-full items-center justify-between text-left"
          >
            <div>
              <h3 className="font-heading text-sm font-bold text-[#2C1E16]">
                Foto Kustom / Di Luar Varian Standar ({unmappedPhotos.length})
              </h3>
              <p className="text-xs text-[#8B7355] mt-0.5">
                Foto-foto ini tersimpan tetapi memiliki kombinasi atribut khusus atau berbeda dari varian standar.
              </p>
            </div>
            {showUnmapped ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
          </button>

          {showUnmapped && (
            <div className="mt-3 pt-3 border-t border-[#F1EBE0] space-y-3">
              {unmappedPhotos.map((ph, uIdx) => (
                <div
                  key={ph.id || uIdx}
                  className="rounded-xl border border-[#E5DCC5] bg-[#FAF8F5] p-3 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3"
                >
                  <div className="flex items-center gap-3">
                    <div className="h-16 w-16 overflow-hidden rounded-lg border border-[#E5DCC5] bg-white shrink-0">
                      {ph.main_url || ph.front_url || ph.side_url ? (
                        <img
                          src={imgUrl(ph.main_url || ph.front_url || ph.side_url)}
                          alt=""
                          className="h-full w-full object-cover"
                        />
                      ) : (
                        <div className="flex h-full items-center justify-center text-[10px] text-[#8B7355]">
                          Kosong
                        </div>
                      )}
                    </div>
                    <div>
                      <div className="flex flex-wrap gap-1">
                        {Object.entries(ph.attributes || {}).map(([k, v]) => (
                          <Badge
                            key={k}
                            variant="outline"
                            className="text-[10px] border-[#E5DCC5] bg-white text-[#5C4A3D]"
                          >
                            {k}: {String(v)}
                          </Badge>
                        ))}
                      </div>
                      <p className="text-[11px] text-[#8B7355] mt-1">
                        ID: {ph.id} • {ph.images?.length || 0} foto tambahan
                      </p>
                    </div>
                  </div>

                  <div className="flex items-center gap-2">
                    <input
                      type="file"
                      accept="image/*"
                      hidden
                      ref={(el) => (fileInputs.current[`unmapped_${ph.id}`] = el)}
                      onChange={(e) => {
                        if (e.target.files && e.target.files[0]) {
                          uploadTo(e.target.files[0], (url) => {
                            const next = photos.map((x) =>
                              x.id === ph.id ? { ...x, main_url: url } : x
                            );
                            onUpdatePhotos(next);
                            toast.success("Foto kustom diperbarui!");
                          });
                          e.target.value = "";
                        }
                      }}
                    />
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => fileInputs.current[`unmapped_${ph.id}`]?.click()}
                      className="border-[#8B5A2B] text-[#8B5A2B] text-xs rounded-xl"
                    >
                      <Upload size={13} className="mr-1" /> Unggah Foto
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => {
                        const next = photos.filter((x) => x.id !== ph.id);
                        onUpdatePhotos(next);
                        toast.success("Foto kustom dihapus");
                      }}
                      className="border-red-200 text-red-600 hover:bg-red-50 text-xs rounded-xl"
                    >
                      <Trash2 size={13} className="mr-1" /> Hapus
                    </Button>
                  </div>
                </div>
              ))}
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  const newPh = {
                    id: "ph_" + Date.now(),
                    attributes: {},
                    main_url: "",
                    front_url: "",
                    side_url: "",
                    images: [],
                  };
                  onUpdatePhotos([...photos, newPh]);
                }}
                className="w-full border-dashed border-[#8B5A2B] text-[#8B5A2B] text-xs rounded-xl"
              >
                <Plus size={14} className="mr-1" /> Tambah Slot Foto Kustom Bebas
              </Button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
