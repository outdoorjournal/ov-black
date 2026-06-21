"use client";

// Mobile-friendly fallback. Below the md breakpoint, we don't try to fit
// 15 horizontally-scrolling day columns — that's a thumb-rage UI. Instead we
// stack day sections vertically (like the original itinerary-graph
// MobileTimeline) and let cards be plucked + dropped onto another day with a
// horizontal swipe. The drag interaction reuses framer-motion's drag x-axis
// because @dnd-kit doesn't degrade to touch as gracefully on small screens.

import { AnimatePresence, motion, useAnimate } from "framer-motion";
import { useCallback, useMemo, useState } from "react";

import { NodeCard } from "./NodeCard";
import { formatDayTile, offsetHoursOr } from "../../model/horizontalTime";
import { type NodeResponse } from "../../model/horizontalTypes";
import { getHMeta } from "../../model/horizontalTypes";
import { itineraryGraphStore } from "../../store/itineraryGraphStore";

interface MobileDayListProps {
  daysMeta: Array<{ date: string; label: string; weather_emoji?: string }>;
  tzOffsetHours: number;
  onCardClick: (id: string) => void;
}

interface DayGroup {
  date: string;
  label: string;
  weather_emoji?: string;
  items: NodeResponse[];
}

export function MobileDayList({
  daysMeta,
  tzOffsetHours,
  onCardClick,
}: MobileDayListProps) {
  const nodes = itineraryGraphStore.useStore((s) => s.nodes);
  const pendingProposals = itineraryGraphStore.useStore((s) => s.pendingProposals);
  const storeApi = itineraryGraphStore.useStoreApi();

  const groups = useMemo<DayGroup[]>(() => {
    const byDay = new Map<string, NodeResponse[]>();
    const all = [...nodes, ...pendingProposals];
    for (const n of all) {
      const m = getHMeta(n);
      if (!m.start_time) continue;
      const nodeTz = offsetHoursOr(m.start_time, tzOffsetHours);
      const ms = new Date(m.start_time).getTime() + nodeTz * 3600 * 1000;
      const d = new Date(ms);
      const y = d.getUTCFullYear();
      const mo = String(d.getUTCMonth() + 1).padStart(2, "0");
      const day = String(d.getUTCDate()).padStart(2, "0");
      const key = `${y}-${mo}-${day}`;
      const arr = byDay.get(key) ?? [];
      arr.push(n);
      byDay.set(key, arr);
    }
    return daysMeta.map((dm) => {
      const items = (byDay.get(dm.date) ?? []).slice().sort((a, b) => {
        const sa = new Date(getHMeta(a).start_time ?? "").getTime();
        const sb = new Date(getHMeta(b).start_time ?? "").getTime();
        return sa - sb;
      });
      return {
        date: dm.date,
        label: dm.label,
        ...(dm.weather_emoji ? { weather_emoji: dm.weather_emoji } : {}),
        items,
      };
    });
  }, [nodes, pendingProposals, daysMeta, tzOffsetHours]);

  const [parked, setParked] = useState<NodeResponse | null>(null);

  const handlePluck = useCallback((node: NodeResponse) => {
    setParked(node);
  }, []);

  const handleLand = useCallback(
    (date: string) => {
      if (!parked) return;
      storeApi.getState().moveNode(parked.id, date, null);
      setParked(null);
    },
    [parked, storeApi],
  );

  return (
    <div className="relative mx-auto w-full max-w-[460px] px-3 pb-24">
      <AnimatePresence initial={false}>
        {groups.map((group) => {
          const isEmpty = group.items.length === 0;
          const { weekday, dayMonth } = formatDayTile(group.date);
          return (
            <motion.section key={group.date} layout className="mb-5">
              <header className="mb-2 flex items-center gap-2">
                <span className="font-serif text-[15px] text-ink/85">
                  {group.label}
                </span>
                <span className="text-[11px] text-ink/55">
                  {weekday} · {dayMonth}
                </span>
                {group.weather_emoji ? (
                  <span className="text-[14px]" aria-hidden>
                    {group.weather_emoji}
                  </span>
                ) : null}
                <span className="h-px flex-1 bg-ink/15" />
                {parked ? (
                  <button
                    type="button"
                    onClick={() => handleLand(group.date)}
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
                {group.items
                  .filter((n) => n.id !== parked?.id)
                  .map((node) => (
                    <MobileRow
                      key={node.id}
                      node={node}
                      tzOffsetHours={tzOffsetHours}
                      onClick={() => onCardClick(node.id)}
                      onPluck={() => handlePluck(node)}
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
            className="fixed bottom-4 right-3 z-50 w-[230px] rotate-[-2deg]"
            style={{ pointerEvents: "auto" }}
          >
            <div className="rounded-md bg-paper p-1 shadow-[0_18px_40px_-8px_rgba(0,0,0,0.45)]">
              <div className="mb-1 text-center text-[9px] uppercase tracking-[0.22em] text-ink/60">
                Held · tap a day to drop
              </div>
              <NodeCard node={parked} tzOffsetHours={tzOffsetHours} />
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

function MobileRow({
  node,
  tzOffsetHours,
  onClick,
  onPluck,
}: {
  node: NodeResponse;
  tzOffsetHours: number;
  onClick: () => void;
  onPluck: () => void;
}) {
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
      <NodeCard node={node} tzOffsetHours={tzOffsetHours} onClick={onClick} />
    </motion.div>
  );
}
