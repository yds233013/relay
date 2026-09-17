/**
 * Server-side configuration for the web app.
 *
 * RELAY_API_URL is read on the server only (it has no NEXT_PUBLIC_ prefix, so Next.js never inlines
 * it into browser bundles). The browser never calls the API directly in M0.
 */

export interface ServerConfig {
  /** Base URL of the Relay API, always ending in "/". */
  readonly apiBaseUrl: URL;
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
  return { apiBaseUrl: url };
}
