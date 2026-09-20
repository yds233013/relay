/**
 * Server-side configuration for the web app.
 *
 * RELAY_API_URL is read on the server only (it has no NEXT_PUBLIC_ prefix, so Next.js never inlines
 * it into browser bundles). The browser never calls the API directly in M0.
 */

export interface ServerConfig {
  /** Base URL of the Relay API, always ending in "/". */
  readonly apiBaseUrl: URL;
  /**
   * Whether this process is the public portfolio demo (the API runs with RELAY_ENV=demo).
   *
   * Nobody signs in: the API resolves every caller to its read-only demo visitor, so the web app
   * must not ask for an identity or send one. It also hides the actions the API would refuse, so
   * a visitor meets "view-only in public demo" rather than a failure.
   */
  readonly publicDemo: boolean;
}

export class ConfigError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ConfigError";
  }
}

export function parseServerConfig(env: Readonly<Record<string, string | undefined>>): ServerConfig {
  const raw = env.RELAY_API_URL?.trim();
  if (!raw) {
    throw new ConfigError("RELAY_API_URL is not set");
  }

  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    throw new ConfigError("RELAY_API_URL is not a valid absolute URL");
  }

  if (url.protocol !== "http:" && url.protocol !== "https:") {
    throw new ConfigError("RELAY_API_URL must use http or https");
  }
  if (url.username || url.password) {
    throw new ConfigError("RELAY_API_URL must not contain credentials");
  }
  if (url.search || url.hash) {
    throw new ConfigError("RELAY_API_URL must not contain a query string or fragment");
  }
  if (!url.pathname.endsWith("/")) {
    url.pathname = `${url.pathname}/`;
  }
  return { apiBaseUrl: url, publicDemo: isPublicDemoEnv(env) };
}

/**
 * Whether this process serves the public demo, read on its own.
 *
 * Separate from `parseServerConfig` because the root layout needs it during the build, when
 * RELAY_API_URL is not set and parsing the whole configuration would throw. Only an explicit "1"
 * or "true" turns it on; anything else, including an empty value, is off — a deployment that
 * passes the variable unconditionally must not become a public demo by accident.
 */
export function isPublicDemoEnv(env: Readonly<Record<string, string | undefined>>): boolean {
  const value = env.RELAY_PUBLIC_DEMO?.trim().toLowerCase();
  return value === "1" || value === "true";
}
