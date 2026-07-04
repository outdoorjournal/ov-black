// The Timeline destination. Auth + fetch + the store live in the layout; this
// route just renders the planning-space view, which reads the shared store.

import { TimelinePlanningSpace } from "../_shell/TimelinePlanningSpace";

export const dynamic = "force-dynamic";

export default function TimelinePage() {
  return <TimelinePlanningSpace />;
}
