"use client";

// A node entry on the Journal spine: the shared glance card (CardShell +
// CardBody via NodeCard — cards are NOT reinvented here) beside its spine
// circle, with the MARGIN CHANNEL hanging off the card wrapper (phase 2):
// attached notes render as annotations beside the card, never as spine nodes.
// A free-standing `note` node renders as the small SpineNoteCard instead of a
// full glance card.
//
// Phase 3 adds:
//   · drag-to-move — the card is a dnd-kit drag source (DragOverlay carries
//     the clone; the source only dims, so the absolutely-positioned margin
//     never breaks). Listeners live on the CARD wrapper, not the article, so
//     margin-note editors stay plain text surfaces.
//   · problem state — red ring on the circle + a non-color ⚠ glyph OUTSIDE it
//     + a one-line caption under the card (the rail carries the explanation).
//   · grouped_with bracket — a thin bracket spanning consecutive grouped cards.
//   · alternatives as a FORK IN THE SPINE — the spine splits into 2–3 short
//     parallel rails (side by side on desktop, stacked with an "or —" seam on
//     mobile; same DOM, responsive), rejoining after. Choosing one is the
//     existing per-node approval; the unchosen collapse to a ghost chip
//     ("you also considered…", tap to restore). Vocabulary rule: alternatives
//     split the spine; version diffs (phase 4) never will.

import { useDraggable } from "@dnd-kit/core";
import { Fragment, useCallback, useState, type RefCallback } from "react";

import { inferCardKind, statusToKind } from "../../shared/cards/CardBody";
import type { NodeResponse } from "../../model/types";
import { NodeCard } from "../horizontal/NodeCard";
import {
  itineraryGraphStore,
  selectCanApprove,
} from "../../store/itineraryGraphStore";

import { journalDragId } from "./journalEditing";
import { MarginNotes, SpineNoteCard } from "./JournalNotes";
import type { JournalProblem } from "./problems";
import { SPINE_COL_PX, SpineCircle } from "./Spine";
import type { GroupedRole } from "./toJournal";

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
  dragEnabled = false,
  problem = null,
  bracket = null,
  marginInline = false,
}: {
  node: NodeResponse;
  tzOffsetHours: number;
  active: boolean;
  /** The `note` nodes annotating this one — rendered in the margin channel. */
  attachedNotes?: NodeResponse[];
  onActivate: (nodeId: string) => void;
  /** Callback ref registering the row with the scroll-active observer. */
  observeRef: RefCallback<HTMLElement>;
  /** The view says drags are on (an editable surface / the trunk's fork
   *  offer); a firmed card or a note still refuses its own drag. */
  dragEnabled?: boolean;
  /** Problem treatment (red ring + ⚠ + caption); null = healthy. */
  problem?: JournalProblem | null;
  /** Position inside a `grouped_with` run — draws the spanning bracket. */
  bracket?: GroupedRole | null;
  /** Render margin notes in-flow (used inside alt branches, where the
   *  absolute margin would overlay the neighbouring branch). */
  marginInline?: boolean;
}) {
  const kind = inferCardKind(node);
  const status = statusToKind(node.status);
  // A free-standing day note is a node ON the spine, but it reads as a margin
  // artifact, not an itinerary card — small, yellow, editable in place.
  const isNote = node.type === "note";
  // Approval locks the card (existing semantics) — a firmed card offers no
  // drag; notes keep their editors free of drag listeners.
  const canDrag = dragEnabled && !isNote && !node.lock_reason;

  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: journalDragId(node.id),
    disabled: !canDrag,
  });

  // The article is both the scroll-active observation target and the drag
  // measurement node. (Handles/listeners stay on the card wrapper below —
  // attaching them to the article would swallow the margin's editors.)
  const setArticleRef = useCallback<RefCallback<HTMLElement>>(
    (el) => {
      observeRef(el);
      setNodeRef(el);
    },
    [observeRef, setNodeRef],
  );

  return (
    <article
      ref={setArticleRef}
      data-testid="journal-node"
      data-node-id={node.id}
      data-active={active ? "true" : undefined}
      data-dragging={isDragging ? "true" : undefined}
      className={[
        "group/jnode grid grid-cols-[var(--spine-col)_minmax(0,1fr)] items-start gap-x-4",
        isDragging ? "opacity-40" : "",
      ].join(" ")}
      style={spineColStyle}
    >
      <div className="relative flex justify-center pt-3">
        <SpineCircle
          kind={kind}
          status={status}
          active={active}
          problem={problem !== null}
        />
        {/* The non-color problem glyph — OUTSIDE the circle, per the spec. */}
        {problem ? (
          <span
            aria-hidden
            data-testid="journal-problem-glyph"
            className="absolute -left-0.5 top-1 z-10 text-[11px] leading-none text-[#b3261e]"
          >
            ⚠
          </span>
        ) : null}
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
        {/* The grouped_with bracket — a thin span saying "these belong
            together" (never a choice; that's the alternatives split). */}
        {bracket ? (
          <span
            aria-hidden
            data-testid="journal-bracket"
            data-role={bracket}
            title="Planned together"
            className={[
              "pointer-events-none absolute -left-3.5 w-1.5 border-l border-ink/25",
              bracket === "start"
                ? "-bottom-2 top-4 rounded-tl-sm border-t"
                : bracket === "end"
                  ? "-top-2 bottom-4 rounded-bl-sm border-b"
                  : "-bottom-2 -top-2",
            ].join(" ")}
          />
        ) : null}
        {isNote ? (
          <SpineNoteCard node={node} />
        ) : (
          <div
            {...(canDrag ? { ...listeners, ...attributes } : {})}
            className={canDrag ? "touch-none" : undefined}
            data-testid={canDrag ? "journal-drag-handle" : undefined}
          >
            <NodeCard
              node={node}
              tzOffsetHours={tzOffsetHours}
              onClick={() => onActivate(node.id)}
            />
          </div>
        )}
        {/* The one-line problem caption — the rail carries the explanation
            and the "get help" action when the card is active. */}
        {problem ? (
          <p
            data-testid="journal-problem-caption"
            data-severity={problem.severity}
            className="mt-1 flex items-start gap-1 pl-1 font-sans text-[11px] leading-snug text-[#8b2a1d]"
          >
            <span aria-hidden>⚠</span>
            <span className="min-w-0 truncate">{problem.message}</span>
          </p>
        ) : null}
        {/* The margin channel — annotations beside the card on desktop,
            tucked under it below lg. Notes on a note stay a non-shape. */}
        {!isNote ? (
          <MarginNotes
            hostId={node.id}
            notes={attachedNotes}
            inline={marginInline}
          />
        ) : null}
      </div>
    </article>
  );
}

