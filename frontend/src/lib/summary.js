export function config_summary_client(category, cfg = {}) {
  if (cfg._summary) return cfg._summary;
  const parts = [];
  if (category === "rak") {
    if (cfg.length) parts.push(`${cfg.length} cm`);
    if (cfg.level) parts.push(`${cfg.level} Tingkat`);
    if (cfg.type) parts.push(`Tipe ${cfg.type}`);
    if (cfg.finishing) parts.push(cfg.finishing);
  } else if (category === "meja") {
    if (cfg.size) parts.push(`${cfg.size} cm`);
    if (cfg.height) parts.push(`Tinggi ${cfg.height} cm`);
    if (cfg.finishing) parts.push(cfg.finishing);
  } else if (category === "meja_rak") {
    if (cfg.variant) parts.push(cfg.variant);
    if (cfg.type) parts.push(`Tipe ${cfg.type}`);
    if (cfg.finishing) parts.push(cfg.finishing);
  }
  if (cfg.custom_size) parts.push("Ukuran Custom");
  return parts.join(", ");
}
