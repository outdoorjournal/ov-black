"use client";

// The Collection (wish list) surface: the pile of maybes a traveler and the
// concierge accumulate before anything is scheduled. It reads the same graph
// store every other view does — the Collection is just the store's unscheduled,
// non-discarded nodes (see `selectCollectionItems`) — and slices them along a
// switchable axis (type / cost / proximity), animating the re-flow with
// framer-motion `layout` when the axis changes.
//
// Cards are draggable within the parent view's DndContext: dropping one on a
// day column schedules it (the shared `handleDragEnd` calls `moveNode`), so the
// item leaves the Collection and lands on the timeline. Rendered `board` when
// the Collection is the dominant surface (no timeline yet) and `rail` when it
// sits beside a populated timeline.

import { useDraggable, useDroppable } from "@dnd-kit/core";
import { AnimatePresence, motion } from "framer-motion";
import { X } from "lucide-react";
import { useMemo, useState } from "react";

import type { NodeResponse } from "../model/horizontalTypes";
import { CardShell } from "../shared/cards/CardShell";
import {
  CardBody,
  inferCardKind,
  statusToKind,
} from "../shared/cards/CardBody";
import { useComposerControl } from "@/app/itinerary/[id]/_shell/ComposerControl";

import {
  collectionDragId,
  collectionItemsOf,
  isNodeScheduled,
  itineraryGraphStore,
  selectCanLeaveNote,
  selectCanSchedule,
  selectEditable,
} from "../store/itineraryGraphStore";

import { GROUP_AXES, groupCollection, type GroupAxis } from "./grouping";

