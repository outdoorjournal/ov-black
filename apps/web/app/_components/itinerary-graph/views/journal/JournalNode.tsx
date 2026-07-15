"use client";

// A node entry on the Journal spine: the shared glance card (CardShell +
// CardBody via NodeCard — cards are NOT reinvented here) beside its spine
// circle. Attached notes annotate the card from the right rail's notes thread
// (RightRail → NotesPanel), not beside the card. A free-standing `note` node
// renders as the small SpineNoteCard instead of a full glance card.
//
// Phase 3 adds:
//   · drag-to-move — the card is a dnd-kit drag source (DragOverlay carries
//     the clone; the source only dims). Listeners live on the CARD wrapper,
//     not the article, so in-card text surfaces stay plain.
//   · problem state — red ring on the circle + a non-color ⚠ glyph OUTSIDE it
//     + a one-line caption under the card (the rail carries the explanation).
//   · grouped_with bracket — a thin bracket spanning consecutive grouped cards.
//   · alternatives as a FORK IN THE SPINE — the spine splits into 2–3 short
//     parallel rails (side by side on desktop, stacked with an "or —" seam on
//     mobile; same DOM, responsive), rejoining after. Choosing one is the
//     existing per-node approval; the unchosen collapse to a ghost chip
//     ("you also considered…", tap to restore). Vocabulary rule: alternatives
//     split the spine; version diffs (phase 4) never will.
//
// Phase 4 (diff mode) annotates the SAME rows — stitches/ghosts/dots only,
// never a spine split (that vocabulary belongs to alternatives):
//   · added   — the card renders vivid with a "new in this version" stitch on
//     its spine segment (a dashed brand thread over the line);
//   · changed — a change dot on the circle; the rail shows the field-level
//     before/after;
//   · moved   — a chip on the card; the rail shows old vs new time (no
//     ghost-at-old-position arrows — too much ink);
//   · removed — JournalGhostNode below: a trunk-only row at its trunk time,
//     dashed circle, muted card, "not in your version".

import { useDraggable } from "@dnd-kit/core";
import { Fragment, useCallback, useState, type RefCallback } from "react";

import { useConciergeControl } from "@/app/itinerary/[id]/_shell/ConciergeControl";

import { inferCardKind, statusToKind } from "../../shared/cards/CardBody";
import { TYPE_TOKENS } from "../../shared/cards/tokens";
import { subgraphDaySpan } from "../../shared/subgraph";
import { getVerticalMeta, type NodeResponse } from "../../model/types";
import { hourOfDay, offsetHoursOr } from "../../model/time";
import { NodeCard } from "../horizontal/NodeCard";
import {
  isSchedulePinned,
  itineraryGraphStore,
  selectCanApprove,
} from "../../store/itineraryGraphStore";

import { journalDragId } from "./journalEditing";
import { SpineNoteCard } from "./JournalNotes";
import type { JournalProblem } from "./problems";
import { DurationBar, JOURNEY_INDENT_PX, SPINE_COL_PX, SpineCircle } from "./Spine";
import { durationMinOf, type GroupedRole, type JourneyBeat } from "./toJournal";
import type { JournalNodeDiff } from "./toJournalDiff";

const spineColStyle = {
  "--spine-col": `${SPINE_COL_PX}px`,
} as React.CSSProperties;

// Windowed rendering (phase 5): a long journal skips layout/paint for
// offscreen rows via `content-visibility: auto` + an intrinsic-size estimate
// (scrollbar stays honest; IntersectionObserver keeps seeing the box, so the
// scroll-active system is unaffected). Every row's content lives inside its
// box now (attached notes moved to the rail), so nothing opts out.
const WINDOWED_STYLE = {
  contentVisibility: "auto",
  containIntrinsicSize: "auto 140px",
} as React.CSSProperties;

