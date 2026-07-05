"use client";

// The onboarding milestone card — the visual "we know you now" moment,
// interleaved into the conversation the instant the server's onboarding_complete
// verdict flips true (evaluate_onboarding). It fires on that ONE derived
// criterion, not on any single fact, so raising the bar (two facts + a known
// age, etc.) changes only the server rule, never this card. Kept delightful — a
// spring pop, a sparkle, a one-time shimmer — but on-brand: serif, brand orange
// as the only punch of colour. Rendered by ConversationStream for turns with
// role "milestone".

import { motion } from "framer-motion";
import { Sparkles } from "lucide-react";

import { Eyebrow } from "@/components/ui/eyebrow";

export function OnboardingMilestoneCard() {
  return (
    <motion.div
      data-testid="onboarding-milestone-card"
      data-role="milestone"
      initial={{ opacity: 0, scale: 0.92, y: 10 }}
      animate={{ opacity: 1, scale: 1, y: 0 }}
      transition={{ type: "spring", stiffness: 420, damping: 26 }}
      className="relative self-start overflow-hidden rounded-md border border-brand/30 bg-brand/4 px-5 py-4"
    >
      {/* One-time shimmer sweep on entrance — the "something happened" spark. */}
      <motion.span
        aria-hidden
        initial={{ x: "-130%" }}
        animate={{ x: "130%" }}
        transition={{ delay: 0.12, duration: 0.9, ease: "easeInOut" }}
        className="pointer-events-none absolute inset-y-0 left-0 w-1/3 bg-linear-to-r from-transparent via-white/50 to-transparent"
      />
      <div className="relative flex items-center gap-2">
        <motion.span
          aria-hidden
          initial={{ scale: 0, rotate: -40 }}
          animate={{ scale: 1, rotate: 0 }}
          transition={{ delay: 0.08, type: "spring", stiffness: 500, damping: 16 }}
          className="text-brand"
        >
          <Sparkles className="h-4 w-4" strokeWidth={1.75} />
        </motion.span>
        <Eyebrow>We&rsquo;ve got a feel for you</Eyebrow>
      </div>
      <p className="relative mt-2 font-serif text-lg leading-snug text-ink">
        Enough to begin shaping things around how you travel. Your concierge
        takes it from here.
      </p>
    </motion.div>
  );
}
