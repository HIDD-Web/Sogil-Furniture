import "@/App.css";
import React, { useEffect, useState } from "react";
import { BrowserRouter, Routes, Route, useLocation } from "react-router-dom";
import { Toaster } from "sonner";
import api from "./lib/api";
import { AuthProvider } from "./context/AuthContext";
import { LanguageProvider } from "./context/LanguageContext";
import { CartProvider } from "./context/CartContext";
import { CustomerProvider } from "./context/CustomerContext";
import { Header } from "./components/Header";
import { Footer } from "./components/Footer";

import Home from "./pages/Home";
import Catalog from "./pages/Catalog";
import CategoryPage from "./pages/CategoryPage";
import ProductConfigure from "./pages/ProductConfigure";
import Cart from "./pages/Cart";
import Checkout from "./pages/Checkout";
import OrderConfirmation from "./pages/OrderConfirmation";
import CaraPesan from "./pages/CaraPesan";
import Kontak from "./pages/Kontak";
import CustomerAccount from "./pages/CustomerAccount";
import GuestTrackOrder from "./pages/GuestTrackOrder";

import AdminLogin from "./pages/admin/AdminLogin";
import AdminLayout from "./pages/admin/AdminLayout";
import AdminOverview from "./pages/admin/AdminOverview";
import AdminOrders from "./pages/admin/AdminOrders";
import AdminOrderDetail from "./pages/admin/AdminOrderDetail";
import AdminProducts from "./pages/admin/AdminProducts";
import AdminProductEdit from "./pages/admin/AdminProductEdit";
import AdminCategories from "./pages/admin/AdminCategories";
import AdminCustomRequests from "./pages/admin/AdminCustomRequests";
import AdminSettings from "./pages/admin/AdminSettings";
import AdminAnalytics from "./pages/admin/AdminAnalytics";
import AdminFinance from "./pages/admin/AdminFinance";
import AdminFinanceStats from "./pages/admin/AdminFinanceStats";
import AdminExport from "./pages/admin/AdminExport";
import AdminAdmins from "./pages/admin/AdminAdmins";
import AdminDiscounts from "./pages/admin/AdminDiscounts";
import AdminReferrals from "./pages/admin/AdminReferrals";
import AdminCustomers from "./pages/admin/AdminCustomers";
import CustomOrderPage from "./pages/CustomOrderPage";

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

  useEffect(() => {
    const link = document.getElementById("manifest-link");
    const themeMeta = document.querySelector('meta[name="theme-color"]');
    if (!link) return;

    if (isAdmin) {
      link.setAttribute("href", "/manifest-admin.json");
      if (themeMeta) themeMeta.setAttribute("content", "#2C1E16");
    } else {
      link.setAttribute("href", "/manifest.json");
      if (themeMeta) themeMeta.setAttribute("content", "#8B5A2B");
    }
  }, [isAdmin]);

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
          <Route path="categories" element={<AdminCategories />} />
          <Route path="custom-requests" element={<AdminCustomRequests />} />
          <Route path="analytics" element={<AdminAnalytics />} />
          <Route path="finance" element={<AdminFinance />} />
          <Route path="finance/statistics" element={<AdminFinanceStats />} />
          <Route path="export" element={<AdminExport />} />
          <Route path="discounts" element={<AdminDiscounts />} />
          <Route path="referrals" element={<AdminReferrals />} />
          <Route path="customers" element={<AdminCustomers />} />
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

        <Route
          path="/produk/kategori/:category"
          element={<CategoryPage />}
        />
        
        <Route path="/produk/:slug" element={<ProductConfigure />} />
        <Route path="/request-custom" element={<CustomOrderPage />} />
        <Route path="/custom-order" element={<CustomOrderPage />} />
        <Route path="/keranjang" element={<Cart />} />
        <Route path="/checkout" element={<Checkout />} />
        <Route path="/pesanan/:id" element={<OrderConfirmation />} />
        <Route path="/cara-pesan" element={<CaraPesan />} />
        <Route path="/kontak" element={<Kontak />} />
        <Route path="/akun" element={<CustomerAccount />} />
        <Route path="/lacak" element={<GuestTrackOrder />} />
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
            <CustomerProvider>
              <BrowserRouter>
                <Layout />
                <Toaster position="top-center" richColors />
              </BrowserRouter>
            </CustomerProvider>
          </CartProvider>
        </AuthProvider>
      </LanguageProvider>
    </div>
  );
}

export default App;
