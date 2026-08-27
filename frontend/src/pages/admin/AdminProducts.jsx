import React, { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import api from "../../lib/api";
import { fmtLE } from "../../lib/format";
import { CATEGORY_LABELS } from "../../lib/constants";
import { ProductImage } from "../../components/ProductImage";
import { Button } from "../../components/ui/button";
import { Badge } from "../../components/ui/badge";
import { Plus, Pencil } from "lucide-react";
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
    <div>
      <div className="flex items-center justify-between">
        <div>
          <h1 className="font-heading text-2xl font-bold text-[#2C1E16]">Produk</h1>
          <p className="mt-1 text-sm text-[#8B7355]">Kelola produk, harga, dan konfigurasi.</p>
        </div>
        <Button onClick={createNew} data-testid="add-product" className="rounded-xl bg-[#8B5A2B] hover:bg-[#6B4423]"><Plus size={16} className="mr-1" /> Tambah</Button>
      </div>

      <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {products.map((p) => (
          <div key={p.id} className="rounded-2xl border border-[#E5DCC5] bg-white p-3 shadow-sm" data-testid={`admin-product-${p.slug}`}>
            <div className="overflow-hidden rounded-xl"><ProductImage url={p.display_image} ratio="aspect-video" /></div>
            <div className="p-2">
              <div className="flex items-center gap-2">
                <span className="text-xs text-[#8B7355]">{CATEGORY_LABELS[p.category]}</span>
                {p.active ? <Badge variant="outline" className="border-green-300 bg-green-50 text-[10px] text-green-700">Aktif</Badge>
                          : <Badge variant="outline" className="border-red-300 bg-red-50 text-[10px] text-red-700">Nonaktif</Badge>}
                {p.configurable && <Badge variant="outline" className="border-[#E5DCC5] text-[10px] text-[#8B5A2B]">Konfigurasi</Badge>}
              </div>
              <h3 className="mt-1 font-heading text-lg font-semibold text-[#2C1E16]">{p.name}</h3>
              {p.starting_price_le > 0 && <div className="text-sm text-[#5C4A3D]">Mulai {fmtLE(p.starting_price_le)} LE</div>}
              <Button variant="outline" onClick={() => navigate(`/admin/products/${p.id}`)} data-testid={`edit-product-${p.slug}`}
                className="mt-3 w-full rounded-xl border-[#8B5A2B] text-[#8B5A2B]"><Pencil size={14} className="mr-1" /> Kelola</Button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
