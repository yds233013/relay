/**
 * FC-15 guard: the web app formats server-provided amount strings and never computes with money.
 * Numeric parsing and rounding functions are not allowed anywhere in the app source; integer
 * parsing (`Number.parseInt`) is allowed for page cursors.
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";

import { describe, expect, it } from "vitest";

const ROOT = join(__dirname, "..");
const FORBIDDEN = [
  /\bparseFloat\s*\(/,
  /\bNumber\.parseFloat\s*\(/,
  /(?<![.\w])Number\s*\(/,
  /\.toFixed\s*\(/,
  /\bMath\.(round|floor|ceil|trunc|abs|sign|fround)\s*\(/,
  /\bIntl\.NumberFormat\b/,
  /\bBigInt\s*\(/,
];

function sourceFiles(directory: string): string[] {
  return readdirSync(directory).flatMap((name) => {
    const path = join(directory, name);
    if (statSync(path).isDirectory()) {
      return sourceFiles(path);
    }
    return /\.(ts|tsx)$/.test(name) && !name.endsWith(".test.ts") && !name.endsWith(".d.ts")
      ? [path]
      : [];
  });
}

describe("no money arithmetic in the web app", () => {
  it("scans real files", () => {
    expect(sourceFiles(ROOT).length).toBeGreaterThan(10);
  });

  it("uses no numeric parsing or rounding functions", () => {
    const offenders = sourceFiles(ROOT).flatMap((path) => {
      const text = readFileSync(path, "utf8");
      return FORBIDDEN.filter((pattern) => pattern.test(text)).map(
        (pattern) => `${relative(ROOT, path)}: ${pattern.source}`,
      );
    });
    expect(offenders).toEqual([]);
  });
});
