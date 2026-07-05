"use client";

// The drawing surface. Layout (positions + segments) is computed *outside* by
// the shell so the time axis on the left and the cards in here stay in lock-
// step. This component owns the per-card draggable wiring + measurements; the
// DndContext itself lives one level up in HorizontalView so it can drive the
// preview layout while a drag is in flight.
//
// Internal stack (top → bottom of the DOM):
//   1. Headers strip — sticky-top so it never scrolls vertically out of view.
//   2. Body wrapper — alternating per-day backgrounds + separator lines,
//      droppable rails, night bars, and cards positioned absolutely.

import { useDraggable, useDroppable } from "@dnd-kit/core";
import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useMemo, useRef } from "react";

import { NodeCard } from "./NodeCard";
import {
  COL_WIDTH,
  DAY_HEADER_HEIGHT,
  NIGHT_BAR_WIDTH,
  mapMinuteToY,
  type DayLayout,
  type HLayoutResult,
  type PositionedHNode,
} from "./layout";
import {
  formatDayTile,
  localMinuteOfDay,
  offsetHoursOr,
} from "../../model/horizontalTime";
import type { NodeResponse, NodeStatus, NodeType } from "../../model/horizontalTypes";
import { BRAND_RGB } from "../../shared/cards/tokens";

const LOCKED_STATUSES: ReadonlySet<NodeStatus> = new Set(["approved", "confirmed"]);

function isLockedStatus(status: NodeStatus): boolean {
  return LOCKED_STATUSES.has(status);
}

const DURATION_BAR_TYPE_COLOR: Partial<Record<NodeType, string>> = {
  flight: "#4d7490",
  transit: "#7a7a7a",
  experience: "#b58a3a",
  destination: "#5f7a4a",
  hotel: "#3a3a3a",
  meal: "#b85a3e",
  free_time: "#a0a0a0",
  note: "#bbb6ad",
};

function durationBarColor(type: NodeType): string {
  return DURATION_BAR_TYPE_COLOR[type] ?? "#8a8a8a";
}

const DURATION_BAR_WIDTH = 16;

interface HorizontalCanvasProps {
  layout: HLayoutResult;
  pendingProposals: NodeResponse[];
  flashNodeId: string | null;
  focusedNodeId: string | null;
  // Staff editing is unlocked — only then are cards draggable to reorder.
  editable: boolean;
  tzOffsetHours: number;
  axisWidth: number;
  activeDragId: string | null;
  ghostId: string | null;
  // Place mode (PS5): while a card is held, day columns become pulsing tap
  // targets. `onPlaceTap` reports the tapped day + raw clientY back to the
  // host, which resolves it to a minute against the shared layout segments.
  placing: boolean;
  onPlaceTap: (dayKey: string, clientY: number) => void;
  // Create-at-slot (ADV-4): while editable and not placing/dragging, clicking
  // empty day-column space reports the day + raw clientY back to the host, which
  // resolves the minute and opens the composer pre-set to that slot (Outlook-
  // style). Absent → no create affordance (e.g. traveler surfaces).
  onCreateTap?: (dayKey: string, clientY: number) => void;
  bodyRef: React.Ref<HTMLDivElement>;
  onCardHover: (id: string | null) => void;
  onCardClick: (id: string) => void;
  onAcceptProposal: (id: string) => void;
  onDismissProposal: (id: string) => void;
  onMeasureCard: (id: string, height: number) => void;
  onScrollToNode: (id: string) => void;
  // Host node id → attached `note` nodes, for the per-card note badge.
  attachedNotes?: Map<string, NodeResponse[]>;
}

function MeasuredCard({
  id,
  onMeasure,
  children,
}: {
  id: string;
  onMeasure: (id: string, height: number) => void;
  children: React.ReactNode;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (!entry) return;
      const h = Math.round(entry.contentRect.height);
      if (h > 0) onMeasure(id, h);
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [id, onMeasure]);
  return <div ref={ref}>{children}</div>;
}

