import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import api from "../../lib/api";
import { fmtLE } from "../../lib/format";
import { CATEGORY_LABELS } from "../../lib/constants";
import { Button } from "../../components/ui/button";
import { Badge } from "../../components/ui/badge";
import { Plus, Pencil, Layers, Sparkles } from "lucide-react";
import { toast } from "sonner";

export default function AdminProducts() {
  const [products, setProducts] = useState([]);
  const navigate = useNavigate();

  const load = () => api.get("/products?admin_view=true").then((r) => setProducts(r.data));
  useEffect(() => { load(); }, []);

  const createNew = async () => {
    try {
      const { data } = await api.post("/admin/products", { name: "Produk Baru", category: "custom", configurable: false });
      navigate(`/admin/products/${data.id}`);
    } catch (e) { toast.error("Gagal membuat produk"); }
  };

  return (
    <div className="space-y-4 sm:space-y-6">
      <div className="flex items-center justify-between gap-2">
        <div>
          <h1 className="font-heading text-xl sm:text-2xl font-bold text-[#2C1E16]">Produk</h1>
          <p className="mt-0.5 text-xs sm:text-sm text-[#8B7355]">Kelola produk, harga, dan konfigurasi.</p>
        </div>
        <Button onClick={createNew} data-testid="add-product" className="h-9 sm:h-10 rounded-xl bg-[#8B5A2B] text-xs sm:text-sm hover:bg-[#6B4423]">
          <Plus size={15} className="mr-1" /> Tambah
        </Button>
      </div>

      <div className="grid gap-3 sm:gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {products.map((p) => {
          const categoryName = CATEGORY_LABELS[p.category] || p.category;
          const photoCount = Array.isArray(p.photos) ? p.photos.length : 0;
          return (
            <div
              key={p.id}
              className="flex flex-col justify-between rounded-2xl border border-[#E5DCC5] bg-white p-4 shadow-xs transition-shadow hover:shadow-sm"
              data-testid={`admin-product-${p.slug}`}
            >
              <div>
                <div className="flex items-center justify-between gap-2">
                  <span className="text-xs font-semibold uppercase tracking-wider text-[#8B7355]">
                    {categoryName}
                  </span>
                  <div className="flex items-center gap-1.5">
                    {p.active ? (
                      <Badge variant="outline" className="border-green-300 bg-green-50 px-1.5 py-0 text-[10px] text-green-700">
                        Aktif
                      </Badge>
                    ) : (
                      <Badge variant="outline" className="border-red-300 bg-red-50 px-1.5 py-0 text-[10px] text-red-700">
                        Nonaktif
                      </Badge>
                    )}
                    {p.configurable && (
                      <Badge variant="outline" className="border-[#E5DCC5] px-1.5 py-0 text-[10px] text-[#8B5A2B]">
                        Konfig
                      </Badge>
                    )}
                  </div>
                </div>

                <h3 className="mt-2 font-heading text-base sm:text-lg font-bold text-[#2C1E16]">
                  {categoryName}
                </h3>

                {p.description && (
                  <p className="mt-1 text-xs text-[#5C4A3D] line-clamp-2">
                    {p.description}
                  </p>
                )}

                <div className="mt-3 flex items-center justify-between border-t border-[#F1EBE0] pt-2.5 text-xs text-[#5C4A3D]">
                  <div>
                    {p.starting_price_le > 0 ? (
                      <span>Mulai <strong className="font-semibold text-[#8B5A2B]">{fmtLE(p.starting_price_le)} LE</strong></span>
                    ) : (
                      <span className="text-[#8B7355]">Harga belum diatur</span>
                    )}
                  </div>
                  <div className="inline-flex items-center gap-1 text-[11px] text-[#8B7355]">
                    <Layers size={13} /> {photoCount} foto
                  </div>
                </div>
              </div>

                <div className="mt-3 flex flex-col gap-2">
                  <Button
                    variant="outline"
                    onClick={() => navigate(`/admin/categories?featured=${p.category}`)}
                    data-testid={`featured-product-${p.slug}`}
                    className="h-8 w-full rounded-xl border-[#8B5A2B]/40 bg-[#FAF5EE] text-xs font-semibold text-[#8B5A2B] hover:bg-[#8B5A2B] hover:text-white transition-colors"
                  >
                    <Sparkles size={12} className="mr-1.5" /> Atur 3 Produk Beranda
                  </Button>

                  <Button
                    variant="outline"
                    onClick={() => navigate(`/admin/products/${p.id}`)}
                    data-testid={`edit-product-${p.slug}`}
                    className="h-8 sm:h-9 w-full rounded-xl border-[#8B5A2B] text-xs font-medium text-[#8B5A2B] hover:bg-[#F5EFEB]"
                  >
                    <Pencil size={13} className="mr-1.5" /> Kelola Produk & Foto
                  </Button>
                </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
