export const fmtLE = (v) => {
  const n = Math.round(Number(v) || 0);
  return n.toLocaleString("de-DE");
};

export const fmtIDR = (v) => {
  const n = Math.round(Number(v) || 0);
  return "Rp" + n.toLocaleString("de-DE");
};

export const formatApiError = (detail) => {
  if (detail == null) return "Terjadi kesalahan. Silakan coba lagi.";
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail))
    return detail.map((e) => (e && typeof e.msg === "string" ? e.msg : JSON.stringify(e))).join(" ");
  if (detail && typeof detail.msg === "string") return detail.msg;
  return String(detail);
};