export function JournalNode({
  node,
  tzOffsetHours,
  active,
  durationMinutes = 60,
  subgraphChildren = [],
  onActivate,
  observeRef,
  dragEnabled = false,
  problem = null,
  bracket = null,
  diff = null,
  journey = null,
}: {
  node: NodeResponse;
  tzOffsetHours: number;
  active: boolean;
  /** Event length (minutes) — sizes the spine duration bar. */
  durationMinutes?: number;
  /** The node's embedded subgraph (a multi-day item's day-by-day journey) —
   *  its children render as derived journey beats on the days they cover;
   *  the parent card wears the span caption. */
  subgraphChildren?: NodeResponse[];
  /** This card IS a derived journey beat — day k of N of its parent's
   *  journey. Wears the membership chip; never draggable (the parent owns
   *  the schedule). */
  journey?: JourneyBeat | null;
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
  /** Diff-mode annotation (added / changed / moved) — stitches and dots only;
   *  removed rows render as JournalGhostNode instead. Null = versions agree. */
  diff?: JournalNodeDiff | null;
}) {
  const kind = inferCardKind(node);
  const status = statusToKind(node.status);
  const journalPxPerMinute = itineraryGraphStore.useStore(
    (s) => s.journalPxPerMinute,
  );
  // A free-standing day note is a node ON the spine, but it reads as a margin
  // artifact, not an itinerary card — small, yellow, editable in place.
  const isNote = node.type === "note";
  // The card's local start hour (its OWN offset — a trip spans timezones), so
  // the duration bar can carry hour ticks that continue the day's ruler THROUGH
  // the card instead of only in the gaps. Null when the node carries no time.
  const startIso = getVerticalMeta(node).start_time;
  const startHour =
    !isNote && startIso
      ? hourOfDay(startIso, offsetHoursOr(startIso, tzOffsetHours))
      : null;
  // A flight's time is pinned to its booking (offer depart_at), so it's never
  // re-timable by anyone — the timeline slot is derived, not placed.
  const pinned = isSchedulePinned(node);
  // Approval locks the card (existing semantics) — a firmed card offers no
  // drag; notes keep their editors free of drag listeners; a journey beat's
  // placement is derived from its parent, so it offers no drag either; a pinned
  // flight refuses its own drag (its schedule is the airline's, not a placement).
  const canDrag =
    dragEnabled &&
    !isNote &&
    !pinned &&
    !node.lock_reason &&
    !node.parent_subgraph_id;
  // The nudge replaces the (absent) drag handle for a pinned card on an editable
  // surface: tell the traveler why it can't move, and where to go instead.
  const showPinnedNudge = dragEnabled && pinned && !isNote;
  const [pinnedHintOpen, setPinnedHintOpen] = useState(false);
  const { openConcierge } = useConciergeControl();

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
      data-diff={diff?.kind}
      data-journey-beat={journey ? "true" : undefined}
      className={[
        "group/jnode grid grid-cols-[var(--spine-col)_minmax(0,1fr)] items-start gap-x-4",
        isDragging ? "opacity-40" : "",
      ].join(" ")}
      style={{
        ...spineColStyle,
        // A journey beat's whole row shifts right onto the CHILD journey line —
        // a sub-rail sitting just right of the parent experience's own colored
        // line, so the package reads as a parent spine with its days branching
        // off to the side.
        ...(journey ? { marginLeft: JOURNEY_INDENT_PX } : {}),
        ...WINDOWED_STYLE,
      }}
    >
      <div className="relative flex flex-col items-center pt-3">
        {/* "New in this version" — a dashed brand STITCH over the spine
            segment (never a split; version divergence keeps one spine). */}
        {diff?.kind === "added" ? (
          <span
            aria-hidden
            data-testid="journal-diff-stitch"
            className="absolute -bottom-1 -top-1 w-0 border-l-2 border-dashed border-brand/70"
            style={{ left: SPINE_COL_PX / 2 }}
          />
        ) : null}
        <SpineCircle
          kind={kind}
          status={status}
          active={active}
          problem={problem !== null}
        />
        {/* The duration bar — the card's color extending down the timeline,
            length = how long it runs. Notes carry no duration. A subgraph
            parent (a multi-day package) shows NO bar: its span is carried by
            the accent-colored journey thread that runs the whole way down
            through its beats, so a short capped stub here would read as the
            trip's line "stopping" at the first beat. */}
        {!isNote && subgraphChildren.length === 0 ? (
          <DurationBar
            kind={kind}
            minutes={durationMinutes}
            pxPerMinute={journalPxPerMinute}
            nodeId={node.id}
            discarded={status === "discarded"}
            startHour={startHour}
          />
        ) : null}
        {/* The change DOT on the circle — a quiet "this differs" marker; the
            rail carries the field-level before/after. */}
        {diff?.kind === "changed" ? (
          <span
            aria-hidden
            data-testid="journal-diff-dot"
            title="Changed in this version"
            className="absolute top-2 z-20 h-2.5 w-2.5 rounded-full bg-brand ring-2 ring-paper"
            style={{ left: SPINE_COL_PX / 2 + 8 }}
          />
        ) : null}
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
        {/* Pinned-flight nudge: a flight leaves when the airline says, so it has
            no drag handle — this caption says why, and points to the concierge
            (the only way to a different time is a different flight). */}
        {showPinnedNudge ? (
          <div className="mt-1 pl-1" data-testid="journal-flight-pinned">
            <button
              type="button"
              onClick={() => setPinnedHintOpen((v) => !v)}
              aria-expanded={pinnedHintOpen}
              title="A flight's time is set by the airline"
              className="font-serif text-[11px] italic text-ink/45 hover:text-ink/70"
            >
              Pinned to your flight booking
            </button>
            {pinnedHintOpen ? (
              <p className="mt-1 max-w-[380px] text-[11px] not-italic leading-relaxed text-ink/55">
                A flight&rsquo;s departure time is set by the airline, so it
                stays put on your timeline.{" "}
                <button
                  type="button"
                  onClick={openConcierge}
                  className="text-brand underline underline-offset-2 hover:text-brand/80"
                >
                  Ask your concierge
                </button>{" "}
                to find a different flight.
              </p>
            ) : null}
          </div>
        ) : null}
        {/* A multi-day card's span caption — the embedded journey is laid out
            on the days it covers (the beats below carry the chips). */}
        {!isNote && subgraphChildren.length > 0 ? (
          <p
            data-testid="journal-journey-span"
            className="mt-1 pl-1 font-serif text-[11px] italic text-ink/45"
          >
            a {subgraphDaySpan(subgraphChildren)}-day journey — the days ahead
            carry it
          </p>
        ) : null}
        {/* The journey-beat chip — this card is day k of N of its parent's
            packaged journey. */}
        {journey ? (
          <p className="mt-1 pl-1">
            <span
              data-testid="journal-journey-chip"
              data-parent-id={journey.parentId}
              className="inline-flex max-w-full items-center gap-1.5 rounded-full border border-ink/20 px-2.5 py-0.5 font-sans text-[9px] uppercase tracking-[0.16em] text-ink/50"
            >
              <span aria-hidden>↳</span>
              <span className="min-w-0 truncate">
                day {journey.index} of {journey.total} · {journey.parentTitle}
              </span>
            </span>
          </p>
        ) : null}
        {/* Diff captions — manuscript margin marks, not paint: a brand line
            for "new", a small chip for "moved" (the rail shows old vs new). */}
        {diff?.kind === "added" ? (
          <p
            data-testid="journal-diff-added-caption"
            className="mt-1 pl-1 font-sans text-[9px] uppercase tracking-[0.2em] text-brand"
          >
            new in this version
          </p>
        ) : null}
        {diff?.kind === "moved" ? (
          <p className="mt-1 pl-1">
            <span
              data-testid="journal-diff-moved"
              title="Moved in this version"
              className="inline-flex items-center gap-1 rounded-full border border-brand/40 px-2 py-0.5 font-sans text-[9px] uppercase tracking-[0.18em] text-brand"
            >
              <span aria-hidden>⇅</span> moved
            </span>
          </p>
        ) : null}
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
  subgraphChildren,
  onActivate,
  observeRef,
  problems,
  diffs,
}: {
  nodes: NodeResponse[];
  tzOffsetHours: number;
  focusedNodeId: string | null;
  /** Embedded subgraphs by parent id — a member can be a multi-day package. */
  subgraphChildren?: Map<string, NodeResponse[]> | undefined;
  onActivate: (nodeId: string) => void;
  observeRef: (nodeId: string) => RefCallback<HTMLElement>;
  problems?: Map<string, JournalProblem> | undefined;
  /** Diff-mode annotations (phase 4) — a member can be added/changed/moved. */
  diffs?: Map<string, JournalNodeDiff> | undefined;
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
          durationMinutes={durationMinOf(chosen)}
          subgraphChildren={subgraphChildren?.get(chosen.id) ?? []}
          onActivate={onActivate}
          observeRef={observeRef(chosen.id)}
          problem={problems?.get(chosen.id) ?? null}
          diff={diffs?.get(chosen.id) ?? null}
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
                durationMinutes={durationMinOf(node)}
                subgraphChildren={subgraphChildren?.get(node.id) ?? []}
                onActivate={onActivate}
                observeRef={observeRef(node.id)}
                problem={problems?.get(node.id) ?? null}
                diff={diffs?.get(node.id) ?? null}
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

/**
 * A trunk-only row in diff mode (phase 4): the node exists on the official
 * trip but not in this version. A GHOST — dashed circle, muted card, "not in
 * your version" — sitting at its TRUNK time in the unified sequence. It is
 * synthesized from the diff's `before` snapshot (never in the store), so it is
 * read/activate-only: activating it puts the removal (and, for an advisor,
 * the accept/keep decision) in the rail.
 */
export function JournalGhostNode({
  node,
  active,
  caption,
  onActivate,
  observeRef,
}: {
  node: NodeResponse;
  active: boolean;
  /** Role-aware: "not in your version" (traveler) / "not in this version"
   *  (advisor reviewing someone else's fork). */
  caption: string;
  onActivate: (nodeId: string) => void;
  observeRef: RefCallback<HTMLElement>;
}) {
  const kind = inferCardKind(node);
  const token = TYPE_TOKENS[kind];
  return (
    <article
      ref={observeRef}
      data-testid="journal-ghost"
      data-node-id={node.id}
      data-active={active ? "true" : undefined}
      data-diff="removed"
      className="grid grid-cols-[var(--spine-col)_minmax(0,1fr)] items-start gap-x-4"
      style={{ ...spineColStyle, ...WINDOWED_STYLE }}
    >
      <div className="relative flex justify-center pt-3">
        {/* The dashed circle — the type still reads, the presence doesn't. */}
        <span
          role="img"
          aria-label={`${token.label} — ${caption}`}
          data-testid="journal-ghost-circle"
          data-kind={kind}
          className={[
            "relative z-10 flex h-7 w-7 items-center justify-center rounded-full border-2 border-dashed bg-paper text-ink/40 transition-transform duration-200",
            active ? "scale-110 border-ink/45" : "border-ink/30",
          ].join(" ")}
        >
          <token.Icon size={13} strokeWidth={1.8} aria-hidden />
        </span>
      </div>
      <div className="relative max-w-[420px] pb-1 pt-3">
        <span
          aria-hidden
          className={[
            "pointer-events-none absolute -left-2 bottom-3 top-3 w-[2.5px] rounded-full bg-brand transition-opacity duration-200",
            active ? "opacity-80" : "opacity-0",
          ].join(" ")}
        />
        <button
          type="button"
          onClick={() => onActivate(node.id)}
          className="w-full rounded-lg border border-dashed border-ink/25 bg-paper/60 px-3.5 py-2.5 text-left opacity-75 transition-opacity hover:opacity-100"
        >
          <p className="font-serif text-[14px] leading-snug text-ink/55 line-through decoration-ink/25">
            {node.title}
          </p>
          <p className="mt-0.5 font-sans text-[9px] uppercase tracking-[0.2em] text-ink/40">
            {caption}
          </p>
        </button>
      </div>
    </article>
  );
}
