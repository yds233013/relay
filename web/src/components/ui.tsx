/**
 * Shared layout primitives.
 *
 * Pages compose these instead of restyling themselves, so the whole product speaks one visual
 * language: a sunken workspace, raised white surfaces, one accent, and colour reserved for states
 * a person must act on.
 *
 * Depth is a three-step vocabulary and nothing may invent a fourth: the workspace is flat, a
 * `Panel` lifts off it by a hairline, and at most one surface per screen is emphasised.
 */
import Link from "next/link";

export type Tone = "neutral" | "accent" | "critical" | "warning" | "positive";

/** Tinted surfaces. Used where the surface itself is the message (callouts, state rows). */
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

/** The emphasis ring. One tile, one row or one panel per screen — never a set of them. */
const TONE_RING: Record<Tone, string> = {
  neutral: "ring-1 ring-[var(--border-strong)]",
  accent: "ring-1 ring-[var(--accent)]/30",
  critical: "ring-1 ring-[var(--critical)]/30",
  warning: "ring-1 ring-[var(--warning)]/35",
  positive: "ring-1 ring-[var(--positive)]/30",
};

/** A trail back to where the reader came from. Evidence pages are reached by drilling in. */
export function Breadcrumbs({ items }: { items: readonly { label: string; href?: string }[] }) {
  return (
    <nav aria-label="Breadcrumb" className="mb-2">
      <ol className="flex flex-wrap items-center gap-1.5 text-xs text-[var(--ink-subtle)]">
        {items.map((item, index) => (
          <li key={`${item.label}-${index}`} className="flex items-center gap-1.5">
            {index > 0 ? (
              <span aria-hidden="true" className="text-[var(--border-strong)]">
                /
              </span>
            ) : null}
            {item.href ? (
              <Link
                href={item.href}
                className="transition-colors hover:text-[var(--accent-ink)] hover:underline"
              >
                {item.label}
              </Link>
            ) : (
              <span className="font-medium text-[var(--ink-muted)]">{item.label}</span>
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
          <div className="flex flex-wrap items-center gap-2.5">
            <h1 className="text-xl font-semibold tracking-tight text-[var(--ink)]">{title}</h1>
            {status}
          </div>
          {description ? (
            <p className="mt-1.5 max-w-3xl text-sm leading-relaxed text-[var(--ink-muted)]">
              {description}
            </p>
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
    <section className="mb-7" aria-label={title} id={id}>
      <div className="mb-2.5 flex flex-wrap items-baseline justify-between gap-2">
        <div>
          {/* The label tier: uppercase extra-small marks every subordinate label in the product. */}
          <h2 className="text-xs font-semibold uppercase tracking-[0.08em] text-[var(--ink-subtle)]">
            {title}
          </h2>
          {description ? (
            <p className="mt-1 max-w-3xl text-sm leading-relaxed text-[var(--ink-muted)]">
              {description}
            </p>
          ) : null}
        </div>
        {actions ? <div className="flex items-center gap-2 text-sm">{actions}</div> : null}
      </div>
      {children}
    </section>
  );
}

/** A raised surface. Everything that groups content sits on one of these. */
export function Panel({
  children,
  tone = "neutral",
  emphasis = false,
  className = "",
  ...rest
}: {
  children: React.ReactNode;
  tone?: Tone;
  /** At most one per screen: the surface this page is actually about. */
  emphasis?: boolean;
  className?: string;
} & React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={`rounded-[var(--radius-card)] border ${TONE_SURFACE[tone]} ${
        emphasis
          ? `${TONE_RING[tone]} shadow-[var(--shadow-raised)]`
          : "shadow-[var(--shadow-card)]"
      } ${className}`}
      {...rest}
    >
      {children}
    </div>
  );
}

/** One figure with its label. Optionally a link to the rows behind it.
 *
 * The markup is `dl > div > dt + dd`: a link may not wrap `dt`/`dd`, so when the tile is clickable
 * the anchor inside the value is stretched over the whole tile instead.
 *
 * Tiles keep a white surface and an ink figure whatever their tone. Tone marks the tile — the
 * label and the emphasis ring — rather than the number, because a screen whose verdict, whose
 * blocking work and whose headline figure are all red has no hierarchy left to spend. `emphasis`,
 * the one number the screen is about, adds the hero size and the ring; exactly one tile in a row
 * should carry it.
 */
export function MetricTile({
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
  return (
    <div
      className={`relative flex flex-col rounded-[var(--radius-card)] border border-[var(--border)] bg-[var(--surface-raised)] p-4 ${
        emphasis
          ? `${TONE_RING[tone]} shadow-[var(--shadow-raised)]`
          : "shadow-[var(--shadow-card)]"
      } ${href ? "transition-colors hover:border-[var(--border-strong)]" : ""}`}
    >
      <dt
        className={`text-xs font-medium uppercase tracking-[0.06em] ${tone === "neutral" ? "text-[var(--ink-subtle)]" : TONE_INK[tone]}`}
      >
        {label}
      </dt>
      {/* The hint stays inside the `dd`: a `dl > div` may hold only `dt` and `dd`, and a stray
          paragraph there is a real structure error, not a styling detail. */}
      <dd
        className={`mt-1.5 text-[var(--ink)] ${emphasis ? "figure-hero" : "text-xl font-semibold tracking-tight tabular-nums"}`}
      >
        {href ? (
          <Link href={href} className="no-underline after:absolute after:inset-0">
            {value}
          </Link>
        ) : (
          value
        )}
        {hint ? (
          <span className="mt-1.5 block text-xs font-normal leading-snug text-[var(--ink-muted)]">
            {hint}
          </span>
        ) : null}
      </dd>
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
    <div
      className={`rounded-[var(--radius-card)] border px-3.5 py-2.5 text-sm leading-relaxed ${TONE_SURFACE[tone]}`}
    >
      {title ? <p className={`font-semibold ${TONE_INK[tone]}`}>{title}</p> : null}
      <div className="text-[var(--ink-muted)]">{children}</div>
    </div>
  );
}

export function EmptyState({ title, hint }: { title: string; hint?: React.ReactNode }) {
  return (
    <div className="rounded-[var(--radius-card)] border border-dashed border-[var(--border-strong)] bg-[var(--surface-raised)] px-4 py-10 text-center">
      <p className="text-sm font-medium text-[var(--ink)]">{title}</p>
      {hint ? (
        <p className="mx-auto mt-1.5 max-w-lg text-xs leading-relaxed text-[var(--ink-muted)]">
          {hint}
        </p>
      ) : null}
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
          <dt className="text-xs font-medium uppercase tracking-[0.06em] text-[var(--ink-subtle)]">
            {item.label}
          </dt>
          <dd className="mt-1 text-sm text-[var(--ink)]">{item.value}</dd>
        </div>
      ))}
    </dl>
  );
}

const BUTTON_BASE =
  "inline-flex items-center justify-center gap-1.5 rounded-[var(--radius-control)] border px-3 py-1.5 text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-60";

export const BUTTON_STYLES = {
  primary: `${BUTTON_BASE} border-[var(--accent)] bg-[var(--accent)] text-white shadow-[var(--shadow-card)] hover:border-[var(--accent-ink)] hover:bg-[var(--accent-ink)]`,
  secondary: `${BUTTON_BASE} border-[var(--border-strong)] bg-[var(--surface)] text-[var(--ink)] hover:border-[var(--ink-muted)] hover:bg-[var(--surface-sunken)]`,
  danger: `${BUTTON_BASE} border-[var(--critical)]/60 bg-[var(--surface)] text-[var(--critical)] hover:bg-[var(--critical-soft)]`,
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
    label: "Original source",
    className: "border-[var(--border-strong)] bg-[var(--surface)] text-[var(--ink-muted)]",
    title:
      "Original source: the legacy system's own export, exactly as it arrived. Relay stores it append-only and never edits it — corrections are applied on top as approved overlays.",
  },
  canonical: {
    label: "Normalized record",
    className: "border-[var(--accent)]/40 bg-[var(--accent-soft)] text-[var(--accent-ink)]",
    title:
      "Normalized record: Relay's reading of the source row — the same values parsed into typed fields by the approved column mapping. It is an interpretation, so when it looks wrong the mapping or an approved override changes, never the source.",
  },
  derived: {
    label: "Relay check result",
    className: "border-[var(--border)] bg-[var(--surface-sunken)] text-[var(--ink-muted)]",
    title:
      "Relay check result: computed by Relay's deterministic checks from normalized records, and recomputed from scratch on every run. Nobody types these values in or edits them.",
  },
};

export function ProvenanceBadge({ kind }: { kind: "source" | "canonical" | "derived" }) {
  const style = PROVENANCE[kind];
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.06em] ${style.className}`}
      title={style.title}
      data-provenance={kind}
    >
      {style.label}
    </span>
  );
}
