// The Card detail destination (M006/PS4). Auth + fetch + the graph store live in
// the layout; this route just hands the target node id to the full-bleed detail
// view, which reads the shared store. Deep-linkable + role-agnostic: an advisor
// can send a traveler "look at this card" and it resolves for either.

import { CardDetailView } from "../../../_shell/CardDetailView";

export const dynamic = "force-dynamic";

export default async function CardDetailPage({
  params,
}: {
  params: Promise<{ nodeId: string }>;
}) {
  const { nodeId } = await params;
  return <CardDetailView nodeId={nodeId} />;
}