export function CollectionRail({
  variant = "rail",
  onOpenNode,
}: {
  // `board` = dominant surface (no timeline yet); `rail` = beside a populated
  // timeline (also a drop target for un-scheduling); `overlay` = a summonable
  // drawer that floats over another surface for pick-then-place (M006/PS5).
  variant?: "board" | "rail" | "overlay";
  /** Open a card's full-bleed detail (M006/PS4). Absent → cards are browse-only. */
  onOpenNode?: (nodeId: string) => void;
}) {
  const nodes = itineraryGraphStore.useStore((s) => s.nodes);
  const pending = itineraryGraphStore.useStore((s) => s.pendingProposals);
  const canAdd = itineraryGraphStore.useStore(selectCanLeaveNote);
  // The advisor sees a *client's* wish list; the traveler sees their own — the
  // whole surface speaks in the viewer's voice (heading, empty state).
  const canEdit = itineraryGraphStore.useStore((s) => s.canEdit);
  const [axis, setAxis] = useState<GroupAxis>("type");
  // Whether already-placed cards are revealed. Off by default: the wish list is
  // for the unscheduled "maybes", and showing everything you've already put on
  // the timeline just clutters it. A deliberate toggle brings them back.
  const [showScheduled, setShowScheduled] = useState(false);

  const items = useMemo(
    // Notes are feedback for staff, not wish-list cards — they have their own
    // home in the Journal, so they're kept OUT of the Collection (bugs.md:
    // "notes not needed in collection"). Articles (reading list) stay in.
    () => collectionItemsOf(nodes, pending).filter((n) => n.type !== "note"),
    [nodes, pending],
  );
  // Split the pile: unscheduled maybes (the wish list proper) vs cards that
  // already carry a real time (on the timeline). `scheduledIds` lets a card
  // know it's a placed one so it can wear the quiet "On timeline" marker.
  const { unscheduled, scheduledIds } = useMemo(() => {
    const unscheduled: NodeResponse[] = [];
    const scheduledIds = new Set<string>();
    for (const node of items) {
      if (isNodeScheduled(node)) scheduledIds.add(node.id);
      else unscheduled.push(node);
    }
    return { unscheduled, scheduledIds };
  }, [items]);
  const scheduledCount = scheduledIds.size;

  const visibleItems = useMemo(
    () => (showScheduled ? items : unscheduled),
    [showScheduled, items, unscheduled],
  );
  const lanes = useMemo(
    () => groupCollection(visibleItems, axis),
    [visibleItems, axis],
  );

  // Rail mode is a drop target: dragging a scheduled timeline card onto it
  // un-schedules it (the parent view's handleDragEnd calls `unscheduleNode`),
  // returning it to the wish list. The board mode has no timeline to receive.
  const { setNodeRef: setDropRef, isOver } = useDroppable({
    id: "collection-drop",
    disabled: variant !== "rail",
  });

  return (
    <section
      ref={setDropRef}
      data-testid="collection-rail"
      data-variant={variant}
      data-item-count={items.length}
      data-drop-active={isOver ? "true" : "false"}
      className={
        "flex min-h-0 w-full flex-col bg-paper/85 transition-colors " +
        (variant === "rail" ? "border-l border-ink/10 " : "") +
        (isOver ? "bg-[rgba(245,112,31,0.06)]" : "")
      }
    >
      <header className="flex shrink-0 flex-wrap items-center justify-between gap-2 border-b border-ink/10 px-4 py-3">
        <div>
          <div className="text-[10px] uppercase tracking-[0.22em] text-ink/55">
            Collection
          </div>
          <div className="font-serif text-lg text-ink">
            {canEdit ? "Client's wish list" : "Your wish list"}
          </div>
        </div>
        <div className="flex items-center gap-2">
          {/* Reveal the already-placed cards. Hidden by default so the wish list
              stays the pile of unscheduled maybes; a click brings the timeline's
              items back into view (dimmed, marked "On timeline"). */}
          {scheduledCount > 0 ? (
            <button
              type="button"
              onClick={() => setShowScheduled((v) => !v)}
              aria-pressed={showScheduled}
              data-testid="collection-show-scheduled"
              className={`h-6 rounded-md border px-2 font-sans text-[10px] uppercase tracking-[0.16em] transition-colors ${
                showScheduled
                  ? "border-ink/25 bg-ink/10 text-ink"
                  : "border-ink/15 text-ink/50 hover:bg-ink/5"
              }`}
            >
              {showScheduled ? "Hide scheduled" : `Scheduled · ${scheduledCount}`}
            </button>
          ) : null}
          <GroupByToggle axis={axis} onChange={setAxis} />
        </div>
      </header>

      {canAdd ? <AddAffordances /> : null}

      <div
        className={
          "min-h-0 flex-1 overflow-y-auto px-4 py-4 " +
          (variant === "board"
            ? "grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 content-start"
            : "flex flex-col gap-6")
        }
      >
        {items.length === 0 ? (
          <p
            data-testid="collection-empty"
            className="font-serif text-sm italic text-ink/50"
          >
            {canEdit
              ? "Nothing here yet. As you and the concierge gather places to eat, stay, and things to do, they’ll collect here — ready to place on the timeline when the shape is right."
              : "Nothing saved yet. As you and the concierge find places to eat, stay, and things to do, they’ll gather here — ready to place on the timeline when the shape is right."}
          </p>
        ) : visibleItems.length === 0 ? (
          <p
            data-testid="collection-all-scheduled"
            className="font-serif text-sm italic text-ink/50"
          >
            Everything here is on the timeline. Use{" "}
            <span className="not-italic font-sans text-[11px] uppercase tracking-[0.16em]">
              Scheduled
            </span>{" "}
            above to see the placed cards.
          </p>
        ) : (
          <AnimatePresence initial={false}>
            {lanes.map((lane) => (
              <motion.div
                key={lane.key}
                layout
                data-testid="collection-lane"
                data-lane={lane.key}
                className="min-w-0"
              >
                <h3 className="mb-2 flex items-baseline gap-2 font-sans text-[11px] uppercase tracking-[0.18em] text-ink/60">
                  {lane.label}
                  <span className="text-ink/35">{lane.items.length}</span>
                </h3>
                <div className="flex flex-col gap-3">
                  <AnimatePresence initial={false}>
                    {lane.items.map((node) => (
                      <CollectionCard
                        key={node.id}
                        node={node}
                        scheduled={scheduledIds.has(node.id)}
                        {...(onOpenNode ? { onOpen: onOpenNode } : {})}
                      />
                    ))}
                  </AnimatePresence>
                </div>
              </motion.div>
            ))}
          </AnimatePresence>
        )}
      </div>
    </section>
  );
}

