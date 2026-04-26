"use client";

// The drawing surface. Layout (positions + segments) is computed *outside* by
// the shell so the time axis on the left and the cards in here stay in lock-
// step. This component owns the drag-and-drop wiring and the per-card
// height measurements that feed back into the next layout pass.
//
// Internal stack (top → bottom of the DOM):
//   1. Headers strip — sticky-top so it never scrolls vertically out of view.
//   2. Body wrapper — alternating per-day backgrounds + separator lines,
//      droppable rails, night bars, and cards positioned absolutely.

import {
  DndContext,
  type DragEndEvent,
  PointerSensor,
  pointerWithin,
  useDraggable,
  useDroppable,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useMemo, useRef, useState } from "react";

import { JapanCard } from "./JapanCard";
import {
  COL_WIDTH,
  DAY_HEADER_HEIGHT,
  NIGHT_BAR_WIDTH,
  mapMinuteToY,
  type DayLayout,
  type HLayoutResult,
  type PositionedHNode,
} from "../_state/layout";
import { formatDayTile, localMinuteOfDay } from "../_lib/time";
import type { NodeResponse } from "../_lib/types";
import { horizontalStore } from "../_state/horizontalStore";

interface HorizontalCanvasProps {
  layout: HLayoutResult;
  pendingProposals: NodeResponse[];
  flashNodeId: string | null;
  focusedNodeId: string | null;
  tzOffsetHours: number;
  axisWidth: number;
  onCardHover: (id: string | null) => void;
  onCardClick: (id: string) => void;
  onAcceptProposal: (id: string) => void;
  onDismissProposal: (id: string) => void;
  onMeasureCard: (id: string, height: number) => void;
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
  tzOffsetHours,
  axisWidth,
  onCardHover,
  onCardClick,
  onAcceptProposal,
  onDismissProposal,
  onMeasureCard,
}: HorizontalCanvasProps) {
  const storeApi = horizontalStore.useStoreApi();
  const [activeDrag, setActiveDrag] = useState<string | null>(null);

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
  );

  const positioned = Array.from(layout.positions.values());
  const proposalIds = useMemo(
    () => new Set(pendingProposals.map((p) => p.id)),
    [pendingProposals],
  );

  const handleDragEnd = (event: DragEndEvent) => {
    setActiveDrag(null);
    const { active, over } = event;
    if (!over) return;
    const overId = String(over.id);
    if (!overId.startsWith("day-")) return;
    const targetDayKey = overId.slice(4);
    if (!targetDayKey) return;
    storeApi.getState().moveNodeToDay(String(active.id), targetDayKey);
  };

  // Cards are positioned in the canvas's coordinate system, which subtracts
  // the axis width from layout.x (layout.x includes the axis gutter).
  const xOf = (p: PositionedHNode) => p.x - axisWidth;
  const colXOf = (d: DayLayout) => d.columnX - axisWidth;

  const innerWidth = layout.totalWidth - axisWidth;

  return (
    <DndContext
      sensors={sensors}
      collisionDetection={pointerWithin}
      onDragStart={(e) => setActiveDrag(String(e.active.id))}
      onDragCancel={() => setActiveDrag(null)}
      onDragEnd={handleDragEnd}
    >
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
          className="sticky top-0 z-30 border-b border-ink/10 bg-paper/85 backdrop-blur-sm"
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
          className="relative"
          style={{ width: innerWidth, height: layout.totalHeight }}
        >
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
              isDragActive={activeDrag !== null}
            />
          ))}

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

          <AnimatePresence initial={false}>
            {positioned
              .filter((p) => !p.nightBar)
              .map((p) => {
                const isProposal = proposalIds.has(p.node.id);
                const isFlashing = flashNodeId === p.node.id;
                const isFocused = focusedNodeId === p.node.id;
                return (
                  <CardWrap
                    key={p.node.id}
                    p={p}
                    axisWidth={axisWidth}
                    isProposal={isProposal}
                    isFlashing={isFlashing}
                    isFocused={isFocused}
                    onHover={(id) => onCardHover(id)}
                    onMeasure={onMeasureCard}
                    onClick={() => onCardClick(p.node.id)}
                    onAccept={() => onAcceptProposal(p.node.id)}
                    onDismiss={() => onDismissProposal(p.node.id)}
                    tzOffsetHours={tzOffsetHours}
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
                ? localMinuteOfDay(meta.start_time, tzOffsetHours)
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
                  <JapanCard
                    node={p}
                    tzOffsetHours={tzOffsetHours}
                    onClick={() => onCardClick(p.id)}
                  />
                </motion.div>
              );
            })}
        </div>
      </div>
    </DndContext>
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
      <div className="relative mx-auto flex h-full w-full max-w-[300px] flex-col justify-center rounded-md border border-ink/15 bg-paper px-3 py-1.5 shadow-sm">
        <span
          aria-hidden
          className="pointer-events-none absolute -top-1 left-3 h-2 w-12 rotate-[-2deg] bg-amber-600/40"
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

