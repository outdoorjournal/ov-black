// The shared public-marketing masthead — the "front of house" chrome for
// unauthenticated surfaces (landing, operator profiles, campaign fronts), as
// distinct from the ink app-chrome `AppHeader` used inside the signed-in
// product. Transparent by design so it floats over a cinematic hero; paper
// text, so it expects a dark backdrop beneath it. Presentational + dumb.

import Link from "next/link";

export function SiteHeader() {
  return (
    <header className="relative z-20 flex items-baseline justify-between gap-4 px-6 py-6 text-paper sm:px-10">
      <Link
        href="/"
        className="flex items-baseline gap-3 transition-opacity hover:opacity-80"
      >
        <span className="font-serif text-2xl tracking-tight">
          Outdoor Voyage
        </span>
        <span className="text-[10px] uppercase tracking-eyebrow text-paper/60">
          Black
        </span>
      </Link>
      <span className="hidden text-[10px] uppercase tracking-[0.35em] text-paper/55 sm:block">
        By invitation only
      </span>
    </header>
  );
}
