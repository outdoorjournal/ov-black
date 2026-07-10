"use client";

// The decision surface — the agent lays 2–4 alternatives on the table.
//
// Each option gets room for the agent's case; the traveler answers by
// tapping "Choose this". The pick flows back through the ordinary turn
// endpoint as the traveler's next message (composed by the shell), so the
// agent reads it like any reply — no second write path into the graph.
// R014: buttons disable while a turn is streaming; no spinners.

import { cn } from "@/lib/utils";

import type { OptionsSurfaceView, OptionView } from "./types";

export type OptionsSurfaceProps = {
  options: OptionsSurfaceView;
  /** True while a turn is streaming — choosing must wait for the reply. */
  busy: boolean;
  onChoose: (option: OptionView) => void;
};

export function OptionsSurface({ options, busy, onChoose }: OptionsSurfaceProps) {
  return (
    <div className="px-6 py-5" data-testid="options-surface">
      <h2 className="font-serif text-[22px] leading-snug text-ink">{options.question}</h2>
      {options.context ? (
        <p className="mt-1.5 font-sans text-[13px] leading-snug text-ink/60">{options.context}</p>
      ) : null}

      <div className="mt-5 space-y-4">
        {options.options.map((option) => (
          <article
            key={option.id}
            data-testid="options-surface-option"
            className="rounded-md bg-paper px-4 py-4 ring-1 ring-ink/10"
          >
            <h3 className="font-serif text-[17px] leading-snug text-ink">{option.title}</h3>
            {option.tagline ? (
              <p className="mt-0.5 font-sans text-[11px] uppercase tracking-[0.14em] text-ink/50">
                {option.tagline}
              </p>
            ) : null}
            {option.case ? (
              <p className="mt-2.5 font-sans text-[13px] leading-relaxed text-ink/70">
                {option.case}
              </p>
            ) : null}
            <button
              type="button"
              disabled={busy}
              onClick={() => onChoose(option)}
              data-testid="options-surface-choose"
              className={cn(
                "mt-3.5 rounded-full px-4 py-1.5 font-sans text-[12px] tracking-wide",
                "text-brand ring-1 ring-inset ring-brand/40 transition-colors",
                "hover:bg-brand/10 hover:ring-brand disabled:cursor-default",
                "disabled:text-ink/35 disabled:ring-ink/15 disabled:hover:bg-transparent",
              )}
            >
              Choose this
            </button>
          </article>
        ))}
      </div>
    </div>
  );
}
