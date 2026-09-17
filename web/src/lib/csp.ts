/**
 * Content Security Policy for the web app (SEC-15).
 *
 * Scripts are allowed only by per-request nonce plus `strict-dynamic`, never `unsafe-inline`.
 * Nothing in Relay loads third-party scripts, fonts, images or frames, so every other directive
 * stays at `'self'` or `'none'`. `connect-src 'self'` covers Server Function calls back to the app;
 * the browser never calls the Relay API directly.
 */
export function contentSecurityPolicy(nonce: string, development: boolean): string {
  // React reconstructs server stacks with eval in development only; production needs no eval.
  const script = `'self' 'nonce-${nonce}' 'strict-dynamic'${development ? " 'unsafe-eval'" : ""}`;
  return [
    "default-src 'self'",
    `script-src ${script}`,
    `style-src 'self' 'nonce-${nonce}'`,
    "img-src 'self' data:",
    "font-src 'self'",
    "connect-src 'self'",
    "object-src 'none'",
    "base-uri 'none'",
    "form-action 'self'",
    "frame-ancestors 'none'",
    "frame-src 'none'",
  ].join("; ");
}
