import React, { useEffect, useState } from "react";
import api from "../lib/api";
import { MapPin, Phone, ExternalLink } from "lucide-react";
import { Button } from "../components/ui/button";

export default function Kontak() {
  const [info, setInfo] = useState(null);
  useEffect(() => { api.get("/store-info").then((r) => setInfo(r.data)); }, []);

  const waLink = info?.whatsapp_number
    ? `https://wa.me/${info.whatsapp_number.replace(/[^0-9]/g, "")}`
    : "#";

  return (
    <div className="mx-auto max-w-3xl px-4 py-12 sm:px-6">
      <h1 className="font-heading text-3xl font-bold tracking-tight text-[#2C1E16] sm:text-4xl">Kontak & Toko</h1>
      <p className="mt-2 text-[#5C4A3D]">Punya pertanyaan atau kebutuhan khusus? Hubungi kami langsung.</p>

      <div className="mt-8 space-y-4">
        <div className="rounded-2xl border border-[#E5DCC5] bg-white p-6 shadow-sm">
          <div className="flex items-start gap-3">
            <MapPin className="mt-0.5 text-[#8B5A2B]" size={22} />
            <div>
              <div className="font-heading font-semibold text-[#2C1E16]">Alamat Toko</div>
              <p className="mt-1 text-sm text-[#5C4A3D]">{info?.store_address || "-"}</p>
              {info?.store_maps_url && (
                <a href={info.store_maps_url} target="_blank" rel="noreferrer" data-testid="kontak-maps-link"
                  className="mt-2 inline-flex items-center gap-1 text-sm font-medium text-[#8B5A2B] hover:underline">
                  Buka di Google Maps <ExternalLink size={14} />
                </a>
              )}
            </div>
          </div>
        </div>

        <div className="rounded-2xl border border-[#E5DCC5] bg-white p-6 shadow-sm">
          <div className="flex items-start gap-3">
            <Phone className="mt-0.5 text-[#8B5A2B]" size={22} />
            <div className="flex-1">
              <div className="font-heading font-semibold text-[#2C1E16]">WhatsApp</div>
              <p className="mt-1 text-sm text-[#5C4A3D]">{info?.whatsapp_number || "-"}</p>
              <a href={waLink} target="_blank" rel="noreferrer" data-testid="kontak-whatsapp-link">
                <Button className="mt-3 h-11 rounded-full bg-[#25D366] hover:bg-[#1eb556]">Chat via WhatsApp</Button>
              </a>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
