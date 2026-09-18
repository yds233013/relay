/**
 * The only components that render AI output (CLAUDE.md). Everything is plain text: no links from
 * model text, no HTML. Verification comes from the server, never from the model.
 */
import type { Schemas } from "@/lib/api/client";
import { humanize } from "@/lib/format";

import { StatusChip } from "./status-chip";

type Finding = Schemas["FindingOut"];
type Step = Schemas["InvestigationStepOut"];

const VERIFICATION: Record<string, string> = {
  verified: "pass",
  partially_verified: "stale",
  failed: "fail",
};

export function AiLabel() {
  return (
    <p
      className="mb-3 rounded border border-purple-300 bg-purple-50 px-3 py-2 text-sm text-purple-950"
      data-testid="ai-label"
    >
      AI-generated. Findings are proposals checked only for provenance; a person decides, and every
      change still needs approval by someone else.
    </p>
  );
}

function evidenceList(finding: Finding) {
  const report = (finding.verification_report.evidence ?? []) as {
    claim: string;
    ok: boolean;
    problems: string[];
  }[];
  return finding.evidence.map((item, index) => {
    const checked = report[index];
    const value = item as {
      claim?: string;
      step_seqs?: number[];
      record_refs?: string[];
      quoted_values?: { label: string; value: string }[];
    };
    return (
      <li key={index} className="rounded border border-[var(--border)] p-2">
        <p className="flex flex-wrap items-center gap-2">
          <StatusChip
            status={checked?.ok ? "pass" : "fail"}
            label={checked?.ok ? "evidence checked" : "evidence not found"}
          />
          <span>{String(value.claim ?? "")}</span>
        </p>
        <p className="text-xs text-[var(--ink-muted)]">
          Steps {(value.step_seqs ?? []).join(", ")}
          {value.record_refs?.length ? ` · records ${value.record_refs.join(", ")}` : ""}
          {value.quoted_values?.length
            ? ` · ${value.quoted_values.map((q) => `${q.label}: ${q.value}`).join("; ")}`
            : ""}
        </p>
        {checked && !checked.ok ? (
          <ul className="list-inside list-disc text-xs text-red-900">
            {checked.problems.map((problem) => (
              <li key={problem}>{problem}</li>
            ))}
          </ul>
        ) : null}
      </li>
    );
  });
}

export function FindingCard({
  finding,
  children,
}: {
  finding: Finding;
  children?: React.ReactNode;
}) {
  const action = finding.suggested_action as Record<string, unknown>;
  const failed = finding.verification_status === "failed";
  const details = (
    <>
      <p className="mb-2 whitespace-pre-wrap">{finding.hypothesis}</p>
      <ol className="mb-2 space-y-1">{evidenceList(finding)}</ol>
      <p className="mb-1">
        Suggested action: <span className="font-mono text-xs">{humanize(String(action.type))}</span>
        {finding.requires_approval ? " (would require approval)" : ""}
      </p>
      <pre className="mb-2 overflow-x-auto rounded bg-[var(--surface-sunken)] p-2 text-xs">
        {JSON.stringify(action, null, 2)}
      </pre>
      {finding.open_questions.length > 0 ? (
        <p className="text-xs text-[var(--ink-muted)]">
          Open questions: {finding.open_questions.join(" · ")}
        </p>
      ) : null}
    </>
  );
  return (
    <article
      className={`rounded border p-3 text-sm ${failed ? "border-red-300 bg-red-50" : "border-[var(--border)]"}`}
      data-testid="ai-finding"
      data-verification={finding.verification_status}
    >
      <p className="mb-1 flex flex-wrap items-center gap-2">
        <StatusChip
          status={VERIFICATION[finding.verification_status] ?? "unknown"}
          label={humanize(finding.verification_status)}
        />
        <span className="text-xs text-[var(--ink-muted)]">
          model-reported confidence: {finding.confidence}
        </span>
        <StatusChip status={finding.review_status} label={humanize(finding.review_status)} />
      </p>
      {failed ? (
        <p className="mb-1 font-medium text-red-900">
          Verification failed: this finding cites evidence the tools did not return. It cannot be
          accepted or turned into a change request.
        </p>
      ) : null}
      {failed ? (
        <details>
          <summary className="mb-1 cursor-pointer text-sm underline">
            Show the unverified finding
          </summary>
          {details}
        </details>
      ) : (
        details
      )}
      {children}
    </article>
  );
}

export function Transcript({ steps }: { steps: Step[] }) {
  return (
    <ol className="space-y-1 text-xs" data-testid="ai-transcript">
      {steps.map((step) => (
        <li key={step.seq} className="rounded border border-[var(--border)] p-2">
          <p className="font-medium">
            {step.seq}. {humanize(step.type)}
            {step.tool_name ? ` · ${step.tool_name}` : ""}
            {step.is_error ? " · error" : ""}
            {step.truncated ? " · truncated" : ""}
          </p>
          {step.text ? <p className="whitespace-pre-wrap">{step.text}</p> : null}
          {step.arguments ? (
            <pre className="overflow-x-auto">{JSON.stringify(step.arguments)}</pre>
          ) : null}
          {step.result ? (
            <details>
              <summary className="cursor-pointer underline">Result</summary>
              <pre className="max-h-64 overflow-auto whitespace-pre-wrap">{step.result}</pre>
            </details>
          ) : null}
        </li>
      ))}
    </ol>
  );
}
