"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";

import { Card } from "@/app/_components/itinerary-graph/shared/ExpandedCard";
import type { VerticalTimeline, NodeResponse } from "@/app/_components/itinerary-graph/model/types";
import { getVerticalMeta } from "@/app/_components/itinerary-graph/model/types";
import { computeVerticalLayout } from "../_state/layout";
import { runScenario } from "../_state/mockStream";
import { verticalStore } from "../_state/verticalStore";
import { AIDemoController } from "./AIDemoController";
import { AmbientBackdrop } from "./AmbientBackdrop";
import { ChatPanel } from "./ChatPanel";
import { TimeAxis } from "./TimeAxis";
import { TimelineColumn } from "./TimelineColumn";
import { ZoomControls } from "./ZoomControls";

interface VerticalShellProps {
  timeline: VerticalTimeline;
}

export function VerticalShell({ timeline }: VerticalShellProps) {
  return (
    <verticalStore.Provider initial={{ timeline }}>
      <VerticalShellInner timeline={timeline} />
    </verticalStore.Provider>
  );
}

function VerticalShellInner({ timeline }: VerticalShellProps) {
  const nodes = verticalStore.useStore((s) => s.nodes);
  const edges = verticalStore.useStore((s) => s.edges);
  const pendingProposals = verticalStore.useStore((s) => s.pendingProposals);
  const messages = verticalStore.useStore((s) => s.messages);
  const focusedNodeId = verticalStore.useStore((s) => s.focusedNodeId);
  const flashNodeId = verticalStore.useStore((s) => s.flashNodeId);
  const pxPerMinute = verticalStore.useStore((s) => s.pxPerMinute);
  const storeApi = verticalStore.useStoreApi();

  const scrollRef = useRef<HTMLDivElement>(null);
  const anchorRef = useRef<{ nodeId: string | null; offsetFromTop: number }>({
    nodeId: null,
    offsetFromTop: 0,
  });
  const [sweptIds, setSweptIds] = useState<Set<string>>(new Set());
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [cardHeights, setCardHeights] = useState<Map<string, number>>(
    () => new Map(),
  );

  // Keyboard shortcuts: ⌘+ / ⌘- / ⌘0 — bound here so they live alongside the
  // shell's lifecycle. Reads actions off the store at fire time, so the
  // handler stays stable across renders.
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

  const handleMeasureCard = useCallback((id: string, height: number) => {
    setCardHeights((prev) => {
      if (prev.get(id) === height) return prev;
      const next = new Map(prev);
      next.set(id, height);
      return next;
    });
  }, []);

  const layout = useMemo(
    () =>
      computeVerticalLayout({
        nodes: [...nodes, ...pendingProposals],
        edges,
        pxPerMinute,
        windowStart: timeline.windowStart,
        windowEnd: timeline.windowEnd,
        tzOffsetHours: timeline.timezoneOffsetHours,
        daysMeta: timeline.days,
        cardHeights,
      }),
    [nodes, pendingProposals, edges, pxPerMinute, timeline, cardHeights],
  );

  const scrollToNode = useCallback(
    (id: string, behavior: ScrollBehavior = "smooth") => {
      const container = scrollRef.current;
      const pos = layout.positions.get(id);
      if (!container || !pos) return;
      const target = pos.y - container.clientHeight * 0.3;
      container.scrollTo({ top: Math.max(0, target), behavior });
    },
    [layout],
  );

  // Auto-scroll the timeline to newly arrived proposals so the user sees
  // them land. The chat exposes a per-card "Show" button to jump back.
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
  }, [pendingProposals, scrollToNode]);

  // Auto-scroll on flash (UPDATE / ACCEPT) so swaps are visible.
  const prevFlashId = useRef<string | null>(null);
  useEffect(() => {
    if (!flashNodeId || flashNodeId === prevFlashId.current) return;
    prevFlashId.current = flashNodeId;
    const t = setTimeout(() => scrollToNode(flashNodeId), 80);
    return () => clearTimeout(t);
  }, [flashNodeId, scrollToNode]);

  // Scroll anchoring: before zoom changes, remember the card closest to center.
  const prevPxPerMinute = useRef(pxPerMinute);
  useEffect(() => {
    const container = scrollRef.current;
    if (!container) {
      prevPxPerMinute.current = pxPerMinute;
      return;
    }
    if (prevPxPerMinute.current === pxPerMinute) return;

    const anchor = anchorRef.current;
    if (anchor.nodeId) {
      const pos = layout.positions.get(anchor.nodeId);
      if (pos) {
        container.scrollTop = pos.y - anchor.offsetFromTop;
      }
    }
    prevPxPerMinute.current = pxPerMinute;
  }, [pxPerMinute, layout]);

  // Time-ordered list of focusable (non-night-bar) node ids — used by the
  // scroll handler to walk forward/back from the currently focused card.
  const sortedFocusableIds = useMemo(() => {
    return [...nodes]
      .filter((n) => {
        const p = layout.positions.get(n.id);
        return p && !p.nightBar;
      })
      .sort((a, b) => {
        const sa = new Date(getVerticalMeta(a).start_time ?? "").getTime();
        const sb = new Date(getVerticalMeta(b).start_time ?? "").getTime();
        return sa - sb;
      })
      .map((n) => n.id);
  }, [nodes, layout]);

  const lastScrollTopRef = useRef(0);

  const onScroll = useCallback(() => {
    const container = scrollRef.current;
    if (!container) return;
    const scrollTop = container.scrollTop;
    const delta = scrollTop - lastScrollTopRef.current;
    lastScrollTopRef.current = scrollTop;
    const viewportCenter = scrollTop + container.clientHeight / 2;

    let anchorId: string | null = null;
    let anchorDist = Infinity;
    for (const [id, p] of layout.positions.entries()) {
      if (p.nightBar) continue;
      const cardCenter = p.y + Math.min(p.cardH, p.barH) / 2;
      const d = Math.abs(cardCenter - viewportCenter);
      if (d < anchorDist) {
        anchorDist = d;
        anchorId = id;
      }
    }
    if (anchorId) {
      const pos = layout.positions.get(anchorId);
      if (pos) {
        anchorRef.current = {
          nodeId: anchorId,
          offsetFromTop: pos.y - container.scrollTop,
        };
      }
    }

    if (sortedFocusableIds.length === 0) return;

    const currentFocus = storeApi.getState().focusedNodeId;
    const currentIdx = currentFocus
      ? sortedFocusableIds.indexOf(currentFocus)
      : -1;

    if (Math.abs(delta) < 0.5 || currentIdx < 0) {
      if (anchorId && anchorId !== currentFocus) {
        storeApi.getState().focusNode(anchorId);
      }
      return;
    }
    const dir = delta > 0 ? 1 : -1;
    let idx = currentIdx;
    while (true) {
      const nextIdx = idx + dir;
      if (nextIdx < 0 || nextIdx >= sortedFocusableIds.length) break;
      const nextId = sortedFocusableIds[nextIdx];
      if (!nextId) break;
      const nextPos = layout.positions.get(nextId);
      if (!nextPos) break;
      const nextCenter = nextPos.y + Math.min(nextPos.cardH, nextPos.barH) / 2;
      if (dir > 0 ? nextCenter <= viewportCenter : nextCenter >= viewportCenter) {
        idx = nextIdx;
      } else {
        break;
      }
    }
    const nextFocusId = sortedFocusableIds[idx];
    if (nextFocusId && nextFocusId !== currentFocus) {
      storeApi.getState().focusNode(nextFocusId);
    }
  }, [layout, sortedFocusableIds, storeApi]);

  useEffect(() => {
    const container = scrollRef.current;
    if (!container) return;
    lastScrollTopRef.current = container.scrollTop;
    container.addEventListener("scroll", onScroll, { passive: true });
    return () => container.removeEventListener("scroll", onScroll);
  }, [onScroll]);

  // Focused node → ambient image + map coords.
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
    const loc = getVerticalMeta(focusedNode).location;
    if (!loc) return null;
    const base = { lat: loc.lat, lng: loc.lng };
    return loc.label ? { ...base, label: loc.label } : base;
  }, [focusedNode]);

  // For travel cards (flights, transit), compute the great-circle endpoints.
  // Flights typically carry explicit from/to in metadata; trains/transit
  // inherit "from" from the previous node's location (sorted by start_time).
  const focusArc = useMemo(() => {
    if (!focusedNode) return null;
    if (focusedNode.type !== "flight" && focusedNode.type !== "transit")
      return null;
    const meta = getVerticalMeta(focusedNode);
    let from = meta.from_location ?? null;
    const to =
      meta.to_location ?? (meta.location ? meta.location : null);
    if (!from) {
      const sorted = [...nodes].sort((a, b) => {
        const sa = new Date(getVerticalMeta(a).start_time ?? "").getTime();
        const sb = new Date(getVerticalMeta(b).start_time ?? "").getTime();
        return sa - sb;
      });
      const idx = sorted.findIndex((n) => n.id === focusedNode.id);
      for (let i = idx - 1; i >= 0; i--) {
        const prevNode = sorted[i];
        if (!prevNode) continue;
        const prev = getVerticalMeta(prevNode);
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

  // Preload images so hover cross-fades are smooth.
  useEffect(() => {
    if (typeof window === "undefined") return;
    const urls = new Set<string>();
    for (const n of timeline.nodes) {
      const m = getVerticalMeta(n);
      if (m.ambient_image) urls.add(m.ambient_image);
    }
    for (const u of urls) {
      const img = new Image();
      img.src = u;
    }
  }, [timeline.nodes]);

  const handleRunScenario = useCallback(
    async (scenario: "propose" | "assemble" | "modify") => {
      await runScenario(scenario, {
        store: storeApi,
        onAssembleSweep: (ids) => {
          ids.forEach((id, i) => {
            setTimeout(() => {
              setSweptIds((s) => {
                const next = new Set(s);
                next.add(id);
                return next;
              });
            }, i * 60);
            setTimeout(() => {
              setSweptIds((s) => {
                const next = new Set(s);
                next.delete(id);
                return next;
              });
            }, i * 60 + 900);
          });
        },
      });
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

  // Esc closes the expanded card.
  useEffect(() => {
    if (!expandedId) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setExpandedId(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [expandedId]);

  const dayLayouts = layout.days.map((d) => {
    const dayMeta = timeline.days.find((dm) => dm.date === d.date);
    return dayMeta?.weather_emoji
      ? { ...d, label: dayMeta.label, weather_emoji: dayMeta.weather_emoji }
      : { ...d, label: dayMeta?.label ?? d.date };
  });

  return (
    <div
      className="relative flex h-screen w-screen flex-col bg-paper text-ink"
      style={{ isolation: "isolate" }}
    >
      <AmbientBackdrop focus={focusCoords} arc={focusArc} />

      <header className="relative z-20 flex items-center justify-between gap-4 border-b border-ink/10 bg-paper/80 px-4 py-2 backdrop-blur-sm">
        <div>
          <div className="text-[10px] uppercase tracking-[0.22em] text-ink/55">
            OV Black · Vertical prototype
          </div>
          <div className="font-serif text-lg text-ink">
            {timeline.label}
            <span className="ml-2 text-[12px] italic text-ink/60">
              {timeline.subtitle}
            </span>
          </div>
        </div>
        <div className="flex items-center gap-4">
          <AIDemoController onRun={handleRunScenario} />
          <ZoomControls />
        </div>
      </header>

      <div className="relative z-10 flex min-h-0 flex-1">
        <div
          ref={scrollRef}
          className="flex min-h-0 flex-1 overflow-y-auto overflow-x-auto"
        >
          <div
            className="flex min-w-max"
            style={{ minHeight: layout.totalHeight }}
          >
            <TimeAxis
              days={dayLayouts}
              segments={layout.segments}
              pxPerMinute={pxPerMinute}
              totalHeight={layout.totalHeight}
              timeMarkers={layout.timeMarkers}
            />
            <TimelineColumn
              layout={layout}
              mood={timeline.mood}
              pendingProposals={pendingProposals}
              flashNodeId={flashNodeId}
              sweptIds={sweptIds}
              expandedId={expandedId}
              focusedNodeId={focusedNodeId}
              onHoverNode={(id) => {
                if (id && id !== storeApi.getState().focusedNodeId) {
                  storeApi.getState().focusNode(id);
                }
              }}
              onClickNode={(id) => setExpandedId(id)}
              onAcceptProposal={(id) => storeApi.getState().acceptProposal(id)}
              onDismissProposal={(id) => storeApi.getState().dismissProposal(id)}
              onMeasureCard={handleMeasureCard}
            />
          </div>
        </div>
        <aside className="hidden w-[380px] shrink-0 md:block">
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
              layoutId={`card-${expandedNode.id}`}
              className="w-full max-w-xl"
              onClick={(e) => e.stopPropagation()}
            >
              <Card node={expandedNode} mood={timeline.mood} />
            </motion.div>
          </motion.div>
        ) : null}
      </AnimatePresence>
    </div>
  );
}
