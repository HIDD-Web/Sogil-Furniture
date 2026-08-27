import React, { useEffect, useRef, useState } from "react";
import api, { imgUrl } from "../../lib/api";
import { formatApiError } from "../../lib/format";
import { useAuth } from "../../context/AuthContext";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Textarea } from "../../components/ui/textarea";
import { Label } from "../../components/ui/label";
import { Switch } from "../../components/ui/switch";
import { Plus, Trash2, KeyRound, Mail, Upload } from "lucide-react";
import { toast } from "sonner";

export default function AdminSettings() {
  const { user } = useAuth();
  const [s, setS] = useState(null);
  const [zones, setZones] = useState([]);
  const [newZone, setNewZone] = useState({ name: "", fee_le: "" });
  const [pw, setPw] = useState({ current_password: "", new_password: "" });
  const [em, setEm] = useState({ current_password: "", new_email: "" });
  const [uploading, setUploading] = useState(false);
  const logoRef = useRef();

  const loadZones = () => api.get("/delivery-zones?admin_view=true").then((r) => setZones(r.data));
  useEffect(() => { api.get("/admin/settings").then((r) => setS(r.data)); loadZones(); }, []);
  const setField = (k, v) => setS((prev) => ({ ...prev, [k]: v }));

  const saveSettings = async () => {
    try { await api.put("/admin/settings", s); toast.success("Pengaturan disimpan"); } catch { toast.error("Gagal menyimpan"); }
  };
  const uploadLogo = async (e) => {
    const file = e.target.files?.[0]; if (!file) return; setUploading(true);
    const fd = new FormData(); fd.append("file", file);
    try { const { data } = await api.post("/admin/upload", fd, { headers: { "Content-Type": "multipart/form-data" } }); setField("logo_url", data.url); toast.success("Logo diunggah — klik Simpan Pengaturan"); }
    catch (err) { toast.error(formatApiError(err.response?.data?.detail)); } finally { setUploading(false); }
  };
  const addZone = async () => {
    if (!newZone.name || newZone.fee_le === "") return toast.error("Isi nama & ongkir");
    await api.post("/admin/delivery-zones", { name: newZone.name, fee_le: Number(newZone.fee_le), active: true });
    setNewZone({ name: "", fee_le: "" }); loadZones(); toast.success("Zona ditambahkan");
  };
  const updZone = async (z, patch) => { await api.put(`/admin/delivery-zones/${z.id}`, { ...z, ...patch }); loadZones(); };
  const delZone = async (z) => { if (!window.confirm(`Hapus zona ${z.name}?`)) return; await api.delete(`/admin/delivery-zones/${z.id}`); loadZones(); };
  const changePw = async () => {
    try { await api.post("/auth/change-password", pw); toast.success("Kata sandi diubah"); setPw({ current_password: "", new_password: "" }); }
    catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };
  const changeEmail = async () => {
    try { await api.post("/auth/change-email", em); toast.success("Email diubah"); setEm({ current_password: "", new_email: "" }); }
    catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };

  if (!s) return <div className="text-[#8B7355]">Memuat...</div>;
  const canSettings = user?.role === "owner" || user?.permissions?.manage_settings;

  return (
    <div className="max-w-3xl space-y-6">
      <h1 className="font-heading text-2xl font-bold text-[#2C1E16]">Pengaturan</h1>

      {canSettings && (
        <Card title="Branding & Informasi Toko">
          <div>
            <Label className="mb-1 block text-sm">Logo</Label>
            <div className="flex items-center gap-3">
              <div className="flex h-16 w-16 items-center justify-center overflow-hidden rounded-full border border-[#E5DCC5] bg-white">
                {s.logo_url ? <img src={imgUrl(s.logo_url)} alt="logo" className="h-full w-full object-cover" /> : <span className="text-xs text-[#8B7355]">Logo</span>}
              </div>
              <input ref={logoRef} type="file" accept="image/*" hidden onChange={uploadLogo} data-testid="logo-input" />
              <Button variant="outline" onClick={() => logoRef.current?.click()} disabled={uploading} data-testid="logo-upload" className="rounded-xl border-[#8B5A2B] text-[#8B5A2B]"><Upload size={14} className="mr-1" /> {uploading ? "..." : "Unggah Logo"}</Button>
              {s.logo_url && <Button variant="ghost" onClick={() => setField("logo_url", "")} className="text-xs text-red-500">Hapus</Button>}
            </div>
          </div>
          <F label="Judul Aplikasi"><Input value={s.app_name || ""} onChange={(e) => setField("app_name", e.target.value)} data-testid="set-app-name" className="bg-white" /></F>
          <F label="Nama Toko"><Input value={s.store_name || ""} onChange={(e) => setField("store_name", e.target.value)} data-testid="set-store-name" className="bg-white" /></F>
          <F label="Tagline"><Input value={s.tagline || ""} onChange={(e) => setField("tagline", e.target.value)} className="bg-white" /></F>
          <F label="Alamat Toko"><Textarea value={s.store_address || ""} onChange={(e) => setField("store_address", e.target.value)} data-testid="set-address" className="bg-white" /></F>
          <F label="Link Maps Toko"><Input value={s.store_maps_url || ""} onChange={(e) => setField("store_maps_url", e.target.value)} className="bg-white" /></F>
          <F label="Nomor WhatsApp Admin"><Input value={s.whatsapp_number || ""} onChange={(e) => setField("whatsapp_number", e.target.value)} data-testid="set-whatsapp" className="bg-white" placeholder="628XXXXXXXXXX" /></F>
          <F label="Rate IDR per 1 LE"><Input type="number" value={s.exchange_rate_idr_per_le || 0} onChange={(e) => setField("exchange_rate_idr_per_le", e.target.value)} data-testid="set-rate" className="bg-white" /></F>
          <F label="Informasi Bank/Pembayaran"><Textarea value={s.bank_info || ""} onChange={(e) => setField("bank_info", e.target.value)} className="bg-white" /></F>
          <Button onClick={saveSettings} data-testid="save-settings" className="rounded-xl bg-[#8B5A2B] hover:bg-[#6B4423]">Simpan Pengaturan</Button>
        </Card>
      )}

      {canSettings && (
        <Card title="Zona Pengiriman">
          <div className="space-y-2">
            {zones.map((z) => (
              <div key={z.id} className="flex items-center gap-2" data-testid={`zone-row-${z.id}`}>
                <Input defaultValue={z.name} onBlur={(e) => e.target.value !== z.name && updZone(z, { name: e.target.value })} className="flex-1 bg-white" />
                <Input type="number" defaultValue={z.fee_le} onBlur={(e) => Number(e.target.value) !== z.fee_le && updZone(z, { fee_le: Number(e.target.value) })} className="w-24 bg-white" />
                <span className="text-xs text-[#8B7355]">LE</span>
                <Switch checked={z.active} onCheckedChange={(v) => updZone(z, { active: v })} />
                <button onClick={() => delZone(z)} data-testid={`del-zone-${z.id}`} className="p-2 text-red-500"><Trash2 size={16} /></button>
              </div>
            ))}
          </div>
          <div className="mt-3 flex items-center gap-2 border-t border-[#F1EBE0] pt-3">
            <Input placeholder="Nama zona" value={newZone.name} onChange={(e) => setNewZone({ ...newZone, name: e.target.value })} data-testid="new-zone-name" className="flex-1 bg-white" />
            <Input placeholder="Ongkir" type="number" value={newZone.fee_le} onChange={(e) => setNewZone({ ...newZone, fee_le: e.target.value })} data-testid="new-zone-fee" className="w-24 bg-white" />
            <Button onClick={addZone} data-testid="add-zone" className="rounded-xl bg-[#8B5A2B] hover:bg-[#6B4423]"><Plus size={16} /></Button>
          </div>
        </Card>
      )}

      <Card title="Akun Saya">
        <div className="text-sm text-[#5C4A3D]">Email saat ini: <span className="font-medium text-[#2C1E16]">{user?.email}</span></div>
        <div className="grid gap-3 sm:grid-cols-2">
          <F label="Kata Sandi (verifikasi)"><Input type="password" value={em.current_password} onChange={(e) => setEm({ ...em, current_password: e.target.value })} data-testid="email-current-pw" className="bg-white" /></F>
          <F label="Email Baru"><Input value={em.new_email} onChange={(e) => setEm({ ...em, new_email: e.target.value })} data-testid="email-new" className="bg-white" /></F>
        </div>
        <Button onClick={changeEmail} data-testid="change-email" className="rounded-xl bg-[#8B5A2B] hover:bg-[#6B4423]"><Mail size={16} className="mr-1" /> Ubah Email</Button>
        <div className="my-2 border-t border-[#F1EBE0]" />
        <div className="grid gap-3 sm:grid-cols-2">
          <F label="Kata Sandi Saat Ini"><Input type="password" value={pw.current_password} onChange={(e) => setPw({ ...pw, current_password: e.target.value })} data-testid="pw-current" className="bg-white" /></F>
          <F label="Kata Sandi Baru"><Input type="password" value={pw.new_password} onChange={(e) => setPw({ ...pw, new_password: e.target.value })} data-testid="pw-new" className="bg-white" /></F>
        </div>
        <Button onClick={changePw} data-testid="change-password" className="rounded-xl bg-[#8B5A2B] hover:bg-[#6B4423]"><KeyRound size={16} className="mr-1" /> Ubah Kata Sandi</Button>
      </Card>
    </div>
  );
}

const Card = ({ title, children }) => (
  <div className="rounded-2xl border border-[#E5DCC5] bg-white p-5 shadow-sm">
    <div className="mb-4 font-heading text-sm font-bold uppercase tracking-wide text-[#8B5A2B]">{title}</div>
    <div className="space-y-3">{children}</div>
  </div>
);
const F = ({ label, children }) => (<div><Label className="mb-1 block text-sm">{label}</Label>{children}</div>);