export function HorizontalCanvas({
  layout,
  pendingProposals,
  flashNodeId,
  focusedNodeId,
  editable,
  tzOffsetHours,
  axisWidth,
  activeDragId,
  ghostId,
  placing,
  onPlaceTap,
  onCreateTap,
  bodyRef,
  onCardHover,
  onCardClick,
  onAcceptProposal,
  onDismissProposal,
  onMeasureCard,
  onScrollToNode,
  attachedNotes,
}: HorizontalCanvasProps) {
  const positioned = Array.from(layout.positions.values());
  const proposalIds = useMemo(
    () => new Set(pendingProposals.map((p) => p.id)),
    [pendingProposals],
  );

  // Cards are positioned in the canvas's coordinate system, which subtracts
  // the axis width from layout.x (layout.x includes the axis gutter).
  const xOf = (p: PositionedHNode) => p.x - axisWidth;
  const colXOf = (d: DayLayout) => d.columnX - axisWidth;

  const innerWidth = layout.totalWidth - axisWidth;
  const isDragActive = activeDragId !== null;

  return (
    <div
      className="relative"
      style={{
        width: innerWidth,
        minHeight: layout.totalHeight + DAY_HEADER_HEIGHT,
      }}
    >
      {/* Headers strip — first child so sticky `top: 0` anchors here.
          Horizontally, the strip is as wide as the canvas, so day tiles
          scroll-with the columns naturally. */}
      <div
        className="sticky top-0 z-30 border-b border-ink/10 bg-paper/85 backdrop-blur-xs"
        style={{ height: DAY_HEADER_HEIGHT, width: innerWidth }}
      >
        {layout.days.map((d) => (
          <DayHeaderTile key={`hdr-${d.date}`} day={d} colX={colXOf(d)} />
        ))}
      </div>

      {/* Body — cards live in here. Alternating backgrounds and separator
          lines paint behind everything so the visual rhythm reads even
          when a column is sparsely populated. */}
      <div
        ref={bodyRef}
        className="relative"
        style={{ width: innerWidth, height: layout.totalHeight }}
      >
        {/* Create-at-slot layer (ADV-4): full-column click targets rendered
            FIRST (lowest in the stack) so cards + night bars paint above and
            keep their own clicks, while a click on empty column space (the
            zebra/separators are pointer-events-none) falls through to here and
            opens the composer at that day + minute. Only for editable advisors,
            and suppressed while placing/dragging so it never fights those. */}
        {onCreateTap && editable && !placing && !isDragActive
          ? layout.days.map((d) => (
              <button
                key={`create-${d.date}`}
                type="button"
                data-testid="create-slot"
                data-day={d.date}
                aria-label={`Add a card on ${d.label}`}
                onClick={(e) => onCreateTap(d.date, e.clientY)}
                className="absolute cursor-copy rounded-lg transition-colors hover:bg-brand/[0.04]"
                style={{
                  left: colXOf(d) - 4,
                  top: 0,
                  width: d.columnWidth + 8,
                  height: layout.totalHeight,
                }}
              />
            ))
          : null}

        {/* Per-day backgrounds (zebra) + separators. The canvas drops the
            alpha quite low so it reads as a paper-grain alternation, not a
            loud stripe. */}
        {layout.days.map((d, i) => (
          <div
            key={`bg-${d.date}`}
            aria-hidden
            className="pointer-events-none absolute top-0"
            style={{
              left: colXOf(d) - 2,
              width: d.columnWidth + 4,
              height: layout.totalHeight,
              backgroundColor: i % 2 === 0
                ? "rgba(0,0,0,0)"
                : "rgba(10,10,10,0.025)",
            }}
          />
        ))}
        {/* Vertical separators on the *right* edge of every day except the
            last. A 1px line tinted dark enough to read on cream paper. */}
        {layout.days.slice(0, -1).map((d) => (
          <div
            key={`sep-${d.date}`}
            aria-hidden
            className="pointer-events-none absolute top-0"
            style={{
              left: colXOf(d) + d.columnWidth + 9,
              width: 1,
              height: layout.totalHeight,
              backgroundColor: "rgba(10,10,10,0.10)",
            }}
          />
        ))}

        {/* Droppable rails — invisible until a drag is active. */}
        {layout.days.map((d) => (
          <DayRail
            key={`rail-${d.date}`}
            day={d}
            colX={colXOf(d)}
            height={layout.totalHeight}
            isDragActive={isDragActive}
          />
        ))}

        {/* Place mode (PS5): while a card is held, every day column is a pulsing
            tap target. A tap reports its clientY up to the host, which maps it to
            a minute — a non-drag, keyboard-and-touch-friendly way to schedule. */}
        {placing
          ? layout.days.map((d) => (
              <button
                key={`place-${d.date}`}
                type="button"
                data-testid="place-target"
                data-day={d.date}
                aria-label={`Place on ${d.label}`}
                onClick={(e) => onPlaceTap(d.date, e.clientY)}
                className="absolute z-30 animate-pulse rounded-lg border-2 border-dashed border-brand/50 bg-brand/6 transition-colors hover:animate-none hover:bg-brand/12 motion-reduce:animate-none"
                style={{
                  left: colXOf(d) - 4,
                  top: 0,
                  width: d.columnWidth + 8,
                  height: layout.totalHeight,
                }}
              />
            ))
          : null}

        {/* Night bars under cards. */}
        {positioned
          .filter((p) => p.nightBar)
          .map((p) => (
            <div
              key={`night-${p.node.id}`}
              className="absolute rounded-full"
              style={{
                top: p.y,
                left: xOf(p),
                width: NIGHT_BAR_WIDTH,
                height: p.barH,
                backgroundImage:
                  "linear-gradient(180deg, rgba(74,56,98,0.55), rgba(20,23,61,0.7))",
                opacity: 0.55,
              }}
              title={p.node.title}
              aria-label={p.node.title}
            />
          ))}

        {/* Duration bars — a colored strip at each non-night-bar card's
            left edge, height = the event's full duration mapped onto this
            non-linear y axis. Extends past the card body for long events,
            making "this dinner runs 2 hours" visible at a glance. Color is
            keyed to node type (same palette as vertical's DurationBar).
            When the bar extends well below the card, an up-arrow button at
            the bar's tail scrolls the viewport back to the card. */}
        {positioned
          .filter((p) => !p.nightBar && p.barH > 0 && p.node.id !== ghostId)
          .map((p) => {
            const showScrollBack = p.barH > p.cardH + 24;
            return (
              <div
                key={`dur-${p.node.id}`}
                className="pointer-events-none absolute"
                style={{
                  top: p.y,
                  left: xOf(p) - DURATION_BAR_WIDTH - 4,
                  width: DURATION_BAR_WIDTH,
                  height: p.barH,
                }}
              >
                <div
                  aria-hidden
                  className="absolute inset-0 rounded-full"
                  style={{
                    backgroundColor: durationBarColor(p.node.type),
                    opacity: 0.55,
                    boxShadow: "inset 0 0 0 0.5px rgba(0,0,0,0.15)",
                  }}
                />
                {showScrollBack ? (
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      onScrollToNode(p.node.id);
                    }}
                    title={`Scroll back to ${p.node.title}`}
                    aria-label={`Scroll back to ${p.node.title}`}
                    className="pointer-events-auto absolute left-1/2 flex h-5 w-5 -translate-x-1/2 items-center justify-center rounded-full border border-ink/15 bg-paper text-ink/70 shadow-xs transition-colors hover:bg-ink hover:text-paper"
                    style={{ bottom: -2 }}
                  >
                    <svg
                      width="10"
                      height="10"
                      viewBox="0 0 10 10"
                      aria-hidden
                      className="block"
                    >
                      <path
                        d="M5 2.5 L1.8 6 M5 2.5 L8.2 6 M5 2.5 L5 8"
                        stroke="currentColor"
                        strokeWidth="1.4"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        fill="none"
                      />
                    </svg>
                  </button>
                ) : null}
              </div>
            );
          })}

        <AnimatePresence initial={false}>
          {positioned
            .filter((p) => !p.nightBar)
            .map((p) => {
              if (p.node.id === ghostId) {
                return (
                  <GhostSlot
                    key={`ghost-${p.node.id}`}
                    p={p}
                    axisWidth={axisWidth}
                  />
                );
              }
              const isProposal = proposalIds.has(p.node.id);
              const isFlashing = flashNodeId === p.node.id;
              const isFocused = focusedNodeId === p.node.id;
              const isActive = activeDragId === p.node.id;
              return (
                <CardWrap
                  key={p.node.id}
                  p={p}
                  axisWidth={axisWidth}
                  isProposal={isProposal}
                  isFlashing={isFlashing}
                  isFocused={isFocused}
                  isActiveDrag={isActive}
                  isLocked={isLockedStatus(p.node.status)}
                  editable={editable}
                  onHover={(id) => onCardHover(id)}
                  onMeasure={onMeasureCard}
                  onClick={() => onCardClick(p.node.id)}
                  onAccept={() => onAcceptProposal(p.node.id)}
                  onDismiss={() => onDismissProposal(p.node.id)}
                  tzOffsetHours={tzOffsetHours}
                  compact={p.compact}
                  attachedNoteCount={attachedNotes?.get(p.node.id)?.length ?? 0}
                />
              );
            })}
        </AnimatePresence>

        {/* Pending proposals that aren't placed (no start_time) — fall back
            to a stack on the right edge. */}
        {pendingProposals
          .filter((p) => !layout.positions.has(p.id))
          .map((p, i) => {
            const meta = p.metadata as { start_time?: string };
            const min = meta.start_time
              ? localMinuteOfDay(
                  meta.start_time,
                  offsetHoursOr(meta.start_time, tzOffsetHours),
                )
              : 720;
            const y = mapMinuteToY(min, layout.segments);
            const x = innerWidth - COL_WIDTH - 24 - i * 12;
            return (
              <motion.div
                key={`pending-${p.id}`}
                className="absolute"
                style={{ top: y, left: x, width: COL_WIDTH }}
                initial={{ opacity: 0, y: -8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0 }}
              >
                <NodeCard
                  node={p}
                  tzOffsetHours={tzOffsetHours}
                  onClick={() => onCardClick(p.id)}
                />
              </motion.div>
            );
          })}
      </div>
    </div>
  );
}

