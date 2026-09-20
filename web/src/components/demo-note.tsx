import { Callout } from "@/components/ui";
import { DEMO_VIEW_ONLY } from "@/lib/demo";

/**
 * Stands in for an action the public demo does not offer.
 *
 * Shown instead of the form, not beside a dead one: a visitor should see a deliberate boundary and
 * still learn what the product does there. The server refuses these requests regardless
 * (`relay.api.demo_policy`); this only decides what the page looks like.
 */
export function DemoUnavailable({ what }: { what: string }) {
  return (
    <Callout tone="neutral" title={DEMO_VIEW_ONLY}>
      {what} This demo is one shared copy of a fictional implementation, so anything that would
      change it for the next visitor is left out. Everything else — the evidence, the reconciliation
      trail and the governed workflow behind each decision — is real and explorable.
    </Callout>
  );
}
