import { type NextRequest, NextResponse } from "next/server";

import { contentSecurityPolicy } from "@/lib/csp";

/**
 * Sets a nonce-based Content Security Policy on every rendered page (SEC-15). Next.js reads the
 * nonce out of this header and applies it to its own scripts and styles; every page in Relay is
 * dynamically rendered, so each response carries a fresh one.
 */
export function proxy(request: NextRequest): NextResponse {
  const nonce = crypto.randomUUID().replaceAll("-", "");
  const policy = contentSecurityPolicy(nonce, process.env.NODE_ENV === "development");
  const headers = new Headers(request.headers);
  headers.set("x-nonce", nonce);
  headers.set("Content-Security-Policy", policy);
  const response = NextResponse.next({ request: { headers } });
  response.headers.set("Content-Security-Policy", policy);
  return response;
}

export const config = {
  matcher: [
    {
      // Static assets and prefetches need no policy of their own.
      source: "/((?!_next/static|_next/image|favicon.ico).*)",
      missing: [
        { type: "header", key: "next-router-prefetch" },
        { type: "header", key: "purpose", value: "prefetch" },
      ],
    },
  ],
};
