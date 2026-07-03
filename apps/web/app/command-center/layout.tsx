import { redirect } from "next/navigation";
import type { ReactNode } from "react";

import { getAppHeaderContext } from "@/lib/appHeader";
import { createServerSupabase } from "@/lib/supabase/server";

import { CommandCenterChrome } from "./_components/CommandCenterChrome";

// Auth-gated on every request — this layout wraps every advisor page
// under /command-center/** and supplies the shared app masthead. Individual
// pages still call getUser() for their own needs (access token lookups);
// Supabase's SSR helpers reuse the validated session within the request.
export const dynamic = "force-dynamic";

export default async function CommandCenterLayout({
  children,
}: {
  children: ReactNode;
}) {
  const supabase = await createServerSupabase();
  const header = await getAppHeaderContext(supabase);

  if (!header) {
    redirect("/");
  }

  return (
    <div className="flex min-h-screen flex-col bg-paper text-ink">
      <CommandCenterChrome user={header.user} homeHref={header.homeHref} />
      <div className="flex flex-1 flex-col">{children}</div>
    </div>
  );
}
