// The shared full-bleed chrome for /basecamp. Mirrors the login page
// (apps/web/app/page.tsx:6-22) so a freshly magic-linked client doesn't see
// a visual seam between sign-in and home: same radial gradient, same hero
// image at 60% opacity, same ink vignette. The chrome is purely decorative;
// content lives in children, which we slot into a stacked container so
// the gradients stay behind it.

import type { ReactNode } from "react";

import { signOutAction } from "@/app/command-center/_actions/sign-out";

export type BasecampChromeProps = {
  children: ReactNode;
};

export function BasecampChrome({ children }: BasecampChromeProps) {
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
        <form action={signOutAction}>
          <button
            type="submit"
            className="rounded-none border-b border-transparent text-[10px] uppercase tracking-[0.3em] text-paper/70 transition-colors hover:border-paper/70 hover:text-paper"
          >
            Sign out
          </button>
        </form>
      </header>

      <section className="relative z-10">{children}</section>
    </main>
  );
}
