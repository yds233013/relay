/**
 * Development identity: the selected seeded user is kept in an HTTP-only cookie and sent to the API
 * as `X-Relay-User` by the server. This is not authentication (docs/security-and-correctness.md).
 */
import "server-only";

import { cookies } from "next/headers";

export const USER_COOKIE = "relay_dev_user";

const EMAIL = /^[^\s@]{1,64}@[^\s@]{1,190}$/;

export function isPlausibleEmail(value: string): boolean {
  return EMAIL.test(value);
}

export async function currentUserEmail(): Promise<string | null> {
  const value = (await cookies()).get(USER_COOKIE)?.value ?? null;
  return value !== null && isPlausibleEmail(value) ? value : null;
}
