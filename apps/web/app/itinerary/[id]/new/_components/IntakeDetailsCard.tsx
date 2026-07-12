"use client";

// The intake details card — the quiet ledger beside the floating chat that
// fills in as Artemis captures the adventure's shape. Driven entirely by SSE
// frames (`itinerary_updated`, `party_updated`); nothing here is editable —
// the conversation is the editor.

import { motion, useReducedMotion } from "framer-motion";

export type IntakeDetails = {
  title: string;
  timingKind: "exact" | "window" | "flexible" | null;
  dateStart: string | null;
  dateEnd: string | null;
  durationNights: number | null;
  timingNote: string | null;
};

export type IntakePartyMember = {
  id: string;
  full_name?: string;
  relationship_to_primary?: string;
  is_primary?: boolean;
};

const MONTHS = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
] as const;

function prettyDate(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  const month = MONTHS[(m ?? 1) - 1] ?? "";
  return `${month} ${d ?? ""}, ${y ?? ""}`;
}

export function describeTiming(d: IntakeDetails): string | null {
  if (d.timingKind === "exact" && d.dateStart && d.dateEnd) {
    return `${prettyDate(d.dateStart)} – ${prettyDate(d.dateEnd)}`;
  }
  if (d.timingKind === "window" && d.dateStart && d.dateEnd) {
    const nights = d.durationNights ? `~${d.durationNights} nights, ` : "";
    return `${nights}${prettyDate(d.dateStart)} – ${prettyDate(d.dateEnd)}`;
  }
  if (d.timingKind === "flexible") {
    return d.timingNote ? `Open — ${d.timingNote}` : "Open";
  }
  return null;
}

function Row({ label, value }: { label: string; value: string | null }) {
  const reduced = useReducedMotion() ?? false;
  return (
    <div className="space-y-1">
      <p className="font-sans text-[10px] uppercase tracking-[0.22em] text-paper/50">
        {label}
      </p>
      {value ? (
        <motion.p
          key={value}
          initial={{ opacity: 0, y: reduced ? 0 : 4 }}
          animate={{ opacity: 1, y: 0 }}
          className="font-serif text-lg leading-snug text-paper"
        >
          {value}
        </motion.p>
      ) : (
        <p className="font-serif text-lg italic leading-snug text-paper/30">
          still listening…
        </p>
      )}
    </div>
  );
}

export function IntakeDetailsCard({
  details,
  party,
}: {
  details: IntakeDetails;
  party: IntakePartyMember[];
}) {
  // Companions are everyone but the account holder. A settled solo trip seats
  // the primary alone — that's a real answer ("just you"), not silence, so it
  // must stop the "still listening…" state rather than list the traveler's own
  // name back at them.
  const companions = party.filter((m) => !m.is_primary);
  const soloSettled = companions.length === 0 && party.some((m) => m.is_primary);
  const partyLine =
    companions.length > 0
      ? companions
          .map((m) => {
            const name = m.full_name?.trim() || "someone new";
            return m.relationship_to_primary
              ? `${name} (${m.relationship_to_primary})`
              : name;
          })
          .join(" · ")
      : soloSettled
        ? "Just you"
        : null;

  return (
    <aside
      data-testid="intake-details"
      className="w-full max-w-xs space-y-6 rounded-lg border border-paper/15 bg-ink/40 p-6 backdrop-blur-md"
    >
      <p className="font-sans text-[10px] uppercase tracking-[0.3em] text-paper/60">
        The adventure, so far
      </p>
      <Row label="Name" value={details.title.trim() || null} />
      <Row label="When" value={describeTiming(details)} />
      <Row label="Who" value={partyLine} />
    </aside>
  );
}
