import React, { useEffect, useState } from "react";
import api from "../../lib/api";
import { formatApiError } from "../../lib/format";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Switch } from "../../components/ui/switch";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../../components/ui/select";
import { Trash2, UserPlus, Shield, UserCog } from "lucide-react";
import { toast } from "sonner";

const PERMS = [
  ["manage_orders", "Kelola Pesanan"],
  ["modify_products", "Ubah Produk"],
  ["manage_settings", "Kelola Pengaturan"],
  ["access_finance", "Akses Keuangan"],
  ["delete_data", "Hapus Data"],
];

const ROLES = [
  ["manager", "Manager"],
  ["admin", "Admin"],
  ["employee", "Employee"],
];

const DEFAULT_ROLE_PERMS = {
  owner: {
    manage_orders: true,
    modify_products: true,
    manage_settings: true,
    access_finance: true,
    delete_data: true,
  },
  manager: {
    manage_orders: true,
    modify_products: true,
    manage_settings: true,
    access_finance: true,
    delete_data: false,
  },
  admin: {
    manage_orders: true,
    modify_products: true,
    manage_settings: true,
    access_finance: false,
    delete_data: false,
  },
  employee: {
    manage_orders: true,
    modify_products: false,
    manage_settings: false,
    access_finance: false,
    delete_data: false,
  },
};

const ROLE_RANK = { owner: 0, manager: 1, admin: 2, employee: 3 };

