import "server-only";

import { isPublicDemoEnv } from "@/lib/config";

/**
 * Whether this process is serving the public portfolio demo.
 *
 * Used to hide what the API would refuse, so a visitor meets a short explanation instead of a
 * failed action. It is never the protection itself: `relay.api.demo_policy` refuses those requests
 * server-side whether or not anything is hidden here.
 */
export function isPublicDemo(): boolean {
  return isPublicDemoEnv(process.env);
}

/** The one sentence used wherever an action is unavailable in the demo. */
export const DEMO_VIEW_ONLY = "View-only in public demo";
