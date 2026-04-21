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

import { useCallback, useState } from "react";

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

export type DraftItineraryEditorProps = {
  itineraryId: string;
  apiBaseUrl: string;
  accessToken: string;
  initialNodes: NodeResponse[];
  initialEdges: EdgeResponse[];
  initialStatus: ItineraryStatus;
};

type LockStatus = "unlocked" | "locked-by-me" | "locked-by-other";

type NodeView = {
  id: string;
  title: string;
  source: string | null;
  source_id: string | null;
};

function toNodeView(node: NodeResponse): NodeView {
  return {
    id: node.id,
    title: node.title,
    source: node.source ?? null,
    source_id: node.source_id ?? null,
  };
}

export function DraftItineraryEditor({
  itineraryId,
  apiBaseUrl,
  accessToken,
  initialNodes,
  initialEdges: _initialEdges,
  initialStatus,
}: DraftItineraryEditorProps) {
  const [status, setStatus] = useState<ItineraryStatus>(initialStatus);
  const [lockStatus, setLockStatus] = useState<LockStatus>("unlocked");
  const [nodes, setNodes] = useState<NodeView[]>(
    initialNodes.map(toNodeView),
  );
  // In-flight flags — the only signal the DOM carries for "working on it".
  // Reverting a button press when the request rejects is the error
  // affordance (R014 — no toast, no spinner).
  const [edgePending, setEdgePending] = useState(false);
  const [releasePending, setReleasePending] = useState(false);
  const [approvePending, setApprovePending] = useState(false);

  const lockedBySelf = lockStatus === "locked-by-me";
  const isApproved = status === "approved";
  const inputsEditable = lockedBySelf && !isApproved;

  const clientForAction = useCallback(
    () => createApiClient({ baseUrl: apiBaseUrl, accessToken }),
    [apiBaseUrl, accessToken],
  );

  const onEdit = useCallback(() => {
    if (edgePending || lockedBySelf || isApproved) return;
    setEdgePending(true);
    const previousLock = lockStatus;
    // Optimistic flip: most advisors will acquire cleanly. Revert to the
    // previous state on failure (already_locked → locked-by-other;
    // anything else → unlocked).
    setLockStatus("locked-by-me");
    void acquireItineraryLock(clientForAction(), itineraryId)
      .then((result) => {
        if (!result.ok) {
          if (result.detail === "already_locked") {
            setLockStatus("locked-by-other");
          } else {
            setLockStatus(previousLock);
          }
        }
      })
      .finally(() => {
        setEdgePending(false);
      });
  }, [
    clientForAction,
    edgePending,
    isApproved,
    itineraryId,
    lockStatus,
    lockedBySelf,
  ]);

  const onRelease = useCallback(() => {
    if (releasePending || !lockedBySelf) return;
    setReleasePending(true);
    const previousLock = lockStatus;
    setLockStatus("unlocked");
    void releaseItineraryLock(clientForAction(), itineraryId)
      .then((result) => {
        if (!result.ok) {
          setLockStatus(previousLock);
        }
      })
      .finally(() => {
        setReleasePending(false);
      });
  }, [clientForAction, itineraryId, lockStatus, lockedBySelf, releasePending]);

  const onApprove = useCallback(() => {
    if (approvePending || isApproved) return;
    setApprovePending(true);
    const previousStatus = status;
    setStatus("approved");
    void approveItinerary(clientForAction(), itineraryId)
      .then((result) => {
        if (!result.ok) {
          setStatus(previousStatus);
        }
      })
      .finally(() => {
        setApprovePending(false);
      });
  }, [approvePending, clientForAction, isApproved, itineraryId, status]);

  const onNodeFieldBlur = useCallback(
    (nodeId: string, field: "title" | "source_id", nextValue: string) => {
      if (!inputsEditable) return;
      const target = nodes.find((n) => n.id === nodeId);
      if (!target) return;
      const currentValue = field === "title" ? target.title : target.source_id;
      if ((currentValue ?? "") === nextValue) return;
      const previousNodes = nodes;
      setNodes((prev) =>
        prev.map((n) =>
          n.id === nodeId
            ? { ...n, [field]: nextValue }
            : n,
        ),
      );
      const patch =
        field === "title" ? { title: nextValue } : { source_id: nextValue };
      void updateNode(clientForAction(), {
        itineraryId,
        nodeId,
        patch,
      }).then((result) => {
        if (!result.ok) {
          setNodes(previousNodes);
        }
      });
    },
    [clientForAction, inputsEditable, itineraryId, nodes],
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
                className="w-full border-0 bg-transparent font-serif text-xl leading-tight text-ink focus:outline-none focus:ring-0"
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
                className="flex-1 border-0 bg-transparent font-sans text-sm text-ink/80 focus:outline-none focus:ring-0"
              />
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}
