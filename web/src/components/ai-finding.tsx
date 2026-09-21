/**
 * The only components that render AI output (CLAUDE.md). Everything is plain text: no links from
 * model text, no HTML. Verification comes from the server, never from the model.
 *
 * The case file keeps four kinds of statement visually apart, because conflating them is how an
 * assistant becomes untrustworthy:
 *
 *   deterministic result — computed by the engine, not an opinion
 *   investigator inference — what it makes of that, and the only part that could be wrong
 *   verified evidence — claims Relay re-checked against the tool results they cite
 *   human decision — what nothing here is allowed to do on its own
 *
 * Each has its own label, surface and position, so no reader has to remember which is which.
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

/** The banner used where AI output appears outside a full case file. */
export function AiLabel() {
  return (
    <p
      className="mb-3 rounded-[var(--radius-card)] border border-[var(--accent)]/30 bg-[var(--accent-soft)] px-3.5 py-2.5 text-sm text-[var(--accent-ink)]"
      data-testid="ai-label"
    >
      AI-generated. Findings are proposals checked only for provenance; a person decides, and every
      change still needs approval by someone else.
    </p>
  );
}

/** A small uppercase heading that names which of the four kinds of statement follows. */
export function KindLabel({
  kind,
  children,
}: {
  kind: "deterministic" | "inference" | "evidence" | "decision";
  children: React.ReactNode;
}) {
  const tone = {
    deterministic: "text-[var(--ink-subtle)]",
    inference: "text-[var(--accent-ink)]",
    evidence: "text-[var(--ink-subtle)]",
    decision: "text-[var(--ink)]",
  }[kind];
  return (
    <p className={`text-[10px] font-semibold uppercase tracking-[0.1em] ${tone}`}>{children}</p>
  );
}

/**
 * What the investigator actually did, in order: which read-only tool it called and how long that
 * took. The latency is the server's own measurement of the call, not a decoration.
 */
export function ProcessSteps({ steps }: { steps: readonly Step[] }) {
  const calls = steps.filter((step) => step.tool_name !== null);
  if (calls.length === 0) {
    return <p className="px-4 py-3 text-sm text-[var(--ink-muted)]">No tools were called.</p>;
  }
  return (
    <ol className="divide-y divide-[var(--border)]" data-testid="ai-process">
      {calls.map((step) => (
        <li key={step.seq} className="flex items-baseline gap-3 px-4 py-2.5">
          <span
            aria-hidden="true"
            className={`shrink-0 text-xs ${step.is_error ? "text-[var(--critical)]" : "text-[var(--positive)]"}`}
          >
            {step.is_error ? "✕" : "✓"}
          </span>
          <span className="min-w-0 flex-1">
            <span className="block truncate font-mono text-xs text-[var(--ink)]">
              {step.tool_name}
            </span>
            {step.is_error || step.truncated ? (
              <span className="block text-[11px] text-[var(--ink-subtle)]">
                {step.is_error ? "returned an error" : ""}
                {step.is_error && step.truncated ? " · " : ""}
                {step.truncated ? "result truncated" : ""}
              </span>
            ) : null}
          </span>
          <span className="shrink-0 text-[11px] tabular-nums text-[var(--ink-subtle)]">
            {step.latency_ms} ms
          </span>
        </li>
      ))}
    </ol>
  );
}

/** Each claim the finding makes, beside Relay's own verdict on whether the tools support it. */
function EvidenceList({ finding }: { finding: Finding }) {
  const report = (finding.verification_report.evidence ?? []) as {
    claim: string;
    ok: boolean;
    problems: string[];
  }[];
  return (
    <ol className="space-y-2">
      {finding.evidence.map((item, index) => {
        const checked = report[index];
        const value = item as {
          claim?: string;
          step_seqs?: number[];
          record_refs?: string[];
          quoted_values?: { label: string; value: string }[];
        };
        return (
          <li
            key={index}
            className={`rounded-[var(--radius-control)] border px-3 py-2.5 ${
              checked?.ok
                ? "border-[var(--border)] bg-[var(--surface-sunken)]"
                : "border-[var(--critical)]/30 bg-[var(--critical-soft)]"
            }`}
          >
            <p className="flex flex-wrap items-start gap-2">
              <StatusChip
                status={checked?.ok ? "pass" : "fail"}
                label={checked?.ok ? "evidence checked" : "evidence not found"}
              />
              <span className="min-w-0 flex-1 text-sm leading-relaxed text-[var(--ink)]">
                {String(value.claim ?? "")}
              </span>
            </p>
            <p className="mt-1.5 font-mono text-[11px] text-[var(--ink-subtle)]">
              steps {(value.step_seqs ?? []).join(", ")}
              {value.record_refs?.length ? ` · ${value.record_refs.join(", ")}` : ""}
              {value.quoted_values?.length
                ? ` · ${value.quoted_values.map((q) => `${q.label}: ${q.value}`).join("; ")}`
                : ""}
            </p>
            {checked && !checked.ok ? (
              <ul className="mt-1 list-inside list-disc text-xs text-[var(--critical)]">
                {checked.problems.map((problem) => (
                  <li key={problem}>{problem}</li>
                ))}
              </ul>
            ) : null}
          </li>
        );
      })}
    </ol>
  );
}

