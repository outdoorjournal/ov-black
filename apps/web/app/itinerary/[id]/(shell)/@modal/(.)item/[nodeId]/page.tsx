// Intercepting route (rail redesign, phase 3). A SOFT navigation to
// /itinerary/[id]/item/[nodeId] from within the shell (a Journal card tap or
// "Open full →") is intercepted here and rendered as a dismissible modal over
// the current surface, instead of the full-page destination. A hard nav /
// refresh bypasses the intercept and hits the real (shell)/item/[nodeId] page.
//
// `(.)item` intercepts the sibling `item` segment at the shell level (the @modal
// slot lives beside it). The @modal slot is rendered inside ItineraryShell by
// the shell layout, so CardDetailView finds the shared graph store + concierge.

import { CardDetailModal } from "../../../../_shell/CardDetailModal";

export const dynamic = "force-dynamic";

export default async function InterceptedCardDetail({
  params,
}: {
  params: Promise<{ nodeId: string }>;
}) {
  const { nodeId } = await params;
  return <CardDetailModal nodeId={nodeId} />;
}
