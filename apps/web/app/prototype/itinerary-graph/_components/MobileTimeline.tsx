"use client";

import { AnimatePresence, motion, useAnimate } from "framer-motion";
import { useCallback, useMemo, useState } from "react";

import { type MoodId, type NodeResponse, getMeta } from "../_lib/types";
import { timelineStore } from "../_state/timelineStore";
import { Card } from "./Card";
import { GhostCard } from "./GhostCard";

interface MobileTimelineProps {
  mood: MoodId;
  onCardClick: (node: NodeResponse) => void;
  onMoveNode: (nodeId: string, dayIndex: number) => void;
  onAcceptProposal: (id: string) => void;
  onDismissProposal: (id: string) => void;
}

interface DayGroup {
  day: number;
  label: string;
  nodes: NodeResponse[];
}

export function MobileTimeline({
  mood,
  onCardClick,
  onMoveNode,
  onAcceptProposal,
  onDismissProposal,
}: MobileTimelineProps) {
  const nodes = timelineStore.useStore((s) => s.nodes);
  const pendingProposals = timelineStore.useStore((s) => s.pendingProposals);
  const dayLabels = timelineStore.useStore((s) => s.sample.dayLabels);

  const [parked, setParked] = useState<NodeResponse | null>(null);
  const proposalIds = useMemo(
    () => new Set(pendingProposals.map((p) => p.id)),
    [pendingProposals],
  );

  const groups = useMemo<DayGroup[]>(() => {
    const byDay = new Map<number, NodeResponse[]>();
    const topLevel = [
      ...nodes.filter((n) => n.parent_subgraph_id === null),
      ...pendingProposals,
    ];
    for (const n of topLevel) {
      const day = (getMeta(n).day_index as number | undefined) ?? 1;
      const arr = byDay.get(day) ?? [];
      arr.push(n);
      byDay.set(day, arr);
    }
    const result: DayGroup[] = [];
    const days = Array.from(byDay.keys()).sort((a, b) => a - b);
    for (const d of days) {
      const inDay = (byDay.get(d) ?? []).slice().sort((a, b) => {
        const ra = (getMeta(a).rank as number | undefined) ?? 0;
        const rb = (getMeta(b).rank as number | undefined) ?? 0;
        return ra - rb;
      });
      result.push({
        day: d,
        label: dayLabels?.[d - 1] ?? `Day ${d}`,
        nodes: inDay,
      });
    }
    return result;
  }, [nodes, pendingProposals, dayLabels]);

  const handlePluck = useCallback((node: NodeResponse) => {
    setParked(node);
  }, []);

  const handleLand = useCallback(
    (day: number) => {
      if (!parked) return;
      onMoveNode(parked.id, day);
      setParked(null);
    },
    [parked, onMoveNode],
  );

  return (
    <div className="relative mx-auto w-full max-w-[420px] pb-24">
      <AnimatePresence initial={false}>
        {groups.map((group) => {
          const isEmpty = group.nodes.length === 0;
          return (
            <motion.section
              key={group.day}
              layout
              className="mb-5"
            >
              <header className="mb-2 flex items-center gap-2">
                <span className="font-serif text-[15px] text-ink/80">
                  {group.label}
                </span>
                <span className="h-px flex-1 bg-ink/15" />
                {parked ? (
                  <button
                    type="button"
                    onClick={() => handleLand(group.day)}
                    className="rounded-md border border-ink/25 bg-ink/5 px-2 py-0.5 text-[10px] uppercase tracking-[0.18em] text-ink/70"
                  >
                    Drop here
                  </button>
                ) : null}
              </header>
              {isEmpty ? (
                <div className="rounded-md border border-dashed border-ink/15 p-3 text-[11px] italic text-ink/50">
                  Empty day — swipe a card here.
                </div>
              ) : null}
              <AnimatePresence initial={false}>
                {group.nodes
                  .filter((n) => n.id !== parked?.id)
                  .map((node) => (
                    <MobileRow
                      key={node.id}
                      node={node}
                      mood={mood}
                      ghost={proposalIds.has(node.id)}
                      onClick={() => onCardClick(node)}
                      onPluck={() => handlePluck(node)}
                      onAccept={() => onAcceptProposal(node.id)}
                      onDismiss={() => onDismissProposal(node.id)}
                    />
                  ))}
              </AnimatePresence>
            </motion.section>
          );
        })}
      </AnimatePresence>

      <AnimatePresence>
        {parked ? (
          <motion.div
            key="parked"
            initial={{ opacity: 0, scale: 0.92, x: 80 }}
            animate={{ opacity: 1, scale: 0.88, x: 0 }}
            exit={{ opacity: 0, scale: 0.9 }}
            className="fixed bottom-4 right-3 z-50 w-[220px] rotate-[-2deg]"
            style={{ pointerEvents: "auto" }}
          >
            <div className="rounded-md bg-paper p-1 shadow-[0_18px_40px_-8px_rgba(0,0,0,0.45)]">
              <div className="mb-1 text-center text-[9px] uppercase tracking-[0.22em] text-ink/60">
                Held · tap a day to drop
              </div>
              <Card node={parked} mood={mood} compact />
              <button
                type="button"
                onClick={() => setParked(null)}
                className="mt-1 w-full rounded border border-ink/20 py-1 text-[10px] uppercase tracking-[0.18em] text-ink/60"
              >
                Cancel
              </button>
            </div>
          </motion.div>
        ) : null}
      </AnimatePresence>
    </div>
  );
}

interface MobileRowProps {
  node: NodeResponse;
  mood: MoodId;
  ghost: boolean;
  onClick: () => void;
  onPluck: () => void;
  onAccept: () => void;
  onDismiss: () => void;
}

function MobileRow({
  node,
  mood,
  ghost,
  onClick,
  onPluck,
  onAccept,
  onDismiss,
}: MobileRowProps) {
  const [scope, animate] = useAnimate();
  const [pluckingOut, setPluckingOut] = useState(false);

  const handleDragEnd = async (
    _e: unknown,
    info: { offset: { x: number; y: number } },
  ) => {
    if (Math.abs(info.offset.x) > 110) {
      setPluckingOut(true);
      await animate(
        scope.current,
        { x: info.offset.x > 0 ? 280 : -280, opacity: 0 },
        { duration: 0.25 },
      );
      onPluck();
    } else {
      await animate(scope.current, { x: 0 }, { duration: 0.18 });
    }
  };

  return (
    <motion.div
      ref={scope}
      layout
      drag="x"
      dragElastic={0.14}
      dragConstraints={{ left: -260, right: 260 }}
      onDragEnd={handleDragEnd}
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: pluckingOut ? 0 : 1, y: 0 }}
      exit={{ opacity: 0, scale: 0.96 }}
      transition={{ duration: 0.22 }}
      className="mb-2 touch-pan-x"
    >
      {ghost ? (
        <GhostCard
          node={node}
          mood={mood}
          onAccept={onAccept}
          onDismiss={onDismiss}
          onClick={onClick}
        />
      ) : (
        <Card node={node} mood={mood} onClick={onClick} />
      )}
    </motion.div>
  );
}
