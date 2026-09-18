import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../../context/AuthContext";
import { formatApiError } from "../../lib/format";
import { Logo } from "../../components/Logo";
import { Button } from "../../components/ui/button";
import { Input } from "../../components/ui/input";
import { Label } from "../../components/ui/label";
import { toast } from "sonner";

export default function AdminLogin() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [storeInfo, setStoreInfo] = useState(null);

  React.useEffect(() => {
    api.get("/store-info").then((r) => setStoreInfo(r.data)).catch(() => {});
  }, []);

  const submit = async (e) => {
    e.preventDefault();
    setLoading(true);
    try {
      await login(email, password);
      toast.success("Berhasil masuk");
      navigate("/admin");
    } catch (err) {
      toast.error(formatApiError(err.response?.data?.detail) || "Gagal masuk");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-[#F9F6F0] px-4">
      <div className="w-full max-w-sm rounded-2xl border border-[#E5DCC5] bg-white p-7 shadow-sm">
        <div className="flex justify-center"><Logo size={48} logoUrl={storeInfo?.logo_url} /></div>
        <h1 className="mt-5 text-center font-heading text-xl font-bold text-[#2C1E16]">Dashboard Admin</h1>
        <p className="mt-1 text-center text-sm text-[#8B7355]">Masuk untuk mengelola pesanan & produk</p>
        <form onSubmit={submit} className="mt-6 space-y-4">
          <div>
            <Label className="mb-1.5 block text-sm">Email</Label>
            <Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} data-testid="login-email" className="h-12 bg-white" required />
          </div>
          <div>
            <Label className="mb-1.5 block text-sm">Kata Sandi</Label>
            <Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} data-testid="login-password" className="h-12 bg-white" required />
          </div>
          <Button type="submit" disabled={loading} data-testid="login-submit" className="h-12 w-full rounded-xl bg-[#8B5A2B] hover:bg-[#6B4423]">
            {loading ? "Memproses..." : "Masuk"}
          </Button>
        </form>
      </div>
    </div>
  );
}
