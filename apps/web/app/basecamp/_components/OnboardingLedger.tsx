"use client";

// The onboarding ledger — the quiet counterpart to the immersive intake's
// details card (app/itinerary/[id]/new/IntakeDetailsCard). It sits beside the
// floating first-touch chat and lights a checkmark as the agent captures each
// of onboarding's two goals. Nothing here is editable — the conversation is
// the editor. Driven entirely by `profile_updated` SSE frames (kind only):
// destination goals key off `dream_signal`/`aspiration`, everything else is
// "something about you".

import { motion, useReducedMotion } from "framer-motion";

export type OnboardingGoals = {
  /** A dream_signal / aspiration profile fact has landed. */
  destinationCaptured: boolean;
  /** Any other profile fact (a passion, a preference, a deal-breaker…). */
  factCaptured: boolean;
};

/** Profile-fact kinds that satisfy the "dream destination" goal. */
export const DESTINATION_FACT_KINDS: ReadonlySet<string> = new Set([
  "dream_signal",
  "aspiration",
]);

function Check() {
  return (
    <span
      aria-hidden
      className="flex h-4 w-4 items-center justify-center rounded-full bg-brand text-[9px] font-semibold text-paper"
    >
      ✓
    </span>
  );
}

function GoalRow({
  label,
  done,
  captured,
}: {
  label: string;
  done: string;
  captured: boolean;
}) {
  const reduced = useReducedMotion() ?? false;
  return (
    <div className="space-y-1.5">
      <p className="font-sans text-[10px] uppercase tracking-[0.22em] text-paper/50">
        {label}
      </p>
      {captured ? (
        <motion.div
          initial={{ opacity: 0, y: reduced ? 0 : 4 }}
          animate={{ opacity: 1, y: 0 }}
          className="flex items-center gap-2"
        >
          <Check />
          <p className="font-serif text-lg leading-snug text-paper">{done}</p>
        </motion.div>
      ) : (
        <p className="font-serif text-lg italic leading-snug text-paper/30">
          still listening…
        </p>
      )}
    </div>
  );
}

export function OnboardingLedger({ goals }: { goals: OnboardingGoals }) {
  return (
    <aside
      data-testid="onboarding-ledger"
      className="w-full max-w-xs space-y-6 rounded-lg border border-paper/15 bg-ink/40 p-6 backdrop-blur-md"
    >
      <p className="font-sans text-[10px] uppercase tracking-[0.3em] text-paper/60">
        The journey, so far
      </p>
      <GoalRow
        label="Dream destination"
        done="Noted"
        captured={goals.destinationCaptured}
      />
      <GoalRow
        label="Something about you"
        done="Noted"
        captured={goals.factCaptured}
      />
    </aside>
  );
}
