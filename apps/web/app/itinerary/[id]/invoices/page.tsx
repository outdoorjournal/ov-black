// The per-trip Invoices destination (ADV-11) — the advisor's billing cockpit as a
// Rail surface. Auth + fetch + the shell (store Provider) live in the layout; this
// route just mounts the view, which reads the shared store. Advisor-focused (the
// Rail only offers this noun to advisors); a traveler landing here sees read-only.

import { InvoicesView } from "../_shell/InvoicesView";

export const dynamic = "force-dynamic";

export default function InvoicesPage() {
  return <InvoicesView />;
}
