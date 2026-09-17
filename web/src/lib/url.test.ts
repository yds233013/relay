import { describe, expect, it } from "vitest";

import { buildPath } from "./url";

describe("buildPath", () => {
  it("omits empty values and encodes the rest", () => {
    expect(
      buildPath("/issues", { status: "open", severity: undefined, nature: "", cursor: 0 }),
    ).toBe("/issues?status=open&cursor=0");
    expect(buildPath("/x", { rule: "RECON.R3", grain: "a=b&c" })).toBe(
      "/x?rule=RECON.R3&grain=a%3Db%26c",
    );
    expect(buildPath("/plain")).toBe("/plain");
  });
});