function DayHeaderTile({ day, colX }: { day: DayLayout; colX: number }) {
  const { weekday, dayMonth } = formatDayTile(day.date);
  return (
    <div
      className="pointer-events-none absolute"
      style={{
        left: colX,
        top: 6,
        width: day.columnWidth,
        height: DAY_HEADER_HEIGHT - 12,
      }}
    >
      <div className="relative mx-auto flex h-full w-full max-w-[300px] flex-col justify-center rounded-md border border-ink/15 bg-paper px-3 py-1.5 shadow-xs">
        <span
          aria-hidden
          className="pointer-events-none absolute -top-1 left-3 h-2 w-12 -rotate-2 bg-amber-600/40"
          style={{ mixBlendMode: "multiply" }}
        />
        <div className="text-[9px] uppercase tracking-[0.22em] text-ink/55">
          {day.label}
        </div>
        <div className="flex items-center justify-between">
          <span className="font-serif text-[13px] leading-tight text-ink">
            {weekday} · {dayMonth}
          </span>
          {day.weather_emoji ? (
            <span className="text-[14px] leading-none" aria-hidden>
              {day.weather_emoji}
            </span>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function DayRail({
  day,
  colX,
  height,
  isDragActive,
}: {
  day: DayLayout;
  colX: number;
  height: number;
  isDragActive: boolean;
}) {
  const { setNodeRef, isOver } = useDroppable({ id: `day-${day.date}` });
  return (
    <div
      ref={setNodeRef}
      className={[
        "absolute rounded-lg transition-colors",
        isDragActive ? "border border-dashed" : "",
        isOver ? "bg-ink/5 border-ink/40" : "border-transparent",
      ].join(" ")}
      style={{
        left: colX - 4,
        top: 0,
        width: day.columnWidth + 8,
        height,
        borderStyle: isDragActive ? "dashed" : undefined,
        pointerEvents: isDragActive ? "auto" : "none",
      }}
    />
  );
}

// The "make room" placeholder shown in the destination day while a drag is
// in flight. It occupies the same y/height the dragged card will land at,
// which is what causes subsequent cards in the column to slide down via the
// shared layout pass — see HorizontalView for the ghost-node wiring.
function GhostSlot({
  p,
  axisWidth,
}: {
  p: PositionedHNode;
  axisWidth: number;
}) {
  return (
    <motion.div
      key={`ghost-${p.node.id}`}
      layout
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.12 }}
      className="pointer-events-none absolute"
      style={{
        left: p.x - axisWidth,
        top: p.y,
        width: p.w,
        height: p.cardH,
      }}
    >
      <div
        className="h-full w-full rounded-lg border-2 border-dashed border-ink/45 bg-ink/4"
        aria-hidden
      >
        <div className="flex h-full w-full items-center justify-center">
          <span className="text-[10px] uppercase tracking-[0.22em] text-ink/55">
            Drop here
          </span>
        </div>
      </div>
    </motion.div>
  );
}

function CardWrap({
  p,
  axisWidth,
  isProposal,
  isFlashing,
  isFocused,
  isActiveDrag,
  isLocked,
  editable,
  onHover,
  onMeasure,
  onClick,
  onAccept,
  onDismiss,
  tzOffsetHours,
  compact,
  attachedNoteCount,
}: {
  p: PositionedHNode;
  axisWidth: number;
  isProposal: boolean;
  isFlashing: boolean;
  isFocused: boolean;
  isActiveDrag: boolean;
  isLocked: boolean;
  editable: boolean;
  onHover: (id: string | null) => void;
  onMeasure: (id: string, h: number) => void;
  onClick: () => void;
  onAccept: () => void;
  onDismiss: () => void;
  tzOffsetHours: number;
  compact: boolean;
  attachedNoteCount: number;
}) {
  // Draggable only when staff editing is unlocked AND the node isn't a
  // locked-status (approved/confirmed) row.
  const dragDisabled = isLocked || !editable;
  const { setNodeRef, listeners, attributes, isDragging } = useDraggable({
    id: p.node.id,
    disabled: dragDisabled,
  });
  // We deliberately don't apply `transform` here — DragOverlay (in
  // HorizontalView) renders the floating clone. Letting the source slot
  // stay anchored keeps the canvas layout calm and lets the ghost slot in
  // the destination day be the only thing that moves to "make room".
  return (
    <motion.div
      layout
      data-testid="timeline-card"
      data-node-id={p.node.id}
      initial={{ opacity: 0, scale: 0.97 }}
      animate={{
        opacity: isDragging || isActiveDrag ? 0.25 : 1,
        scale: 1,
      }}
      exit={{ opacity: 0, scale: 0.96 }}
      transition={{ duration: 0.2 }}
      onMouseEnter={() => onHover(p.node.id)}
      onMouseLeave={() => onHover(null)}
      style={{
        position: "absolute",
        left: p.x - axisWidth,
        top: p.y,
        width: p.w,
      }}
    >
      <MeasuredCard id={p.node.id} onMeasure={onMeasure}>
        <div
          ref={setNodeRef}
          {...listeners}
          {...attributes}
          className="outline-hidden"
          style={{
            cursor: dragDisabled ? "default" : isDragging ? "grabbing" : "grab",
            touchAction: dragDisabled ? "auto" : "none",
          }}
          aria-disabled={dragDisabled || undefined}
          title={isLocked ? `Locked — status is ${p.node.status}` : undefined}
        >
          {/* Focus chrome — the selected node's active accent: a brand-orange
              ring as a motion box-shadow plus a 3px left-edge bar. The
              motion.div hugs the rendered card exactly (260px wide), so the
              focus halo never extends past the visible card. */}
          <motion.div
            animate={{
              boxShadow: isFocused
                ? `0 0 0 1.5px rgba(${BRAND_RGB}, 0.9), 0 10px 28px -10px rgba(${BRAND_RGB}, 0.45)`
                : `0 0 0 0 rgba(${BRAND_RGB}, 0), 0 0 0 0 rgba(0,0,0,0)`,
            }}
            transition={{ duration: 0.18 }}
            className="relative rounded-lg"
          >
            {isFocused ? (
              <span
                aria-hidden
                className="pointer-events-none absolute -left-1 top-2 bottom-2 w-[3px] rounded-full bg-brand"
              />
            ) : null}
            <NodeCard
              node={p.node}
              tzOffsetHours={tzOffsetHours}
              onClick={onClick}
              flash={isFlashing}
              compact={compact}
              attachedNoteCount={attachedNoteCount}
            />
          </motion.div>
          {isProposal ? (
            <div className="mt-1.5 flex gap-1.5">
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  onAccept();
                }}
                className="rounded-md bg-brand px-2 py-1 text-[10px] uppercase tracking-[0.18em] text-brand-foreground"
              >
                Accept
              </button>
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  onDismiss();
                }}
                className="rounded-md border border-ink/20 px-2 py-1 text-[10px] uppercase tracking-[0.18em] text-ink/70"
              >
                Dismiss
              </button>
            </div>
          ) : null}
        </div>
      </MeasuredCard>
    </motion.div>
  );
}
