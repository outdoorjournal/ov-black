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
import { useMemo, useState } from "react";

import { getHMeta, getMeta } from "../model/horizontalTypes";
import type { NodeResponse } from "../model/horizontalTypes";
import { TYPE_TOKENS, type CardKind } from "../shared/cards/tokens";
import {
  collectionDragId,
  collectionItemsOf,
  itineraryGraphStore,
  selectCanLeaveNote,
} from "../store/itineraryGraphStore";

import { GROUP_AXES, groupCollection, type GroupAxis } from "./grouping";

export function CollectionRail({
  variant = "rail",
}: {
  variant?: "board" | "rail";
}) {
  const nodes = itineraryGraphStore.useStore((s) => s.nodes);
  const pending = itineraryGraphStore.useStore((s) => s.pendingProposals);
  const canAdd = itineraryGraphStore.useStore(selectCanLeaveNote);
  const [axis, setAxis] = useState<GroupAxis>("type");
  const items = useMemo(
    () => collectionItemsOf(nodes, pending),
    [nodes, pending],
  );
  const lanes = useMemo(() => groupCollection(items, axis), [items, axis]);

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
          <div className="font-serif text-lg text-ink">Your wish list</div>
        </div>
        <GroupByToggle axis={axis} onChange={setAxis} />
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
            Nothing saved yet. As you and the concierge find places to eat, stay,
            and things to do, they&rsquo;ll gather here — ready to place on the
            timeline when the shape is right.
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
                      <CollectionCard key={node.id} node={node} />
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
    "h-8 w-full rounded-md border border-ink/15 bg-paper px-2 font-sans text-[12px] text-ink placeholder:text-ink/35 focus:border-ink/40 focus:outline-none";

  return (
    <div className="flex shrink-0 flex-col gap-2 border-b border-ink/10 px-4 py-3">
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

function CollectionCard({ node }: { node: NodeResponse }) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: collectionDragId(node.id),
  });
  const token = TYPE_TOKENS[node.type as CardKind] ?? TYPE_TOKENS.destination;
  const meta = getMeta(node);
  const cover = meta.snapshot?.cover_image;
  const loc = getHMeta(node).location?.label ?? meta.snapshot?.location;
  const price =
    node.cost_amount && node.cost_currency
      ? `${node.cost_currency} ${node.cost_amount}`
      : meta.snapshot?.price;

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
    >
      <button
        ref={setNodeRef}
        type="button"
        {...listeners}
        {...attributes}
        className="w-full cursor-grab overflow-hidden rounded-lg border border-ink/12 bg-paper text-left shadow-sm transition-shadow hover:shadow-md active:cursor-grabbing"
      >
        {cover ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={cover}
            alt=""
            className="h-24 w-full object-cover"
            loading="lazy"
          />
        ) : (
          <div
            className="h-2 w-full"
            style={{ backgroundColor: token.accent }}
            aria-hidden
          />
        )}
        <div className="flex flex-col gap-1 px-3 py-2">
          <div className="flex items-center gap-1.5">
            <span
              className="rounded-sm px-1.5 py-0.5 font-sans text-[9px] uppercase tracking-[0.14em]"
              style={{ backgroundColor: token.tint, color: token.accent }}
            >
              {token.label}
            </span>
            {price ? (
              <span className="font-sans text-[10px] tracking-wide text-ink/55">
                {price}
              </span>
            ) : null}
          </div>
          <div className="font-serif text-[15px] leading-snug text-ink">
            {node.title || token.label}
          </div>
          {loc ? (
            <div className="truncate font-sans text-[11px] text-ink/50">{loc}</div>
          ) : null}
        </div>
      </button>
    </motion.div>
  );
}
