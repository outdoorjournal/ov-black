import { redirect } from "next/navigation";
import type { ReactNode } from "react";

import { getAppHeaderContext } from "@/lib/appHeader";
import { createServerSupabase } from "@/lib/supabase/server";

import { CommandCenterChrome } from "./_components/CommandCenterChrome";
import { CommandCenterCrumbProvider } from "./_components/CommandCenterCrumb";
import { CommandCenterRail } from "./_components/CommandCenterRail";

// Auth-gated on every request — this layout wraps every advisor page
// under /command-center/** and supplies the shared app masthead. Individual
// pages still call getUser() for their own needs (access token lookups);
// Supabase's SSR helpers reuse the validated session within the request.
//
// Wave F: the whole advisor shell is ink — the ops-room identity. Client
// surfaces stay light editorial; the advisor works in the dark. Pages stop
// painting their own bg and inherit this frame.
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
    <div className="flex h-dvh flex-col bg-ink text-paper">
      <CommandCenterCrumbProvider>
        <CommandCenterChrome user={header.user} homeHref={header.homeHref} />
        {/* Same shape as the itinerary shell: a fixed-height frame so the rail
            stays put and only the advisor surface scrolls. */}
        <div className="flex min-h-0 flex-1 overflow-hidden">
          <CommandCenterRail />
          <div className="flex min-w-0 flex-1 flex-col overflow-y-auto">
            {children}
          </div>
        </div>
      </CommandCenterCrumbProvider>
    </div>
  );
}
