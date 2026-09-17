/**
 * Helpers for Server Functions: read form fields, validate ids, and build the redirect that carries
 * an outcome message. Authorization is never decided here; the API decides it.
 */
import "server-only";

import { ApiError } from "@/lib/api/client";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function text(formData: FormData, name: string): string {
  const value = formData.get(name);
  return typeof value === "string" ? value : "";
}

export function texts(formData: FormData, name: string): string[] {
  return formData.getAll(name).filter((value): value is string => typeof value === "string");
}

export function isId(value: string): boolean {
  return UUID.test(value);
}

export function id(formData: FormData, name: string): string {
  const value = text(formData, name);
  if (!isId(value)) {
    throw new Error(`invalid ${name}`);
  }
  return value;
}

export function samePath(value: string, fallback: string): string {
  return value.startsWith("/") && !value.startsWith("//") ? value : fallback;
}

export function withMessage(path: string, key: "error" | "notice", message: string): string {
  const [base, query = ""] = path.split("?", 2);
  const params = new URLSearchParams(query);
  params.delete("error");
  params.delete("notice");
  params.set(key, message.slice(0, 300));
  return `${base}?${params.toString()}`;
}

/** The API's message for an expected failure; anything else is rethrown to the error boundary. */
export function messageOf(error: unknown): string {
  if (error instanceof ApiError) {
    return error.message;
  }
  throw error;
}
