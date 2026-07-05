"use client";

// S08 T05 — Advisor draft-itinerary editor surface.
//
// Three plain-text buttons: Edit / Release / Approve. Each wraps an
// optimistic mutation against the S08 lock/release/approve routes with a
// local-revert-on-failure (match the S07 MoodBoard pattern in Card.tsx).
// The three data-attributes on the top-level element are the slice's
// debugging contract: advisors + tests inspect them to reason about state.
//
// Craft-feel invariants (R014): no spinners, no icons, no emoji, no
// skeletons. `disabled` on an action button is the only "in-flight"
// affordance. Revert-on-failure flips state back silently; the advisor
// re-tries.
//
// Lock state is local — the API's ItineraryResponse does not expose
// locked_by, so we treat "unlocked" as the default until the advisor
// clicks Edit and acquireItineraryLock succeeds. If the lock call 409s
// (`already_locked`), we assume another advisor holds it and set
// `locked-by-other`. Release flips back to `unlocked`.

import { useCallback } from "react";

import {
  acquireItineraryLock,
  approveItinerary,
  createApiClient,
  releaseItineraryLock,
  updateNode,
  type EdgeResponse,
  type ItineraryStatus,
  type NodeResponse,
} from "@ov-black/api-client";

import { draftItineraryStore } from "./draftItineraryStore";

export type DraftItineraryEditorProps = {
  itineraryId: string;
  apiBaseUrl: string;
  accessToken: string;
  initialNodes: NodeResponse[];
  initialEdges: EdgeResponse[];
  initialStatus: ItineraryStatus;
};

export function DraftItineraryEditor({
  itineraryId,
  apiBaseUrl,
  accessToken,
  initialNodes,
  initialEdges: _initialEdges,
  initialStatus,
}: DraftItineraryEditorProps) {
  return (
    <draftItineraryStore.Provider initial={{ initialStatus, initialNodes }}>
      <DraftItineraryEditorInner
        itineraryId={itineraryId}
        apiBaseUrl={apiBaseUrl}
        accessToken={accessToken}
      />
    </draftItineraryStore.Provider>
  );
}

type InnerProps = {
  itineraryId: string;
  apiBaseUrl: string;
  accessToken: string;
};

