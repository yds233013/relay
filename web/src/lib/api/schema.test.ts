/** The committed TypeScript API types match the committed OpenAPI document (`npm run api:types`). */
import { readFileSync } from "node:fs";
import { join } from "node:path";

import openapiTS, { astToString } from "openapi-typescript";
import { describe, expect, it } from "vitest";

describe("generated API types", () => {
  it("are up to date with openapi.json", async () => {
    const document = JSON.parse(
      readFileSync(join(__dirname, "openapi.json"), "utf8"),
    ) as Parameters<typeof openapiTS>[0];
    const generated = astToString(await openapiTS(document));
    const committed = readFileSync(join(__dirname, "schema.d.ts"), "utf8");
    // The CLI prepends a banner comment; compare the declarations only.
    expect(generated.length).toBeGreaterThan(10_000);
    expect(committed.endsWith(generated)).toBe(true);
  });
});
