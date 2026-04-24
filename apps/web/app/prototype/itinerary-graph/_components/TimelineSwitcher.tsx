"use client";

import type { SampleTimeline } from "../_lib/types";

interface TimelineSwitcherProps {
  samples: SampleTimeline[];
  activeId: string;
  onChange: (sample: SampleTimeline) => void;
}

export function TimelineSwitcher({
  samples,
  activeId,
  onChange,
}: TimelineSwitcherProps) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {samples.map((s) => {
        const active = s.id === activeId;
        return (
          <button
            key={s.id}
            type="button"
            onClick={() => onChange(s)}
            className={[
              "rounded-md border px-3 py-1.5 text-left transition",
              active
                ? "border-ink bg-ink text-paper"
                : "border-ink/15 bg-paper text-ink/80 hover:bg-ink/5",
            ].join(" ")}
          >
            <div className="font-serif text-[14px] leading-tight">{s.label}</div>
            <div
              className={[
                "text-[10px] uppercase tracking-[0.18em]",
                active ? "text-paper/70" : "text-ink/50",
              ].join(" ")}
            >
              {s.subtitle}
            </div>
          </button>
        );
      })}
    </div>
  );
}