function DraftItineraryEditorInner({
  itineraryId,
  apiBaseUrl,
  accessToken,
}: InnerProps) {
  const status = draftItineraryStore.useStore((s) => s.status);
  const lockStatus = draftItineraryStore.useStore((s) => s.lockStatus);
  const nodes = draftItineraryStore.useStore((s) => s.nodes);
  const edgePending = draftItineraryStore.useStore((s) => s.edgePending);
  const releasePending = draftItineraryStore.useStore((s) => s.releasePending);
  const approvePending = draftItineraryStore.useStore((s) => s.approvePending);
  const storeApi = draftItineraryStore.useStoreApi();

  const lockedBySelf = lockStatus === "locked-by-me";
  const isApproved = status === "approved";
  const inputsEditable = lockedBySelf && !isApproved;

  const clientForAction = useCallback(
    () => createApiClient({ baseUrl: apiBaseUrl, accessToken }),
    [apiBaseUrl, accessToken],
  );

  const onEdit = useCallback(() => {
    const s = storeApi.getState();
    if (s.edgePending || s.lockStatus === "locked-by-me" || s.status === "approved") return;
    s.setEdgePending(true);
    const previousLock = s.lockStatus;
    // Optimistic flip: most advisors will acquire cleanly. Revert to the
    // previous state on failure (already_locked → locked-by-other;
    // anything else → unlocked).
    s.setLockStatus("locked-by-me");
    void acquireItineraryLock(clientForAction(), itineraryId)
      .then((result) => {
        if (!result.ok) {
          if (result.detail === "already_locked") {
            storeApi.getState().setLockStatus("locked-by-other");
          } else {
            storeApi.getState().setLockStatus(previousLock);
          }
        }
      })
      .finally(() => {
        storeApi.getState().setEdgePending(false);
      });
  }, [clientForAction, itineraryId, storeApi]);

  const onRelease = useCallback(() => {
    const s = storeApi.getState();
    if (s.releasePending || s.lockStatus !== "locked-by-me") return;
    s.setReleasePending(true);
    const previousLock = s.lockStatus;
    s.setLockStatus("unlocked");
    void releaseItineraryLock(clientForAction(), itineraryId)
      .then((result) => {
        if (!result.ok) {
          storeApi.getState().setLockStatus(previousLock);
        }
      })
      .finally(() => {
        storeApi.getState().setReleasePending(false);
      });
  }, [clientForAction, itineraryId, storeApi]);

  const onApprove = useCallback(() => {
    const s = storeApi.getState();
    if (s.approvePending || s.status === "approved") return;
    s.setApprovePending(true);
    const previousStatus = s.status;
    s.setStatus("approved");
    void approveItinerary(clientForAction(), itineraryId)
      .then((result) => {
        if (!result.ok) {
          storeApi.getState().setStatus(previousStatus);
        }
      })
      .finally(() => {
        storeApi.getState().setApprovePending(false);
      });
  }, [clientForAction, itineraryId, storeApi]);

  const onNodeFieldBlur = useCallback(
    (nodeId: string, field: "title" | "source_id", nextValue: string) => {
      const s = storeApi.getState();
      const editable =
        s.lockStatus === "locked-by-me" && s.status !== "approved";
      if (!editable) return;
      const target = s.nodes.find((n) => n.id === nodeId);
      if (!target) return;
      const currentValue = field === "title" ? target.title : target.source_id;
      if ((currentValue ?? "") === nextValue) return;
      const previousNodes = s.nodes;
      s.patchNode(nodeId, field, nextValue);
      const patch =
        field === "title" ? { title: nextValue } : { source_id: nextValue };
      void updateNode(clientForAction(), {
        itineraryId,
        nodeId,
        patch,
      }).then((result) => {
        if (!result.ok) {
          storeApi.getState().setNodes(previousNodes);
        }
      });
    },
    [clientForAction, itineraryId, storeApi],
  );

  return (
    <section
      data-testid="draft-itinerary-editor"
      data-lock-status={lockStatus}
      data-itinerary-status={status}
      className="flex flex-col gap-8"
    >
      <div className="flex flex-wrap gap-3">
        <button
          type="button"
          onClick={onEdit}
          disabled={
            edgePending ||
            lockedBySelf ||
            lockStatus === "locked-by-other" ||
            isApproved
          }
          data-testid="draft-itinerary-edit"
          className="h-10 rounded-md border border-ink/20 bg-paper px-4 font-sans text-[12px] uppercase tracking-[0.18em] text-ink transition-colors hover:bg-ink/5 disabled:cursor-default disabled:opacity-50"
        >
          Edit
        </button>
        <button
          type="button"
          onClick={onRelease}
          disabled={releasePending || !lockedBySelf || isApproved}
          data-testid="draft-itinerary-release"
          className="h-10 rounded-md border border-ink/15 bg-paper px-4 font-sans text-[12px] uppercase tracking-[0.18em] text-ink/80 transition-colors hover:bg-ink/5 disabled:cursor-default disabled:opacity-50"
        >
          Release
        </button>
        <button
          type="button"
          onClick={onApprove}
          disabled={approvePending || isApproved}
          data-testid="draft-itinerary-approve"
          className="h-10 rounded-md border border-ink/15 bg-paper px-4 font-sans text-[12px] uppercase tracking-[0.18em] text-ink transition-colors hover:bg-ink/5 disabled:cursor-default disabled:opacity-50"
        >
          Approve
        </button>
      </div>

      {lockStatus === "locked-by-other" ? (
        <p
          data-testid="draft-itinerary-locked-notice"
          className="font-sans text-sm text-ink/70"
        >
          Locked by another advisor.
        </p>
      ) : null}

      <ol className="flex flex-col gap-4" data-testid="draft-itinerary-nodes">
        {nodes.map((node, idx) => (
          <li
            key={node.id}
            data-testid="draft-itinerary-node"
            data-node-id={node.id}
            className="rounded-lg border border-ink/10 bg-paper/90 px-5 py-4"
          >
            <div className="flex items-baseline gap-3">
              <span className="font-sans text-[11px] uppercase tracking-[0.2em] text-ink/50">
                {String(idx + 1).padStart(2, "0")}
              </span>
              <label
                htmlFor={`node-title-${node.id}`}
                className="sr-only"
              >
                Title
              </label>
              <input
                id={`node-title-${node.id}`}
                data-testid="draft-itinerary-node-title"
                type="text"
                defaultValue={node.title}
                readOnly={!inputsEditable}
                disabled={isApproved}
                onBlur={(event) =>
                  onNodeFieldBlur(node.id, "title", event.target.value)
                }
                className="w-full border-0 bg-transparent font-serif text-xl leading-tight text-ink focus:outline-hidden focus:ring-0"
              />
            </div>
            <div className="mt-3 flex items-center gap-3">
              <label
                htmlFor={`node-source-id-${node.id}`}
                className="font-sans text-[11px] uppercase tracking-[0.2em] text-ink/50"
              >
                Source id
              </label>
              <input
                id={`node-source-id-${node.id}`}
                data-testid="draft-itinerary-node-source-id"
                type="text"
                defaultValue={node.source_id ?? ""}
                readOnly={!inputsEditable}
                disabled={isApproved}
                onBlur={(event) =>
                  onNodeFieldBlur(node.id, "source_id", event.target.value)
                }
                className="flex-1 border-0 bg-transparent font-sans text-sm text-ink/80 focus:outline-hidden focus:ring-0"
              />
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}
