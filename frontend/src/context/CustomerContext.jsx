import React, { createContext, useContext, useEffect, useState } from "react";
import api from "../lib/api";

const CustomerContext = createContext(null);

export const CustomerProvider = ({ children }) => {
  const [customer, setCustomer] = useState(null);
  const [checked, setChecked] = useState(false);

  useEffect(() => {
    const token = localStorage.getItem("customer_token");
    if (!token) {
      setCustomer(null);
      setChecked(true);
      return;
    }

    api.get("/customer/me")
      .then((r) => setCustomer(r.data))
      .catch(() => {
        localStorage.removeItem("customer_token");
        setCustomer(null);
      })
      .finally(() => setChecked(true));
  }, []);

  const register = async (payload) => {
    const { data } = await api.post("/customer/register", payload);
    if (data?.token) {
      localStorage.setItem("customer_token", data.token);
    }
    setCustomer(data);
    setChecked(true);
    return data;
  };

  const login = async (identifier, password) => {
    const { data } = await api.post("/customer/login", { identifier, password });
    if (data?.token) {
      localStorage.setItem("customer_token", data.token);
    }
    setCustomer(data);
    setChecked(true);
    return data;
  };

  const logout = async () => {
    localStorage.removeItem("customer_token");
    try { await api.post("/customer/logout"); } catch (e) {}
    setCustomer(null);
    setChecked(true);
  };

  const customerLoading = !checked;
  const customerAuthChecked = checked;

  return (
    <CustomerContext.Provider
      value={{
        customer,
        checked,
        customerLoading,
        customerAuthChecked,
        register,
        login,
        logout,
        setCustomer,
      }}
    >
      {children}
    </CustomerContext.Provider>
  );
};

export const useCustomer = () => useContext(CustomerContext);
