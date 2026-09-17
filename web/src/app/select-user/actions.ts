"use server";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { isPlausibleEmail, USER_COOKIE } from "@/lib/session";

function safeReturnPath(value: FormDataEntryValue | null): string {
  const path = typeof value === "string" ? value : "";
  // Only same-site relative paths: no scheme, no protocol-relative "//host".
  return path.startsWith("/") && !path.startsWith("//") ? path : "/migrations";
}

export async function selectUser(formData: FormData): Promise<void> {
  const email = formData.get("email");
  if (typeof email !== "string" || !isPlausibleEmail(email)) {
    redirect("/select-user");
  }
  (await cookies()).set(USER_COOKIE, email, {
    httpOnly: true,
    sameSite: "lax",
    path: "/",
    secure: process.env.NODE_ENV === "production",
  });
  redirect(safeReturnPath(formData.get("returnTo")));
}
