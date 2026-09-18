import { computeBreakdown } from "./pricing";

/**
 * Helper to build configuration previews from products and their photo variations.
 * Follows AGENTS.md requirements:
 * - Does not invent fake configurations or photos
 * - Preserves existing pricing.js calculation
 * - Identity for Rak: Panjang + Tingkat + Tipe
 */

function getPhotoUrl(photo) {
  if (!photo) return "";
  return photo.main_url || photo.front_url || photo.side_url || (Array.isArray(photo.images) && photo.images[0]) || "";
}

export function buildProductPreviews(product) {
  if (!product) return [];

  const category = product.category;
  const photos = Array.isArray(product.photos) ? product.photos : [];
  const previews = [];

  if (category === "rak") {
    // Unique identity: length + level + type
    const grouped = new Map();

    photos.forEach((ph) => {
      const attr = ph.attributes || {};
      const length = attr.length ? String(attr.length) : null;
      const level = attr.level ? String(attr.level) : null;
      const type = attr.type ? String(attr.type) : null;
      const photoUrl = getPhotoUrl(ph);

      if (!length || !level || !type || !photoUrl) return;

      const key = `${length}_${level}_${type}`;
      if (!grouped.has(key)) {
        grouped.set(key, {
          length,
          level,
          type,
          finishing: attr.finishing || "Natural",
          photos: [ph],
          bestPhoto: ph,
        });
      } else {
        const existing = grouped.get(key);
        existing.photos.push(ph);
        // Prefer Natural finishing or main_url
        if (attr.finishing === "Natural" || (!existing.bestPhoto.main_url && ph.main_url)) {
          existing.bestPhoto = ph;
          existing.finishing = attr.finishing || existing.finishing;
        }
      }
    });

    // If no valid grouped photos, fallback to base product
    if (grouped.size === 0) {
      return [buildFallbackPreview(product)];
    }

    // Convert map to preview cards
    grouped.forEach((item, key) => {
      const config = {
        length: item.length,
        level: item.level,
        type: item.type,
        finishing: item.finishing || "Natural",
        custom_size: false,
      };

      const breakdown = computeBreakdown(product, config, 1);
      const price = breakdown?.unit || product.starting_price_le || 0;
      const imageUrl = getPhotoUrl(item.bestPhoto);

      const searchParams = new URLSearchParams({
        length: item.length,
        level: item.level,
        type: item.type,
        finishing: config.finishing,
      });

      previews.push({
        id: `${product.id || product._id || product.slug}-${key}`,
        productSlug: product.slug,
        productName: product.name,
        category: product.category,
        title: product.name,
        subtitle: `${item.length} cm · ${item.level} Tingkat · Tipe ${item.type}`,
        price,
        image: imageUrl,
        url: `/produk/${product.slug}?${searchParams.toString()}`,
        config,
        sortWeight: Number(item.length) * 100 + Number(item.level) * 10 + (item.type === "B" ? 1 : item.type === "A" ? 2 : item.type === "B+" ? 3 : 4),
      });
    });

    // Sort previews logically: length -> level -> type
    previews.sort((a, b) => (a.sortWeight || 0) - (b.sortWeight || 0));
    return previews;
  }

  if (category === "meja") {
    // Unique identity: size + height
    const grouped = new Map();

    photos.forEach((ph) => {
      const attr = ph.attributes || {};
      const size = attr.size ? String(attr.size) : null;
      const height = attr.height ? String(attr.height) : null;
      const photoUrl = getPhotoUrl(ph);

      if (!size || !height || !photoUrl) return;

      const key = `${size}_${height}`;
      if (!grouped.has(key)) {
        grouped.set(key, {
          size,
          height,
          finishing: attr.finishing || "Natural",
          bestPhoto: ph,
        });
      } else {
        const existing = grouped.get(key);
        if (attr.finishing === "Natural" || (!existing.bestPhoto.main_url && ph.main_url)) {
          existing.bestPhoto = ph;
          existing.finishing = attr.finishing || existing.finishing;
        }
      }
    });

    if (grouped.size === 0) return [buildFallbackPreview(product)];

    grouped.forEach((item, key) => {
      const config = {
        size: item.size,
        height: item.height,
        finishing: item.finishing || "Natural",
        custom_size: false,
      };

      const breakdown = computeBreakdown(product, config, 1);
      const price = breakdown?.unit || product.starting_price_le || 0;
      const imageUrl = getPhotoUrl(item.bestPhoto);

      const searchParams = new URLSearchParams({
        size: item.size,
        height: item.height,
        finishing: config.finishing,
      });

      previews.push({
        id: `${product.id || product._id || product.slug}-${key}`,
        productSlug: product.slug,
        productName: product.name,
        category: product.category,
        title: product.name,
        subtitle: `${item.size} cm · Tinggi ${item.height} cm`,
        price,
        image: imageUrl,
        url: `/produk/${product.slug}?${searchParams.toString()}`,
        config,
      });
    });

    return previews;
  }

  if (category === "meja_rak") {
    // Unique identity: size + levels + height
    const grouped = new Map();

    photos.forEach((ph) => {
      const attr = ph.attributes || {};
      const size = attr.size ? String(attr.size) : null;
      const levels = attr.levels ? String(attr.levels) : null;
      const height = attr.height ? String(attr.height) : null;
      const photoUrl = getPhotoUrl(ph);

      if (!size || !levels || !photoUrl) return;

      const key = `${size}_${levels}_${height || ""}`;
      if (!grouped.has(key)) {
        grouped.set(key, {
          size,
          levels,
          height: height || "30 cm (Lesehan)",
          finishing: attr.finishing || "Natural",
          bestPhoto: ph,
        });
      }
    });

    if (grouped.size === 0) return [buildFallbackPreview(product)];

    grouped.forEach((item, key) => {
      const config = {
        size: item.size,
        levels: item.levels,
        height: item.height,
        finishing: item.finishing || "Natural",
        custom_size: false,
      };

      const breakdown = computeBreakdown(product, config, 1);
      const price = breakdown?.unit || product.starting_price_le || 0;
      const imageUrl = getPhotoUrl(item.bestPhoto);

      const searchParams = new URLSearchParams({
        size: item.size,
        levels: item.levels,
        height: item.height,
        finishing: config.finishing,
      });

      previews.push({
        id: `${product.id || product._id || product.slug}-${key}`,
        productSlug: product.slug,
        productName: product.name,
        category: product.category,
        title: product.name,
        subtitle: `${item.size} · ${item.levels} · ${item.height}`,
        price,
        image: imageUrl,
        url: `/produk/${product.slug}?${searchParams.toString()}`,
        config,
      });
    });

    return previews;
  }

  if (category === "papan_tulis") {
    const grouped = new Map();

    photos.forEach((ph) => {
      const attr = ph.attributes || {};
      const mount = attr.mount ? String(attr.mount) : null;
      const size = attr.size ? String(attr.size) : null;
      const photoUrl = getPhotoUrl(ph);

      if (!mount || !size || !photoUrl) return;

      const key = `${mount}_${size}`;
      if (!grouped.has(key)) {
        grouped.set(key, { mount, size, bestPhoto: ph });
      }
    });

    if (grouped.size === 0) return [buildFallbackPreview(product)];

    grouped.forEach((item, key) => {
      const config = {
        mount: item.mount,
        size: item.size,
        custom_size: false,
      };

      const breakdown = computeBreakdown(product, config, 1);
      const price = breakdown?.unit || product.starting_price_le || 0;
      const imageUrl = getPhotoUrl(item.bestPhoto);

      const searchParams = new URLSearchParams({
        mount: item.mount,
        size: item.size,
      });

      previews.push({
        id: `${product.id || product._id || product.slug}-${key}`,
        productSlug: product.slug,
        productName: product.name,
        category: product.category,
        title: product.name,
        subtitle: `${item.mount} · ${item.size}`,
        price,
        image: imageUrl,
        url: `/produk/${product.slug}?${searchParams.toString()}`,
        config,
      });
    });

    return previews;
  }

  if (category === "blockboard") {
    const grouped = new Map();

    photos.forEach((ph) => {
      const attr = ph.attributes || {};
      const pilihan = attr.pilihan ? String(attr.pilihan) : null;
      const photoUrl = getPhotoUrl(ph);

      if (!pilihan || !photoUrl) return;

      if (!grouped.has(pilihan)) {
        grouped.set(pilihan, { pilihan, bestPhoto: ph });
      }
    });

    if (grouped.size === 0) return [buildFallbackPreview(product)];

    grouped.forEach((item, key) => {
      const config = {
        pilihan: item.pilihan,
        custom_size: false,
      };

      const breakdown = computeBreakdown(product, config, 1);
      const price = breakdown?.unit || product.starting_price_le || 0;
      const imageUrl = getPhotoUrl(item.bestPhoto);

      const searchParams = new URLSearchParams({
        pilihan: item.pilihan,
      });

      previews.push({
        id: `${product.id || product._id || product.slug}-${key}`,
        productSlug: product.slug,
        productName: product.name,
        category: product.category,
        title: product.name,
        subtitle: item.pilihan,
        price,
        image: imageUrl,
        url: `/produk/${product.slug}?${searchParams.toString()}`,
        config,
      });
    });

    return previews;
  }

  if (category === "custom") {
    const grouped = new Map();

    photos.forEach((ph) => {
      const attr = ph.attributes || {};
      const desain = attr.desain ? String(attr.desain) : null;
      const photoUrl = getPhotoUrl(ph);

      if (!desain || !photoUrl) return;

      if (!grouped.has(desain)) {
        grouped.set(desain, { desain, bestPhoto: ph });
      }
    });

    if (grouped.size === 0) return [buildFallbackPreview(product)];

    grouped.forEach((item, key) => {
      const config = {
        desain: item.desain,
        custom_size: false,
      };

      const breakdown = computeBreakdown(product, config, 1);
      const price = breakdown?.unit || product.starting_price_le || 0;
      const imageUrl = getPhotoUrl(item.bestPhoto);

      const searchParams = new URLSearchParams({
        desain: item.desain,
      });

      previews.push({
        id: `${product.id || product._id || product.slug}-${key}`,
        productSlug: product.slug,
        productName: product.name,
        category: product.category,
        title: product.name,
        subtitle: item.desain,
        price,
        image: imageUrl,
        url: `/produk/${product.slug}?${searchParams.toString()}`,
        config,
      });
    });

    return previews;
  }

  return [buildFallbackPreview(product)];
}

function buildFallbackPreview(product) {
  const photo = Array.isArray(product.photos) && product.photos[0];
  const imageUrl = product.display_image || product.image_url || getPhotoUrl(photo);

  return {
    id: `${product.id || product._id || product.slug}-main`,
    productSlug: product.slug,
    productName: product.name,
    category: product.category,
    title: product.name,
    subtitle: product.description || "",
    price: product.starting_price_le || 0,
    image: imageUrl,
    url: `/produk/${product.slug}`,
    config: {},
    isFallback: true,
  };
}

/**
 * Takes an array of products in a category and returns all configuration previews.
 */
export function buildCategoryPreviews(products = []) {
  const allPreviews = [];
  products.forEach((product) => {
    if (product?.active !== false) {
      const previews = buildProductPreviews(product);
      allPreviews.push(...previews);
    }
  });
  return allPreviews;
}
