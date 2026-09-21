/** Form controls with visible labels. Forms post to Server Functions and work without JavaScript. */
import { BUTTON_STYLES } from "@/components/ui";
import { DEMO_VIEW_ONLY, isPublicDemo } from "@/lib/demo";

/** One control treatment: same radius, same border, same hover as every button in the product. */
const CONTROL =
  "rounded-[var(--radius-control)] border border-[var(--border-strong)] bg-[var(--surface)] px-2.5 py-1.5 text-sm text-[var(--ink)] transition-colors placeholder:text-[var(--ink-subtle)] hover:border-[var(--ink-muted)]";

export function TextField({
  name,
  label,
  defaultValue,
  required = false,
  placeholder,
  className = "",
}: {
  name: string;
  label: string;
  defaultValue?: string;
  required?: boolean;
  placeholder?: string;
  className?: string;
}) {
  return (
    <label className={`flex flex-col gap-1 text-sm ${className}`}>
      <span className="text-xs font-medium uppercase tracking-[0.06em] text-[var(--ink-subtle)]">
        {label}
      </span>
      <input
        name={name}
        defaultValue={defaultValue}
        required={required}
        placeholder={placeholder}
        className={CONTROL}
      />
    </label>
  );
}

export function TextArea({
  name,
  label,
  defaultValue,
  required = false,
  rows = 3,
  mono = false,
}: {
  name: string;
  label: string;
  defaultValue?: string;
  required?: boolean;
  rows?: number;
  mono?: boolean;
}) {
  return (
    <label className="flex flex-col gap-1 text-sm">
      <span className="text-xs font-medium uppercase tracking-[0.06em] text-[var(--ink-subtle)]">
        {label}
      </span>
      <textarea
        name={name}
        defaultValue={defaultValue}
        required={required}
        rows={rows}
        className={`${CONTROL} ${mono ? "font-mono text-xs" : ""}`}
      />
    </label>
  );
}

export function SubmitButton({
  children,
  tone = "primary",
  name,
  value,
  allowedInDemo = false,
}: {
  children: React.ReactNode;
  tone?: "primary" | "secondary" | "danger";
  name?: string;
  value?: string;
  /**
   * Render normally in the public demo. Only for actions the server-side demo policy actually
   * permits — today just starting an investigation. Everything else becomes a short note, because
   * a button that submits into a 403 reads as a broken product rather than a deliberate boundary.
   */
  allowedInDemo?: boolean;
}) {
  if (isPublicDemo() && !allowedInDemo) {
    return (
      <span className="inline-flex items-center rounded-full border border-dashed border-[var(--border-strong)] bg-[var(--surface-sunken)] px-2.5 py-1 text-xs font-medium text-[var(--ink-muted)]">
        {DEMO_VIEW_ONLY}
      </span>
    );
  }
  return (
    <button type="submit" name={name} value={value} className={BUTTON_STYLES[tone]}>
      {children}
    </button>
  );
}
