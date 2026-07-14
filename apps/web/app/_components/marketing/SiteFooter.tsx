// Shared public-marketing footer — the counterpart to `SiteHeader`. A
// self-contained ink slab so it reads consistently no matter what colour the
// page body above it is. Presentational + dumb.

import Link from "next/link";

export function SiteFooter() {
  return (
    <footer className="relative z-10 border-t border-paper/10 bg-ink px-6 py-10 text-paper sm:px-10">
      <div className="mx-auto flex max-w-6xl flex-col gap-6 sm:flex-row sm:items-end sm:justify-between">
        <div className="flex flex-col gap-2">
          <Link
            href="/"
            className="font-serif text-lg tracking-tight text-paper transition-opacity hover:opacity-80"
          >
            Outdoor Voyage
          </Link>
          <p className="text-[10px] uppercase tracking-label text-paper/70">
            Boulder, Colorado
          </p>
        </div>

        <p className="max-w-sm text-[11px] leading-relaxed text-paper/60">
          A concierge for considered travel. Every operator we present is
          vetted, certified, and insured — with your money reaching the people
          on the ground.
        </p>
      </div>

      <div className="mx-auto mt-8 max-w-6xl border-t border-paper/5 pt-6 text-[10px] uppercase tracking-label text-paper/50">
        © 2026 Outdoor Voyage, Inc. All rights reserved.
      </div>
    </footer>
  );
}
