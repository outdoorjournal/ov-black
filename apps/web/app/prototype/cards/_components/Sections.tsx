"use client";

import type { ReactNode } from "react";

import {
  STATUS_TOKENS,
  TYPE_TOKENS,
  type CardKind,
  type StatusKind,
} from "@/app/_components/itinerary-graph/shared/cards/tokens";

export function Section({
  index,
  title,
  blurb,
  notes,
  children,
}: {
  index: string;
  title: string;
  blurb?: string;
  notes?: string[];
  children: ReactNode;
}) {
  return (
    <section className="border-t border-ink/10 pt-10 print:break-before-page print:border-t-0 print:pt-0">
      <header className="mb-6 flex items-baseline gap-4 print:break-after-avoid">
        <span className="font-mono text-[11px] uppercase tracking-label text-ink/40">
          {index}
        </span>
        <div>
          <h2 className="font-serif text-2xl leading-tight text-ink sm:text-3xl">
            {title}
          </h2>
          {blurb ? <p className="mt-1 max-w-2xl text-[13px] text-ink/65">{blurb}</p> : null}
        </div>
      </header>

      <div className="grid grid-cols-1 gap-8 lg:grid-cols-[1fr_240px] print:grid-cols-1">
        <div className="space-y-8">{children}</div>
        {notes ? (
          <aside className="rounded-md border border-ink/10 bg-paper/60 p-4 print:break-inside-avoid">
            <p className="text-[10px] uppercase tracking-[0.2em] text-ink/50">
              Design notes
            </p>
            <ul className="mt-2 space-y-2 text-[11px] leading-relaxed text-ink/80">
              {notes.map((n, i) => (
                <li key={i}>· {n}</li>
              ))}
            </ul>
          </aside>
        ) : null}
      </div>
    </section>
  );
}

export function Row({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <div className="print:break-inside-avoid">
      <p className="mb-3 text-[10px] uppercase tracking-[0.2em] text-ink/45 print:break-after-avoid">{label}</p>
      <div className="flex flex-wrap items-start gap-4">{children}</div>
    </div>
  );
}

export function TaxonomyGrid() {
  const order: CardKind[] = [
    "destination",
    "flight",
    "subway",
    "train",
    "drive",
    "walk",
    "boat",
    "hotel",
    "experience",
    "meal",
    "free_time",
    "waiting",
    "note",
  ];
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4">
      {order.map((k) => {
        const t = TYPE_TOKENS[k];
        return (
          <div
            key={k}
            className="flex items-start gap-3 rounded-md border border-ink/10 bg-paper/60 p-3"
          >
            <div
              className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md text-paper"
              style={{ backgroundColor: t.accent }}
              aria-hidden
            >
              <t.Icon size={18} strokeWidth={1.6} />
            </div>
            <div className="min-w-0 flex-1">
              <p className="font-serif text-[14px] leading-tight text-ink">
                {t.label}
              </p>
              <p className="font-mono text-[10px] uppercase tracking-[0.18em] text-ink/55">
                {t.short} · {t.accent.toLowerCase()}
              </p>
              <p className="mt-1 text-[11px] text-ink/70">{t.blurb}</p>
            </div>
          </div>
        );
      })}
    </div>
  );
}

export function StatusLegend() {
  const order: StatusKind[] = [
    "idea",
    "proposed",
    "approved",
    "booked",
    "confirmed",
    "discarded",
  ];
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 md:grid-cols-3">
      {order.map((s) => {
        const t = STATUS_TOKENS[s];
        return (
          <div
            key={s}
            className="rounded-md border border-ink/10 bg-paper/60 p-3"
          >
            <p className="font-serif text-[15px] leading-tight text-ink">
              {t.label}
            </p>
            <p className="mt-0.5 text-[11px] text-ink/65">{t.description}</p>
            <p className="mt-2 text-[10px] uppercase tracking-[0.18em] text-ink/45">
              Non-color cue
            </p>
            <p className="text-[11px] text-ink/80">{t.nonColorCue}</p>
          </div>
        );
      })}
    </div>
  );
}

export function A11yPanel() {
  const items: { title: string; body: string }[] = [
    {
      title: "Never color alone",
      body: "Every type and status carries an icon, label, or texture cue alongside its color. Color-blind users get the same signal.",
    },
    {
      title: "AA contrast on text",
      body: "Body copy is ink/85 on #f7f4ee paper (≈12.4:1). Type accents are tested ≥ 4.5:1 for text use; ≥ 3:1 for non-text indicators.",
    },
    {
      title: "Touch targets ≥ 44×44",
      body: "Glance cards are 260px wide, taps land on the whole shell. Inline actions inside the zoom view sit on 44px hit areas.",
    },
    {
      title: "ARIA + semantic structure",
      body: "Each card has role=group with an accessible name combining type + status. SVG diagrams carry role=img with aria-label summaries.",
    },
    {
      title: "Reduced motion",
      body: "Hover lift and status flash respect prefers-reduced-motion (apply via globals; this prototype uses static lift).",
    },
    {
      title: "Localized signage",
      body: "Foreign-language signage is paired with romanization + English gloss. Subway line color repeats the official agency color so wayfinding transfers in-country.",
    },
    {
      title: "Type sizes",
      body: "Min body 11px (1rem ≈ 16px would be safer; we use 11–12px deliberately for density and verify against the user's text-size override path).",
    },
    {
      title: "Focus states",
      body: "Cards expose a 2px ink/40 outline-solid on :focus-visible (set globally in app), preserving the cream paper aesthetic.",
    },
  ];
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
      {items.map((it) => (
        <div
          key={it.title}
          className="rounded-md border border-ink/10 bg-paper/60 p-3"
        >
          <p className="font-serif text-[15px] leading-tight text-ink">
            {it.title}
          </p>
          <p className="mt-1 text-[11px] leading-relaxed text-ink/75">
            {it.body}
          </p>
        </div>
      ))}
    </div>
  );
}
