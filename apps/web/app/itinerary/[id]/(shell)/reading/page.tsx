// The Reading destination — this trip's saved articles as their own routed
// surface. The store (seeded in the layout) supplies the nodes; this route only
// renders the rack.

import { ReadingPlanningSpace } from "../../_shell/ReadingPlanningSpace";

export const dynamic = "force-dynamic";

export default function ReadingPage() {
  return <ReadingPlanningSpace />;
}
