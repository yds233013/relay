/**
 * Server-side Relay API access. Runs only in Server Components and Server Functions: the API URL
 * and the development identity header never reach the browser (decision D-14).
 *
 * Response types come from the generated OpenAPI schema (`schema.d.ts`), never hand-written.
 */
import "server-only";

import { redirect } from "next/navigation";

import { parseServerConfig } from "@/lib/config";
import { buildPath, type Query } from "@/lib/url";
import { currentUserEmail } from "@/lib/session";

import type { components } from "./schema";

export type Schemas = components["schemas"];
export { buildPath };

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** GET a Relay API resource as the signed-in development user. */
export async function apiGet<T>(path: string, query: Query = {}): Promise<T> {
  const config = parseServerConfig(process.env);
  const user = await currentUserEmail();
  if (user === null && path !== "/api/v1/dev/users") {
    redirect("/select-user");
  }
  const url = new URL(buildPath(path, query).replace(/^\//, ""), config.apiBaseUrl);
  const response = await fetch(url, {
    headers: user ? { "X-Relay-User": user, Accept: "application/json" } : {},
    cache: "no-store",
  });
  if (response.status === 401) {
    redirect("/select-user");
  }
  if (!response.ok) {
    let code = "http.error";
    let detail = response.statusText;
    try {
      const problem = (await response.json()) as { code?: string; detail?: string; title?: string };
      code = problem.code ?? code;
      detail = problem.detail ?? problem.title ?? detail;
    } catch {
      // Non-JSON error bodies keep the status text.
    }
    throw new ApiError(response.status, code, detail);
  }
  return (await response.json()) as T;
}
