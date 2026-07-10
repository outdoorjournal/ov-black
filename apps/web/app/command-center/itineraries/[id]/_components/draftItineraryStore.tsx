"use client";

// Per-itinerary zustand store for the advisor draft-itinerary editor.
// Replaces the four parallel useState calls (status, lockStatus, nodes, plus
// the in-flight pending flags) with a single store scoped to one itinerary
// id. The Provider is mounted by DraftItineraryEditor and seeded from the
// server-provided initial nodes/status.

import {
  createStoreContext,
} from "@/lib/store/createStoreContext";
import type {
  DisplayStatus,
  NodeResponse,
} from "@ov-black/api-client";

export type LockStatus = "unlocked" | "locked-by-me" | "locked-by-other";

export type NodeView = {
  id: string;
  title: string;
  source: string | null;
  source_id: string | null;
};

export function toNodeView(node: NodeResponse): NodeView {
  return {
    id: node.id,
    title: node.title,
    source: node.source ?? null,
    source_id: node.source_id ?? null,
  };
}

export type DraftItineraryState = {
  status: DisplayStatus;
  lockStatus: LockStatus;
  nodes: NodeView[];
  edgePending: boolean;
  releasePending: boolean;
  approvePending: boolean;
  setStatus: (status: DisplayStatus) => void;
  setLockStatus: (lock: LockStatus) => void;
  setNodes: (nodes: NodeView[]) => void;
  patchNode: (
    id: string,
    field: "title" | "source_id",
    value: string,
  ) => void;
  setEdgePending: (pending: boolean) => void;
  setReleasePending: (pending: boolean) => void;
  setApprovePending: (pending: boolean) => void;
};

export type DraftItineraryStoreInit = {
  initialStatus: DisplayStatus;
  initialNodes: NodeResponse[];
};

export const draftItineraryStore = createStoreContext<
  DraftItineraryState,
  DraftItineraryStoreInit
>(
  ({ initialStatus, initialNodes }) =>
    (set) => ({
      status: initialStatus,
      lockStatus: "unlocked",
      nodes: initialNodes.map(toNodeView),
      edgePending: false,
      releasePending: false,
      approvePending: false,
      setStatus: (status) => set({ status }),
      setLockStatus: (lockStatus) => set({ lockStatus }),
      setNodes: (nodes) => set({ nodes }),
      patchNode: (id, field, value) =>
        set((s) => ({
          nodes: s.nodes.map((n) =>
            n.id === id ? { ...n, [field]: value } : n,
          ),
        })),
      setEdgePending: (edgePending) => set({ edgePending }),
      setReleasePending: (releasePending) => set({ releasePending }),
      setApprovePending: (approvePending) => set({ approvePending }),
    }),
  "DraftItinerary",
);
