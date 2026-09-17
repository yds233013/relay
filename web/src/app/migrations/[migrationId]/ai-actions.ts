"use server";

/** Server Functions for AI investigations. The API enforces consent, permissions and verification. */
import { redirect } from "next/navigation";

import { apiSend, type Schemas } from "@/lib/api/client";
import { id, isId, messageOf, samePath, text, withMessage } from "@/lib/form-data";

export async function startInvestigation(formData: FormData): Promise<void> {
  const migrationId = id(formData, "migrationId");
  const issueId = text(formData, "issueId");
  const back = samePath(text(formData, "returnTo"), `/migrations/${migrationId}`);
  let investigationId: string;
  try {
    const investigation = await apiSend<Schemas["InvestigationOut"]>(
      "POST",
      `/api/v1/migrations/${migrationId}/investigations`,
      { question: text(formData, "question"), issue_id: isId(issueId) ? issueId : null },
    );
    investigationId = investigation.id;
  } catch (error) {
    redirect(withMessage(back, "error", messageOf(error)));
  }
  redirect(`/migrations/${migrationId}/investigations/${investigationId}`);
}

export async function reviewFinding(formData: FormData): Promise<void> {
  const migrationId = id(formData, "migrationId");
  const investigationId = id(formData, "investigationId");
  const findingId = id(formData, "findingId");
  const decision = text(formData, "decision") === "accept" ? "accept" : "dismiss";
  const page = `/migrations/${migrationId}/investigations/${investigationId}`;
  try {
    await apiSend("POST", `/api/v1/findings/${findingId}/${decision}`, {
      comment: text(formData, "comment"),
    });
  } catch (error) {
    redirect(withMessage(page, "error", messageOf(error)));
  }
  redirect(withMessage(page, "notice", decision === "accept" ? "Accepted." : "Dismissed."));
}

export async function draftFromFinding(formData: FormData): Promise<void> {
  const migrationId = id(formData, "migrationId");
  const investigationId = id(formData, "investigationId");
  const findingId = id(formData, "findingId");
  const page = `/migrations/${migrationId}/investigations/${investigationId}`;
  let changeId: string;
  try {
    const change = await apiSend<Schemas["ChangeRequestOut"]>(
      "POST",
      `/api/v1/findings/${findingId}/draft-change-request`,
      {},
    );
    changeId = change.id;
  } catch (error) {
    redirect(withMessage(page, "error", messageOf(error)));
  }
  redirect(
    withMessage(
      `/migrations/${migrationId}/change-requests/${changeId}`,
      "notice",
      "Draft created from the finding. Review it, write a justification and submit it.",
    ),
  );
}
