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

async function problem(response: Response): Promise<ApiError> {
  let code = "http.error";
  let detail = response.statusText;
  try {
    const body = (await response.json()) as { code?: string; detail?: string; title?: string };
    code = body.code ?? code;
    detail = body.detail ?? body.title ?? detail;
  } catch {
    // Non-JSON error bodies keep the status text.
  }
  return new ApiError(response.status, code, detail);
}

async function request(method: string, path: string, query: Query, body?: unknown) {
  const config = parseServerConfig(process.env);
  const user = await currentUserEmail();
  if (user === null && path !== "/api/v1/dev/users") {
    redirect("/select-user");
  }
  const url = new URL(buildPath(path, query).replace(/^\//, ""), config.apiBaseUrl);
  const headers: Record<string, string> = { Accept: "application/json" };
  if (user) {
    headers["X-Relay-User"] = user;
  }
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
  }
  const response = await fetch(url, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
    cache: "no-store",
  });
  if (response.status === 401) {
    redirect("/select-user");
  }
  if (!response.ok) {
    throw await problem(response);
  }
  return response;
}

/** GET a Relay API resource as the signed-in development user. */
export async function apiGet<T>(path: string, query: Query = {}): Promise<T> {
  return (await (await request("GET", path, query)).json()) as T;
}

/**
 * Send a mutation as the signed-in development user. Only Server Functions call this; the API
 * decides authorization, so a hidden button is never the only protection.
 */
export async function apiSend<T>(method: "POST" | "PUT", path: string, body: unknown): Promise<T> {
  return (await (await request(method, path, {}, body)).json()) as T;
}
