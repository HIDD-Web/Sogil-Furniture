export const ORDER_STATUS = {
  pesanan_masuk: { label: "Pesanan Masuk", color: "bg-amber-100 text-amber-800 border-amber-200" },
  dikonfirmasi: { label: "Dikonfirmasi", color: "bg-blue-100 text-blue-800 border-blue-200" },
  diproses: { label: "Diproses", color: "bg-indigo-100 text-indigo-800 border-indigo-200" },
  siap: { label: "Siap Diambil/Dikirim", color: "bg-teal-100 text-teal-800 border-teal-200" },
  selesai: { label: "Selesai", color: "bg-green-100 text-green-800 border-green-200" },
  dibatalkan: { label: "Dibatalkan", color: "bg-red-100 text-red-700 border-red-200" },
};

export const PAYMENT_STATUS = {
  belum_dibayar: { label: "Belum Dibayar", color: "bg-red-100 text-red-700 border-red-200" },
  dp: { label: "DP", color: "bg-amber-100 text-amber-800 border-amber-200" },
  lunas: { label: "Lunas", color: "bg-green-100 text-green-800 border-green-200" },
};

export const CATEGORY_LABELS = {
  rak: "Rak",
  meja: "Meja",
  meja_rak: "Meja Rak",
  papan_tulis: "Papan Tulis",
  blockboard: "BlackBoard",
  rak_tempel: "Rak Tempel",
  rak_gantung: "Rak Gantung",
  gantungan_baju: "Gantungan Baju",
  custom: "Koleksi Custom",
};

export const CATEGORY_PRICELISTS = {
  rak: "/pricelists/rak.jpg",
  meja: "/pricelists/meja.jpg",
  meja_rak: "/pricelists/meja_rak.jpg",
  papan_tulis: "/pricelists/papan_tulis.jpg",
  blockboard: "/pricelists/blockboard.jpg",
};
