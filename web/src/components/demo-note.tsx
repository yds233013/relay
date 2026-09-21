import { Callout } from "@/components/ui";
import { DEMO_VIEW_ONLY } from "@/lib/demo";

/**
 * Stands in for an action the public demo does not offer.
 *
 * Shown instead of the form, not beside a dead one: a visitor should see a deliberate boundary and
 * still learn what the product does there. The server refuses these requests regardless
 * (`relay.api.demo_policy`); this only decides what the page looks like.
 *
 * It says what the action is and stops. Several of these can appear on one screen, and repeating
 * the same paragraph about shared demo copies three times reads as an apology rather than a
 * boundary — the standing explanation lives once in the header badge and the page footer.
 */
export function DemoUnavailable({ what }: { what: string }) {
  return (
    <Callout tone="neutral" title={DEMO_VIEW_ONLY}>
      {what}
    </Callout>
  );
}
