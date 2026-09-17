"use server";

/**
 * Server Functions for issue workflow, dispositions, entity decisions, uploads and migration setup.
 * The API decides every permission; these only translate forms into API calls and redirect.
 */
import { redirect } from "next/navigation";

import { apiSend, apiUpload, type Schemas } from "@/lib/api/client";
import { draftAndSubmit } from "@/lib/change-requests";
import { id, isId, messageOf, samePath, text, texts, withMessage } from "@/lib/form-data";

const MAX_UPLOAD_BYTES = 10 * 1024 * 1024;

export async function updateIssue(formData: FormData): Promise<void> {
  const migrationId = id(formData, "migrationId");
  const issueId = id(formData, "issueId");
  const page = `/migrations/${migrationId}/issues/${issueId}`;
  const owner = text(formData, "owner");
  const status = text(formData, "status");
  try {
    await apiSend("PATCH", `/api/v1/issues/${issueId}`, {
      version: Number.parseInt(text(formData, "version"), 10),
      owner_user_id: isId(owner) ? owner : null,
      clear_owner: owner === "none",
      status: status || null,
      note: text(formData, "note"),
    });
  } catch (error) {
    redirect(withMessage(page, "error", messageOf(error)));
  }
  redirect(withMessage(page, "notice", "Issue updated."));
}

export async function addIssueComment(formData: FormData): Promise<void> {
  const migrationId = id(formData, "migrationId");
  const issueId = id(formData, "issueId");
  const page = `/migrations/${migrationId}/issues/${issueId}`;
  try {
    await apiSend("POST", `/api/v1/issues/${issueId}/comments`, { body: text(formData, "body") });
  } catch (error) {
    redirect(withMessage(page, "error", messageOf(error)));
  }
  redirect(withMessage(page, "notice", "Comment added."));
}

export async function createManualIssue(formData: FormData): Promise<void> {
  const migrationId = id(formData, "migrationId");
  const back = `/migrations/${migrationId}/issues`;
  let issueId: string;
  try {
    const issue = await apiSend<Schemas["IssueOut"]>(
      "POST",
      `/api/v1/migrations/${migrationId}/issues`,
      {
        title: text(formData, "title"),
        severity: text(formData, "severity"),
        category: text(formData, "category"),
        nature: text(formData, "nature"),
        description: text(formData, "description"),
      },
    );
    issueId = issue.id;
  } catch (error) {
    redirect(withMessage(back, "error", messageOf(error)));
  }
  redirect(`/migrations/${migrationId}/issues/${issueId}`);
}

export async function proposeDisposition(formData: FormData): Promise<void> {
  const migrationId = id(formData, "migrationId");
  const back = samePath(text(formData, "returnTo"), `/migrations/${migrationId}/issues`);
  const issueIds = texts(formData, "issueId").filter(isId);
  if (issueIds.length === 0) {
    redirect(withMessage(back, "error", "Select at least one issue."));
  }
  const amount = text(formData, "amount").trim();
  const owner = text(formData, "followUpOwner");
  let changeId: string;
  try {
    changeId = await draftAndSubmit(
      migrationId,
      {
        kind: "disposition",
        title: text(formData, "title") || "Disposition",
        payload: {
          issue_ids: issueIds,
          kind: text(formData, "kind"),
          amount: amount === "" ? null : amount,
          follow_up: text(formData, "followUp"),
          follow_up_owner_id: isId(owner) ? owner : null,
        },
        evidence_refs: issueIds.map((issueId) => ({ kind: "issue", issue_id: issueId })),
      },
      text(formData, "justification"),
    );
  } catch (error) {
    redirect(withMessage(back, "error", messageOf(error)));
  }
  redirect(`/migrations/${migrationId}/change-requests/${changeId}`);
}

export async function proposeEntityDecision(formData: FormData): Promise<void> {
  const migrationId = id(formData, "migrationId");
  const back = samePath(text(formData, "returnTo"), `/migrations/${migrationId}/entities`);
  const decision = text(formData, "decision") === "distinct" ? "distinct" : "same_entity";
  const members = texts(formData, "member");
  let changeId: string;
  try {
    changeId = await draftAndSubmit(
      migrationId,
      {
        kind: "entity_decision",
        title: `${decision === "distinct" ? "Keep distinct" : "Merge"}: ${members.join(", ")}`,
        payload: {
          party_type: text(formData, "partyType"),
          decision,
          members,
          survivor: decision === "same_entity" ? text(formData, "survivor") || null : null,
          run_id: id(formData, "runId"),
        },
        evidence_refs: texts(formData, "evidenceIssueId")
          .filter(isId)
          .map((issueId) => ({ kind: "issue", issue_id: issueId })),
      },
      text(formData, "justification"),
    );
  } catch (error) {
    redirect(withMessage(back, "error", messageOf(error)));
  }
  redirect(`/migrations/${migrationId}/change-requests/${changeId}`);
}

