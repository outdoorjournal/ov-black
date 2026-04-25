"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { NodeDetailSheet } from "../../itinerary-graph/_components/NodeDetailSheet";
import type { VerticalTimeline, NodeResponse } from "../_lib/types";
import { getVerticalMeta } from "../_lib/types";
import { computeVerticalLayout } from "../_state/layout";
import { useZoom } from "../_state/zoom";
import { runScenario } from "../_state/mockStream";
import { useVerticalTimelineState } from "../_state/useTimelineState";
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
  const { state, dispatch } = useVerticalTimelineState(timeline);
  const zoom = useZoom();
  const scrollRef = useRef<HTMLDivElement>(null);
  const anchorRef = useRef<{ nodeId: string | null; offsetFromTop: number }>({
    nodeId: null,
    offsetFromTop: 0,
  });
  const [sweptIds, setSweptIds] = useState<Set<string>>(new Set());
  const [detailId, setDetailId] = useState<string | null>(null);

  const layout = useMemo(
    () =>
      computeVerticalLayout({
        nodes: [...state.nodes, ...state.pendingProposals],
        edges: state.edges,
        pxPerMinute: zoom.pxPerMinute,
        windowStart: timeline.windowStart,
        windowEnd: timeline.windowEnd,
        tzOffsetHours: timeline.timezoneOffsetHours,
        daysMeta: timeline.days,
      }),
    [
      state.nodes,
      state.pendingProposals,
      state.edges,
      zoom.pxPerMinute,
      timeline,
    ],
  );

  // Scroll anchoring: before zoom changes, remember the card closest to center.
  const prevPxPerMinute = useRef(zoom.pxPerMinute);
  useEffect(() => {
    const container = scrollRef.current;
    if (!container) {
      prevPxPerMinute.current = zoom.pxPerMinute;
      return;
    }
    if (prevPxPerMinute.current === zoom.pxPerMinute) return;

    const anchor = anchorRef.current;
    if (anchor.nodeId) {
      const pos = layout.positions.get(anchor.nodeId);
      if (pos) {
        container.scrollTop = pos.y - anchor.offsetFromTop;
      }
    }
    prevPxPerMinute.current = zoom.pxPerMinute;
  }, [zoom.pxPerMinute, layout]);

  // Track the closest node to viewport center on scroll (used both for anchor and focus).
  const recomputeCenterAnchor = useCallback(() => {
    const container = scrollRef.current;
    if (!container) return;
    const viewportCenter = container.scrollTop + container.clientHeight / 2;
    let bestId: string | null = null;
    let bestDist = Infinity;
    for (const [id, p] of layout.positions.entries()) {
      if (p.nightBar) continue;
      const cardCenter = p.y + Math.min(p.cardH, p.barH) / 2;
      const dist = Math.abs(cardCenter - viewportCenter);
      if (dist < bestDist) {
        bestDist = dist;
        bestId = id;
      }
    }
    if (bestId) {
      const pos = layout.positions.get(bestId);
      if (pos) {
        anchorRef.current = {
          nodeId: bestId,
          offsetFromTop: pos.y - container.scrollTop,
        };
      }
      // Drive ambient focus from scroll: whichever card is closest to center
      // becomes the selected node and powers the map / image.
      if (bestId !== state.focusedNodeId) {
        dispatch({ type: "FOCUS_NODE", id: bestId });
      }
    }
  }, [layout, state.focusedNodeId, dispatch]);

  useEffect(() => {
    const container = scrollRef.current;
    if (!container) return;
    const onScroll = () => recomputeCenterAnchor();
    container.addEventListener("scroll", onScroll, { passive: true });
    recomputeCenterAnchor();
    return () => container.removeEventListener("scroll", onScroll);
  }, [recomputeCenterAnchor]);

  // Focused node → ambient image + map coords.
  const focusedNode: NodeResponse | null = useMemo(() => {
    if (!state.focusedNodeId) return null;
    return (
      state.nodes.find((n) => n.id === state.focusedNodeId) ??
      state.pendingProposals.find((n) => n.id === state.focusedNodeId) ??
      null
    );
  }, [state.focusedNodeId, state.nodes, state.pendingProposals]);

  const ambientImage = useMemo(() => {
    if (!focusedNode) return null;
    const m = getVerticalMeta(focusedNode);
    if (m.ambient_image) return m.ambient_image;
    const snap = m.snapshot;
    if (snap && typeof snap.cover_image === "string") return snap.cover_image;
    return null;
  }, [focusedNode]);

  const focusCoords = useMemo(() => {
    if (!focusedNode) return null;
    const loc = getVerticalMeta(focusedNode).location;
    if (!loc) return null;
    const base = { lat: loc.lat, lng: loc.lng };
    return loc.label ? { ...base, label: loc.label } : base;
  }, [focusedNode]);

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
        state,
        dispatch,
        onAssembleSweep: (ids) => {
          // Sweep cards in order with staggered flashes.
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
    [state, dispatch],
  );

  const handleChatSubmit = useCallback(
    (text: string) => {
      void runScenario("freeform", { state, dispatch }, text);
    },
    [state, dispatch],
  );

  const subNodes = useMemo(() => {
    if (!detailId) return [];
    return state.nodes.filter((n) => n.parent_subgraph_id === detailId);
  }, [detailId, state.nodes]);

  const detailNode = detailId
    ? state.nodes.find((n) => n.id === detailId) ?? null
    : null;

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
      <AmbientBackdrop imageSrc={ambientImage} focus={focusCoords} />

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
          <ZoomControls {...zoom} />
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
              pxPerMinute={zoom.pxPerMinute}
              totalHeight={layout.totalHeight}
            />
            <TimelineColumn
              layout={layout}
              mood={timeline.mood}
              tzOffsetHours={timeline.timezoneOffsetHours}
              pendingProposals={state.pendingProposals}
              flashNodeId={state.flashNodeId}
              sweptIds={sweptIds}
              onHoverNode={() => {
                /* hover no longer drives focus — scroll position does */
              }}
              onClickNode={(id) => setDetailId(id)}
              onAcceptProposal={(id) =>
                dispatch({ type: "ACCEPT_PROPOSAL", id })
              }
              onDismissProposal={(id) =>
                dispatch({ type: "DISMISS_PROPOSAL", id })
              }
            />
          </div>
        </div>
        <aside className="hidden w-[380px] shrink-0 md:block">
          <ChatPanel
            messages={state.messages}
            pendingProposals={state.pendingProposals}
            onAccept={(id) => dispatch({ type: "ACCEPT_PROPOSAL", id })}
            onDismiss={(id) => dispatch({ type: "DISMISS_PROPOSAL", id })}
            onSubmit={handleChatSubmit}
          />
        </aside>
      </div>

      <NodeDetailSheet
        node={detailNode}
        mood={timeline.mood}
        subNodes={subNodes}
        onClose={() => setDetailId(null)}
      />
    </div>
  );
}
