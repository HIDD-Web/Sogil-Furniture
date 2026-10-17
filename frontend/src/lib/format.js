export const fmtLE = (v) => {
  if (v == null || v === "") return "-";
  const n = Number(v);
  if (!Number.isFinite(n)) return "-";
  return n.toLocaleString("de-DE", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 4,
  });
};

export const fmtIDR = (v, options = {}) => {
  if (v == null || v === "") return "-";
  const n = Number(v);
  if (!Number.isFinite(n)) return "-";
  const prefix = options.prefix != null ? options.prefix : (options.space ? "Rp " : "Rp");
  const rounded = Math.round(n);
  const sign = rounded < 0 ? "-" : "";
  return `${sign}${prefix}${Math.abs(rounded).toLocaleString("de-DE")}`;
};

export const formatMoney = (v, cur = "EGP", options = {}) => {
  if (v == null || v === "") return "-";
  const n = Number(v);
  if (!Number.isFinite(n)) return "-";

  const upperCur = cur != null ? String(cur).trim().toUpperCase() : "";
  if (upperCur === "IDR") {
    return fmtIDR(n, options);
  }

  const numStr = n.toLocaleString("de-DE", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 4,
  });
  const suffix = options.suffix != null
    ? options.suffix
    : (upperCur === "EGP" || upperCur === "LE" ? " LE" : (upperCur && upperCur !== "CUSTOMER_CREDIT" ? ` ${upperCur}` : ""));
  return `${numStr}${suffix}`;
};

export const formatApiError = (detail) => {
  if (detail == null) return "Terjadi kesalahan. Silakan coba lagi.";
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail))
    return detail.map((e) => (e && typeof e.msg === "string" ? e.msg : JSON.stringify(e))).join(" ");
  if (detail && typeof detail.msg === "string") return detail.msg;
  return String(detail);
};

export const copyToClipboard = async (text) => {
  if (!text) return false;
  try {
    if (navigator?.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch (e) {}

  try {
    const textArea = document.createElement("textarea");
    textArea.value = text;
    textArea.style.position = "fixed";
    textArea.style.left = "-9999px";
    textArea.style.top = "0";
    document.body.appendChild(textArea);
    textArea.focus();
    textArea.select();
    const successful = document.execCommand("copy");
    document.body.removeChild(textArea);
    return successful;
  } catch (err) {
    return false;
  }
};
