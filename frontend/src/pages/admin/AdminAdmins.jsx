import React, { useEffect, useState } from "react";
import api from "../../lib/api";
import { formatApiError } from "../../lib/format";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { Switch } from "../../components/ui/switch";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../../components/ui/select";
import { Trash2, UserPlus } from "lucide-react";
import { toast } from "sonner";

const PERMS = [
  ["manage_orders", "Kelola Pesanan"], ["modify_products", "Ubah Produk"],
  ["manage_settings", "Kelola Pengaturan"], ["access_finance", "Akses Keuangan"], ["delete_data", "Hapus Data"],
];
const ROLES = [["manager", "Manager"], ["admin", "Admin"], ["employee", "Employee"]];

export default function AdminAdmins() {
  const [admins, setAdmins] = useState([]);
  const [wageMap, setWageMap] = useState({});
  const [form, setForm] = useState({ name: "", email: "", password: "", role: "admin", permissions: {} });

  const load = () => {
    api.get("/admin/admins").then((r) => setAdmins(r.data));
    api.get("/admin/employees/wages").then((r) => { const m = {}; r.data.forEach((w) => { m[w.id] = w; }); setWageMap(m); }).catch(() => {});
  };
  useEffect(() => { load(); }, []);

  const resetPw = async (a) => {
    const np = window.prompt(`Set kata sandi baru untuk ${a.name} (min 6 karakter). Admin tidak melihat sandi lama.`);
    if (!np) return;
    try { await api.put(`/admin/admins/${a.id}`, { password: np }); toast.success("Kata sandi direset"); }
    catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };
  const toggleStatus = async (a) => {
    const ns = a.status === "inactive" ? "active" : "inactive";
    await api.put(`/admin/admins/${a.id}`, { status: ns }); toast.success(ns === "inactive" ? "Akun dinonaktifkan" : "Akun diaktifkan"); load();
  };

  const create = async () => {
    if (!form.name || !form.email || !form.password) return toast.error("Lengkapi nama, email, kata sandi");
    try { await api.post("/admin/admins", form); toast.success("Akun dibuat"); setForm({ name: "", email: "", password: "", role: "admin", permissions: {} }); load(); }
    catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };
  const updatePerm = async (a, key, val) => {
    const permissions = { ...(a.permissions || {}), [key]: val };
    await api.put(`/admin/admins/${a.id}`, { permissions }); load();
  };
  const del = async (a) => { if (!window.confirm(`Hapus akun ${a.name}?`)) return; await api.delete(`/admin/admins/${a.id}`); load(); };

  return (
    <div className="space-y-6">
      <h1 className="font-heading text-2xl font-bold text-[#2C1E16]">Akun Admin & Hak Akses</h1>

      <div className="rounded-2xl border border-[#E5DCC5] bg-white p-5 shadow-sm">
        <div className="mb-3 flex items-center gap-2 font-heading font-bold text-[#2C1E16]"><UserPlus size={18} /> Buat Akun Baru</div>
        <div className="grid gap-2 sm:grid-cols-2">
          <Input placeholder="Nama" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} data-testid="new-admin-name" className="bg-white" />
          <Input placeholder="Email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} data-testid="new-admin-email" className="bg-white" />
          <Input type="password" placeholder="Kata sandi" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} data-testid="new-admin-password" className="bg-white" />
          <Select value={form.role} onValueChange={(v) => setForm({ ...form, role: v, permissions: {} })}><SelectTrigger data-testid="new-admin-role" className="bg-white"><SelectValue /></SelectTrigger><SelectContent>{ROLES.map(([v, l]) => <SelectItem key={v} value={v}>{l}</SelectItem>)}</SelectContent></Select>
        </div>
        <div className="mt-3 flex flex-wrap gap-4">
          {PERMS.map(([k, l]) => (
            <label key={k} className="flex items-center gap-2 text-sm"><Switch checked={!!form.permissions[k]} onCheckedChange={(v) => setForm({ ...form, permissions: { ...form.permissions, [k]: v } })} data-testid={`new-perm-${k}`} /> {l}</label>
          ))}
        </div>
        <Button onClick={create} data-testid="create-admin" className="mt-3 rounded-xl bg-[#8B5A2B] hover:bg-[#6B4423]">Buat Akun</Button>
      </div>

      <div className="space-y-3">
        {admins.map((a) => (
          <div key={a.id} className="rounded-2xl border border-[#E5DCC5] bg-white p-5 shadow-sm" data-testid={`admin-account-${a.id}`}>
            <div className="flex items-center justify-between">
              <div><div className="font-heading font-semibold text-[#2C1E16]">{a.name} <span className="ml-1 rounded-full bg-[#EFE6D5] px-2 py-0.5 text-xs text-[#8B5A2B]">{a.role}</span></div><div className="text-xs text-[#8B7355]">{a.email}</div>{a.role === "employee" && wageMap[a.id] && <div className="mt-0.5 text-xs text-[#8B5A2B]" data-testid={`admin-wage-${a.id}`}>Upah: {Object.entries(wageMap[a.id].totals || {}).map(([c, v]) => `${Math.round(v).toLocaleString("de-DE")} ${c}`).join(" · ") || "—"} ({wageMap[a.id].count || 0}x)</div>}</div>
              {a.role !== "owner" && (
                <div className="flex items-center gap-1">
                  <span className={`rounded-full px-2 py-0.5 text-xs ${a.status === "inactive" ? "bg-red-100 text-red-700" : "bg-green-100 text-green-700"}`} data-testid={`admin-status-${a.id}`}>{a.status === "inactive" ? "Nonaktif" : "Aktif"}</span>
                  <Button variant="outline" size="sm" onClick={() => resetPw(a)} data-testid={`reset-admin-${a.id}`} className="h-7 rounded-lg text-xs">Reset Sandi</Button>
                  <Button variant="outline" size="sm" onClick={() => toggleStatus(a)} data-testid={`toggle-admin-${a.id}`} className="h-7 rounded-lg text-xs">{a.status === "inactive" ? "Aktifkan" : "Nonaktifkan"}</Button>
                  <button onClick={() => del(a)} data-testid={`del-admin-${a.id}`} className="p-1.5 text-red-500"><Trash2 size={16} /></button>
                </div>
              )}
            </div>
            {a.role !== "owner" ? (
              <div className="mt-3 flex flex-wrap gap-4 border-t border-[#F1EBE0] pt-3">
                {PERMS.map(([k, l]) => (
                  <label key={k} className="flex items-center gap-2 text-sm"><Switch checked={!!a.permissions?.[k]} onCheckedChange={(v) => updatePerm(a, k, v)} data-testid={`perm-${a.id}-${k}`} /> {l}</label>
                ))}
              </div>
            ) : <div className="mt-2 text-xs text-[#8B7355]">Owner/CEO memiliki akses penuh.</div>}
          </div>
        ))}
      </div>
    </div>
  );
}
