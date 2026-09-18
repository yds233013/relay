/** Form controls with visible labels. Forms post to Server Functions and work without JavaScript. */
import { BUTTON_STYLES } from "@/components/ui";

const CONTROL =
  "rounded border border-[var(--border-strong)] bg-white px-2 py-1 text-sm text-[var(--ink)]";

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
      <span className="text-xs font-medium text-[var(--ink-muted)]">{label}</span>
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
      <span className="text-xs font-medium text-[var(--ink-muted)]">{label}</span>
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
}: {
  children: React.ReactNode;
  tone?: "primary" | "secondary" | "danger";
  name?: string;
  value?: string;
}) {
  return (
    <button type="submit" name={name} value={value} className={BUTTON_STYLES[tone]}>
      {children}
    </button>
  );
}
