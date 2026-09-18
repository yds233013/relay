/**
 * Shared layout primitives.
 *
 * Pages compose these instead of restyling themselves, so the whole product speaks one visual
 * language: quiet surfaces, one accent, and colour reserved for states a person must act on.
 */
import Link from "next/link";

export type Tone = "neutral" | "accent" | "critical" | "warning" | "positive";

const TONE_SURFACE: Record<Tone, string> = {
  neutral: "border-[var(--border)] bg-[var(--surface-raised)]",
  accent: "border-[var(--accent)]/30 bg-[var(--accent-soft)]",
  critical: "border-[var(--critical)]/30 bg-[var(--critical-soft)]",
  warning: "border-[var(--warning)]/30 bg-[var(--warning-soft)]",
  positive: "border-[var(--positive)]/30 bg-[var(--positive-soft)]",
};

const TONE_INK: Record<Tone, string> = {
  neutral: "text-[var(--ink)]",
  accent: "text-[var(--accent-ink)]",
  critical: "text-[var(--critical)]",
  warning: "text-[var(--warning)]",
  positive: "text-[var(--positive)]",
};

/** A trail back to where the reader came from. Evidence pages are reached by drilling in. */
export function Breadcrumbs({ items }: { items: readonly { label: string; href?: string }[] }) {
  return (
    <nav aria-label="Breadcrumb" className="mb-2">
      <ol className="flex flex-wrap items-center gap-1 text-xs text-[var(--ink-subtle)]">
        {items.map((item, index) => (
          <li key={`${item.label}-${index}`} className="flex items-center gap-1">
            {index > 0 ? <span aria-hidden="true">/</span> : null}
            {item.href ? (
              <Link href={item.href} className="hover:text-[var(--accent-ink)] hover:underline">
                {item.label}
              </Link>
            ) : (
              <span className="text-[var(--ink-muted)]">{item.label}</span>
            )}
          </li>
        ))}
      </ol>
    </nav>
  );
}

export function PageHeader({
  title,
  description,
  breadcrumbs,
  status,
  children,
}: {
  title: string;
  description?: React.ReactNode;
  breadcrumbs?: readonly { label: string; href?: string }[];
  status?: React.ReactNode;
  children?: React.ReactNode;
}) {
  return (
    <header className="mb-5">
      {breadcrumbs ? <Breadcrumbs items={breadcrumbs} /> : null}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="text-xl font-semibold tracking-tight text-[var(--ink)]">{title}</h1>
            {status}
          </div>
          {description ? (
            <p className="mt-1 max-w-3xl text-sm text-[var(--ink-muted)]">{description}</p>
          ) : null}
        </div>
        {children ? <div className="flex shrink-0 items-center gap-2">{children}</div> : null}
      </div>
    </header>
  );
}

export function Section({
  title,
  description,
  actions,
  id,
  children,
}: {
  title: string;
  description?: React.ReactNode;
  actions?: React.ReactNode;
  id?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="mb-6" aria-label={title} id={id}>
      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h2 className="text-sm font-semibold uppercase tracking-wide text-[var(--ink-muted)]">
            {title}
          </h2>
          {description ? (
            <p className="mt-0.5 max-w-3xl text-sm text-[var(--ink-muted)]">{description}</p>
          ) : null}
        </div>
        {actions ? <div className="flex items-center gap-2 text-sm">{actions}</div> : null}
      </div>
      {children}
    </section>
  );
}

/** A bordered surface. Everything that groups content sits on one of these. */
export function Panel({
  children,
  tone = "neutral",
  className = "",
  ...rest
}: {
  children: React.ReactNode;
  tone?: Tone;
  className?: string;
} & React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={`rounded-md border ${TONE_SURFACE[tone]} ${className}`} {...rest}>
      {children}
    </div>
  );
}

/** One figure with its label. Optionally a link to the rows behind it. */
export function MetricCard({
  label,
  value,
  hint,
  href,
  tone = "neutral",
  emphasis = false,
}: {
  label: string;
  value: React.ReactNode;
  hint?: React.ReactNode;
  href?: string;
  tone?: Tone;
  emphasis?: boolean;
}) {
  const body = (
    <>
      <dt className="text-xs font-medium uppercase tracking-wide text-[var(--ink-subtle)]">
        {label}
      </dt>
      <dd
        className={`mt-1 tabular-nums ${emphasis ? "text-2xl font-semibold" : "text-lg font-medium"} ${TONE_INK[tone]}`}
      >
        {value}
      </dd>
      {hint ? <p className="mt-1 text-xs text-[var(--ink-muted)]">{hint}</p> : null}
    </>
  );
  return (
    <div
      className={`rounded-md border p-3 ${TONE_SURFACE[tone]} ${href ? "transition-colors hover:border-[var(--border-strong)]" : ""}`}
    >
      {href ? (
        <Link href={href} className="block no-underline">
          {body}
        </Link>
      ) : (
        body
      )}
    </div>
  );
}

