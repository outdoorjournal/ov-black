"use client";

// The concierge's "who you talk to" top nav — the people-circles (M006/PS7).
// Shared so the itinerary ConciergeColumn and the basecamp RightRailChat present
// the SAME channel switch: Artemis (the AI) and the human channel. The human
// circle is labelled by the OTHER party — "Client" for an advisor, "Advisor" for
// a traveler (the default) — via `humanLabel`.

import type { ReactNode } from "react";

/** The two concierge channels. `human` = the Advisor people-circle. */
export type ConciergeChannel = "artemis" | "human";

export function PeopleCircles({
  channel,
  onSelect,
  humanLabel = "Advisor",
  advisorTitle,
  trailing,
}: {
  channel: ConciergeChannel;
  onSelect: (channel: ConciergeChannel) => void;
  /** Label on the human-channel circle. It names the OTHER party in the
   *  conversation, so it flips by viewer: an advisor is talking to the "Client",
   *  the traveler is talking to their "Advisor" (the default). */
  humanLabel?: string;
  /** Tooltip on the human circle (differs advisor-side vs traveler-side). */
  advisorTitle?: string;
  /** Right-aligned extra (e.g. the itinerary column's collapse chevron). */
  trailing?: ReactNode;
}) {
  return (
    <div
      data-testid="people-circles"
      className="flex shrink-0 items-center gap-2 border-b border-ink/10 px-3 py-2"
    >
      <PersonCircle
        label="Artemis"
        active={channel === "artemis"}
        onSelect={() => onSelect("artemis")}
      />
      <PersonCircle
        label={humanLabel}
        active={channel === "human"}
        onSelect={() => onSelect("human")}
        {...(advisorTitle ? { title: advisorTitle } : {})}
      />
      {trailing}
    </div>
  );
}

export function PersonCircle({
  label,
  active = false,
  onSelect,
  title,
}: {
  label: string;
  active?: boolean;
  onSelect?: () => void;
  title?: string;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      disabled={!onSelect}
      className="flex flex-col items-center gap-1"
      data-testid={`person-${label.toLowerCase()}`}
      data-active={active ? "true" : undefined}
      aria-pressed={active}
      {...(title ? { title } : {})}
    >
      <span
        aria-hidden
        className={
          "flex h-8 w-8 items-center justify-center rounded-full border font-serif text-sm transition-colors " +
          (active
            ? "border-ink/30 bg-ink/10 text-ink"
            : "border-ink/15 text-ink/40 hover:border-ink/25 hover:text-ink/60")
        }
      >
        {label.charAt(0)}
      </span>
      <span
        className={
          "font-sans text-[9px] uppercase tracking-[0.14em] " +
          (active ? "text-ink/70" : "text-ink/40")
        }
      >
        {label}
      </span>
    </button>
  );
}
