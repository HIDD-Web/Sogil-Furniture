// Client mirror of backend weighted photo matching.
const DEFAULT_WEIGHTS = {
  rak: { length: 0.45, level: 0.35, type: 0.1, finishing: 0.1 },
  meja: { size: 0.5, height: 0.3, finishing: 0.2 },
  meja_rak: { variant: 0.6, type: 0.2, finishing: 0.2 },
};
const SCALE = { length: 60, level: 5, height: 45 };

function numSim(a, b, scale) {
  const na = Number(a), nb = Number(b);
  if (isNaN(na) || isNaN(nb)) return String(a) === String(b) ? 1 : 0;
  return Math.max(0, 1 - Math.abs(na - nb) / scale);
}

export function matchPhoto(product, config) {
  const photos = product?.photos || [];
  if (!photos.length) return { photo: null, exact: false };
  const category = product.category;
  const weights = (product.photo_weights && Object.keys(product.photo_weights).length ? product.photo_weights : DEFAULT_WEIGHTS[category]) || {};
  const keys = Object.keys(weights);
  let best = null, bestScore = -1, bestExact = false;
  for (const ph of photos) {
    const attr = ph.attributes || {};
    let score = 0;
    for (const k of keys) {
      const rv = config[k], av = attr[k];
      if (rv == null || rv === "" || av == null || av === "") continue;
      if (SCALE[k]) score += weights[k] * numSim(rv, av, SCALE[k]);
      else score += weights[k] * (String(rv) === String(av) ? 1 : 0);
    }
    const exact = keys.every((k) => attr[k] == null || attr[k] === "" || String(config[k]) === String(attr[k]));
    if (exact) score += 100;
    if (score > bestScore) { best = ph; bestScore = score; bestExact = exact; }
  }
  return { photo: best, exact: bestExact };
}

export function normalizePhone(raw) {
  return (raw || "").replace(/[\s\-().]/g, "");
}
export function validIntlPhone(s) {
  return /^\+\d{8,15}$/.test(s);
}
