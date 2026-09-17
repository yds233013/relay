import { describe, expect, it } from "vitest";

import { formatAmount, humanize, param } from "./format";

describe("formatAmount", () => {
  it.each([
    ["0", "0", false],
    ["12.50", "12.50", false],
    ["1234.00", "1,234.00", false],
    ["-2731.45", "(2,731.45)", true],
    ["217212.85", "217,212.85", false],
    ["-84512.00", "(84,512.00)", true],
    ["1000000", "1,000,000", false],
    ["-0.00", "0.00", false],
  ])("formats %s as %s", (value, text, negative) => {
    expect(formatAmount(value)).toEqual({ text, negative });
  });

  it("leaves non-decimal strings unchanged instead of guessing", () => {
    expect(formatAmount("n/a")).toEqual({ text: "n/a", negative: false });
    expect(formatAmount("1e5")).toEqual({ text: "1e5", negative: false });
  });
});

describe("helpers", () => {
  it("humanizes enum values", () => {
    expect(humanize("legacy_coa")).toBe("Legacy coa");
    expect(humanize("RECON.R3")).toBe("RECON R3");
  });

  it("takes the first repeated search parameter", () => {
    expect(param(["a", "b"])).toBe("a");
    expect(param(undefined)).toBeUndefined();
  });
});