function CardWrap({
  p,
  axisWidth,
  isProposal,
  isFlashing,
  isFocused,
  onHover,
  onMeasure,
  onClick,
  onAccept,
  onDismiss,
  tzOffsetHours,
}: {
  p: PositionedHNode;
  axisWidth: number;
  isProposal: boolean;
  isFlashing: boolean;
  isFocused: boolean;
  onHover: (id: string | null) => void;
  onMeasure: (id: string, h: number) => void;
  onClick: () => void;
  onAccept: () => void;
  onDismiss: () => void;
  tzOffsetHours: number;
}) {
  const { setNodeRef, listeners, attributes, transform, isDragging } =
    useDraggable({ id: p.node.id });
  const dragStyle = transform
    ? {
        transform: `translate3d(${transform.x}px, ${transform.y}px, 0)`,
        zIndex: 40,
      }
    : undefined;
  return (
    <motion.div
      layout
      initial={{ opacity: 0, scale: 0.97 }}
      animate={{ opacity: 1, scale: 1 }}
      exit={{ opacity: 0, scale: 0.96 }}
      transition={{ duration: 0.25 }}
      onMouseEnter={() => onHover(p.node.id)}
      onMouseLeave={() => onHover(null)}
      style={{
        position: "absolute",
        left: p.x - axisWidth,
        top: p.y,
        width: p.w,
        ...dragStyle,
      }}
    >
      <MeasuredCard id={p.node.id} onMeasure={onMeasure}>
        <div
          ref={setNodeRef}
          {...listeners}
          {...attributes}
          className={[
            "outline-none",
            isDragging ? "shadow-2xl rounded-lg" : "",
          ].join(" ")}
        >
          {/* Focus chrome — matches the vertical prototype: a soft amber
              ring as a motion box-shadow plus a 3px left-edge accent bar.
              The motion.div hugs the rendered card exactly (260px wide), so
              the focus halo never extends past the visible card. */}
          <motion.div
            animate={{
              boxShadow: isFocused
                ? "0 0 0 1.5px rgba(184,138,62,0.85), 0 10px 28px -10px rgba(184,138,62,0.45)"
                : "0 0 0 0 rgba(184,138,62,0), 0 0 0 0 rgba(0,0,0,0)",
            }}
            transition={{ duration: 0.18 }}
            className="relative rounded-lg"
          >
            {isFocused ? (
              <span
                aria-hidden
                className="pointer-events-none absolute -left-1 top-2 bottom-2 w-[3px] rounded-full"
                style={{ backgroundColor: "#b88a3e" }}
              />
            ) : null}
            <JapanCard
              node={p.node}
              tzOffsetHours={tzOffsetHours}
              onClick={onClick}
              flash={isFlashing}
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
                className="rounded-md bg-ink px-2 py-1 text-[10px] uppercase tracking-[0.18em] text-paper"
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