export default function AdminAdmins() {
  const [admins, setAdmins] = useState([]);
  const [wageMap, setWageMap] = useState({});
  const [form, setForm] = useState({
    name: "",
    email: "",
    password: "",
    role: "admin",
    permissions: { ...DEFAULT_ROLE_PERMS.admin },
  });

  const load = () => {
    api.get("/admin/admins").then((r) => setAdmins(r.data));
    api
      .get("/admin/employees/wages")
      .then((r) => {
        const m = {};
        r.data.forEach((w) => {
          m[w.id] = w;
        });
        setWageMap(m);
      })
      .catch(() => {});
  };

  useEffect(() => {
    load();
  }, []);

  const handleRoleSelectCreate = (r) => {
    setForm((prev) => ({
      ...prev,
      role: r,
      permissions: { ...(DEFAULT_ROLE_PERMS[r] || {}) },
    }));
  };

  const handleRoleChangeExisting = async (a, newRole) => {
    if (a.role === newRole) return;
    const newPerms = { ...DEFAULT_ROLE_PERMS[newRole] };
    try {
      await api.put(`/admin/admins/${a.id}`, { role: newRole, permissions: newPerms });
      toast.success(`Role ${a.name} berhasil diubah ke ${newRole.toUpperCase()}`);
      load();
    } catch (e) {
      toast.error(formatApiError(e.response?.data?.detail));
    }
  };

  const resetPw = async (a) => {
    const np = window.prompt(`Set kata sandi baru untuk ${a.name} (min 6 karakter). Admin tidak melihat sandi lama.`);
    if (!np) return;
    try {
      await api.put(`/admin/admins/${a.id}`, { password: np });
      toast.success("Kata sandi direset");
    } catch (e) {
      toast.error(formatApiError(e.response?.data?.detail));
    }
  };

  const toggleStatus = async (a) => {
    const ns = a.status === "inactive" ? "active" : "inactive";
    await api.put(`/admin/admins/${a.id}`, { status: ns });
    toast.success(ns === "inactive" ? "Akun dinonaktifkan" : "Akun diaktifkan");
    load();
  };

  const create = async () => {
    if (!form.name || !form.email || !form.password) return toast.error("Lengkapi nama, email, kata sandi");
    try {
      await api.post("/admin/admins", form);
      toast.success("Akun tim berhasil dibuat");
      setForm({
        name: "",
        email: "",
        password: "",
        role: "admin",
        permissions: { ...DEFAULT_ROLE_PERMS.admin },
      });
      load();
    } catch (e) {
      toast.error(formatApiError(e.response?.data?.detail));
    }
  };

  const updatePerm = async (a, key, val) => {
    const permissions = { ...(a.permissions || {}), [key]: val };
    await api.put(`/admin/admins/${a.id}`, { permissions });
    load();
  };

  const del = async (a) => {
    if (!window.confirm(`Hapus akun ${a.name}?`)) return;
    await api.delete(`/admin/admins/${a.id}`);
    toast.success("Akun dihapus");
    load();
  };

  const sortedAdmins = [...admins].sort((x, y) => {
    const rx = ROLE_RANK[x.role] ?? 99;
    const ry = ROLE_RANK[y.role] ?? 99;
    if (rx !== ry) return rx - ry;
    return (x.name || "").localeCompare(y.name || "");
  });

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="font-heading text-2xl font-bold text-[#2C1E16]">Akun Tim & Hak Akses</h1>
          <p className="text-xs sm:text-sm text-[#8B7355] mt-0.5">
            Kelola anggota tim Sogil Furniture, peran akun (Owner, Manager, Admin, Employee), dan hak akses spesifik.
          </p>
        </div>
      </div>

      {/* Form Buat Akun Baru */}
      <div className="rounded-2xl border border-[#E5DCC5] bg-white p-5 shadow-sm">
        <div className="mb-3 flex items-center gap-2 font-heading font-bold text-[#2C1E16]">
          <UserPlus size={18} className="text-[#8B5A2B]" /> Buat Akun Tim Baru
        </div>
        <div className="grid gap-2 sm:grid-cols-2">
          <Input
            placeholder="Nama Lengkap"
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            data-testid="new-admin-name"
            className="bg-white"
          />
          <Input
            placeholder="Email"
            type="email"
            value={form.email}
            onChange={(e) => setForm({ ...form, email: e.target.value })}
            data-testid="new-admin-email"
            className="bg-white"
          />
          <Input
            type="password"
            placeholder="Kata sandi (min 6 karakter)"
            value={form.password}
            onChange={(e) => setForm({ ...form, password: e.target.value })}
            data-testid="new-admin-password"
            className="bg-white"
          />
          <div>
            <Select value={form.role} onValueChange={handleRoleSelectCreate}>
              <SelectTrigger data-testid="new-admin-role" className="bg-white">
                <SelectValue placeholder="Pilih Role" />
              </SelectTrigger>
              <SelectContent>
                {ROLES.map(([v, l]) => (
                  <SelectItem key={v} value={v}>
                    {l}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="text-[11px] text-[#8B7355] mt-1">
              {form.role === "manager"
                ? "Default 4 akses (kecuali Hapus Data)"
                : form.role === "admin"
                ? "Default 3 akses (kecuali Keuangan & Hapus Data)"
                : "Default 1 akses (Kelola Pesanan saja)"}
            </p>
          </div>
        </div>

        <div className="mt-4 pt-3 border-t border-[#F1EBE0]">
          <span className="text-xs font-semibold text-[#5C4A3D] block mb-2">
            Sesuaikan Hak Akses (Centang untuk Memberikan Izin):
          </span>
          <div className="flex flex-wrap gap-4">
            {PERMS.map(([k, l]) => (
              <label key={k} className="flex items-center gap-2 text-sm cursor-pointer select-none">
                <Switch
                  checked={!!form.permissions[k]}
                  onCheckedChange={(v) =>
                    setForm({ ...form, permissions: { ...form.permissions, [k]: v } })
                  }
                  data-testid={`new-perm-${k}`}
                />{" "}
                <span className="text-xs sm:text-sm text-[#2C1E16]">{l}</span>
              </label>
            ))}
          </div>
        </div>

        <Button
          onClick={create}
          data-testid="create-admin"
          className="mt-4 rounded-xl bg-[#8B5A2B] hover:bg-[#6B4423] text-white font-medium"
        >
          Buat Akun Tim
        </Button>
      </div>

      {/* Daftar Akun Tim */}
      <div className="space-y-3">
        <div className="text-xs font-semibold uppercase tracking-wider text-[#8B7355] px-1">
          Daftar Akun Tim ({sortedAdmins.length} Akun)
        </div>
        {sortedAdmins.map((a) => (
          <div
            key={a.id}
            className="rounded-2xl border border-[#E5DCC5] bg-white p-4 sm:p-5 shadow-sm"
            data-testid={`admin-account-${a.id}`}
          >
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <div className="flex items-center gap-2">
                  <span className="font-heading font-semibold text-base text-[#2C1E16]">{a.name}</span>
                  {a.role === "owner" ? (
                    <span className="rounded-full bg-[#8B5A2B] px-2.5 py-0.5 text-xs font-semibold text-white flex items-center gap-1">
                      <Shield size={12} /> OWNER (CEO)
                    </span>
                  ) : (
                    <div className="inline-flex items-center gap-1.5">
                      <Select
                        value={a.role}
                        onValueChange={(newRole) => handleRoleChangeExisting(a, newRole)}
                      >
                        <SelectTrigger className="h-7 w-28 bg-[#FBF9F4] text-xs font-semibold text-[#8B5A2B] border-[#E5DCC5]">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {ROLES.map(([v, l]) => (
                            <SelectItem key={v} value={v} className="text-xs">
                              {l}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                  )}
                </div>
                <div className="text-xs text-[#8B7355] mt-0.5">{a.email}</div>
                <div className="mt-1 text-xs text-[#8B5A2B]" data-testid={`admin-wage-${a.id}`}>
                  Total Upah Diterima:{" "}
                  {wageMap[a.id] && Object.entries(wageMap[a.id].totals || {}).length > 0
                    ? Object.entries(wageMap[a.id].totals)
                        .map(([c, v]) => `${Math.round(v).toLocaleString("de-DE")} ${c}`)
                        .join(" · ")
                    : "0 LE"}{" "}
                  ({wageMap[a.id]?.count || 0}x)
                </div>
              </div>

              {a.role !== "owner" && (
                <div className="flex flex-wrap items-center gap-1.5">
                  <span
                    className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${
                      a.status === "inactive" ? "bg-red-100 text-red-700" : "bg-green-100 text-green-700"
                    }`}
                    data-testid={`admin-status-${a.id}`}
                  >
                    {a.status === "inactive" ? "Nonaktif" : "Aktif"}
                  </span>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => resetPw(a)}
                    data-testid={`reset-admin-${a.id}`}
                    className="h-7 rounded-lg text-xs"
                  >
                    Reset Sandi
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => toggleStatus(a)}
                    data-testid={`toggle-admin-${a.id}`}
                    className="h-7 rounded-lg text-xs"
                  >
                    {a.status === "inactive" ? "Aktifkan" : "Nonaktifkan"}
                  </Button>
                  <button
                    onClick={() => del(a)}
                    data-testid={`del-admin-${a.id}`}
                    className="p-1.5 text-red-500 hover:text-red-700 rounded-lg hover:bg-red-50"
                    title="Hapus Akun"
                  >
                    <Trash2 size={16} />
                  </button>
                </div>
              )}
            </div>

            {a.role !== "owner" ? (
              <div className="mt-3.5 flex flex-wrap gap-x-5 gap-y-2 border-t border-[#F1EBE0] pt-3">
                {PERMS.map(([k, l]) => (
                  <label key={k} className="flex items-center gap-2 text-xs sm:text-sm cursor-pointer select-none">
                    <Switch
                      checked={!!a.permissions?.[k]}
                      onCheckedChange={(v) => updatePerm(a, k, v)}
                      data-testid={`perm-${a.id}-${k}`}
                    />{" "}
                    <span className="text-[#5C4A3D]">{l}</span>
                  </label>
                ))}
              </div>
            ) : (
              <div className="mt-2.5 text-xs text-[#8B7355] flex items-center gap-1.5">
                <Shield size={13} className="text-[#8B5A2B]" /> Akun Owner memiliki akses penuh ke seluruh fitur dan pengaturan sistem secara permanen.
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
