import { useEffect, useState } from "react";
import "@/App.css";
import { BrowserRouter, Routes, Route, useLocation } from "react-router-dom";
import { Toaster } from "sonner";
import api from "./lib/api";
import { AuthProvider } from "./context/AuthContext";
import { LanguageProvider } from "./context/LanguageContext";
import { CartProvider } from "./context/CartContext";
import { Header } from "./components/Header";
import { Footer } from "./components/Footer";

import Home from "./pages/Home";
import Catalog from "./pages/Catalog";
import ProductConfigure from "./pages/ProductConfigure";
import Cart from "./pages/Cart";
import Checkout from "./pages/Checkout";
import OrderConfirmation from "./pages/OrderConfirmation";
import CaraPesan from "./pages/CaraPesan";
import Kontak from "./pages/Kontak";

import AdminLogin from "./pages/admin/AdminLogin";
import AdminLayout from "./pages/admin/AdminLayout";
import AdminOverview from "./pages/admin/AdminOverview";
import AdminOrders from "./pages/admin/AdminOrders";
import AdminOrderDetail from "./pages/admin/AdminOrderDetail";
import AdminProducts from "./pages/admin/AdminProducts";
import AdminProductEdit from "./pages/admin/AdminProductEdit";
import AdminSettings from "./pages/admin/AdminSettings";
import AdminAnalytics from "./pages/admin/AdminAnalytics";
import AdminFinance from "./pages/admin/AdminFinance";
import AdminAdmins from "./pages/admin/AdminAdmins";
import AdminDiscounts from "./pages/admin/AdminDiscounts";

function CustomerShell({ children }) {
  const [store, setStore] = useState(null);
  useEffect(() => { api.get("/store-info").then((r) => setStore(r.data)).catch(() => {}); }, []);
  return (
    <div className="flex min-h-screen flex-col">
      <Header storeInfo={store} />
      <div className="flex-1">{children}</div>
      <Footer storeInfo={store} />
    </div>
  );
}

function Layout() {
  const location = useLocation();
  const isAdmin = location.pathname.startsWith("/admin");
  if (isAdmin) {
    return (
      <Routes>
        <Route path="/admin/login" element={<AdminLogin />} />
        <Route path="/admin" element={<AdminLayout />}>
          <Route index element={<AdminOverview />} />
          <Route path="orders" element={<AdminOrders />} />
          <Route path="orders/:id" element={<AdminOrderDetail />} />
          <Route path="products" element={<AdminProducts />} />
          <Route path="products/:id" element={<AdminProductEdit />} />
          <Route path="analytics" element={<AdminAnalytics />} />
          <Route path="finance" element={<AdminFinance />} />
          <Route path="discounts" element={<AdminDiscounts />} />
          <Route path="admins" element={<AdminAdmins />} />
          <Route path="settings" element={<AdminSettings />} />
        </Route>
      </Routes>
    );
  }
  return (
    <CustomerShell>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/produk" element={<Catalog />} />
        <Route path="/produk/:slug" element={<ProductConfigure />} />
        <Route path="/keranjang" element={<Cart />} />
        <Route path="/checkout" element={<Checkout />} />
        <Route path="/pesanan/:id" element={<OrderConfirmation />} />
        <Route path="/cara-pesan" element={<CaraPesan />} />
        <Route path="/kontak" element={<Kontak />} />
      </Routes>
    </CustomerShell>
  );
}

function App() {
  return (
    <div className="App">
      <LanguageProvider>
        <AuthProvider>
          <CartProvider>
            <BrowserRouter>
              <Layout />
              <Toaster position="top-center" richColors />
            </BrowserRouter>
          </CartProvider>
        </AuthProvider>
      </LanguageProvider>
    </div>
  );
}

export default App;