function GroupByToggle({
  axis,
  onChange,
}: {
  axis: GroupAxis;
  onChange: (a: GroupAxis) => void;
}) {
  return (
    <div
      data-testid="collection-groupby"
      className="flex items-center gap-1 rounded-md border border-ink/15 bg-paper p-0.5"
    >
      {GROUP_AXES.map((a) => (
        <button
          key={a.id}
          type="button"
          onClick={() => onChange(a.id)}
          aria-pressed={axis === a.id}
          data-testid={`collection-groupby-${a.id}`}
          className={`h-6 rounded px-2 font-sans text-[10px] uppercase tracking-[0.16em] transition-colors ${
            axis === a.id
              ? "bg-ink/10 text-ink"
              : "text-ink/50 hover:bg-ink/5"
          }`}
        >
          {a.label}
        </button>
      ))}
    </div>
  );
}

function AddAffordances() {
  const storeApi = itineraryGraphStore.useStoreApi();
  const savingLink = itineraryGraphStore.useStore((s) => s.savingLink);
  const editable = itineraryGraphStore.useStore(selectEditable);
  const { openComposer } = useComposerControl();
  const [link, setLink] = useState("");
  const [note, setNote] = useState("");

  const submitLink = () => {
    const url = link.trim();
    if (!url) return;
    storeApi.getState().saveLinkToCollection(url);
    setLink("");
  };
  const submitNote = () => {
    const text = note.trim();
    if (!text) return;
    storeApi.getState().addCollectionNote(text);
    setNote("");
  };

  const input =
    "h-8 w-full rounded-md border border-ink/15 bg-paper-white px-2 font-sans text-[12px] text-ink placeholder:text-ink/35 focus:border-ink/40 focus:outline-hidden";

  return (
    <div className="flex shrink-0 flex-col gap-2 border-b border-ink/10 px-4 py-3">
      {editable ? (
        <button
          type="button"
          onClick={() => openComposer()}
          data-testid="collection-add-card"
          className="h-8 rounded-md border border-ink/20 bg-paper px-3 font-sans text-[11px] uppercase tracking-[0.16em] text-ink transition-colors hover:bg-ink/5"
        >
          Add a card
        </button>
      ) : null}
      <label className="flex items-center gap-2">
        <span className="w-14 shrink-0 font-sans text-[10px] uppercase tracking-[0.16em] text-ink/45">
          Link
        </span>
        <input
          type="url"
          value={link}
          onChange={(e) => setLink(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") submitLink();
          }}
          disabled={savingLink}
          placeholder="Paste a restaurant, hotel, or article…"
          data-testid="collection-add-link"
          className={input}
        />
      </label>
      <label className="flex items-center gap-2">
        <span className="w-14 shrink-0 font-sans text-[10px] uppercase tracking-[0.16em] text-ink/45">
          Note
        </span>
        <input
          type="text"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") submitNote();
          }}
          placeholder="Jot an idea…"
          data-testid="collection-add-note"
          className={input}
        />
      </label>
    </div>
  );
}

