import React, { createContext, useContext, useEffect, useState } from "react";
import api from "../lib/api";

const AuthContext = createContext(null);

export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(null); // null=checking, false=none, obj=auth
  const [checked, setChecked] = useState(false);

  useEffect(() => {
    api.get("/auth/me")
      .then((r) => setUser(r.data))
      .catch(() => setUser(false))
      .finally(() => setChecked(true));
  }, []);

  const login = async (email, password) => {
    const { data } = await api.post("/auth/login", { email, password });
    if (data?.token) {
      localStorage.setItem("admin_token", data.token);
    }
    setUser(data);
    return data;
  };

  const logout = async () => {
    localStorage.removeItem("admin_token");
    try { await api.post("/auth/logout"); } catch (e) {}
    setUser(false);
  };

  return (
    <AuthContext.Provider value={{ user, checked, login, logout, setUser }}>
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => useContext(AuthContext);
