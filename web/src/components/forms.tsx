/** Form controls with visible labels. Forms post to Server Functions and work without JavaScript. */
const CONTROL = "rounded border border-gray-400 bg-white px-2 py-1 text-sm text-gray-900";

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
      <span className="text-xs font-medium text-gray-700">{label}</span>
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
      <span className="text-xs font-medium text-gray-700">{label}</span>
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
  const tones = {
    primary: "border-blue-800 bg-blue-800 text-white hover:bg-blue-900",
    secondary: "border-gray-400 bg-white text-gray-900 hover:bg-gray-100",
    danger: "border-red-800 bg-white text-red-900 hover:bg-red-50",
  };
  return (
    <button
      type="submit"
      name={name}
      value={value}
      className={`rounded border px-3 py-1 text-sm font-medium ${tones[tone]}`}
    >
      {children}
    </button>
  );
}
