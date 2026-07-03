"use client";

// Traveler-facing two-version control. Every trip is presented as the OFFICIAL
// (staff-agreed) version and the traveler's own MY VERSION; this segmented
// toggle switches between them. "My version" is lazily forked on the first edit
// (see store.forkAndMove), so before any change it's just a read-through of
// Official — the toggle is shown regardless so the two-version model is legible.
// On a real fork the traveler can ask staff to merge (and cancel that request)
// or discard the whole version. Advisors have their own DiffPanel/reconcile
// tooling, so this renders nothing for them.

import { useRouter } from "next/navigation";

import { itineraryGraphStore } from "../store/itineraryGraphStore";

export function VersionSwitcher() {
  const router = useRouter();
  const canEdit = itineraryGraphStore.useStore((s) => s.canEdit);
  const hasCreds = itineraryGraphStore.useStore((s) =>
    Boolean(s.apiBaseUrl && s.accessToken),
  );
  const forkedFromId = itineraryGraphStore.useStore(
    (s) => s.sample.itinerary?.forked_from_id ?? null,
  );
  const draftMine = itineraryGraphStore.useStore((s) => s.draftMine);
  const requestingMerge = itineraryGraphStore.useStore((s) => s.requestingMerge);
  const mergeRequested = itineraryGraphStore.useStore((s) => s.mergeRequested);
  const cancelingMerge = itineraryGraphStore.useStore((s) => s.cancelingMerge);
  const discarding = itineraryGraphStore.useStore((s) => s.discarding);
  const selectVersion = itineraryGraphStore.useStore((s) => s.selectVersion);
  const requestMerge = itineraryGraphStore.useStore((s) => s.requestMerge);
  const cancelMerge = itineraryGraphStore.useStore((s) => s.cancelMerge);
  const discardMine = itineraryGraphStore.useStore((s) => s.discardMine);

  // Advisor tooling lives elsewhere; without credentials we can't mutate.
  if (canEdit || !hasCreds) return null;

  const isFork = Boolean(forkedFromId);
  const onMine = isFork || draftMine;
  const push = (id: string) => router.push(`/itinerary/${id}`);

  const seg = (active: boolean) =>
    `px-3 py-1 font-sans text-[11px] font-medium transition-colors ${
      active ? "bg-ink text-paper" : "text-ink/70 hover:bg-ink/5"
    }`;
  const pill =
    "rounded-full border border-ink/20 bg-paper/80 px-3 py-1 font-sans text-[11px] font-medium text-ink/80 transition-colors hover:bg-ink/5 disabled:opacity-50";

  return (
    <div className="flex flex-wrap items-center gap-2">
      <div
        role="group"
        aria-label="Itinerary version"
        className="inline-flex overflow-hidden rounded-full border border-ink/20 bg-paper/80"
      >
        <button
          type="button"
          data-testid="version-official"
          aria-pressed={!onMine}
          onClick={() => selectVersion("official", push)}
          className={seg(!onMine)}
        >
          Official
        </button>
        <button
          type="button"
          data-testid="version-mine"
          aria-pressed={onMine}
          onClick={() => selectVersion("mine", push)}
          className={`${seg(onMine)} border-l border-ink/15`}
        >
          My version
        </button>
      </div>

      {/* On the traveler's own version (a real fork): merge + discard. */}
      {isFork ? (
        <>
          {mergeRequested ? (
            <>
              <span
                data-testid="merge-requested"
                className="font-sans text-[11px] text-ink/60"
              >
                Merge requested ✓
              </span>
              <button
                type="button"
                data-testid="cancel-merge"
                onClick={cancelMerge}
                disabled={cancelingMerge}
                className={pill}
              >
                {cancelingMerge ? "Cancelling…" : "Cancel request"}
              </button>
            </>
          ) : (
            <button
              type="button"
              data-testid="request-merge"
              onClick={requestMerge}
              disabled={requestingMerge}
              className={pill}
            >
              {requestingMerge ? "Sending…" : "Ask staff to merge"}
            </button>
          )}
          <button
            type="button"
            data-testid="discard-mine"
            onClick={() => discardMine(push)}
            disabled={discarding}
            className={pill}
          >
            {discarding ? "Discarding…" : "Discard my version"}
          </button>
        </>
      ) : null}

      {/* Draft preview (on Official, no fork yet): editing starts the version. */}
      {draftMine && !isFork ? (
        <span
          data-testid="draft-mine-hint"
          className="font-sans text-[11px] italic text-ink/55"
        >
          Make a change to start your private version.
        </span>
      ) : null}
    </div>
  );
}