/**
 * One finding, read top to bottom as: what it thinks, what backs that up, what it proposes, and
 * what it still does not know. A finding whose evidence failed verification is folded away behind
 * its own refusal, because it is not a proposal anyone may act on.
 */
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
      <div className="border-l-2 border-[var(--accent)]/40 pl-3.5">
        <KindLabel kind="inference">Investigator inference · not computed</KindLabel>
        <p className="mt-1.5 whitespace-pre-wrap text-sm leading-relaxed text-[var(--ink)]">
          {finding.hypothesis}
        </p>
      </div>

      <div className="mt-5">
        <KindLabel kind="evidence">
          Verified evidence · {finding.evidence.length} claim
          {finding.evidence.length === 1 ? "" : "s"} re-checked by Relay
        </KindLabel>
        <div className="mt-2">
          <EvidenceList finding={finding} />
        </div>
      </div>

      <div className="mt-5">
        <KindLabel kind="deterministic">Recommended next action</KindLabel>
        <p className="mt-1.5 text-sm text-[var(--ink)]">
          {humanize(String(action.type))}
          {finding.requires_approval ? (
            <span className="text-[var(--ink-muted)]"> · would require approval</span>
          ) : null}
        </p>
        <details className="mt-2">
          <summary className="text-xs text-[var(--ink-muted)]">Exactly what it proposes</summary>
          <pre className="mt-1.5 overflow-x-auto rounded-[var(--radius-control)] bg-[var(--surface-sunken)] p-3 text-xs">
            {JSON.stringify(action, null, 2)}
          </pre>
        </details>
      </div>

      {finding.open_questions.length > 0 ? (
        <div className="mt-5">
          <KindLabel kind="evidence">Open questions</KindLabel>
          <ul className="mt-1.5 list-inside list-disc text-sm leading-relaxed text-[var(--ink-muted)]">
            {finding.open_questions.map((question) => (
              <li key={question}>{question}</li>
            ))}
          </ul>
        </div>
      ) : null}
    </>
  );
  return (
    <article
      className={`rounded-[var(--radius-card)] border p-4 shadow-[var(--shadow-card)] sm:p-5 ${
        failed
          ? "border-[var(--critical)]/30 bg-[var(--critical-soft)]"
          : "border-[var(--border)] bg-[var(--surface-raised)]"
      }`}
      data-testid="ai-finding"
      data-verification={finding.verification_status}
    >
      <p className="mb-4 flex flex-wrap items-center gap-2">
        <StatusChip
          status={VERIFICATION[finding.verification_status] ?? "unknown"}
          label={humanize(finding.verification_status)}
        />
        <StatusChip status={finding.review_status} label={humanize(finding.review_status)} />
        <span className="text-xs text-[var(--ink-subtle)]">
          model-reported confidence: {finding.confidence}
        </span>
      </p>
      {failed ? (
        <p className="mb-3 text-sm font-semibold text-[var(--critical)]">
          Verification failed: this finding cites evidence the tools did not return. It cannot be
          accepted or turned into a change request.
        </p>
      ) : null}
      {failed ? (
        <details>
          <summary className="mb-2 text-sm text-[var(--ink-muted)]">
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

/** Every step in order, exactly as it happened — for audit rather than reading. */
export function Transcript({ steps }: { steps: Step[] }) {
  return (
    <ol className="space-y-1.5 text-xs" data-testid="ai-transcript">
      {steps.map((step) => (
        <li
          key={step.seq}
          className="rounded-[var(--radius-control)] border border-[var(--border)] bg-[var(--surface-raised)] p-2.5"
        >
          <p className="font-medium">
            {step.seq}. {humanize(step.type)}
            {step.tool_name ? ` · ${step.tool_name}` : ""}
            {step.is_error ? " · error" : ""}
            {step.truncated ? " · truncated" : ""}
            <span className="ml-1 tabular-nums text-[var(--ink-subtle)]">{step.latency_ms} ms</span>
          </p>
          {step.text ? (
            <p className="mt-1 whitespace-pre-wrap text-[var(--ink-muted)]">{step.text}</p>
          ) : null}
          {step.arguments ? (
            <pre className="mt-1 overflow-x-auto text-[var(--ink-muted)]">
              {JSON.stringify(step.arguments)}
            </pre>
          ) : null}
          {step.result ? (
            <details className="mt-1">
              <summary className="text-[var(--ink-muted)]">Result</summary>
              <pre className="mt-1 max-h-64 overflow-auto whitespace-pre-wrap">{step.result}</pre>
            </details>
          ) : null}
        </li>
      ))}
    </ol>
  );
}
