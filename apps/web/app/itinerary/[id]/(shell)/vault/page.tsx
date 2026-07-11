// The per-trip Vault destination — travel documents as a Rail surface. Auth +
// fetch + the shell (store Provider) live in the layout; this route just mounts
// the view, which reads the shared store. Advisor-focused (the Rail only offers
// this noun to advisors); a traveler landing here sees read-only.

import { VaultView } from "../../_shell/VaultView";

export const dynamic = "force-dynamic";

export default function VaultPage() {
  return <VaultView />;
}
