import { redirect } from "next/navigation";

import { Eyebrow } from "@/components/ui/eyebrow";
import { resolveUserRole } from "@/lib/role";
import { createServerSupabase } from "@/lib/supabase/server";

import { HeroCarousel } from "./_components/hero-carousel";
import { SignInEntry } from "./_components/sign-in-entry";

export const dynamic = "force-dynamic";

// Front-door hero frames. Curated Unsplash CDN convention from
// lib/atmos/moods.ts (2400px, q=80, auto=format, fit=crop) — images.unsplash.com
// is already allowlisted in next.config.ts, so we get real high-resolution
// photography without committing multi-MB binaries. A cohesive dark-cinematic
// set that alternates warm/cool and harmonises with the orange accent.
const HERO_IMAGES = [
  "1761141954476-2921e2e43e99", // kyoto-zen — pagoda at golden dusk
  "1634951412593-b2cdca1ae519", // monsoon — Ha Long Bay karsts
  "1761078206756-68d3023f3021", // savannah — acacia at orange sunset
  "1732045133230-1a670eef8620", // highland — misty Scottish crags
  "1717508723994-ec9c13a6d4bc", // andes — red desert ranges
].map(
  (id) =>
    `https://images.unsplash.com/photo-${id}?w=2400&q=80&auto=format&fit=crop`,
);

export default async function HomePage() {
  const supabase = await createServerSupabase();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (user) {
    const role = await resolveUserRole(supabase);
    redirect(role === "advisor" ? "/command-center" : "/basecamp");
  }

  return (
    <main className="relative min-h-screen overflow-hidden bg-ink text-paper">
      <HeroCarousel images={HERO_IMAGES} />

      <header className="relative z-10 flex items-baseline justify-between gap-4 px-6 py-6 sm:px-10">
        <div className="flex items-baseline gap-3">
          <span className="font-serif text-2xl tracking-tight">
            Outdoor Voyage
          </span>
          <span className="text-[10px] uppercase tracking-eyebrow text-paper/60">
            Black
          </span>
        </div>
        <span className="hidden text-[10px] uppercase tracking-[0.35em] text-paper/55 sm:block">
          By invitation only
        </span>
      </header>

      <section className="relative z-10 mx-auto flex min-h-[calc(100vh-9rem)] max-w-6xl flex-col justify-between gap-16 px-6 pb-16 pt-8 sm:px-10 lg:flex-row lg:items-center lg:gap-20 lg:pt-0">
        <div className="max-w-xl">
          <Eyebrow rule>The concierge for considered travel</Eyebrow>
          <h1 className="mt-6 font-serif text-5xl leading-[1.02] tracking-tight sm:text-6xl lg:text-7xl">
            A voyage composed in private.
          </h1>
          <p className="mt-6 max-w-md text-base leading-relaxed text-paper/75 sm:text-lg">
            An invitation-only atelier for the world&rsquo;s most deliberate
            travelers. Your itinerary is shaped slowly &mdash; by hand and by
            intelligence, never on demand.
          </p>
        </div>

        <div className="flex w-full max-w-md flex-col gap-6">
          <div className="rounded-sm bg-card p-8 text-ink shadow-float sm:p-10">
            <h2 className="font-serif text-3xl tracking-tight">Sign in</h2>
            <p className="mt-2 text-[11px] uppercase tracking-label text-ink/55">
              Enter your email for a sign-in link
            </p>
            <div className="mt-8">
              <SignInEntry />
            </div>
          </div>

          <p className="text-center text-[11px] uppercase tracking-label text-paper/50">
            Membership is extended by referral
          </p>
        </div>
      </section>

      <footer className="relative z-10 border-t border-paper/10 px-6 py-6 text-[10px] uppercase tracking-label text-paper/50 sm:px-10">
        <div className="mx-auto flex max-w-6xl items-center justify-between">
          <span>© Outdoor Voyage</span>
          <span className="hidden sm:inline">Est. in the field</span>
        </div>
      </footer>
    </main>
  );
}