/** A short, deliberate statement: what this screen means, or what a state does not imply. */
export function Callout({
  tone = "neutral",
  title,
  children,
}: {
  tone?: Tone;
  title?: string;
  children: React.ReactNode;
}) {
  return (
    <div className={`rounded-md border px-3 py-2 text-sm ${TONE_SURFACE[tone]}`}>
      {title ? <p className={`font-medium ${TONE_INK[tone]}`}>{title}</p> : null}
      <div className="text-[var(--ink-muted)]">{children}</div>
    </div>
  );
}

export function EmptyState({ title, hint }: { title: string; hint?: React.ReactNode }) {
  return (
    <div className="rounded-md border border-dashed border-[var(--border)] px-3 py-6 text-center">
      <p className="text-sm font-medium text-[var(--ink-muted)]">{title}</p>
      {hint ? <p className="mt-1 text-xs text-[var(--ink-subtle)]">{hint}</p> : null}
    </div>
  );
}

/** Label/value metadata, the shape used on every detail page. */
export function MetaList({
  items,
  columns = 3,
}: {
  items: readonly { label: string; value: React.ReactNode }[];
  columns?: 2 | 3 | 4;
}) {
  const grid = { 2: "sm:grid-cols-2", 3: "sm:grid-cols-3", 4: "sm:grid-cols-4" }[columns];
  return (
    <dl className={`grid grid-cols-1 gap-x-6 gap-y-3 ${grid}`}>
      {items.map((item) => (
        <div key={item.label}>
          <dt className="text-xs font-medium uppercase tracking-wide text-[var(--ink-subtle)]">
            {item.label}
          </dt>
          <dd className="mt-0.5 text-sm text-[var(--ink)]">{item.value}</dd>
        </div>
      ))}
    </dl>
  );
}

const BUTTON_BASE =
  "inline-flex items-center justify-center gap-1 rounded border px-3 py-1.5 text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-60";

export const BUTTON_STYLES = {
  primary: `${BUTTON_BASE} border-[var(--accent)] bg-[var(--accent)] text-white hover:bg-[var(--accent-ink)]`,
  secondary: `${BUTTON_BASE} border-[var(--border-strong)] bg-white text-[var(--ink)] hover:bg-[var(--surface-sunken)]`,
  danger: `${BUTTON_BASE} border-[var(--critical)] bg-white text-[var(--critical)] hover:bg-[var(--critical-soft)]`,
} as const;

export function ButtonLink({
  href,
  children,
  variant = "secondary",
}: {
  href: string;
  children: React.ReactNode;
  variant?: keyof typeof BUTTON_STYLES;
}) {
  return (
    <Link href={href} className={`${BUTTON_STYLES[variant]} no-underline`}>
      {children}
    </Link>
  );
}

/** Where a value came from. A transformed number must never read as customer evidence. */
const PROVENANCE: Record<
  "source" | "canonical" | "derived",
  { label: string; className: string; title: string }
> = {
  source: {
    label: "Source",
    className: "border-[var(--border-strong)] bg-white text-[var(--ink-muted)]",
    title: "Exactly as the legacy system exported it. Never modified.",
  },
  canonical: {
    label: "Canonical",
    className: "border-[var(--accent)]/40 bg-[var(--accent-soft)] text-[var(--accent-ink)]",
    title: "Relay's normalized record, derived from the source row by the approved mapping.",
  },
  derived: {
    label: "Engine result",
    className: "border-[var(--border-strong)] bg-[var(--surface-sunken)] text-[var(--ink-muted)]",
    title: "Computed by the deterministic engine from canonical records.",
  },
};

export function ProvenanceBadge({ kind }: { kind: "source" | "canonical" | "derived" }) {
  const style = PROVENANCE[kind];
  return (
    <span
      className={`inline-flex items-center rounded border px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${style.className}`}
      title={style.title}
      data-provenance={kind}
    >
      {style.label}
    </span>
  );
}
