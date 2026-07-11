// The Travel Party destination — "who's coming" as its own routed surface. The
// store (seeded in the layout) supplies role + credentials; this route only
// mounts the view. Role-agnostic: an advisor attaches from the household, a
// traveler reads the roster and keeps their household current.

import { PartyView } from "../../_shell/PartyView";

export const dynamic = "force-dynamic";

export default function PartyPage() {
  return <PartyView />;
}
