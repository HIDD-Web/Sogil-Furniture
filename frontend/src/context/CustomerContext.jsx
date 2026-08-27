import React, { createContext, useContext, useEffect, useState } from "react";
import api from "../lib/api";

const CustomerContext = createContext(null);

export const CustomerProvider = ({ children }) => {
  const [customer, setCustomer] = useState(null);
  const [checked, setChecked] = useState(false);

  useEffect(() => {
    api.get("/customer/me").then((r) => setCustomer(r.data)).catch(() => setCustomer(false)).finally(() => setChecked(true));
  }, []);

  const register = async (payload) => { const { data } = await api.post("/customer/register", payload); setCustomer(data); return data; };
  const login = async (identifier, password) => { const { data } = await api.post("/customer/login", { identifier, password }); setCustomer(data); return data; };
  const logout = async () => { try { await api.post("/customer/logout"); } catch (e) {} setCustomer(false); };

  return <CustomerContext.Provider value={{ customer, checked, register, login, logout, setCustomer }}>{children}</CustomerContext.Provider>;
};

export const useCustomer = () => useContext(CustomerContext);
