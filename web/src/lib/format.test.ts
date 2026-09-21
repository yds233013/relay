import { describe, expect, it } from "vitest";

import { formatAmount, humanize, param, splitTitle } from "./format";

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

describe("splitTitle", () => {
  it("lifts the sentence out of a title whose tail is exactly its subjects", () => {
    expect(
      splitTitle("Trial balance control vs GL detail: recon:R1:account=6200", [
        "recon:R1:account=6200",
      ]),
    ).toEqual({
      headline: "Trial balance control vs GL detail",
      subject: "recon:R1:account=6200",
    });
  });

  it("joins several subjects in the order the payload gives them", () => {
    expect(
      splitTitle("Possible duplicate parties: party:a, party:b", ["party:a", "party:b"]),
    ).toEqual({ headline: "Possible duplicate parties", subject: "party:a, party:b" });
  });

  it("leaves a title whole rather than cutting it somewhere arbitrary", () => {
    expect(splitTitle("A manual issue", [])).toEqual({
      headline: "A manual issue",
      subject: null,
    });
    expect(splitTitle("A title that does not end in its subjects", ["party:a"])).toEqual({
      headline: "A title that does not end in its subjects",
      subject: null,
    });
    expect(splitTitle(": party:a", ["party:a"])).toEqual({
      headline: ": party:a",
      subject: null,
    });
  });
});
