"use client";

// Traveler-facing alternative-version controls. On the agreed plan it offers to
// branch an alternative (a fork) the traveler can reshape; on an alternative it
// offers to ask staff to merge it back. Advisors have their own fork tooling
// (the DiffPanel), so this renders nothing for them. The agreed plan is never
// edited directly — reshaping always happens on a branched alternative.

import { useRouter } from "next/navigation";

import { itineraryGraphStore } from "../store/itineraryGraphStore";

export function AlternativeControls() {
  const router = useRouter();
  const canEdit = itineraryGraphStore.useStore((s) => s.canEdit);
  const sample = itineraryGraphStore.useStore((s) => s.sample);
  const hasCreds = itineraryGraphStore.useStore((s) =>
    Boolean(s.apiBaseUrl && s.accessToken),
  );
  const creating = itineraryGraphStore.useStore((s) => s.creatingAlternative);
  const requesting = itineraryGraphStore.useStore((s) => s.requestingMerge);
  const requested = itineraryGraphStore.useStore((s) => s.mergeRequested);
  const createAlternative = itineraryGraphStore.useStore(
    (s) => s.createAlternative,
  );
  const requestMerge = itineraryGraphStore.useStore((s) => s.requestMerge);

  // Advisor tooling lives elsewhere; without credentials we can't mutate.
  if (canEdit || !hasCreds) return null;

  const isAlternative = Boolean(sample.itinerary?.forked_from_id);

  const buttonClass =
    "rounded-full border border-ink/20 bg-paper/80 px-3 py-1 font-sans text-[11px] font-medium text-ink/80 transition-colors hover:bg-ink/5 disabled:opacity-50";

  if (isAlternative) {
    return (
      <button
        type="button"
        data-testid="request-merge"
        onClick={requestMerge}
        disabled={requesting || requested}
        className={buttonClass}
      >
        {requested
          ? "Merge requested ✓"
          : requesting
            ? "Sending…"
            : "Ask staff to merge"}
      </button>
    );
  }

  return (
    <button
      type="button"
      data-testid="make-alternative"
      onClick={() =>
        createAlternative((forkId) => router.push(`/itinerary/${forkId}`))
      }
      disabled={creating}
      className={buttonClass}
    >
      {creating ? "Creating…" : "Make an alternative"}
    </button>
  );
}
