"use server";

/**
 * Server Functions for governed changes. Each one calls the Relay API as the signed-in user and
 * redirects: to the change request on success, or back with the API's error message. The API
 * enforces every permission and segregation-of-duties rule; nothing here decides authorization.
 */
import { redirect } from "next/navigation";

import { apiSend, type Schemas } from "@/lib/api/client";
import { draftAndSubmit, issueRefs } from "@/lib/change-requests";
import { id, messageOf, samePath, text, withMessage } from "@/lib/form-data";

export async function proposeAccountMapping(formData: FormData): Promise<void> {
  const migrationId = id(formData, "migrationId");
  const back = `/migrations/${migrationId}/mappings`;
  const changes = [...formData.entries()]
    .filter(([name, value]) => name.startsWith("target:") && typeof value === "string")
    .map(([name, value]) => ({
      legacy: name.slice("target:".length),
      target: String(value).trim(),
      rationale: text(formData, `rationale:${name.slice("target:".length)}`).trim() || null,
    }))
    .filter((change) => change.target !== "");
  if (changes.length === 0) {
    redirect(withMessage(back, "error", "Enter at least one new target account."));
  }
  let changeId: string;
  try {
    const mappingSet = await apiSend<Schemas["AccountMappingSetOut"]>(
      "POST",
      `/api/v1/migrations/${migrationId}/account-mapping-sets`,
      { base: text(formData, "base") === "import" ? "import" : "approved", changes },
    );
    changeId = await draftAndSubmit(
      migrationId,
      {
        kind: "account_mapping_set",
        title: text(formData, "title") || "Account mapping change",
        payload: { mapping_set_id: mappingSet.id },
      },
      text(formData, "justification"),
    );
  } catch (error) {
    redirect(withMessage(back, "error", messageOf(error)));
  }
  redirect(`/migrations/${migrationId}/change-requests/${changeId}`);
}

export async function proposeColumnMapping(formData: FormData): Promise<void> {
  const migrationId = id(formData, "migrationId");
  const datasetId = id(formData, "datasetId");
  const back = `/migrations/${migrationId}/mappings/columns/${datasetId}`;
  let config: unknown;
  try {
    config = JSON.parse(text(formData, "config"));
  } catch {
    redirect(withMessage(back, "error", "The mapping is not valid JSON."));
  }
  let changeId: string;
  try {
    const mappingSet = await apiSend<Schemas["ColumnMappingSetOut"]>(
      "POST",
      `/api/v1/datasets/${datasetId}/column-mapping-sets`,
      config,
    );
    changeId = await draftAndSubmit(
      migrationId,
      {
        kind: "column_mapping_set",
        title: text(formData, "title") || "Column mapping change",
        payload: { mapping_set_id: mappingSet.id },
      },
      text(formData, "justification"),
    );
  } catch (error) {
    redirect(withMessage(back, "error", messageOf(error)));
  }
  redirect(`/migrations/${migrationId}/change-requests/${changeId}`);
}

export async function proposeFieldOverride(formData: FormData): Promise<void> {
  const migrationId = id(formData, "migrationId");
  const runId = id(formData, "runId");
  const naturalKey = text(formData, "naturalKey");
  const field = text(formData, "field");
  const back = samePath(text(formData, "returnTo"), `/migrations/${migrationId}`);
  let changeId: string;
  try {
    changeId = await draftAndSubmit(
      migrationId,
      {
        kind: "record_override",
        title: `Correct ${field.replaceAll("_", " ")} of ${naturalKey}`,
        field_override: {
          run_id: runId,
          natural_key: naturalKey,
          field,
          new_value: text(formData, "newValue"),
        },
        evidence_refs: [
          { kind: "record", run_id: runId, natural_key: naturalKey },
          ...issueRefs(formData),
        ],
      },
      text(formData, "justification"),
    );
  } catch (error) {
    redirect(withMessage(back, "error", messageOf(error)));
  }
  redirect(`/migrations/${migrationId}/change-requests/${changeId}`);
}

export async function proposeQuarantineRepair(formData: FormData): Promise<void> {
  const migrationId = id(formData, "migrationId");
  const exceptionId = id(formData, "exceptionId");
  const back = samePath(text(formData, "returnTo"), `/migrations/${migrationId}`);
  let changeId: string;
  try {
    changeId = await draftAndSubmit(
      migrationId,
      {
        kind: "record_override",
        title: "Repair a quarantined source row",
        quarantine_repair: {
          exception_id: exceptionId,
          replacement_text: text(formData, "replacementText"),
        },
        evidence_refs: [{ kind: "finding", exception_id: exceptionId }, ...issueRefs(formData)],
      },
      text(formData, "justification"),
    );
  } catch (error) {
    redirect(withMessage(back, "error", messageOf(error)));
  }
  redirect(`/migrations/${migrationId}/change-requests/${changeId}`);
}

export async function proposeRevert(formData: FormData): Promise<void> {
  const migrationId = id(formData, "migrationId");
  const overrideId = id(formData, "targetId");
  const back = `/migrations/${migrationId}/overrides`;
  let changeId: string;
  try {
    changeId = await draftAndSubmit(
      migrationId,
      {
        kind: "revert",
        title: `Revert ${text(formData, "label")}`,
        payload: { target: text(formData, "target"), target_id: overrideId },
      },
      text(formData, "justification"),
    );
  } catch (error) {
    redirect(withMessage(back, "error", messageOf(error)));
  }
  redirect(`/migrations/${migrationId}/change-requests/${changeId}`);
}

export async function reviewChangeRequest(formData: FormData): Promise<void> {
  const migrationId = id(formData, "migrationId");
  const changeId = id(formData, "changeId");
  const decision = text(formData, "decision") === "reject" ? "reject" : "approve";
  const page = `/migrations/${migrationId}/change-requests/${changeId}`;
  let notice: string;
  try {
    const outcome = await apiSend<Schemas["ReviewOutcomeOut"]>(
      "POST",
      `/api/v1/change-requests/${changeId}/${decision}`,
      { comment: text(formData, "comment") },
    );
    const status = outcome.change_request.status;
    notice =
      status === "applied"
        ? "Approved and applied. A pipeline run was requested."
        : status === "stale"
          ? "Not recorded: the change request became stale because its base changed."
          : status === "rejected"
            ? "Rejected."
            : "Approval recorded. More approvals are required.";
  } catch (error) {
    redirect(withMessage(page, "error", messageOf(error)));
  }
  redirect(withMessage(page, "notice", notice));
}

export async function withdrawChangeRequest(formData: FormData): Promise<void> {
  const migrationId = id(formData, "migrationId");
  const changeId = id(formData, "changeId");
  const page = `/migrations/${migrationId}/change-requests/${changeId}`;
  try {
    await apiSend("POST", `/api/v1/change-requests/${changeId}/withdraw`, {
      reason: text(formData, "reason"),
    });
  } catch (error) {
    redirect(withMessage(page, "error", messageOf(error)));
  }
  redirect(withMessage(page, "notice", "Withdrawn."));
}
