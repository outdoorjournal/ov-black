import Link from "next/link";
import { redirect } from "next/navigation";

import { Button } from "@/components/ui/button";
import { createServerSupabase } from "@/lib/supabase";

import { VoodooDollForm } from "./_components/voodoo-doll-form";

// Auth-gated per request; the form submits via a server action that
// re-reads the advisor's access token on the server.
export const dynamic = "force-dynamic";

export default async function NewClientPage() {
  const supabase = await createServerSupabase();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    redirect("/");
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-3xl flex-col gap-10 px-6 py-16">
      <header className="flex items-end justify-between gap-6">
        <div>
          <h1 className="font-serif text-5xl tracking-tight text-ink">
            New Client
          </h1>
          <p className="mt-3 font-sans text-xs uppercase tracking-[0.3em] text-ink/60">
            Voodoo Doll &amp; invite
          </p>
        </div>
        <Button asChild variant="outline">
          <Link href="/command-center">Back</Link>
        </Button>
      </header>

      <VoodooDollForm />
    </main>
  );
}
