"use client";

import { useEffect, useRef } from "react";
import { AnimatePresence, motion } from "framer-motion";

import { Card } from "@/app/_components/itinerary-graph/shared/ExpandedCard";
import { GhostCard } from "../../itinerary-graph/_components/GhostCard";
import type { MoodId, NodeResponse } from "@/app/_components/itinerary-graph/model/types";
import type { LayoutResultV, PositionedVNode } from "../_state/layout";
import {
  CARD_WIDTH,
  LANE_WIDTH,
  LEFT_GUTTER,
  NIGHT_BAR_GAP,
  NIGHT_BAR_WIDTH,
  mapMinuteToY,
} from "../_state/layout";
import { formatDuration, minutesSince } from "@/app/_components/itinerary-graph/model/time";
import { AltCluster } from "./AltCluster";
import { DurationBar } from "./DurationBar";

interface TimelineColumnProps {
  layout: LayoutResultV;
  mood: MoodId;
  pendingProposals: NodeResponse[];
  flashNodeId: string | null;
  focusedNodeId: string | null;
  sweptIds: Set<string>;
  expandedId: string | null;
  onHoverNode: (id: string | null) => void;
  onClickNode: (id: string) => void;
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

export function TimelineColumn(props: TimelineColumnProps) {
  const {
    layout,
    mood,
    pendingProposals,
    flashNodeId,
    focusedNodeId,
    sweptIds,
    expandedId,
    onHoverNode,
    onClickNode,
    onAcceptProposal,
    onDismissProposal,
    onMeasureCard,
  } = props;

  const positioned = Array.from(layout.positions.values());
  const nonNightBar = positioned.filter((p) => !p.nightBar);
  const nightBars = positioned.filter((p) => p.nightBar);

  // Build alt cluster boxes.
  const altClusters: Array<{
    groupKey: string;
    top: number;
    height: number;
    laneCount: number;
    anchorLane: number;
  }> = [];
  for (const [groupKey, members] of layout.altGroups.entries()) {
    const positions = members
      .map((id) => layout.positions.get(id))
      .filter((p): p is PositionedVNode => Boolean(p));
    if (positions.length < 2) continue;
    const minY = Math.min(...positions.map((p) => p.y));
    const maxBot = Math.max(...positions.map((p) => p.y + p.barH));
    const laneCount = positions.length;
    const anchorLane = Math.min(...positions.map((p) => p.lane));
    altClusters.push({
      groupKey,
      top: minY - 18,
      height: maxBot - minY + 28,
      laneCount,
      anchorLane,
    });
  }

  const maxLane = positioned.reduce((m, p) => Math.max(m, p.lane), 0);
  const innerWidth =
    LEFT_GUTTER + NIGHT_BAR_WIDTH + NIGHT_BAR_GAP + (maxLane + 1) * LANE_WIDTH + 24;

  return (
    <div
      className="relative flex-1"
      style={{ minHeight: layout.totalHeight, width: innerWidth }}
    >
      {/* Elision markers — a thin dashed band across the column */}
      {layout.segments.map((seg, i) =>
        seg.type === "elide" ? (
          <div
            key={`elide-col-${i}`}
            className="pointer-events-none absolute left-0 right-0"
            style={{ top: seg.yStart, height: seg.yEnd - seg.yStart }}
          >
            <div
              aria-hidden
              className="absolute inset-x-4 top-1/2 -translate-y-1/2 border-t border-dashed border-ink/20"
            />
            <div className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 rounded-full bg-paper px-2 py-0.5 text-[9px] uppercase tracking-[0.22em] text-ink/45">
              · · · {formatDuration(seg.endMin - seg.startMin)} elided · · ·
            </div>
          </div>
        ) : null,
      )}

      {/* Alt clusters (render first so cards sit on top) */}
      {altClusters.map((c) => {
        const left =
          LEFT_GUTTER +
          NIGHT_BAR_WIDTH +
          NIGHT_BAR_GAP +
          c.anchorLane * LANE_WIDTH -
          10;
        const width = c.laneCount * LANE_WIDTH;
        return (
          <AltCluster
            key={c.groupKey}
            top={c.top}
            left={left}
            width={width}
            height={c.height}
          >
            <span className="sr-only">Alt cluster {c.groupKey}</span>
          </AltCluster>
        );
      })}

      {/* Night bars */}
      {nightBars.map((p) => (
        <div
          key={p.node.id}
          className="absolute rounded-full"
          style={{
            top: p.y,
            left: p.x,
            width: p.w,
            height: p.barH,
            backgroundImage:
              "linear-gradient(180deg, rgba(74,56,98,0.55), rgba(20,23,61,0.7))",
            opacity: 0.55,
          }}
          title={p.node.title}
        />
      ))}

      {/* Cards */}
      {nonNightBar.map((p) => {
        const meta = p.node.metadata as {
          duration_minutes?: number;
        };
        const dur =
          typeof meta.duration_minutes === "number" ? meta.duration_minutes : 30;
        const swept = sweptIds.has(p.node.id);
        const flashing = flashNodeId === p.node.id;
        const isFocused = focusedNodeId === p.node.id;
        const motionExtras = swept
          ? {
              animate: {
                boxShadow: [
                  "0 0 0 0 rgba(180,138,58,0)",
                  "0 0 0 6px rgba(180,138,58,0.3)",
                  "0 0 0 0 rgba(180,138,58,0)",
                ],
              },
              transition: { duration: 0.6 },
            }
          : {};
        return (
          <motion.div
            key={p.node.id}
            className="absolute"
            style={{ top: p.y, left: p.x, width: CARD_WIDTH }}
            onMouseEnter={() => onHoverNode(p.node.id)}
            onMouseLeave={() => onHoverNode(null)}
            {...motionExtras}
          >
            <DurationBar type={p.node.type} barH={p.barH} durationMinutes={dur} />
            <div className="pl-4">
              {expandedId === p.node.id ? (
                <div style={{ visibility: "hidden" }}>
                  <Card node={p.node} mood={mood} />
                </div>
              ) : (
                <MeasuredCard id={p.node.id} onMeasure={onMeasureCard}>
                  <motion.div
                    layoutId={`card-${p.node.id}`}
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
                    <Card
                      node={p.node}
                      mood={mood}
                      onClick={() => onClickNode(p.node.id)}
                      {...(flashing ? { flash: true } : {})}
                    />
                  </motion.div>
                </MeasuredCard>
              )}
            </div>
          </motion.div>
        );
      })}

      {/* Pending proposals as ghosts */}
      <AnimatePresence>
        {pendingProposals.map((prop) => {
          const meta = prop.metadata as {
            start_time?: string;
            duration_minutes?: number;
          };
          const minutes = meta.start_time
            ? minutesSince(layout.windowStart, meta.start_time)
            : 0;
          const y = mapMinuteToY(minutes, layout.segments);
          const x =
            LEFT_GUTTER + NIGHT_BAR_WIDTH + NIGHT_BAR_GAP + (maxLane + 1) * LANE_WIDTH;
          return (
            <motion.div
              key={prop.id}
              className="absolute"
              style={{ top: y, left: x, width: CARD_WIDTH }}
            >
              <GhostCard
                node={prop}
                mood={mood}
                onAccept={() => onAcceptProposal(prop.id)}
                onDismiss={() => onDismissProposal(prop.id)}
              />
            </motion.div>
          );
        })}
      </AnimatePresence>
    </div>
  );
}
