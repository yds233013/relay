import Link from "next/link";

import { SubmitButton, TextField } from "@/components/forms";
import { Notice } from "@/components/notice";
import { PageHeader, Section } from "@/components/page-header";
import { param } from "@/lib/format";

import { createMigration } from "../[migrationId]/workflow-actions";

export const dynamic = "force-dynamic";

function DateField({ name, label }: { name: string; label: string }) {
  return (
    <label className="flex flex-col gap-1 text-sm">
      <span className="text-xs font-medium text-[var(--ink-muted)]">{label}</span>
      <input
        type="date"
        name={name}
        required
        className="rounded border border-[var(--border-strong)] bg-white px-2 py-1"
      />
    </label>
  );
}

export default async function NewMigrationPage(props: PageProps<"/migrations/new">) {
  const query = await props.searchParams;
  return (
    <main className="mx-auto max-w-3xl p-4">
      <PageHeader
        title="New migration"
        description={
          <>
            Implementation leads create migrations.{" "}
            <Link href="/migrations" className="underline">
              Back to the portfolio
            </Link>
          </>
        }
      />
      <Notice error={param(query.error)} />
      <form action={createMigration} className="flex flex-col gap-4">
        <Section title="Company">
          <div className="grid gap-2 md:grid-cols-2">
            <TextField name="companyName" label="Company name" required />
            <TextField name="legalName" label="Legal name (defaults to the company name)" />
            <TextField name="country" label="Country (ISO code)" required defaultValue="US" />
            <TextField name="currency" label="Functional currency" required defaultValue="USD" />
            <TextField
              name="fiscalYearStartMonth"
              label="Fiscal year start month (1-12)"
              required
              defaultValue="1"
            />
          </div>
        </Section>
        <Section title="Migration">
          <div className="grid gap-2 md:grid-cols-2">
            <TextField name="name" label="Migration name" required />
            <TextField
              name="issueKeyPrefix"
              label="Issue key prefix (2-6 capital letters)"
              required
            />
          </div>
        </Section>
        <Section title="Conversion plan">
          <p className="mb-2 text-sm text-[var(--ink-muted)]">
            Opening balances are taken at the opening balance date; history runs from the history
            start to cutover; go-live follows cutover.
          </p>
          <div className="grid gap-2 md:grid-cols-2">
            <DateField name="openingBalanceDate" label="Opening balance date" />
            <DateField name="historyStartDate" label="History start date" />
            <DateField name="cutoverDate" label="Cutover date" />
            <DateField name="goLiveDate" label="Go-live date" />
          </div>
        </Section>
        <span>
          <SubmitButton>Create migration</SubmitButton>
        </span>
      </form>
    </main>
  );
}
