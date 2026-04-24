"use client";

import { AnimatePresence, motion } from "framer-motion";

import { Card } from "../../itinerary-graph/_components/Card";
import { GhostCard } from "../../itinerary-graph/_components/GhostCard";
import type { MoodId, NodeResponse } from "../_lib/types";
import { formatClock } from "../_lib/time";
import type { LayoutResultV, PositionedVNode } from "../_state/layout";
import {
  CARD_WIDTH,
  LANE_WIDTH,
  LEFT_GUTTER,
  NIGHT_BAR_GAP,
  NIGHT_BAR_WIDTH,
} from "../_state/layout";
import { AltCluster } from "./AltCluster";
import { DurationBar } from "./DurationBar";

interface TimelineColumnProps {
  layout: LayoutResultV;
  mood: MoodId;
  tzOffsetHours: number;
  pendingProposals: NodeResponse[];
  flashNodeId: string | null;
  sweptIds: Set<string>;
  onHoverNode: (id: string | null) => void;
  onClickNode: (id: string) => void;
  onAcceptProposal: (id: string) => void;
  onDismissProposal: (id: string) => void;
}

export function TimelineColumn(props: TimelineColumnProps) {
  const {
    layout,
    mood,
    tzOffsetHours,
    pendingProposals,
    flashNodeId,
    sweptIds,
    onHoverNode,
    onClickNode,
    onAcceptProposal,
    onDismissProposal,
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
          start_time?: string;
        };
        const dur =
          typeof meta.duration_minutes === "number" ? meta.duration_minutes : 30;
        const swept = sweptIds.has(p.node.id);
        const flashing = flashNodeId === p.node.id;
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
            {meta.start_time ? (
              <div className="pointer-events-none absolute -left-12 top-1 font-mono text-[10px] tracking-[0.1em] text-ink/55">
                {formatClock(meta.start_time, tzOffsetHours)}
              </div>
            ) : null}
            <div className="pl-4">
              <Card
                node={p.node}
                mood={mood}
                onClick={() => onClickNode(p.node.id)}
                {...(flashing ? { flash: true } : {})}
              />
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
          const windowStartMs = new Date(layout.windowStart).getTime();
          const startMs = meta.start_time
            ? new Date(meta.start_time).getTime()
            : windowStartMs;
          const minutes = (startMs - windowStartMs) / 60000;
          const y = minutes * layout.pxPerMinute;
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
