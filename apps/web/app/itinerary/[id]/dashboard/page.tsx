// The per-trip Dashboard destination (M006/PS3) — the itinerary index lands here.
// Auth + fetch + the shell (store Provider, concierge) live in the layout; this
// route just mounts the view, which reads the shared store + timeline context.
// Role-agnostic: both a traveler and an advisor land here, affordances differ.

import { DashboardView } from "../_shell/DashboardView";

export const dynamic = "force-dynamic";

export default function DashboardPage() {
  return <DashboardView />;
}
