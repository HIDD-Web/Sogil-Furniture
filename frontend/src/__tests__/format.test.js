import { fmtLE, fmtIDR, formatMoney } from "../lib/format";

describe("Currency Formatters Suite (EGP/LE & IDR)", () => {
  describe("1. Integer LE values display without .00", () => {
    test("formats whole integers without trailing decimals", () => {
      expect(fmtLE(1900)).toBe("1.900");
      expect(fmtLE(1900.0)).toBe("1.900");
      expect(fmtLE("1900.00")).toBe("1.900");
      expect(fmtLE(750)).toBe("750");
      expect(fmtLE("750")).toBe("750");
      expect(fmtLE(50)).toBe("50");
    });
  });

  describe("2. LE values with insignificant trailing zeros display cleanly", () => {
    test("removes trailing decimal zero from .50 and .40", () => {
      expect(fmtLE(1900.5)).toBe("1.900,5");
      expect(fmtLE("1900.50")).toBe("1.900,5");
      expect(fmtLE(123.4)).toBe("123,4");
      expect(fmtLE("123.40")).toBe("123,4");
      expect(fmtLE(50.0)).toBe("50");
    });
  });

  describe("3. Meaningful fractional LE values remain visible and unchanged", () => {
    test("preserves 2-decimal fractional amounts without rounding", () => {
      expect(fmtLE(1900.75)).toBe("1.900,75");
      expect(fmtLE(750.75)).toBe("750,75");
      expect(fmtLE("750.75")).toBe("750,75");
      expect(fmtLE(0.25)).toBe("0,25");
      expect(fmtLE(16.67)).toBe("16,67");
    });

    test("preserves up to 4 significant decimals when present", () => {
      expect(fmtLE(357.1234)).toBe("357,1234");
      expect(fmtLE(357.5)).toBe("357,5");
    });
  });

  describe("4. Zero and negative values display correctly", () => {
    test("formats zero correctly", () => {
      expect(fmtLE(0)).toBe("0");
      expect(fmtLE("0")).toBe("0");
      expect(fmtLE("0.00")).toBe("0");
      expect(fmtIDR(0)).toBe("Rp0");
      expect(formatMoney(0, "EGP")).toBe("0 LE");
      expect(formatMoney(0, "IDR")).toBe("Rp0");
    });

    test("formats negative values with clean minus sign", () => {
      expect(fmtLE(-1900.5)).toBe("-1.900,5");
      expect(fmtLE(-750)).toBe("-750");
      expect(fmtIDR(-50000)).toBe("-Rp50.000");
      expect(formatMoney(-1900.5, "EGP")).toBe("-1.900,5 LE");
      expect(formatMoney(-50000, "IDR")).toBe("-Rp50.000");
      expect(formatMoney(-50000, "IDR", { space: true })).toBe("-Rp 50.000");
    });
  });

  describe("5. IDR displays as an integer with appropriate separators", () => {
    test("formats rupiah as whole numbers with thousands separators and no decimal rupiah", () => {
      expect(fmtIDR(178500)).toBe("Rp178.500");
      expect(fmtIDR("178500")).toBe("Rp178.500");
      expect(fmtIDR(2000000)).toBe("Rp2.000.000");
      expect(fmtIDR(178500.45)).toBe("Rp178.500"); // No decimal rupiah
      expect(fmtIDR(178500.8)).toBe("Rp178.501");  // Rounds to whole rupiah
    });

    test("supports optional space prefix", () => {
      expect(fmtIDR(178500, { space: true })).toBe("Rp 178.500");
      expect(fmtIDR(2000000, { space: true })).toBe("Rp 2.000.000");
    });
  });

  describe("6. Invalid numeric values do not silently appear as zero", () => {
    test("returns fallback '-' for null, undefined, empty, NaN, and non-numeric strings", () => {
      expect(fmtLE(null)).toBe("-");
      expect(fmtLE(undefined)).toBe("-");
      expect(fmtLE("")).toBe("-");
      expect(fmtLE("abc")).toBe("-");
      expect(fmtLE(NaN)).toBe("-");
      expect(fmtLE(Infinity)).toBe("-");

      expect(fmtIDR(null)).toBe("-");
      expect(fmtIDR(undefined)).toBe("-");
      expect(fmtIDR("")).toBe("-");
      expect(fmtIDR("xyz")).toBe("-");
      expect(fmtIDR(NaN)).toBe("-");

      expect(formatMoney(null, "EGP")).toBe("-");
      expect(formatMoney(undefined, "IDR")).toBe("-");
      expect(formatMoney("", "EGP")).toBe("-");
      expect(formatMoney("invalid", "EGP")).toBe("-");
    });
  });

  describe("7. Currency labels and formatMoney integration", () => {
    test("appends LE suffix for EGP currency", () => {
      expect(formatMoney(1900, "EGP")).toBe("1.900 LE");
      expect(formatMoney(1900.5, "EGP")).toBe("1.900,5 LE");
      expect(formatMoney(750.75, "LE")).toBe("750,75 LE");
    });

    test("supports custom suffix and spacing", () => {
      expect(formatMoney(50, "EGP", { suffix: " EGP" })).toBe("50 EGP");
      expect(formatMoney(178500, "IDR", { space: true })).toBe("Rp 178.500");
      expect(formatMoney(178500, "IDR", { space: false })).toBe("Rp178.500");
    });

    test("handles undefined currency gracefully without adding unexpected label", () => {
      expect(formatMoney(1200, null)).toBe("1.200");
      expect(formatMoney(1200, "")).toBe("1.200");
      expect(formatMoney(1200, "CUSTOMER_CREDIT")).toBe("1.200");
    });
  });

  describe("8. Immutability & Numeric Calculation Safety", () => {
    test("formatting a numeric balance leaves the underlying variable completely unchanged", () => {
      const originalBalance = 750.75;
      const formatted = fmtLE(originalBalance);

      // Verify the formatted string matches display expectations
      expect(formatted).toBe("750,75");

      // Verify original variable remains an exact floating-point number
      expect(typeof originalBalance).toBe("number");
      expect(originalBalance).toBe(750.75);

      // Verify financial arithmetic using the variable is completely unaffected
      const updatedBalance = originalBalance - 250.25;
      expect(updatedBalance).toBe(500.5);
      expect(fmtLE(updatedBalance)).toBe("500,5");
    });
  });

  describe("9. Variance & signed IDR formatting", () => {
    test("formats positive and negative variance correctly with explicit sign", () => {
      const formatVariance = (v) => (v > 0 ? "+" : "") + fmtIDR(v, { space: true });
      expect(formatVariance(900)).toBe("+Rp 900");
      expect(formatVariance(-900)).toBe("-Rp 900");
      expect(formatVariance(0)).toBe("Rp 0");
    });
  });
});
