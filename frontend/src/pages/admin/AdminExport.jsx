import React, { useState } from "react";
import api from "../../lib/api";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../../components/ui/select";
import { Download } from "lucide-react";
import { toast } from "sonner";

const PERIODS = [["this_month", "Bulan Ini"], ["last_month", "Bulan Lalu"], ["last_3_months", "3 Bulan Terakhir"], ["this_year", "Tahun Ini"], ["last_year", "Tahun Lalu"], ["custom", "Kustom"]];

export default function AdminExport() {
  const [period, setPeriod] = useState("this_year");
  const [range, setRange] = useState({ start: "", end: "" });

  const dl = async (path, filename, useDate) => {
    const params = useDate ? { period, ...(period === "custom" ? { start: range.start, end: range.end } : {}) } : {};
    try {
      const r = await api.get(path, { params, responseType: "blob" });
      const url = URL.createObjectURL(r.data);
      const a = document.createElement("a"); a.href = url; a.download = filename; document.body.appendChild(a); a.click(); a.remove();
      URL.revokeObjectURL(url);
      toast.success("Export berhasil diunduh");
    } catch (e) { toast.error("Export gagal atau tidak diizinkan"); }
  };

  const Card = ({ title, desc, testid, onClick }) => (
    <div className="rounded-2xl border border-[#E5DCC5] bg-white p-5 shadow-sm">
      <div className="font-heading font-bold text-[#2C1E16]">{title}</div>
      <p className="mt-1 text-sm text-[#8B7355]">{desc}</p>
      <Button onClick={onClick} data-testid={testid} className="mt-3 rounded-xl bg-[#8B5A2B] hover:bg-[#6B4423]"><Download size={16} className="mr-1" /> Unduh XLSX</Button>
    </div>
  );

  return (
    <div className="space-y-6">
      <h1 className="font-heading text-2xl font-bold text-[#2C1E16]">Export Data</h1>

      <div className="rounded-2xl border border-[#E5DCC5] bg-white p-5 shadow-sm">
        <div className="mb-2 text-sm font-medium text-[#5C4A3D]">Rentang tanggal (untuk Keuangan & Pesanan)</div>
        <div className="flex flex-wrap gap-2">
          <Select value={period} onValueChange={setPeriod}><SelectTrigger data-testid="export-period" className="w-44 bg-white"><SelectValue /></SelectTrigger>
            <SelectContent>{PERIODS.map(([v, l]) => <SelectItem key={v} value={v}>{l}</SelectItem>)}</SelectContent></Select>
          {period === "custom" && (<>
            <Input type="date" value={range.start} onChange={(e) => setRange({ ...range, start: e.target.value })} className="w-40 bg-white" data-testid="export-start" />
            <Input type="date" value={range.end} onChange={(e) => setRange({ ...range, end: e.target.value })} className="w-40 bg-white" data-testid="export-end" />
          </>)}
        </div>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <Card title="Keuangan" desc="Transaksi keuangan (tanggal, tipe, klasifikasi, kategori, jumlah, penerima, dicatat oleh)." testid="export-finance" onClick={() => dl("/admin/export/finance", "keuangan.xlsx", true)} />
        <Card title="Pesanan" desc="Backup pesanan lengkap dengan snapshot harga, diskon, referral, status." testid="export-orders" onClick={() => dl("/admin/export/orders", "pesanan.xlsx", true)} />
        <Card title="Analitik Konfigurasi Produk" desc="Peringkat konfigurasi produk yang paling sering dipesan." testid="export-config" onClick={() => dl("/admin/export/config-analytics", "analitik_konfigurasi.xlsx", false)} />
        <Card title="Data Pelanggan" desc="Data pelanggan (tanpa sandi/hash). Nama, email, HP, status, poin." testid="export-customers" onClick={() => dl("/admin/export/customers", "pelanggan.xlsx", false)} />
        <Card title="Akun & Upah (Owner)" desc="Akun admin/manager/employee + ringkasan & riwayat upah (2 sheet). Tanpa sandi." testid="export-accounts" onClick={() => dl("/admin/export/accounts", "akun_dan_upah.xlsx", false)} />
        <Card title="Harga Produk" desc="Riwayat perubahan harga + harga saat ini (2 sheet)." testid="export-prices" onClick={() => dl("/admin/export/product-prices", "harga_produk.xlsx", false)} />
      </div>
    </div>
  );
}