function CollectionCard({
  node,
  scheduled = false,
  onOpen,
}: {
  node: NodeResponse;
  /** This card already has a real time (it's on the timeline). Only shown when
   *  the "Scheduled" toggle is on — dimmed + marked so it reads as placed. */
  scheduled?: boolean;
  onOpen?: (nodeId: string) => void;
}) {
  // Non-schedulable cards (articles / reading list) live in the Collection only
  // — they never go on a day. Disable the drag + hide the Place affordance; the
  // card still opens to read. `schedulable` is derived server-side on the node.
  const schedulable = node.schedulable !== false;
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: collectionDragId(node.id),
    disabled: !schedulable,
  });
  const storeApi = itineraryGraphStore.useStoreApi();
  // Pick-then-place (PS5): the primary, no-drag way to schedule. Click "Place"
  // to lift the card, then click a slot on the timeline — no held mouse. Only a
  // real editable surface offers it (a draft-mine traveler keeps the drag→lazy-
  // fork path). The card body click stays free for opening the card's detail.
  const canSchedule = itineraryGraphStore.useStore(selectCanSchedule);
  // Remove a wish-list maybe (soft delete). Offered to anyone who can write
  // (advisor or the traveler on their own itinerary); a firmed card must be
  // demoted first (G1), and a placed card is managed from the timeline instead.
  const canDelete =
    itineraryGraphStore.useStore(selectCanLeaveNote) &&
    !node.lock_reason &&
    !scheduled;
  // A Collection card is the SAME card as the timeline glance of this node
  // (M006 harmonization): shared CardShell substrate + shared CardBody. The
  // drag handle + Schedule overlay stay as chrome around the shell. Collection
  // items are unscheduled, so tz is moot (0) — CardBody just omits the time row.
  const kind = inferCardKind(node);
  const status = statusToKind(node.status);

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: isDragging ? 0.4 : 1, y: 0 }}
      exit={{ opacity: 0, scale: 0.96 }}
      transition={{ type: "spring", stiffness: 500, damping: 40 }}
      data-testid="collection-card"
      data-node-id={node.id}
      data-node-type={node.type}
      data-scheduled={scheduled ? "true" : "false"}
      className={"relative " + (scheduled ? "opacity-60" : "")}
    >
      {/* Remove from the collection (soft delete). Sits top-left as a standing
          affordance (mirrors the top-right "Place"); a scheduled card hides it —
          that spot carries the "On timeline" tag and it's managed from there. */}
      {canDelete ? (
        <button
          type="button"
          onClick={() => storeApi.getState().removeNode(node.id)}
          data-testid="collection-remove"
          aria-label={`Remove ${node.title || "this"} from the collection`}
          title="Remove from collection"
          className="absolute left-2 top-2 z-10 rounded-full border border-ink/15 bg-paper/95 p-1 text-ink/55 shadow-xs transition-colors hover:bg-[#8b2a1d] hover:text-paper"
        >
          <X className="h-3.5 w-3.5" aria-hidden />
        </button>
      ) : null}
      {/* A placed card wears a quiet marker so, when revealed, it reads as
          already on the timeline rather than another loose maybe. */}
      {scheduled ? (
        <span
          data-testid="collection-scheduled-tag"
          className="absolute left-2 top-2 z-10 rounded-full border border-ink/15 bg-paper/95 px-2 py-0.5 font-sans text-[9px] uppercase tracking-[0.16em] text-ink/55 shadow-xs"
        >
          On timeline
        </span>
      ) : null}
      {/* Pick-then-place: "Place" lifts the card into the holding chip (a sibling
          of the card button — nesting buttons is invalid, and this must not start
          a drag). Click a slot on the timeline to drop it — no held mouse.
          Desktop-only: place targets live on the ≥md timeline canvas; on a phone
          the card-detail schedule facet (PS4) sets the day/time instead. */}
      {canSchedule && schedulable ? (
        <button
          type="button"
          onClick={() => storeApi.getState().holdItem(node.id)}
          data-testid="collection-schedule"
          aria-label={`Place ${node.title || "this"} on the timeline`}
          className="absolute right-2 top-2 z-10 hidden rounded-full border border-ink/15 bg-paper/95 px-2.5 py-1 font-sans text-[10px] uppercase tracking-[0.16em] text-ink/70 shadow-xs transition-colors hover:bg-ink hover:text-paper md:block"
        >
          {scheduled ? "Move" : "Place"}
        </button>
      ) : null}
      {/* The card body is a plain click target: it opens the card's detail
          (explore). Dragging still works (the fork path leans on it), but click —
          not drag — is the advertised gesture, so it reads as a pointer. */}
      <button
        ref={setNodeRef}
        type="button"
        {...listeners}
        {...attributes}
        onClick={onOpen ? () => onOpen(node.id) : undefined}
        className="block w-full cursor-pointer rounded-lg text-left transition focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-brand"
      >
        <CardShell
          kind={kind}
          status={status}
          width="glance"
          lockReason={node.lock_reason ?? null}
          lockLabel={node.type}
        >
          <CardBody node={node} kind={kind} tzOffsetHours={0} />
        </CardShell>
      </button>
    </motion.div>
  );
}
