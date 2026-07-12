"use client";

// The people axis (M006/PS1 → PS7) — the persistent concierge. PS1 lifted it out
// of the canvas so it survives navigation; PS2 turns each Artemis audience into a
// scoped session LIST (browse / resume / new / rename / archive); PS7 wires the
// "Advisor" people-circle to the real HUMAN channel (traveler ↔ advisor ↔ party,
// no agent turn).
//
// People circles across the top are the channel switch: Artemis (the AI session
// list) and Advisor (the human channel). Both bodies persist — the Artemis body
// stays mounted (it holds live streams + both audience sub-threads); the human
// body mounts on demand (it has no stream, so a re-load on entry is correct).
// The concierge learns which card is on screen silently (the Journal's focused
// card rides along on each turn), so there's no manual "ask about this" scope.

import { useEffect, useRef, useState } from "react";

import { itineraryGraphStore } from "@/app/_components/itinerary-graph/store/itineraryGraphStore";
import { useTimelineData } from "@/app/_components/itinerary-graph/TimelineDataContext";
import { PeopleCircles } from "@/app/_components/concierge/PeopleCircles";

import { useConciergeControl } from "./ConciergeControl";
import { HumanThread } from "./HumanThread";
import { SessionThread } from "./SessionThread";

export function ConciergeColumn({
  onClose,
  onCollapse,
}: {
  /** Close the <1100px summoned overlay. */
  onClose: () => void;
  /** Collapse the ≥1100px in-flow column to the edge tab (Q5). */
  onCollapse?: () => void;
}) {
  const { timeline } = useTimelineData();
  const canEdit = itineraryGraphStore.useStore((s) => s.canEdit);
  const apiBaseUrl = itineraryGraphStore.useStore((s) => s.apiBaseUrl);
  const accessToken = itineraryGraphStore.useStore((s) => s.accessToken);
  const itineraryId = itineraryGraphStore.useStore((s) => s.itineraryId);
  const nodeCount = itineraryGraphStore.useStore((s) => s.nodes.length);
  const clientId = timeline.itinerary.client_id;

  // Campaign dashboard auto-kickoff: on the traveler's OWN campaign trip whose
  // skeleton hasn't been built yet, the agent speaks first and lays it out. The
  // spine-build is what fills the graph, so an empty graph is the once-only
  // trigger (the kickoff endpoint is idempotent as a backstop).
  const autoKickoff =
    !canEdit && Boolean(timeline.itinerary.campaign_id) && nodeCount === 0;

  // Which people-circle is open: the AI session list, or the human channel (PS7).
  const [channel, setChannel] = useState<"artemis" | "human">("artemis");

  // A summon (openConcierge) bumps `nudge`. When it changes we snap to the
  // Artemis channel and wave an orange flag on its circle — the one-shot cue
  // that lands even when the panel was already open. The ref seeds from the
  // current value so a fresh mount (e.g. the <1100px overlay) doesn't self-fire.
  const { nudge } = useConciergeControl();
  const [artemisPulse, setArtemisPulse] = useState(false);
  const seenNudge = useRef(nudge);
  useEffect(() => {
    if (nudge === seenNudge.current) return;
    seenNudge.current = nudge;
    setChannel("artemis");
    setArtemisPulse(true);
    const t = setTimeout(() => setArtemisPulse(false), 1400);
    return () => clearTimeout(t);
  }, [nudge]);

  return (
    <div data-testid="concierge" className="flex min-h-0 flex-1 flex-col">
      {/* Overlay chrome — only when the column is a summoned overlay (<1100px). */}
      <div className="flex shrink-0 items-center justify-between border-b border-ink/10 px-3 py-2 min-[1100px]:hidden">
        <span className="text-[10px] uppercase tracking-[0.22em] text-ink/55">
          Concierge
        </span>
        <button
          type="button"
          onClick={onClose}
          data-testid="concierge-close"
          className="h-7 rounded-md px-2 font-sans text-[11px] uppercase tracking-[0.16em] text-ink/55 transition-colors hover:bg-ink/5 hover:text-ink"
        >
          Close
        </button>
      </div>

      {/* People circles — the channel switch (Artemis session list ↔ human chat). */}
      <PeopleCircles
        channel={channel}
        onSelect={setChannel}
        artemisPulse={artemisPulse}
        humanLabel={canEdit ? "Client" : "Advisor"}
        advisorTitle={canEdit ? "The client conversation" : "Message your advisor & party"}
        trailing={
          onCollapse ? (
            <button
              type="button"
              onClick={onCollapse}
              data-testid="concierge-collapse"
              aria-label="Collapse the concierge"
              className="ml-auto hidden h-7 items-center rounded-md px-2 font-sans text-base text-ink/45 transition-colors hover:bg-ink/5 hover:text-ink min-[1100px]:flex"
            >
              ‹
            </button>
          ) : null
        }
      />

      {/* The two channel bodies share the remaining space. Artemis stays mounted
          (live streams + both audience sub-threads); the human body mounts on
          demand (no stream — a re-load on entry is the right behaviour). */}
      <div className="relative min-h-0 flex-1">
        {/* ── Artemis channel ── */}
        <div
          className={
            channel === "artemis" ? "absolute inset-0 flex flex-col" : "hidden"
          }
        >
          {/* Artemis is one conversation per viewer: the advisor's PRIVATE
              workspace (the traveler never sees it), or the traveler's own shared
              thread. The client-facing conversation for an advisor is the human
              "Client" people-circle, not a second AI tab — so there's no
              private/shared audience switch here anymore, just the two circles. */}
          <div className="min-h-0 flex-1">
            <SessionThread
              audience={canEdit ? "advisor" : "traveler"}
              clientId={clientId}
              itineraryId={itineraryId}
              apiBaseUrl={apiBaseUrl}
              accessToken={accessToken}
              autoKickoff={autoKickoff}
              {...(canEdit
                ? {
                    intro:
                      "Private workspace — just you and the concierge. The traveler never sees this conversation.",
                  }
                : {})}
            />
          </div>
        </div>

        {/* ── Human channel (PS7) — mounted on demand ── */}
        {channel === "human" ? (
          <div className="absolute inset-0 flex flex-col">
            <HumanThread
              clientId={clientId}
              itineraryId={itineraryId}
              apiBaseUrl={apiBaseUrl}
              accessToken={accessToken}
              viewerKind={canEdit ? "advisor" : "traveler"}
            />
          </div>
        ) : null}
      </div>
    </div>
  );
}
