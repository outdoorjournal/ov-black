"use client";

// A node entry on the Journal spine: the shared glance card (CardShell +
// CardBody via NodeCard — cards are NOT reinvented here) beside its spine
// circle, with the MARGIN CHANNEL hanging off the card wrapper (phase 2):
// attached notes render as annotations beside the card, never as spine nodes.
// A free-standing `note` node renders as the small SpineNoteCard instead of a
// full glance card. Also renders the phase-1 alternative group: members
// stacked with an "or —" connector (fork-in-the-spine rendering is later).

import type { RefCallback } from "react";

import { inferCardKind, statusToKind } from "../../shared/cards/CardBody";
import type { NodeResponse } from "../../model/types";
import { NodeCard } from "../horizontal/NodeCard";

import { MarginNotes, SpineNoteCard } from "./JournalNotes";
import { SPINE_COL_PX, SpineCircle } from "./Spine";

const spineColStyle = {
  "--spine-col": `${SPINE_COL_PX}px`,
} as React.CSSProperties;

export function JournalNode({
  node,
  tzOffsetHours,
  active,
  attachedNotes = [],
  onActivate,
  observeRef,
}: {
  node: NodeResponse;
  tzOffsetHours: number;
  active: boolean;
  /** The `note` nodes annotating this one — rendered in the margin channel. */
  attachedNotes?: NodeResponse[];
  onActivate: (nodeId: string) => void;
  /** Callback ref registering the row with the scroll-active observer. */
  observeRef: RefCallback<HTMLElement>;
}) {
  const kind = inferCardKind(node);
  const status = statusToKind(node.status);
  // A free-standing day note is a node ON the spine, but it reads as a margin
  // artifact, not an itinerary card — small, yellow, editable in place.
  const isNote = node.type === "note";
  return (
    <article
      ref={observeRef}
      data-testid="journal-node"
      data-node-id={node.id}
      data-active={active ? "true" : undefined}
      className="group/jnode grid grid-cols-[var(--spine-col)_minmax(0,1fr)] items-start gap-x-4"
      style={spineColStyle}
    >
      <div className="flex justify-center pt-3">
        <SpineCircle kind={kind} status={status} active={active} />
      </div>
      <div className="relative max-w-[420px] pb-1">
        {/* Active emphasis: a restrained brand rule beside the card — the
            signature orange as punctuation, not paint. */}
        <span
          aria-hidden
          className={[
            "pointer-events-none absolute -left-2 bottom-3 top-3 w-[2.5px] rounded-full bg-brand transition-opacity duration-200",
            active ? "opacity-80" : "opacity-0",
          ].join(" ")}
        />
        {isNote ? (
          <SpineNoteCard node={node} />
        ) : (
          <NodeCard
            node={node}
            tzOffsetHours={tzOffsetHours}
            onClick={() => onActivate(node.id)}
          />
        )}
        {/* The margin channel — annotations beside the card on desktop,
            tucked under it below lg. Notes on a note stay a non-shape. */}
        {!isNote ? <MarginNotes hostId={node.id} notes={attachedNotes} /> : null}
      </div>
    </article>
  );
}

/**
 * Phase-1 alternatives: the group's members stacked with a quiet "or" seam.
 * The grouping comes from `toJournal` (alt_group metadata + alternative_to
 * edges); choosing/collapsing is phase 3.
 */
export function JournalAltGroup({
  nodes,
  tzOffsetHours,
  focusedNodeId,
  attachedNotes,
  onActivate,
  observeRef,
}: {
  nodes: NodeResponse[];
  tzOffsetHours: number;
  focusedNodeId: string | null;
  attachedNotes?: Map<string, NodeResponse[]> | undefined;
  onActivate: (nodeId: string) => void;
  observeRef: (nodeId: string) => RefCallback<HTMLElement>;
}) {
  return (
    <div data-testid="journal-alt-group" className="flex flex-col">
      {nodes.map((node, i) => (
        <div key={node.id} className="flex flex-col">
          {i > 0 ? (
            <div
              className="grid grid-cols-[var(--spine-col)_minmax(0,1fr)] items-center gap-x-4 py-1"
              style={spineColStyle}
            >
              <span />
              <span className="font-serif text-[11px] italic tracking-wide text-ink/40">
                or —
              </span>
            </div>
          ) : null}
          <JournalNode
            node={node}
            tzOffsetHours={tzOffsetHours}
            active={focusedNodeId === node.id}
            attachedNotes={attachedNotes?.get(node.id) ?? []}
            onActivate={onActivate}
            observeRef={observeRef(node.id)}
          />
        </div>
      ))}
    </div>
  );
}
