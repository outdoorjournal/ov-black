import { InviteEntry } from "./_components/invite-entry";
import { SignInEntry } from "./_components/sign-in-entry";

export default function HomePage() {
  return (
    <main className="relative min-h-screen overflow-hidden bg-ink text-paper">
      <div
        aria-hidden
        className="absolute inset-0 bg-[radial-gradient(ellipse_at_30%_20%,#3a4a5c_0%,#1a1f2a_45%,#0a0a0a_85%)]"
      />
      <div
        aria-hidden
        className="absolute inset-0 bg-[url('/images/hero.jpg')] bg-cover bg-center opacity-60"
      />
      <div
        aria-hidden
        className="absolute inset-0 bg-gradient-to-b from-ink/50 via-ink/40 to-ink/90"
      />
      <div
        aria-hidden
        className="absolute inset-x-0 bottom-0 h-48 bg-gradient-to-t from-ink to-transparent"
      />

      <header className="relative z-10 flex items-center justify-between px-6 py-6 sm:px-10">
        <div className="flex items-baseline gap-3">
          <span className="font-serif text-2xl tracking-tight">
            Outdoor Voyage
          </span>
          <span className="text-[10px] uppercase tracking-[0.35em] text-paper/60">
            Black
          </span>
        </div>
        <span className="hidden text-[10px] uppercase tracking-[0.35em] text-paper/60 sm:block">
          By invitation only
        </span>
      </header>

      <section className="relative z-10 mx-auto flex min-h-[calc(100vh-5.5rem)] max-w-6xl flex-col justify-between gap-16 px-6 pb-16 pt-8 sm:px-10 lg:flex-row lg:items-center lg:gap-20 lg:pt-0">
        <div className="max-w-xl">
          <p className="text-[10px] uppercase tracking-[0.4em] text-paper/60">
            The concierge for considered travel
          </p>
          <h1 className="mt-6 font-serif text-5xl leading-[1.02] tracking-tight sm:text-6xl lg:text-7xl">
            A voyage composed in private.
          </h1>
          <p className="mt-6 max-w-md text-base leading-relaxed text-paper/75 sm:text-lg">
            Outdoor Voyage Black is an invitation-only atelier for the
            world&rsquo;s most deliberate travelers. Your itinerary is shaped slowly, by hand
            and by intelligence — never on demand.
          </p>
        </div>

        <div className="flex w-full max-w-md flex-col gap-6">
          <div className="rounded-sm bg-paper p-8 text-ink shadow-[0_30px_80px_-20px_rgba(0,0,0,0.6)] sm:p-10">
            <h2 className="font-serif text-3xl tracking-tight">Sign in</h2>
            <p className="mt-2 text-[11px] uppercase tracking-[0.3em] text-ink/55">
              Returning members
            </p>
            <div className="mt-8">
              <SignInEntry />
            </div>

            <div className="my-8 flex items-center gap-3 text-[10px] uppercase tracking-[0.3em] text-ink/40">
              <span className="h-px flex-1 bg-ink/10" />
              <span>New here</span>
              <span className="h-px flex-1 bg-ink/10" />
            </div>

            <h3 className="font-serif text-2xl tracking-tight">
              Claim your invitation
            </h3>
            <p className="mt-2 text-[11px] uppercase tracking-[0.3em] text-ink/55">
              Enter the code you were given
            </p>
            <div className="mt-6">
              <InviteEntry />
            </div>
          </div>

          <p className="text-center text-[11px] uppercase tracking-[0.3em] text-paper/50">
            Membership is extended by referral
          </p>
        </div>
      </section>

      <footer className="relative z-10 border-t border-paper/10 px-6 py-6 text-[10px] uppercase tracking-[0.3em] text-paper/50 sm:px-10">
        <div className="mx-auto flex max-w-6xl items-center justify-between">
          <span>© Outdoor Voyage</span>
          <span className="hidden sm:inline">Est. in the field</span>
        </div>
      </footer>
    </main>
  );
}
