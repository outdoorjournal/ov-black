"use client";

// Top-level layout for the horizontal prototype.
//
//   ┌─ header ─────────────────────────────────────────────────────────┐
//   │                                                                  │
//   ├─ axis ─┬─ horizontally-scrolling canvas ──┬─ chat aside ─────────┤
//   │  (V)   │  (V + H scroll)                  │                      │
//   │        │                                  │                      │
//   ├─ map strip (full body width, doesn't scroll) ────────────────────┤
//   └──────────────────────────────────────────────────────────────────┘
//
// The axis lives **outside** the horizontal scroller so it never moves
// horizontally; we synchronize its scrollTop to the canvas's scrollTop so it
// follows along vertically. The map sits below everything in its own row, so
// it stays anchored to the bottom of the viewport regardless of how the
// canvas above scrolls.
//
// Below md: the canvas + axis are replaced with MobileDayList and the map
// drops to the bottom of the page.

import {
  DndContext,
  DragOverlay,
  type DragEndEvent,
  type DragOverEvent,
  PointerSensor,
  pointerWithin,
  useSensor,
  useSensors,
} from "@dnd-kit/core";
import { AnimatePresence, motion } from "framer-motion";
import {
  type UIEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import { Card } from "../../itinerary-graph/_components/Card";
import type { HorizontalTimeline, NodeResponse } from "../_lib/types";
import { getHMeta } from "../_lib/types";
import { tzDayKey } from "../_lib/time";
import {
  computeHorizontalLayout,
  DAY_HEADER_HEIGHT,
  TIME_GUTTER,
  mapYToMinute,
} from "../_state/layout";
import { horizontalStore } from "../_state/horizontalStore";
import { runScenario } from "../_state/mockStream";

import { AIDemoController } from "./AIDemoController";
import { ChatPanel } from "./ChatPanel";
import { HorizontalCanvas } from "./HorizontalCanvas";
import { JapanCard } from "./JapanCard";
import { MapStrip } from "./MapStrip";
import { MobileDayList } from "./MobileDayList";
import { ScrollHint } from "./ScrollHint";
import { TimeAxis } from "./TimeAxis";
import { ZoomControls } from "./ZoomControls";

const DRAG_GHOST_ID = "__drag-ghost__";

// Build an ISO timestamp anchored on `dayKey` at `minuteOfDay` in the
// traveler's tz. Used to synthesize a *preview* start_time for the ghost
// card while a drag is in flight — final commit goes through the
// in-store rebase helpers.
function buildIsoOnDayAtMinute(
  dayKey: string,
  minuteOfDay: number,
  tzOffsetHours: number,
): string {
  const clamped = Math.max(0, Math.min(1439, Math.round(minuteOfDay)));
  const hh = String(Math.floor(clamped / 60)).padStart(2, "0");
  const mm = String(clamped % 60).padStart(2, "0");
  const sign = tzOffsetHours >= 0 ? "+" : "-";
  const absOff = Math.abs(tzOffsetHours);
  const offH = String(Math.floor(absOff)).padStart(2, "0");
  const offM = String(Math.round((absOff % 1) * 60)).padStart(2, "0");
  return `${dayKey}T${hh}:${mm}:00${sign}${offH}:${offM}`;
}

// How far the left/right scroll-hints jump when clicked. ~one column +
// gutter, so each click lands the viewport on the next day's column.
const SCROLL_HINT_STEP_PX = 320;

interface HorizontalShellProps {
  timeline: HorizontalTimeline;
}

export function HorizontalShell({ timeline }: HorizontalShellProps) {
  return (
    <horizontalStore.Provider initial={{ timeline }}>
      <Inner timeline={timeline} />
    </horizontalStore.Provider>
  );
}

function Inner({ timeline }: HorizontalShellProps) {
  const nodes = horizontalStore.useStore((s) => s.nodes);
  const edges = horizontalStore.useStore((s) => s.edges);
  const pendingProposals = horizontalStore.useStore((s) => s.pendingProposals);
  const messages = horizontalStore.useStore((s) => s.messages);
  const focusedNodeId = horizontalStore.useStore((s) => s.focusedNodeId);
  const flashNodeId = horizontalStore.useStore((s) => s.flashNodeId);
  const pxPerMinute = horizontalStore.useStore((s) => s.pxPerMinute);
  const storeApi = horizontalStore.useStoreApi();

  const canvasScrollRef = useRef<HTMLDivElement>(null);
  const axisScrollRef = useRef<HTMLDivElement>(null);
  const [cardHeights, setCardHeights] = useState<Map<string, number>>(
    () => new Map(),
  );
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [scrollHints, setScrollHints] = useState({ left: false, right: false });
  // Drag preview state. While `activeDragId` is set, we add a synthetic
  // "ghost" node to the layout in the day the pointer is over so other cards
  // in that column slide down to make room before the drop is committed.
  // `overMinute` is derived from the pointer's y position inside the canvas
  // body, so dropping high in the column lands a morning slot and dropping
  // low lands an evening slot — independent of where the card came from.
  const [drag, setDrag] = useState<{
    activeId: string | null;
    overDayKey: string | null;
    overMinute: number | null;
  }>({ activeId: null, overDayKey: null, overMinute: null });
  const bodyRef = useRef<HTMLDivElement>(null);

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
  );

  const allNodes = useMemo(
    () => [...nodes, ...pendingProposals],
    [nodes, pendingProposals],
  );

  const activeNode = useMemo(
    () => (drag.activeId ? allNodes.find((n) => n.id === drag.activeId) : null) ?? null,
    [drag.activeId, allNodes],
  );

  const activeSourceDayKey = useMemo(() => {
    if (!activeNode) return null;
    const start = getHMeta(activeNode).start_time;
    if (!start) return null;
    return tzDayKey(start, timeline.timezoneOffsetHours);
  }, [activeNode, timeline.timezoneOffsetHours]);

  const ghostNode: NodeResponse | null = useMemo(() => {
    if (!activeNode || !drag.overDayKey) return null;
    const meta = getHMeta(activeNode);
    if (!meta.start_time) return null;
    const minute = drag.overMinute;
    // If the pointer hasn't been measured yet, fall back to the source
    // minute so the very first frame is still meaningful.
    const fallbackMinute = (() => {
      const start = new Date(meta.start_time).getTime();
      const local = new Date(start + timeline.timezoneOffsetHours * 3600 * 1000);
      return local.getUTCHours() * 60 + local.getUTCMinutes();
    })();
    // No ghost when hovering over the source day at the source minute —
    // the original card already occupies that slot. Otherwise (different
    // day OR same day at a different time) we want the preview.
    const previewMinute = minute ?? fallbackMinute;
    if (
      drag.overDayKey === activeSourceDayKey &&
      Math.abs(previewMinute - fallbackMinute) < 10
    ) {
      return null;
    }
    return {
      id: DRAG_GHOST_ID,
      itinerary_id: activeNode.itinerary_id,
      parent_subgraph_id: null,
      type: activeNode.type,
      status: activeNode.status,
      title: activeNode.title,
      source: activeNode.source,
      source_id: activeNode.source_id,
      metadata: {
        ...activeNode.metadata,
        start_time: buildIsoOnDayAtMinute(
          drag.overDayKey,
          previewMinute,
          timeline.timezoneOffsetHours,
        ),
      },
    } satisfies NodeResponse;
  }, [activeNode, drag.overDayKey, drag.overMinute, activeSourceDayKey, timeline.timezoneOffsetHours]);

  const layoutCardHeights = useMemo(() => {
    if (!ghostNode || !drag.activeId) return cardHeights;
    const h = cardHeights.get(drag.activeId);
    if (!h) return cardHeights;
    const next = new Map(cardHeights);
    next.set(ghostNode.id, h);
    return next;
  }, [cardHeights, ghostNode, drag.activeId]);

  const layoutNodes = useMemo(
    () => (ghostNode ? [...allNodes, ghostNode] : allNodes),
    [allNodes, ghostNode],
  );

  const handleMeasureCard = useCallback((id: string, h: number) => {
    setCardHeights((prev) => {
      if (prev.get(id) === h) return prev;
      const next = new Map(prev);
      next.set(id, h);
      return next;
    });
  }, []);

  // Keyboard zoom shortcuts — same conventions as the vertical prototype.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (!(e.metaKey || e.ctrlKey)) return;
      if (e.key === "=" || e.key === "+") {
        e.preventDefault();
        storeApi.getState().zoomIn();
      } else if (e.key === "-") {
        e.preventDefault();
        storeApi.getState().zoomOut();
      } else if (e.key === "0") {
        e.preventDefault();
        storeApi.getState().resetZoom();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [storeApi]);

  // Esc closes the expanded card.
  useEffect(() => {
    if (!expandedId) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setExpandedId(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [expandedId]);

  const layout = useMemo(
    () =>
      computeHorizontalLayout({
        nodes: layoutNodes,
        edges,
        pxPerMinute,
        tzOffsetHours: timeline.timezoneOffsetHours,
        daysMeta: timeline.days,
        cardHeights: layoutCardHeights,
        ...(drag.activeId ? { excludeNodeId: drag.activeId } : {}),
      }),
    [
      layoutNodes,
      edges,
      pxPerMinute,
      timeline.timezoneOffsetHours,
      timeline.days,
      layoutCardHeights,
      drag.activeId,
    ],
  );

  const handleDragStart = useCallback((id: string) => {
    setDrag({ activeId: id, overDayKey: null, overMinute: null });
  }, []);

  const handleDragOver = useCallback((event: DragOverEvent) => {
    const overId = event.over?.id;
    const dayKey =
      typeof overId === "string" && overId.startsWith("day-")
        ? overId.slice(4)
        : null;
    setDrag((prev) =>
      prev.overDayKey === dayKey ? prev : { ...prev, overDayKey: dayKey },
    );
  }, []);

  // Latest pointer y inside the canvas body, in the layout's coordinate
  // system. We resolve it against `layout.segments` to find the minute-of-
  // day the user is hovering over.
  const dragSegmentsRef = useRef(layout.segments);
  dragSegmentsRef.current = layout.segments;
  useEffect(() => {
    if (!drag.activeId) return;
    const onMove = (e: PointerEvent) => {
      const body = bodyRef.current;
      if (!body) return;
      const rect = body.getBoundingClientRect();
      const y = e.clientY - rect.top;
      const rawMinute = mapYToMinute(y, dragSegmentsRef.current);
      // Snap the live preview to a 15-minute grid so the ghost doesn't jitter
      // and the dropped time is always a clean quarter-hour.
      const snapped = Math.round(rawMinute / 15) * 15;
      setDrag((prev) =>
        prev.overMinute === snapped ? prev : { ...prev, overMinute: snapped },
      );
    };
    window.addEventListener("pointermove", onMove);
    return () => window.removeEventListener("pointermove", onMove);
  }, [drag.activeId]);

  const handleDragEnd = useCallback(
    (event: DragEndEvent) => {
      const { active, over } = event;
      const snapshot = drag;
      setDrag({ activeId: null, overDayKey: null, overMinute: null });
      if (!over) return;
      const overId = String(over.id);
      if (!overId.startsWith("day-")) return;
      const targetDayKey = overId.slice(4);
      if (!targetDayKey) return;
      const minute = snapshot.overMinute;
      if (typeof minute === "number") {
        storeApi
          .getState()
          .moveNodeToDayAndMinute(String(active.id), targetDayKey, minute);
      } else {
        storeApi.getState().moveNodeToDay(String(active.id), targetDayKey);
      }
    },
    [drag, storeApi],
  );

  const handleDragCancel = useCallback(() => {
    setDrag({ activeId: null, overDayKey: null, overMinute: null });
  }, []);


  // Recompute whether scroll-hints should show based on the canvas's current
  // scrollLeft / clientWidth / scrollWidth. The 16px slop keeps hints from
  // flickering on/off when the viewport rests within a pixel of an edge.
  const updateScrollHints = useCallback(() => {
    const el = canvasScrollRef.current;
    if (!el) return;
    setScrollHints({
      left: el.scrollLeft > 16,
      right: el.scrollLeft + el.clientWidth < el.scrollWidth - 16,
    });
  }, []);

  // Mirror the canvas's vertical scroll into the axis container so labels and
  // sun gradient stay aligned with cards. Horizontal scroll on the canvas is
  // ignored by the axis (it sits outside the horizontal scroller) but does
  // drive the scroll-hint visibility.
  const onCanvasScroll = useCallback(
    (e: UIEvent<HTMLDivElement>) => {
      const top = e.currentTarget.scrollTop;
      if (axisScrollRef.current) axisScrollRef.current.scrollTop = top;
      updateScrollHints();
    },
    [updateScrollHints],
  );

  // Also re-check hints on layout changes (zoom or new proposals can grow the
  // canvas wider) and on viewport resize.
  useEffect(() => {
    updateScrollHints();
    const el = canvasScrollRef.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => updateScrollHints());
    ro.observe(el);
    return () => ro.disconnect();
  }, [updateScrollHints, layout.totalWidth]);

  const scrollHintBy = useCallback((dx: number) => {
    const el = canvasScrollRef.current;
    if (!el) return;
    el.scrollBy({ left: dx, behavior: "smooth" });
  }, []);

  // Auto-scroll horizontally to bring a freshly-arrived proposal into view.
  const prevPendingIds = useRef<Set<string>>(new Set());
  useEffect(() => {
    const currentIds = pendingProposals.map((p) => p.id);
    const newOnes = currentIds.filter((id) => !prevPendingIds.current.has(id));
    prevPendingIds.current = new Set(currentIds);
    if (newOnes.length === 0) return;
    const target = newOnes[newOnes.length - 1];
    if (!target) return;
    const t = setTimeout(() => scrollToNode(target), 120);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingProposals.length]);

  const scrollToNode = useCallback(
    (id: string) => {
      const container = canvasScrollRef.current;
      const pos = layout.positions.get(id);
      if (!container || !pos) return;
      // Center horizontally; place vertically about 30% from top. Card x
      // values are relative to the canvas inner content (which excludes the
      // axis gutter), so subtract TIME_GUTTER from layout.x.
      const targetX = pos.x - TIME_GUTTER - container.clientWidth * 0.4;
      const targetY = pos.y - container.clientHeight * 0.3;
      container.scrollTo({
        left: Math.max(0, targetX),
        top: Math.max(0, targetY),
        behavior: "smooth",
      });
    },
    [layout],
  );

  // Focused node → map focus + arc.
  const focusedNode: NodeResponse | null = useMemo(() => {
    if (!focusedNodeId) return null;
    return (
      nodes.find((n) => n.id === focusedNodeId) ??
      pendingProposals.find((n) => n.id === focusedNodeId) ??
      null
    );
  }, [focusedNodeId, nodes, pendingProposals]);

  const focusCoords = useMemo(() => {
    if (!focusedNode) return null;
    const loc = getHMeta(focusedNode).location;
    if (!loc) return null;
    const base = { lat: loc.lat, lng: loc.lng };
    return loc.label ? { ...base, label: loc.label } : base;
  }, [focusedNode]);

  const focusArc = useMemo(() => {
    if (!focusedNode) return null;
    if (focusedNode.type !== "flight" && focusedNode.type !== "transit")
      return null;
    const meta = getHMeta(focusedNode);
    let from = meta.from_location ?? null;
    const to = meta.to_location ?? (meta.location ? meta.location : null);
    if (!from) {
      const sorted = [...nodes].sort((a, b) => {
        const sa = new Date(getHMeta(a).start_time ?? "").getTime();
        const sb = new Date(getHMeta(b).start_time ?? "").getTime();
        return sa - sb;
      });
      const idx = sorted.findIndex((n) => n.id === focusedNode.id);
      for (let i = idx - 1; i >= 0; i--) {
        const prevNode = sorted[i];
        if (!prevNode) continue;
        const prev = getHMeta(prevNode);
        const prevLoc = prev.to_location ?? prev.location;
        if (prevLoc) {
          from = prevLoc;
          break;
        }
      }
    }
    if (!from || !to) return null;
    if (from.lat === to.lat && from.lng === to.lng) return null;
    return {
      from: [from.lng, from.lat] as [number, number],
      to: [to.lng, to.lat] as [number, number],
    };
  }, [focusedNode, nodes]);

  const handleRunScenario = useCallback(
    async (scenario: "propose" | "assemble" | "modify") => {
      await runScenario(scenario, { store: storeApi });
    },
    [storeApi],
  );

  const handleChatSubmit = useCallback(
    (text: string) => {
      void runScenario("freeform", { store: storeApi }, text);
    },
    [storeApi],
  );

  const expandedNode: NodeResponse | null = useMemo(() => {
    if (!expandedId) return null;
    return (
      nodes.find((n) => n.id === expandedId) ??
      pendingProposals.find((n) => n.id === expandedId) ??
      null
    );
  }, [expandedId, nodes, pendingProposals]);

  return (
    <DndContext
      sensors={sensors}
      collisionDetection={pointerWithin}
      onDragStart={(e) => handleDragStart(String(e.active.id))}
      onDragOver={handleDragOver}
      onDragEnd={handleDragEnd}
      onDragCancel={handleDragCancel}
    >
    <div className="flex h-screen w-screen flex-col bg-paper text-ink">
      <header className="z-30 flex flex-wrap items-center justify-between gap-3 border-b border-ink/10 bg-paper/85 px-4 py-2 backdrop-blur-sm">
        <div>
          <div className="text-[10px] uppercase tracking-[0.22em] text-ink/55">
            OV Black · Horizontal prototype
          </div>
          <div className="font-serif text-lg text-ink">
            {timeline.label}
            <span className="ml-2 text-[12px] italic text-ink/60">
              {timeline.subtitle}
            </span>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <AIDemoController onRun={handleRunScenario} />
          <ZoomControls />
        </div>
      </header>

      {/* md+ layout: axis (fixed left) + canvas (h+v scroll) + chat aside,
          all sitting above the bottom map strip. */}
      <div className="hidden min-h-0 flex-1 flex-col md:flex">
        <div className="flex min-h-0 flex-1">
          {/* Time axis. Width fixed, vertical overflow hidden — we drive
              scrollTop manually from the canvas scroll handler. The first
              DAY_HEADER_HEIGHT is a spacer that lines up with the canvas's
              sticky-top day-headers strip, so 09:00 in the axis sits at the
              same y as 09:00 in the cards. */}
          <div
            ref={axisScrollRef}
            className="shrink-0 overflow-hidden border-r border-ink/10 bg-paper/85 backdrop-blur-sm"
            style={{ width: TIME_GUTTER }}
          >
            <div
              style={{
                height: layout.totalHeight + DAY_HEADER_HEIGHT,
                paddingTop: DAY_HEADER_HEIGHT,
                position: "relative",
              }}
            >
              <TimeAxis
                segments={layout.segments}
                pxPerMinute={pxPerMinute}
                totalHeight={layout.totalHeight}
                timeMarkers={layout.timeMarkers}
                days={layout.days}
              />
            </div>
          </div>

          {/* Canvas: horizontally + vertically scrolling. Card x values from
              layout include the axis gutter, so the canvas subtracts it.
              Wrapped in a relative container so the scroll-hints can hover
              over the viewport's edges without scrolling along with the
              cards. */}
          <div className="relative flex min-w-0 flex-1">
            <div
              ref={canvasScrollRef}
              onScroll={onCanvasScroll}
              className="flex min-h-0 flex-1 overflow-x-auto overflow-y-auto"
            >
              <HorizontalCanvas
                layout={layout}
                pendingProposals={pendingProposals}
                flashNodeId={flashNodeId}
                focusedNodeId={focusedNodeId}
                tzOffsetHours={timeline.timezoneOffsetHours}
                axisWidth={TIME_GUTTER}
                activeDragId={drag.activeId}
                ghostId={ghostNode?.id ?? null}
                bodyRef={bodyRef}
                onCardHover={(id) => {
                  if (id && id !== storeApi.getState().focusedNodeId) {
                    storeApi.getState().focusNode(id);
                  }
                }}
                onCardClick={(id) => setExpandedId(id)}
                onAcceptProposal={(id) =>
                  storeApi.getState().acceptProposal(id)
                }
                onDismissProposal={(id) =>
                  storeApi.getState().dismissProposal(id)
                }
                onMeasureCard={handleMeasureCard}
                onScrollToNode={scrollToNode}
              />
            </div>
            <ScrollHint
              direction="left"
              visible={scrollHints.left}
              onClick={() => scrollHintBy(-SCROLL_HINT_STEP_PX)}
            />
            <ScrollHint
              direction="right"
              visible={scrollHints.right}
              onClick={() => scrollHintBy(SCROLL_HINT_STEP_PX)}
            />
          </div>

          {/* Chat panel — fixed width, doesn't scroll with the canvas. */}
          <aside className="hidden w-[440px] shrink-0 md:block">
            <ChatPanel
              messages={messages}
              pendingProposals={pendingProposals}
              onAccept={(id) => storeApi.getState().acceptProposal(id)}
              onDismiss={(id) => storeApi.getState().dismissProposal(id)}
              onSubmit={handleChatSubmit}
              onScrollToNode={scrollToNode}
            />
          </aside>
        </div>

        {/* Bottom map strip — full body width including under the chat
            aside. Anchored to the bottom of the body, doesn't scroll with
            anything above. */}
        <MapStrip focus={focusCoords} arc={focusArc} height={220} />
      </div>

      {/* Mobile fallback. */}
      <div className="flex flex-1 flex-col overflow-hidden md:hidden">
        <div className="flex-1 overflow-y-auto">
          <MobileDayList
            daysMeta={timeline.days}
            tzOffsetHours={timeline.timezoneOffsetHours}
            onCardClick={(id) => setExpandedId(id)}
          />
        </div>
        <MapStrip focus={focusCoords} arc={focusArc} height={180} />
      </div>

      <AnimatePresence>
        {expandedNode ? (
          <motion.div
            key="expand-backdrop"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 p-6 backdrop-blur-sm"
            onClick={() => setExpandedId(null)}
          >
            <motion.div
              className="w-full max-w-xl"
              onClick={(e) => e.stopPropagation()}
            >
              <Card node={expandedNode} mood={timeline.mood} />
            </motion.div>
          </motion.div>
        ) : null}
      </AnimatePresence>

      {/* DragOverlay portals a clone of the dragged card so it can follow the
          cursor without disturbing the canvas's absolute layout (which is busy
          opening up a ghost slot in the target day). */}
      <DragOverlay dropAnimation={null}>
        {activeNode ? (
          <div style={{ width: 260, cursor: "grabbing" }}>
            <JapanCard
              node={activeNode}
              tzOffsetHours={timeline.timezoneOffsetHours}
            />
          </div>
        ) : null}
      </DragOverlay>
    </div>
    </DndContext>
  );
}
