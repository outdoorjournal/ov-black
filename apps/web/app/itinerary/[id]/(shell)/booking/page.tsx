// The per-trip Booking destination — the advisor's book/confirm cockpit as a
// Rail surface. Auth + fetch + the shell (store Provider) live in the layout;
// this route just mounts the view, which reads the shared store. Advisor-focused
// (the Rail only offers this noun to advisors); a traveler landing here sees
// read-only.

import { BookingView } from "../../_shell/BookingView";

export const dynamic = "force-dynamic";

export default function BookingPage() {
  return <BookingView />;
}
