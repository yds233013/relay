import { describe, expect, it } from "vitest";

import { contentSecurityPolicy } from "./csp";

describe("content security policy", () => {
  it("allows scripts only by nonce, and never inline", () => {
    const policy = contentSecurityPolicy("abc123", false);
    expect(policy).toContain("script-src 'self' 'nonce-abc123' 'strict-dynamic'");
    expect(policy).not.toContain("unsafe-inline");
    expect(policy).not.toContain("unsafe-eval");
  });

  it("denies framing, plugins, base tags and third-party origins", () => {
    const policy = contentSecurityPolicy("abc123", false);
    for (const directive of [
      "default-src 'self'",
      "object-src 'none'",
      "base-uri 'none'",
      "frame-ancestors 'none'",
      "frame-src 'none'",
      "connect-src 'self'",
    ]) {
      expect(policy).toContain(directive);
    }
  });

  it("allows eval in development only, where React uses it for error stacks", () => {
    expect(contentSecurityPolicy("abc123", true)).toContain("'unsafe-eval'");
  });
});
