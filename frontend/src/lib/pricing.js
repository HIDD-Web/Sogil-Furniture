// Client mirror of backend compute_item_price. Server remains authoritative.
const num = (v) => {
  const n = Number(v);
  return isNaN(n) ? 0 : n;
};

export function computeBreakdown(product, config, quantity) {
  const pricing = product?.pricing || {};
  const category = product?.category;
  const qty = Math.max(1, parseInt(quantity || 1, 10));
  const bd = {
    base: 0, adjustments: 0, finishing: 0, unit: 0, subtotal: 0,
    lines: [], requiresConfirm: false,
  };

  if (config?.custom_size) {
    bd.requiresConfirm = true;
    bd.lines.push({ label: "Ukuran Custom", value: 0, note: "Akan dikonfirmasi admin" });
    return bd;
  }

  if (category === "rak") {
    const { length, level, type = "B", finishing = "Natural" } = config;
    const base = num((pricing.base_prices || {})[`${length}_${level}`]);
    bd.base = base;
    if (length && level) bd.lines.push({ label: `Harga dasar (${length} cm, ${level} tingkat)`, value: base });
    const typeAdj = num(((pricing.type_adjustments || {})[type] || {})[length]);
    if (typeAdj) { bd.adjustments += typeAdj; bd.lines.push({ label: `Tipe ${type}`, value: typeAdj }); }
    const fin = (pricing.finishing || {})[finishing];
    let finCost = 0;
    if (fin && typeof fin === "object") finCost = num(fin[length]) * num(level);
    else finCost = num(fin);
    if (finCost) { bd.finishing = finCost; bd.lines.push({ label: `Finishing ${finishing}`, value: finCost }); }
  } else if (category === "meja") {
    const { size, height, finishing = "Natural" } = config;
    const base = num((pricing.base_prices || {})[`${size}_${height}`]);
    bd.base = base;
    if (size && height) bd.lines.push({ label: `Harga dasar (${size} cm, tinggi ${height} cm)`, value: base });
    const fin = (pricing.finishing || {})[finishing];
    const finCost = typeof fin === "object" ? 0 : num(fin);
    if (finCost) { bd.finishing = finCost; bd.lines.push({ label: `Finishing ${finishing}`, value: finCost }); }
  } else if (category === "meja_rak") {
    const { variant, type = "B", finishing = "Natural" } = config;
    const base = num((pricing.base_prices || {})[variant]);
    bd.base = base;
    if (variant) bd.lines.push({ label: `Harga dasar (${variant})`, value: base });
    const typeAdj = num(((pricing.type_adjustments || {})[type] || {})[variant]);
    if (typeAdj) { bd.adjustments += typeAdj; bd.lines.push({ label: `Tipe ${type}`, value: typeAdj }); }
    const fin = (pricing.finishing || {})[finishing];
    const finCost = typeof fin === "object" ? 0 : num(fin);
    if (finCost) { bd.finishing = finCost; bd.lines.push({ label: `Finishing ${finishing}`, value: finCost }); }
  } else {
    bd.requiresConfirm = true;
  }

  bd.unit = bd.base + bd.adjustments + bd.finishing;
  bd.subtotal = bd.unit * qty;
  return bd;
}