export async function uploadImport(formData: FormData): Promise<void> {
  const migrationId = id(formData, "migrationId");
  const datasetId = id(formData, "datasetId");
  const back = samePath(text(formData, "returnTo"), `/migrations/${migrationId}/data`);
  const file = formData.get("file");
  if (!(file instanceof File) || file.size === 0) {
    redirect(withMessage(back, "error", "Choose a non-empty CSV file."));
  }
  if (file.size > MAX_UPLOAD_BYTES) {
    redirect(withMessage(back, "error", "Files over 10 MB are uploaded through the API."));
  }
  let notice: string;
  try {
    const bytes = new Uint8Array(await file.arrayBuffer());
    const result = await apiUpload<Schemas["ImportOut"]>(
      `/api/v1/datasets/${datasetId}/imports`,
      file.name,
      bytes,
    );
    notice =
      result.status === "pending"
        ? `Uploaded ${result.original_filename} as import #${result.sequence}; it is being read.`
        : `This file was already imported as import #${result.sequence}; nothing changed.`;
  } catch (error) {
    redirect(withMessage(back, "error", messageOf(error)));
  }
  redirect(withMessage(back, "notice", notice));
}

export async function requestRun(formData: FormData): Promise<void> {
  const migrationId = id(formData, "migrationId");
  const back = samePath(text(formData, "returnTo"), `/migrations/${migrationId}/runs`);
  let notice: string;
  try {
    const run = await apiSend<Schemas["RunOut"]>(
      "POST",
      `/api/v1/migrations/${migrationId}/pipeline-runs`,
      {},
    );
    notice = `Run #${run.sequence} is ${run.status}.`;
  } catch (error) {
    redirect(withMessage(back, "error", messageOf(error)));
  }
  redirect(withMessage(back, "notice", notice));
}

export async function createMigration(formData: FormData): Promise<void> {
  let migrationId: string;
  try {
    const migration = await apiSend<Schemas["MigrationOut"]>("POST", "/api/v1/migrations", {
      company: {
        name: text(formData, "companyName"),
        legal_name: text(formData, "legalName") || text(formData, "companyName"),
        country: text(formData, "country").toUpperCase(),
        functional_currency: text(formData, "currency").toUpperCase(),
        fiscal_year_start_month: Number.parseInt(text(formData, "fiscalYearStartMonth"), 10),
      },
      name: text(formData, "name"),
      issue_key_prefix: text(formData, "issueKeyPrefix").toUpperCase(),
      opening_balance_date: text(formData, "openingBalanceDate"),
      history_start_date: text(formData, "historyStartDate"),
      cutover_date: text(formData, "cutoverDate"),
      go_live_date: text(formData, "goLiveDate"),
    });
    migrationId = migration.id;
  } catch (error) {
    redirect(withMessage("/migrations/new", "error", messageOf(error)));
  }
  redirect(`/migrations/${migrationId}/setup`);
}

export async function createSourceSystem(formData: FormData): Promise<void> {
  const migrationId = id(formData, "migrationId");
  const page = `/migrations/${migrationId}/setup`;
  try {
    await apiSend("POST", `/api/v1/migrations/${migrationId}/source-systems`, {
      name: text(formData, "name"),
      kind: text(formData, "kind"),
    });
  } catch (error) {
    redirect(withMessage(page, "error", messageOf(error)));
  }
  redirect(withMessage(page, "notice", "Source system added."));
}

export async function createDataset(formData: FormData): Promise<void> {
  const migrationId = id(formData, "migrationId");
  const page = `/migrations/${migrationId}/setup`;
  const asOf = text(formData, "asOfDate");
  try {
    await apiSend("POST", `/api/v1/migrations/${migrationId}/datasets`, {
      source_system_id: id(formData, "sourceSystemId"),
      dataset_type: text(formData, "datasetType"),
      name: text(formData, "name"),
      as_of_date: asOf === "" ? null : asOf,
      is_required: text(formData, "isRequired") !== "no",
      bank_account: text(formData, "bankAccount") || null,
      gl_account: text(formData, "glAccount") || null,
    });
  } catch (error) {
    redirect(withMessage(page, "error", messageOf(error)));
  }
  redirect(withMessage(page, "notice", "Dataset added."));
}
