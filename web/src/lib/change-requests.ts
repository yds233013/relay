/** Server-side helpers for Server Functions that create change requests. Not callable from clients. */
import "server-only";

import { apiSend, type Schemas } from "@/lib/api/client";
import { isId, texts } from "@/lib/form-data";

/** Create a draft and submit it with its justification; returns the change request id. */
export async function draftAndSubmit(
  migrationId: string,
  body: Record<string, unknown>,
  justification: string,
): Promise<string> {
  const change = await apiSend<Schemas["ChangeRequestOut"]>(
    "POST",
    `/api/v1/migrations/${migrationId}/change-requests`,
    body,
  );
  try {
    await apiSend("POST", `/api/v1/change-requests/${change.id}/submit`, { justification });
  } catch (error) {
    // Submission was refused (for example a missing justification): do not leave a stray draft.
    await apiSend("POST", `/api/v1/change-requests/${change.id}/withdraw`, {
      reason: "submission refused",
    }).catch(() => undefined);
    throw error;
  }
  return change.id;
}

/** Issues a form names as the evidence for a change (they wait for verification once applied). */
export function issueRefs(formData: FormData): { kind: "issue"; issue_id: string }[] {
  return texts(formData, "evidenceIssueId")
    .filter(isId)
    .slice(0, 20)
    .map((issueId) => ({ kind: "issue", issue_id: issueId }));
}
