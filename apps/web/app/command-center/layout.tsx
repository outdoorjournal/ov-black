import { redirect } from "next/navigation";
import type { ReactNode } from "react";

import { createServerSupabase } from "@/lib/supabase/server";

import { Navbar } from "./_components/navbar";

// Auth-gated on every request — this layout wraps every advisor page
// under /command-center/** and supplies the persistent navbar. Individual
// pages still call getUser() for their own needs (access token lookups);
// Supabase's SSR helpers reuse the validated session within the request.
export const dynamic = "force-dynamic";

export default async function CommandCenterLayout({
  children,
}: {
  children: ReactNode;
}) {
  const supabase = await createServerSupabase();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    redirect("/");
  }

  return (
    <div className="flex min-h-screen flex-col bg-paper text-ink">
      <Navbar email={user.email ?? "Signed in"} />
      <div className="flex flex-1 flex-col">{children}</div>
    </div>
  );
}
