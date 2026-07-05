"use client";

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
import { useMemo, useState } from "react";

import { type MoodId, type NodeResponse } from "@/app/_components/itinerary-graph/model/baseTypes";
import {
  CARD_GAP,
  CARD_HEIGHT,
  COL_GAP,
  COL_WIDTH,
  DAY_HEADER_HEIGHT,
  PAD_X,
  PAD_Y,
  computeLayout,
} from "../_state/layout";
import { timelineStore } from "../_state/timelineStore";
import { Card } from "@/app/_components/itinerary-graph/shared/ExpandedCard";
import { EdgeLayer } from "./EdgeLayer";
import { GhostCard } from "./GhostCard";

interface TimelineCanvasProps {
  mood: MoodId;
  onCardClick: (node: NodeResponse) => void;
  onMoveNode: (nodeId: string, dayIndex: number) => void;
  onAcceptProposal: (id: string) => void;
  onDismissProposal: (id: string) => void;
}

export function TimelineCanvas({
  mood,
  onCardClick,
  onMoveNode,
  onAcceptProposal,
  onDismissProposal,
}: TimelineCanvasProps) {
  const nodes = timelineStore.useStore((s) => s.nodes);
  const edges = timelineStore.useStore((s) => s.edges);
  const pendingProposals = timelineStore.useStore((s) => s.pendingProposals);
  const assemblePulse = timelineStore.useStore((s) => s.assemblePulse);
  const flashNodeId = timelineStore.useStore((s) => s.flashNodeId);
  const sample = timelineStore.useStore((s) => s.sample);

  const [activeDrag, setActiveDrag] = useState<string | null>(null);

  const layout = useMemo(() => {
    const combined = [...nodes, ...pendingProposals];
    return computeLayout(combined, edges);
  }, [nodes, pendingProposals, edges]);

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
  );

  const dayIndices = layout.dayIndices;
  const proposalIds = new Set(pendingProposals.map((p) => p.id));

  const handleDragEnd = (event: DragEndEvent) => {
    setActiveDrag(null);
    const { active, over } = event;
    if (!over) return;
    const overId = String(over.id);
    if (!overId.startsWith("day-")) return;
    const targetDay = Number(overId.slice(4));
    if (Number.isNaN(targetDay)) return;
    onMoveNode(String(active.id), targetDay);
  };

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
        style={{ width: layout.width, height: layout.height }}
      >
        <EdgeLayer edges={edges} layout={layout} pulse={assemblePulse} />

        {/* Day columns — droppable rails + headers */}
        {dayIndices.map((day, i) => (
          <DayColumn
            key={day}
            day={day}
            columnIndex={i}
            height={layout.height - PAD_Y - DAY_HEADER_HEIGHT}
            label={sample.dayLabels?.[day - 1] ?? `Day ${day}`}
            active={activeDrag !== null}
          />
        ))}

        {/* Positioned cards */}
        <AnimatePresence initial={false}>
          {Array.from(layout.positions.values()).map(({ node, x, y, w, h }) => {
            const isProposal = proposalIds.has(node.id);
            return (
              <motion.div
                key={node.id}
                layout
                initial={{ opacity: 0, scale: 0.97 }}
                animate={{ opacity: 1, scale: 1 }}
                exit={{ opacity: 0, scale: 0.96 }}
                transition={{ duration: 0.25 }}
                style={{
                  position: "absolute",
                  left: x,
                  top: y,
                  width: w,
                  height: h,
                }}
              >
                {isProposal ? (
                  <GhostCard
                    node={node}
                    mood={mood}
                    onAccept={() => onAcceptProposal(node.id)}
                    onDismiss={() => onDismissProposal(node.id)}
                    onClick={() => onCardClick(node)}
                  />
                ) : (
                  <DraggableCard
                    node={node}
                    mood={mood}
                    flash={flashNodeId === node.id}
                    isActive={activeDrag === node.id}
                    onClick={() => onCardClick(node)}
                  />
                )}
              </motion.div>
            );
          })}
        </AnimatePresence>
      </div>
    </DndContext>
  );
}

function DayColumn({
  day,
  columnIndex,
  height,
  label,
  active,
}: {
  day: number;
  columnIndex: number;
  height: number;
  label: string;
  active: boolean;
}) {
  const { setNodeRef, isOver } = useDroppable({ id: `day-${day}` });
  const x = PAD_X + columnIndex * (COL_WIDTH + COL_GAP);
  return (
    <>
      <div
        className="absolute text-[10px] uppercase tracking-[0.22em] text-ink/55 font-sans"
        style={{ left: x, top: PAD_Y, width: COL_WIDTH }}
      >
        {label}
      </div>
      <div
        ref={setNodeRef}
        className={[
          "absolute rounded-lg transition-colors",
          active ? "border border-dashed" : "",
          isOver ? "bg-ink/5 border-ink/30" : "border-ink/10",
        ].join(" ")}
        style={{
          left: x - 6,
          top: PAD_Y + DAY_HEADER_HEIGHT - 6,
          width: COL_WIDTH + 12,
          height: height + CARD_HEIGHT + CARD_GAP,
          borderStyle: active ? "dashed" : undefined,
        }}
      />
    </>
  );
}

function DraggableCard({
  node,
  mood,
  flash,
  isActive,
  onClick,
}: {
  node: NodeResponse;
  mood: MoodId;
  flash: boolean;
  isActive: boolean;
  onClick: () => void;
}) {
  const { setNodeRef, listeners, attributes, transform } = useDraggable({
    id: node.id,
  });
  const dragStyle = transform
    ? {
        transform: `translate3d(${transform.x}px, ${transform.y}px, 0)`,
        zIndex: 40,
      }
    : undefined;
  return (
    <div
      ref={setNodeRef}
      style={dragStyle}
      {...listeners}
      {...attributes}
      className="outline-hidden"
    >
      <Card
        node={node}
        mood={mood}
        onClick={onClick}
        isDragging={isActive}
        flash={flash}
      />
    </div>
  );
}
