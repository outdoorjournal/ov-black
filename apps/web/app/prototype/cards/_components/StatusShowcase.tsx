"use client";

import { ExperienceGlance } from "./ExperienceCard";
import type { StatusKind } from "../_lib/tokens";

const ORDER: StatusKind[] = [
  "idea",
  "proposed",
  "approved",
  "booked",
  "confirmed",
  "discarded",
];

export function StatusShowcase() {
  return (
    <div className="flex flex-wrap items-end gap-4 print:break-inside-avoid">
      {ORDER.map((s) => (
        <div key={s} className="flex flex-col items-center gap-2 print:break-inside-avoid">
          <ExperienceGlance status={s} />
          <p className="text-[10px] uppercase tracking-[0.2em] text-ink/55">
            {s.replace("_", " ")}
          </p>
        </div>
      ))}
    </div>
  );
}
