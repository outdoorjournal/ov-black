import { redirect } from "next/navigation";

import { createServerSupabase } from "@/lib/supabase";

// Always render per-request — this page gates on the current user session,
// which lives in request cookies and must never be cached.
export const dynamic = "force-dynamic";

export default async function CommandCenterPage() {
  const supabase = await createServerSupabase();

  // getUser() revalidates the JWT against the Supabase server; getSession()
  // would trust the cookie contents. Always use getUser() for auth gates.
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    redirect("/");
  }

  return (
    <main className="flex min-h-screen items-center justify-center px-6 py-16">
      <div className="text-center">
        <h1 className="font-serif text-6xl tracking-tight text-ink">
          Command Center
        </h1>
        <p className="mt-6 font-sans text-sm uppercase tracking-[0.3em] text-ink/60">
          Ready when you are.
        </p>
      </div>
    </main>
  );
}
