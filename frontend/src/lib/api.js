import axios from "axios";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
export const API_BASE = `${BACKEND_URL}/api`;

const api = axios.create({
  baseURL: API_BASE,
  withCredentials: true,
});

api.interceptors.request.use((config) => {
  const adminToken = localStorage.getItem("admin_token");
  const customerToken = localStorage.getItem("customer_token");

  if (customerToken) {
    config.headers["X-Customer-Authorization"] = `Bearer ${customerToken}`;
  }

  if (adminToken && !config.headers.Authorization) {
    config.headers.Authorization = `Bearer ${adminToken}`;
  } else if (customerToken && !config.headers.Authorization) {
    config.headers.Authorization = `Bearer ${customerToken}`;
  }
  return config;
});

export const imgUrl = (path) => {
  if (!path) return "";
  if (path.startsWith("http")) return path;
  if (path.startsWith("/pricelists/")) return path;
  return `${BACKEND_URL}${path}`;
};

export default api;