/**
 * Alternatives as a fork in the spine (phase 3): the spine splits into short
 * parallel rails — cards side by side on desktop, stacked with an "or —" seam
 * below md (same DOM, responsive) — and rejoins after the group. Choosing one
 * is the EXISTING approval action (`approveNode`, trunk-only via
 * `selectCanApprove`); once a member is chosen the unchosen collapse to a
 * ghost chip ("you also considered…", tap to restore the split view).
 */
export function JournalAltGroup({
  nodes,
  tzOffsetHours,
  focusedNodeId,
  attachedNotes,
  onActivate,
  observeRef,
  problems,
}: {
  nodes: NodeResponse[];
  tzOffsetHours: number;
  focusedNodeId: string | null;
  attachedNotes?: Map<string, NodeResponse[]> | undefined;
  onActivate: (nodeId: string) => void;
  observeRef: (nodeId: string) => RefCallback<HTMLElement>;
  problems?: Map<string, JournalProblem> | undefined;
}) {
  const canApprove = itineraryGraphStore.useStore(selectCanApprove);
  const approvingNodeId = itineraryGraphStore.useStore((s) => s.approvingNodeId);
  const storeApi = itineraryGraphStore.useStoreApi();
  // "Tap to restore": purely a view state — the unchosen stay real pending
  // nodes in the graph; the chip only collapses them out of the story.
  const [restored, setRestored] = useState(false);

  const chosen =
    nodes.find(
      (n) =>
        n.status === "approved" ||
        n.status === "booked" ||
        n.status === "confirmed",
    ) ?? null;
  const others = chosen ? nodes.filter((n) => n.id !== chosen.id) : [];

  if (chosen && !restored) {
    return (
      <div
        data-testid="journal-alt-group"
        data-collapsed="true"
        className="flex flex-col gap-1"
      >
        <JournalNode
          node={chosen}
          tzOffsetHours={tzOffsetHours}
          active={focusedNodeId === chosen.id}
          attachedNotes={attachedNotes?.get(chosen.id) ?? []}
          onActivate={onActivate}
          observeRef={observeRef(chosen.id)}
          problem={problems?.get(chosen.id) ?? null}
        />
        <div
          className="grid grid-cols-[var(--spine-col)_minmax(0,1fr)] gap-x-4"
          style={spineColStyle}
        >
          <span />
          <button
            type="button"
            data-testid="journal-alt-ghost"
            onClick={() => setRestored(true)}
            className="self-start rounded-full border border-dashed border-ink/25 px-3 py-1 text-left font-serif text-[11px] italic text-ink/45 transition-colors hover:border-ink/45 hover:text-ink"
          >
            you also considered{" "}
            {others.map((o) => o.title || o.type).join(" · ")} …
          </button>
        </div>
      </div>
    );
  }

  return (
    <div data-testid="journal-alt-group" className="relative flex flex-col">
      {/* The split — the spine forks here. */}
      <div
        className="grid grid-cols-[var(--spine-col)_minmax(0,1fr)] items-center gap-x-4 pb-1"
        style={spineColStyle}
      >
        <div className="flex justify-center">
          <span
            aria-hidden
            className="z-10 flex h-4 w-4 items-center justify-center rounded-full border border-ink/25 bg-paper text-[9px] leading-none text-ink/50"
          >
            ⑂
          </span>
        </div>
        <p className="font-sans text-[9px] uppercase tracking-[0.22em] text-ink/40">
          choose one
        </p>
      </div>

      {/* The parallel rails — one DOM, responsive: columns ≥md, stacked with
          an "or —" seam below. Each branch carries its own short spine. */}
      <div className="flex flex-col md:flex-row md:items-start md:gap-3">
        {nodes.map((node, i) => (
          <Fragment key={node.id}>
            {i > 0 ? (
              <div
                className="grid grid-cols-[var(--spine-col)_minmax(0,1fr)] items-center gap-x-4 py-1 md:hidden"
                style={spineColStyle}
              >
                <span />
                <span className="font-serif text-[11px] italic tracking-wide text-ink/40">
                  or —
                </span>
              </div>
            ) : null}
            <div
              data-testid="journal-alt-branch"
              className="relative min-w-0 md:flex-1"
            >
              {/* The branch's own rail (desktop; below md the day's main
                  spine already runs behind the stacked members). */}
              <span
                aria-hidden
                className="absolute bottom-0 top-0 hidden w-px bg-ink/15 md:block"
                style={{ left: SPINE_COL_PX / 2 }}
              />
              <JournalNode
                node={node}
                tzOffsetHours={tzOffsetHours}
                active={focusedNodeId === node.id}
                attachedNotes={attachedNotes?.get(node.id) ?? []}
                onActivate={onActivate}
                observeRef={observeRef(node.id)}
                problem={problems?.get(node.id) ?? null}
                marginInline
              />
              {/* Choosing = the existing approval action. Only before any
                  member is chosen (approving a second alternative would put
                  two on the plan). */}
              {!chosen && canApprove && node.status === "pending" ? (
                <div
                  className="grid grid-cols-[var(--spine-col)_minmax(0,1fr)] gap-x-4 pb-1"
                  style={spineColStyle}
                >
                  <span />
                  <button
                    type="button"
                    data-testid="journal-alt-choose"
                    data-node-id={node.id}
                    disabled={approvingNodeId !== null}
                    onClick={() => storeApi.getState().approveNode(node.id)}
                    className="self-start rounded-full border border-ink/25 px-3.5 py-1 font-sans text-[10px] uppercase tracking-[0.16em] text-ink/70 transition-colors hover:bg-ink hover:text-paper disabled:cursor-default disabled:opacity-40"
                  >
                    Choose this
                  </button>
                </div>
              ) : null}
            </div>
          </Fragment>
        ))}
      </div>

      {/* The rejoin — the rails fold back into one spine. */}
      <div
        className="grid grid-cols-[var(--spine-col)_minmax(0,1fr)] items-center gap-x-4 pt-1"
        style={spineColStyle}
      >
        <div className="flex justify-center">
          <span
            aria-hidden
            className="z-10 block h-1.5 w-1.5 rounded-full bg-ink/25"
          />
        </div>
        {chosen && restored ? (
          <button
            type="button"
            data-testid="journal-alt-collapse"
            onClick={() => setRestored(false)}
            className="self-start font-sans text-[9px] uppercase tracking-[0.2em] text-ink/40 transition-colors hover:text-ink"
          >
            hide the alternatives
          </button>
        ) : (
          <span />
        )}
      </div>
    </div>
  );
}
