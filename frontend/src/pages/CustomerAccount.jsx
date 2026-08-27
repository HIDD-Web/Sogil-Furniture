import React, { useEffect, useState } from "react";
import api from "../lib/api";
import { fmtLE } from "../lib/format";
import { config_summary_client } from "../lib/summary";
import { ORDER_STATUS, PAYMENT_STATUS } from "../lib/constants";
import { useCustomer } from "../context/CustomerContext";
import { formatApiError } from "../lib/format";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Badge } from "../components/ui/badge";
import { toast } from "sonner";
import { User, Gift, Copy, LogOut } from "lucide-react";

export default function CustomerAccount() {
  const { customer, checked, register, login, logout } = useCustomer();
  const [mode, setMode] = useState("login");
  const [f, setF] = useState({ username: "", phone: "", password: "", identifier: "" });
  const [orders, setOrders] = useState([]);
  const [points, setPoints] = useState(null);

  useEffect(() => {
    if (customer) {
      api.get("/customer/orders").then((r) => setOrders(r.data)).catch(() => {});
      api.get("/customer/points").then((r) => setPoints(r.data)).catch(() => {});
    }
  }, [customer]);

  if (!checked) return <div className="py-20 text-center text-[#8B7355]">Memuat...</div>;

  if (!customer) {
    const submit = async (e) => {
      e.preventDefault();
      try {
        if (mode === "register") await register({ username: f.username, phone: f.phone, password: f.password });
        else await login(f.identifier, f.password);
        toast.success("Berhasil masuk");
      } catch (err) { toast.error(formatApiError(err.response?.data?.detail)); }
    };
    return (
      <div className="mx-auto max-w-sm px-4 py-12 sm:px-6">
        <div className="rounded-2xl border border-[#E5DCC5] bg-white p-6 shadow-sm">
          <div className="flex justify-center"><div className="flex h-12 w-12 items-center justify-center rounded-full bg-[#EFE6D5] text-[#8B5A2B]"><User /></div></div>
          <h1 className="mt-3 text-center font-heading text-xl font-bold text-[#2C1E16]">{mode === "register" ? "Daftar Akun" : "Masuk Akun"}</h1>
          <p className="mt-1 text-center text-xs text-[#8B7355]">Login untuk poin & referral. Belanja tetap bisa tanpa akun.</p>
          <form onSubmit={submit} className="mt-5 space-y-3">
            {mode === "register" ? (<>
              <div><Label className="mb-1 block text-sm">Username</Label><Input value={f.username} onChange={(e) => setF({ ...f, username: e.target.value })} data-testid="reg-username" className="bg-white" required /></div>
              <div><Label className="mb-1 block text-sm">No HP (+kode negara)</Label><Input value={f.phone} onChange={(e) => setF({ ...f, phone: e.target.value })} data-testid="reg-phone" placeholder="+201234567890" className="bg-white" required /></div>
            </>) : (
              <div><Label className="mb-1 block text-sm">Username / No HP</Label><Input value={f.identifier} onChange={(e) => setF({ ...f, identifier: e.target.value })} data-testid="login-identifier" className="bg-white" required /></div>
            )}
            <div><Label className="mb-1 block text-sm">Kata Sandi</Label><Input type="password" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} data-testid="cust-password" className="bg-white" required /></div>
            <Button type="submit" data-testid="cust-submit" className="h-11 w-full rounded-xl bg-[#8B5A2B] hover:bg-[#6B4423]">{mode === "register" ? "Daftar" : "Masuk"}</Button>
          </form>
          <button onClick={() => setMode(mode === "register" ? "login" : "register")} className="mt-3 w-full text-center text-sm text-[#8B5A2B]" data-testid="toggle-mode">
            {mode === "register" ? "Sudah punya akun? Masuk" : "Belum punya akun? Daftar"}
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-4xl px-4 py-10 sm:px-6">
      <div className="flex items-center justify-between">
        <div><h1 className="font-heading text-2xl font-bold text-[#2C1E16]">Halo, {customer.username}</h1><p className="text-sm text-[#8B7355]">{customer.phone}</p></div>
        <Button variant="outline" onClick={logout} data-testid="cust-logout" className="rounded-full border-[#E5DCC5] text-[#5C4A3D]"><LogOut size={16} className="mr-1" /> Keluar</Button>
      </div>

      <div className="mt-6 grid gap-4 sm:grid-cols-3">
        <div className="rounded-2xl border border-[#E5DCC5] bg-[#8B5A2B] p-5 text-white shadow-sm" data-testid="points-available">
          <div className="text-sm text-white/80">Poin Tersedia</div>
          <div className="mt-1 font-heading text-3xl font-bold">{fmtLE(points?.available || 0)}</div>
          <div className="text-xs text-white/70">1 poin = 1 LE</div>
        </div>
        <div className="rounded-2xl border border-[#E5DCC5] bg-white p-5 shadow-sm"><div className="text-sm text-[#5C4A3D]">Total Diperoleh</div><div className="mt-1 font-heading text-2xl font-bold text-[#2C1E16]">{fmtLE(points?.earned || 0)}</div></div>
        <div className="rounded-2xl border border-[#E5DCC5] bg-white p-5 shadow-sm"><div className="text-sm text-[#5C4A3D]">Total Ditukar</div><div className="mt-1 font-heading text-2xl font-bold text-[#2C1E16]">{fmtLE(points?.redeemed || 0)}</div></div>
      </div>

      <div className="mt-4 rounded-2xl border border-[#E5DCC5] bg-white p-5 shadow-sm">
        <div className="flex items-center gap-2 font-heading font-bold text-[#2C1E16]"><Gift size={18} /> Kode Referral Kamu</div>
        <div className="mt-2 flex items-center gap-2">
          <code className="rounded-lg bg-[#EFE6D5] px-3 py-2 font-mono text-lg font-bold text-[#8B5A2B]" data-testid="my-referral-code">{customer.referral_code}</code>
          <Button variant="outline" onClick={() => { navigator.clipboard.writeText(customer.referral_code); toast.success("Kode disalin"); }} className="rounded-xl border-[#8B5A2B] text-[#8B5A2B]"><Copy size={14} /></Button>
        </div>
        <p className="mt-2 text-xs text-[#8B7355]">Bagikan kode ini — kamu dapat poin saat pesanan referral dibayar.</p>
      </div>

      <h2 className="mt-8 font-heading text-lg font-bold text-[#2C1E16]">Riwayat Pesanan</h2>
      {orders.length === 0 ? <div className="mt-3 rounded-2xl border border-dashed border-[#E5DCC5] bg-white p-8 text-center text-[#8B7355]">Belum ada pesanan.</div> : (
        <div className="mt-3 space-y-2">
          {orders.map((o) => (
            <div key={o.id} className="rounded-2xl border border-[#E5DCC5] bg-white p-4 shadow-sm" data-testid={`cust-order-${o.order_number}`}>
              <div className="flex items-center justify-between">
                <div className="font-medium text-[#8B5A2B]">{o.order_number}</div>
                <div className="flex gap-1"><Badge variant="outline" className={PAYMENT_STATUS[o.payment_status]?.color}>{PAYMENT_STATUS[o.payment_status]?.label}</Badge><Badge variant="outline" className={ORDER_STATUS[o.order_status]?.color}>{ORDER_STATUS[o.order_status]?.label}</Badge></div>
              </div>
              <div className="mt-1 text-sm text-[#5C4A3D]">{(o.items || [o.item]).map((it) => `${it?.product_name_snapshot} ×${it?.quantity}`).join(", ")}</div>
              <div className="mt-1 text-sm font-semibold text-[#2C1E16]">{fmtLE(o.total_le)} LE</div>
            </div>
          ))}
        </div>
      )}

      {points?.transactions?.length > 0 && (<>
        <h2 className="mt-8 font-heading text-lg font-bold text-[#2C1E16]">Riwayat Poin</h2>
        <div className="mt-3 overflow-hidden rounded-2xl border border-[#E5DCC5] bg-white shadow-sm">
          <table className="w-full text-sm"><tbody>
            {points.transactions.map((t) => (
              <tr key={t.id} className="border-t border-[#F1EBE0] first:border-0"><td className="px-4 py-2 text-[#5C4A3D]">{(t.created_at || "").slice(0, 10)}</td><td className="px-4 py-2 text-[#8B7355]">{t.reason}</td><td className={`px-4 py-2 text-right font-medium ${t.amount >= 0 ? "text-green-600" : "text-red-600"}`}>{t.amount >= 0 ? "+" : ""}{fmtLE(t.amount)}</td></tr>
            ))}
          </tbody></table>
        </div>
      </>)}
    </div>
  );
}
