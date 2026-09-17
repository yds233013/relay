export function PageHeader({
  title,
  description,
  children,
}: {
  title: string;
  description?: React.ReactNode;
  children?: React.ReactNode;
}) {
  return (
    <header className="mb-4 flex flex-wrap items-start justify-between gap-2">
      <div>
        <h1 className="text-lg font-semibold text-gray-900">{title}</h1>
        {description ? <p className="text-sm text-gray-700">{description}</p> : null}
      </div>
      {children}
    </header>
  );
}

export function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mb-6" aria-label={title}>
      <h2 className="mb-2 text-base font-semibold text-gray-900">{title}</h2>
      {children}
    </section>
  );
}
