// The Collection destination — the wish list as its own routed surface. The
// store (seeded in the layout) supplies the unscheduled nodes; this route only
// renders the board.

import { CollectionPlanningSpace } from "../_shell/CollectionPlanningSpace";

export const dynamic = "force-dynamic";

export default function CollectionPage() {
  return <CollectionPlanningSpace />;
}
