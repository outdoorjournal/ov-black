"use client";

// Two-version control over the trunk/fork model. Every trip is presented as
// the OFFICIAL version (the trunk — the transacted record) plus the viewer's
// own working copy: the traveler's "My version", the advisor's "My workspace".
// Either is lazily forked on the first edit (see store.forkAndMove), so before
// any change it's just a read-through of Official — the toggle is shown
// regardless so the two-version model is legible.
//
// On a real fork the affordances differ by role: a traveler asks staff to
// merge (and can cancel or discard); an advisor PUBLISHES — an accept-all
// reconcile that folds the workspace into the official trunk. A blocking
// feasibility finding refuses the fast path; the diff panel's review/override
// flow is the escape hatch.

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
  const publishing = itineraryGraphStore.useStore((s) => s.publishing);
  const publishBlocked = itineraryGraphStore.useStore((s) => s.publishBlocked);
  const selectVersion = itineraryGraphStore.useStore((s) => s.selectVersion);
  const requestMerge = itineraryGraphStore.useStore((s) => s.requestMerge);
  const cancelMerge = itineraryGraphStore.useStore((s) => s.cancelMerge);
  const discardMine = itineraryGraphStore.useStore((s) => s.discardMine);
  const publishMine = itineraryGraphStore.useStore((s) => s.publishMine);

  // Without credentials we can't fork or mutate — nothing to switch.
  if (!hasCreds) return null;

  const isFork = Boolean(forkedFromId);
  const onMine = isFork || draftMine;
  const mineLabel = canEdit ? "My workspace" : "My version";
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
          {mineLabel}
        </button>
      </div>

      {/* Advisor on their workspace: publish folds it into the official trunk. */}
      {isFork && canEdit ? (
        <>
          <button
            type="button"
            data-testid="publish-mine"
            onClick={() => publishMine(push)}
            disabled={publishing}
            className={pill}
          >
            {publishing ? "Publishing…" : "Publish to official"}
          </button>
          {publishBlocked ? (
            <span
              data-testid="publish-blocked"
              className="font-sans text-[11px] text-ink/60"
            >
              A blocking finding refused the publish — review it in the diff
              panel.
            </span>
          ) : null}
          <button
            type="button"
            data-testid="discard-mine"
            onClick={() => discardMine(push)}
            disabled={discarding}
            className={pill}
          >
            {discarding ? "Discarding…" : "Discard workspace"}
          </button>
        </>
      ) : null}

      {/* Traveler on their own version (a real fork): merge + discard. */}
      {isFork && !canEdit ? (
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

      {/* Working-copy preview (on Official, no fork yet): editing starts it. */}
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
