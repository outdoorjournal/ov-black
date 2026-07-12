// The per-trip Finances destination (doc/thoughts.md, née Invoices/ADV-11) — the
// advisor's billing cockpit as a Rail surface. Auth + fetch + the shell (store
// Provider) live in the layout; this route just mounts the view, which reads the
// shared store. The route segment stays `invoices` (deep links + the /invoices/[id]
// pay page) while the Rail labels it "Finances".

import { FinancesView } from "../../_shell/FinancesView";

export const dynamic = "force-dynamic";

export default function FinancesPage() {
  return <FinancesView />;
}
