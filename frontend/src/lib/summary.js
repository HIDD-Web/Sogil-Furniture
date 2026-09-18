const FALLBACK_TRANSLATIONS = {
  "cfg.tingkat": "Tingkat",
  "cfg.tipe": "Tipe",
  "cfg.tinggi": "Tinggi",
  "cfg.ukuran_custom": "Ukuran Custom",
};

export function config_summary_client(category, cfg = {}, t) {
  if (!cfg) return "";
  if (cfg._summary) return cfg._summary;

  const tr = typeof t === "function" ? t : (k) => FALLBACK_TRANSLATIONS[k] || k;
  const parts = [];

  if (category === "rak") {
    if (cfg.length) parts.push(`${cfg.length} cm`);
    if (cfg.level) parts.push(`${cfg.level} ${tr("cfg.tingkat")}`);
    if (cfg.type) parts.push(`${tr("cfg.tipe")} ${cfg.type}`);
    if (cfg.finishing) parts.push(cfg.finishing);
  } else if (category === "meja") {
    if (cfg.size) parts.push(`${cfg.size} cm`);
    if (cfg.height) parts.push(`${tr("cfg.tinggi")} ${cfg.height} cm`);
    if (cfg.finishing) parts.push(cfg.finishing);
  } else if (category === "meja_rak") {
    if (cfg.variant) parts.push(cfg.variant);
    if (cfg.type) parts.push(`${tr("cfg.tipe")} ${cfg.type}`);
    if (cfg.finishing) parts.push(cfg.finishing);
  } else if (category === "custom") {
    if (cfg.desain) parts.push(cfg.desain);
    if (cfg.furniture_type) parts.push(cfg.furniture_type);
    if (cfg.dimensions) {
      const d = cfg.dimensions;
      const dims = [d.length && `P: ${d.length} cm`, d.width && `L: ${d.width} cm`, d.height && `T: ${d.height} cm`].filter(Boolean);
      if (dims.length) parts.push(dims.join(" × "));
    }
    if (cfg.material) parts.push(cfg.material);
  }

  if (cfg.custom_size && !parts.includes(tr("cfg.ukuran_custom"))) {
    parts.push(tr("cfg.ukuran_custom"));
  }
  if (cfg.custom_note) {
    parts.push(cfg.custom_note);
  }

  return parts.join(", ");
}