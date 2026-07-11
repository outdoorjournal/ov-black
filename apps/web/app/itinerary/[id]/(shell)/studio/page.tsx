// The advisor Studio destination (transitional home for Build/Diff + the
// not-yet-rehomed advisor panels). Advisor-only: a traveler collapses to
// notFound() so the surface never appears in their world. The layout already
// gated visibility of the itinerary itself; this adds the role gate for the
// authoring tools specifically.

import { notFound, redirect } from "next/navigation";

import { resolveUserRole } from "@/lib/role";
import { createServerSupabase } from "@/lib/supabase/server";

import { StudioPlanningSpace } from "../../_shell/StudioPlanningSpace";

export const dynamic = "force-dynamic";

export default async function StudioPage() {
  const supabase = await createServerSupabase();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    redirect("/");
  }
  const role = await resolveUserRole(supabase);
  if (role !== "advisor") {
    notFound();
  }
  return <StudioPlanningSpace />;
}
