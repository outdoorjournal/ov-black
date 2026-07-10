import Link from "next/link";
import { redirect } from "next/navigation";

import { Button } from "@/components/ui/button";
import { createServerSupabase } from "@/lib/supabase/server";

import { DossierForm } from "./_components/dossier-form";

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
    <main className="mx-auto flex w-full max-w-3xl flex-col gap-10 px-6 py-12 sm:px-10 sm:py-16">
      <header className="flex flex-col gap-6 border-b border-paper/10 pb-8 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="font-sans text-[10px] uppercase tracking-eyebrow text-paper/55">
            Dossier &amp; welcome
          </p>
          <h1 className="mt-4 font-serif text-5xl tracking-tight text-paper sm:text-6xl">
            New Client
          </h1>
        </div>
        <Button
          asChild
          variant="outline"
          className="border-paper/20 bg-transparent text-paper hover:bg-paper/10 hover:text-paper"
        >
          <Link href="/command-center/clients">Back</Link>
        </Button>
      </header>

      <DossierForm />
    </main>
  );
}
