import { computeBreakdown } from "./pricing";
import { CATEGORY_PRICELISTS } from "./constants";

/**
 * Helper to build configuration previews from products and their photo variations.
 * Follows requirements:
 * - Generates full variant matrix for catalog categories (Rak, Meja, Meja Rak, Papan Tulis, BlackBoard)
 * - If physical photo is uploaded for the variant, displays physical photo
 * - If physical photo is not yet uploaded, displays official Price List photo
 * - Exact price calculated via pricing engine (computeBreakdown)
 * - Rak identity: Panjang + Tingkat + Tipe
 */

function getPhotoUrl(photo) {
  if (!photo) return "";
  return photo.main_url || photo.front_url || photo.side_url || (Array.isArray(photo.images) && photo.images[0]) || "";
}

function cartesianGroups(groups) {
  if (!groups || groups.length === 0) return [{}];
  return groups.reduce(
    (acc, group) => {
      const opts = group.options || [];
      if (opts.length === 0) return acc;
      const res = [];
      acc.forEach((combo) => {
        opts.forEach((opt) => {
          res.push({ ...combo, [group.key]: opt });
        });
      });
      return res;
    },
    [{}]
  );
}

export function buildProductPreviews(product) {
  if (!product) return [];

  const category = product.category;
  const photos = Array.isArray(product.photos) ? product.photos : [];
  const pricing = product.pricing || {};
  const priceListFallback = CATEGORY_PRICELISTS[category] || product.display_image || "";
  const previews = [];

  // 1. If product uses dynamic additive groups (e.g. Papan Tulis / BlackBoard when grouped)
  if (category !== "custom" && category !== "meja" && category !== "meja_rak" && Array.isArray(pricing.groups) && pricing.groups.length > 0) {
    const combos = cartesianGroups(pricing.groups);
    combos.forEach((cfg, idx) => {
      // Find matching photo
      const matchedPhoto = photos.find((ph) => {
        const attr = ph.attributes || {};
        return pricing.groups.every((g) => !cfg[g.key] || !attr[g.key] || String(attr[g.key]) === String(cfg[g.key]));
      });

      const imageUrl = matchedPhoto ? getPhotoUrl(matchedPhoto) : priceListFallback;
      const config = { ...cfg, custom_size: false };
      const breakdown = computeBreakdown(product, config, 1);
      const price = breakdown?.unit || product.starting_price_le || 0;

      const searchParams = new URLSearchParams();
      Object.entries(cfg).forEach(([k, v]) => {
        if (v) searchParams.set(k, v);
      });

      const subtitle = Object.values(cfg).join(" · ");

      previews.push({
        id: `${product.id || product._id || product.slug}-${idx}`,
        productSlug: product.slug,
        productName: product.name,
        category: product.category,
        title: product.name,
        subtitle,
        price,
        image: imageUrl,
        url: `/produk/${product.slug}?${searchParams.toString()}`,
        config,
      });
    });
    return previews;
  }

  // 2. Rak Kayu: Panjang (60, 80, 120) × Tingkat (2..7) × Tipe (B, A) = 36 variants
  if (category === "rak") {
    const lengths = pricing.lengths || ["60", "80", "120"];
    const levels = pricing.levels || ["2", "3", "4", "5", "6", "7"];
    const types = (pricing.types || ["B", "A"]).filter((t) => t === "B" || t === "A");

    lengths.forEach((length) => {
      levels.forEach((level) => {
        types.forEach((type) => {
          // Look up matching photo in product.photos
          const matchedPhoto = photos.find((ph) => {
            const attr = ph.attributes || {};
            return (
              String(attr.length) === String(length) &&
              String(attr.level) === String(level) &&
              String(attr.type) === String(type) &&
              Boolean(getPhotoUrl(ph))
            );
          });

          const imageUrl = matchedPhoto ? getPhotoUrl(matchedPhoto) : (CATEGORY_PRICELISTS.rak || priceListFallback);

          const config = {
            length: String(length),
            level: String(level),
            type: String(type),
            finishing: "Natural",
            custom_size: false,
          };

          const breakdown = computeBreakdown(product, config, 1);
          const price = breakdown?.unit || product.starting_price_le || 0;

          const searchParams = new URLSearchParams({
            length: String(length),
            level: String(level),
            type: String(type),
            finishing: "Natural",
          });

          previews.push({
            id: `${product.id || product._id || product.slug}-${length}_${level}_${type}`,
            productSlug: product.slug,
            productName: product.name,
            category: product.category,
            title: product.name,
            subtitle: `${length} cm · ${level} Tingkat · Tipe ${type}`,
            price,
            image: imageUrl,
            url: `/produk/${product.slug}?${searchParams.toString()}`,
            config,
            sortWeight:
              Number(length) * 100 +
              Number(level) * 10 +
              (type === "B" ? 1 : 2),
          });
        });
      });
    });

    previews.sort((a, b) => (a.sortWeight || 0) - (b.sortWeight || 0));
    return previews;
  }

  // 3. Meja: Standar (Ukuran × Tinggi) + Khusus Finishing Lapis HPL (Ukuran × Tinggi × Lapis HPL)
  if (category === "meja") {
    const sizes = pricing.sizes || ["40x80", "50x80"];
    const heights = pricing.heights || ["30", "75"];

    // 3a. Standar (Natural)
    sizes.forEach((size) => {
      heights.forEach((height) => {
        const matchedPhoto = photos.find((ph) => {
          const attr = ph.attributes || {};
          const isHpl = attr.finishing === "Lapis HPL" || attr.finishing === "Premium";
          return (
            String(attr.size) === String(size) &&
            String(attr.height) === String(height) &&
            !isHpl &&
            Boolean(getPhotoUrl(ph))
          );
        });

        const imageUrl = matchedPhoto ? getPhotoUrl(matchedPhoto) : (CATEGORY_PRICELISTS.meja || priceListFallback);

        const config = {
          size: String(size),
          height: String(height),
          finishing: "Natural",
          custom_size: false,
        };

        const breakdown = computeBreakdown(product, config, 1);
        const price = breakdown?.unit || product.starting_price_le || 0;

        const searchParams = new URLSearchParams({
          size: String(size),
          height: String(height),
          finishing: "Natural",
        });

        previews.push({
          id: `${product.id || product._id || product.slug}-${size}_${height}`,
          productSlug: product.slug,
          productName: product.name,
          category: product.category,
          title: product.name,
          subtitle: `${size} cm · Tinggi ${height} cm ${height === "30" ? "(Lesehan)" : height === "75" ? "(Kursi)" : ""}`,
          price,
          image: imageUrl,
          url: `/produk/${product.slug}?${searchParams.toString()}`,
          config,
        });
      });
    });

    // 3b. Khusus Finishing Lapis HPL
    sizes.forEach((size) => {
      heights.forEach((height) => {
        const matchedPhoto = photos.find((ph) => {
          const attr = ph.attributes || {};
          const isHpl = attr.finishing === "Lapis HPL" || attr.finishing === "Premium";
          return (
            String(attr.size) === String(size) &&
            String(attr.height) === String(height) &&
            isHpl &&
            Boolean(getPhotoUrl(ph))
          );
        });

        const imageUrl = matchedPhoto ? getPhotoUrl(matchedPhoto) : (CATEGORY_PRICELISTS.meja || priceListFallback);

        const config = {
          size: String(size),
          height: String(height),
          finishing: "Lapis HPL",
          custom_size: false,
        };

        const breakdown = computeBreakdown(product, config, 1);
        const price = breakdown?.unit || product.starting_price_le || 0;

        const searchParams = new URLSearchParams({
          size: String(size),
          height: String(height),
          finishing: "Lapis HPL",
        });

        previews.push({
          id: `${product.id || product._id || product.slug}-${size}_${height}_hpl`,
          productSlug: product.slug,
          productName: product.name,
          category: product.category,
          title: product.name,
          subtitle: `${size} cm · Tinggi ${height} cm ${height === "30" ? "(Lesehan)" : height === "75" ? "(Kursi)" : ""} · Lapis HPL`,
          price,
          image: imageUrl,
          url: `/produk/${product.slug}?${searchParams.toString()}`,
          config,
        });
      });
    });

    return previews;
  }

  // 4. Meja Rak: Ukuran Meja × Jumlah Tingkat Rak × Tinggi Meja (tanpa finishing)
  if (category === "meja_rak") {
    const sizeOpts = pricing.groups?.find((g) => g.key === "size")?.options || ["Meja 40x80 cm", "Meja 50x80 cm"];
    const levelOpts = pricing.groups?.find((g) => g.key === "levels")?.options || ["2 Tingkat", "3 Tingkat", "4 Tingkat", "5 Tingkat"];
    const heightOpts = pricing.groups?.find((g) => g.key === "height")?.options || ["30 cm (Lesehan)", "75 cm (Kursi)"];

    sizeOpts.forEach((sz) => {
      levelOpts.forEach((lvl) => {
        heightOpts.forEach((h) => {
          const matchedPhoto = photos.find((ph) => {
            const attr = ph.attributes || {};
            return (
              String(attr.size) === String(sz) &&
              String(attr.levels) === String(lvl) &&
              String(attr.height) === String(h) &&
              Boolean(getPhotoUrl(ph))
            );
          });

          const imageUrl = matchedPhoto ? getPhotoUrl(matchedPhoto) : (CATEGORY_PRICELISTS.meja_rak || priceListFallback);

          const config = {
            size: String(sz),
            levels: String(lvl),
            height: String(h),
            finishing: "Natural",
            custom_size: false,
          };

          const breakdown = computeBreakdown(product, config, 1);
          const price = breakdown?.unit || product.starting_price_le || 0;

          const searchParams = new URLSearchParams({
            size: String(sz),
            levels: String(lvl),
            height: String(h),
            finishing: "Natural",
          });

          previews.push({
            id: `${product.id || product._id || product.slug}-${sz}_${lvl}_${h}`,
            productSlug: product.slug,
            productName: product.name,
            category: product.category,
            title: product.name,
            subtitle: `${sz} · ${lvl} · ${h}`,
            price,
            image: imageUrl,
            url: `/produk/${product.slug}?${searchParams.toString()}`,
            config,
          });
        });
      });
    });

    return previews;
  }

  // 5. Papan Tulis: Mount × Size
  if (category === "papan_tulis") {
    const mounts = ["Gantung", "+ Kaki 150 cm"];
    const sizes = [
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

    mounts.forEach((mount) => {
      sizes.forEach((size) => {
        // Small sizes are Gantung only — skip Kaki
        if (mount === "+ Kaki 150 cm" && (size === "30x50 cm" || size === "40x60 cm" || size === "50x70 cm")) {
          return;
        }
        const matchedPhoto = photos.find((ph) => {
          const attr = ph.attributes || {};
          return (
            String(attr.mount) === String(mount) &&
            String(attr.size) === String(size) &&
            Boolean(getPhotoUrl(ph))
          );
        });

        const imageUrl = matchedPhoto ? getPhotoUrl(matchedPhoto) : (CATEGORY_PRICELISTS.papan_tulis || priceListFallback);

        const config = {
          mount: String(mount),
          size: String(size),
          custom_size: false,
        };

        const breakdown = computeBreakdown(product, config, 1);
        const price = breakdown?.unit || product.starting_price_le || 0;

        const searchParams = new URLSearchParams({
          mount: String(mount),
          size: String(size),
        });

        previews.push({
          id: `${product.id || product._id || product.slug}-${mount}_${size}`,
          productSlug: product.slug,
          productName: product.name,
          category: product.category,
          title: product.name,
          subtitle: `${mount} · ${size}`,
          price,
          image: imageUrl,
          url: `/produk/${product.slug}?${searchParams.toString()}`,
          config,
        });
      });
    });

    return previews;
  }

  // 6. BlackBoard
  if (category === "blockboard") {
    const options = [
      "Gantung 80x60 cm",
      "Gantung 80x120 cm",
      "Gantung 200x60 cm",
      "Stand 2 Muka (Papan 60x80 + Stand 60x120)",
    ];

    options.forEach((opt) => {
      const matchedPhoto = photos.find((ph) => {
        const attr = ph.attributes || {};
        return String(attr.pilihan) === String(opt) && Boolean(getPhotoUrl(ph));
      });

      const imageUrl = matchedPhoto ? getPhotoUrl(matchedPhoto) : (CATEGORY_PRICELISTS.blockboard || priceListFallback);

      const config = {
        pilihan: String(opt),
        custom_size: false,
      };

      const breakdown = computeBreakdown(product, config, 1);
      const price = breakdown?.unit || product.starting_price_le || 0;

      const searchParams = new URLSearchParams({
        pilihan: String(opt),
      });

      previews.push({
        id: `${product.id || product._id || product.slug}-${opt}`,
        productSlug: product.slug,
        productName: product.name,
        category: product.category,
        title: product.name,
        subtitle: opt,
        price,
        image: imageUrl,
        url: `/produk/${product.slug}?${searchParams.toString()}`,
        config,
      });
    });

    return previews;
  }

  // 7. Koleksi Custom (Showcase of customer requests & custom works)
  if (category === "custom") {
    const validPhotos = photos.filter((ph) => Boolean(getPhotoUrl(ph)));
    if (validPhotos.length > 0) {
      return validPhotos.map((ph, idx) => {
        const attr = ph.attributes || {};
        const designName = attr.desain || attr.title || attr.name || `Desain ${idx + 1}`;
        const title = designName;
        const subtitle = attr.desc || attr.spesifikasi || null;
        const photoUrl = getPhotoUrl(ph);

        const basePrices = product.pricing?.base_prices || {};
        const designPrice = Number(attr.price) || Number(basePrices[designName]) || Number(product.starting_price_le) || 0;

        const searchParams = new URLSearchParams({
          photo: ph.id || String(idx),
        });
        if (attr.desain) searchParams.set("desain", attr.desain);

        return {
          id: `${product.id || product._id || product.slug}-${ph.id || idx}`,
          productSlug: product.slug,
          productName: title,
          category: product.category,
          title,
          subtitle,
          price: designPrice,
          image: photoUrl,
          url: `/produk/${product.slug}?${searchParams.toString()}`,
          config: { photo_id: ph.id, desain: attr.desain || "" },
          isCustomShowcase: true,
        };
      });
    }

    return [buildFallbackPreview(product)];
  }

  return [buildFallbackPreview(product)];
}

function buildFallbackPreview(product) {
  const photo = Array.isArray(product.photos) && product.photos[0];
  const imageUrl = product.display_image || product.image_url || getPhotoUrl(photo) || CATEGORY_PRICELISTS[product.category] || "";

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
