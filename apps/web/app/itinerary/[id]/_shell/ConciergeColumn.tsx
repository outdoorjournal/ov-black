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
// The context-chip strip belongs to Artemis (PS4's "ask about this").

import { useState } from "react";

import { itineraryGraphStore } from "@/app/_components/itinerary-graph/store/itineraryGraphStore";
import { useTimelineData } from "@/app/_components/itinerary-graph/TimelineDataContext";

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
  const clientId = timeline.itinerary.client_id;

  // Which people-circle is open: the AI session list, or the human channel (PS7).
  const [channel, setChannel] = useState<"artemis" | "human">("artemis");
  // Advisor-only: which Artemis audience (private workspace vs shared client thread).
  const [audience, setAudience] = useState<"advisor" | "traveler">("advisor");

  // PS4 "ask about this" scopes the concierge to a card; the next turn is
  // prefixed with it (see ConciergeChat) and then it clears.
  const askContext = itineraryGraphStore.useStore((s) => s.askContext);
  const setAskContext = itineraryGraphStore.useStore((s) => s.setAskContext);

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
      <div
        data-testid="people-circles"
        className="flex shrink-0 items-center gap-2 border-b border-ink/10 px-3 py-2"
      >
        <PersonCircle
          label="Artemis"
          active={channel === "artemis"}
          onSelect={() => setChannel("artemis")}
        />
        <PersonCircle
          label="Advisor"
          active={channel === "human"}
          onSelect={() => setChannel("human")}
          title={canEdit ? "The client conversation" : "Message your advisor & party"}
        />
        {onCollapse ? (
          <button
            type="button"
            onClick={onCollapse}
            data-testid="concierge-collapse"
            aria-label="Collapse the concierge"
            className="ml-auto hidden h-7 items-center rounded-md px-2 font-sans text-base text-ink/45 transition-colors hover:bg-ink/5 hover:text-ink min-[1100px]:flex"
          >
            ‹
          </button>
        ) : null}
      </div>

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
          {/* Context chip (PS4) — the card the concierge is scoped to. Sits above
              the thread so the next question reads as a reply about that card. */}
          {askContext ? (
            <div
              data-testid="concierge-context-chip"
              className="flex shrink-0 items-center gap-2 border-b border-ink/10 bg-[rgba(245,112,31,0.06)] px-3 py-2"
            >
              <span className="font-sans text-[10px] uppercase tracking-[0.16em] text-ink/45">
                Re:
              </span>
              <span className="min-w-0 flex-1 truncate font-serif text-[13px] text-ink">
                {askContext.title}
              </span>
              <button
                type="button"
                onClick={() => setAskContext(null)}
                data-testid="concierge-context-clear"
                aria-label="Clear card context"
                className="shrink-0 rounded px-1 font-sans text-sm text-ink/50 transition-colors hover:bg-ink/5 hover:text-ink"
              >
                ✕
              </button>
            </div>
          ) : null}

          {canEdit ? (
            <>
              <div
                data-testid="concierge-thread-tabs"
                role="tablist"
                className="flex shrink-0 gap-1 border-b border-ink/10 bg-paper/85 px-3 py-2 backdrop-blur-sm"
              >
                {(["advisor", "traveler"] as const).map((a) => (
                  <button
                    key={a}
                    type="button"
                    role="tab"
                    aria-selected={audience === a}
                    onClick={() => setAudience(a)}
                    data-testid={`concierge-tab-${a}`}
                    className={`h-8 rounded-md px-3 font-sans text-[11px] uppercase tracking-[0.16em] transition-colors ${
                      audience === a ? "bg-ink/10 text-ink" : "text-ink/55 hover:bg-ink/5"
                    }`}
                  >
                    {a === "advisor" ? "Concierge" : "Client thread"}
                  </button>
                ))}
              </div>
              {/* Both audiences stay mounted so a switch never drops a list/thread. */}
              <div className="relative min-h-0 flex-1">
                <div className={audience === "advisor" ? "h-full" : "hidden"}>
                  <SessionThread
                    audience="advisor"
                    clientId={clientId}
                    itineraryId={itineraryId}
                    apiBaseUrl={apiBaseUrl}
                    accessToken={accessToken}
                    intro="Private workspace — just you and the concierge. The traveler never sees this conversation."
                  />
                </div>
                <div className={audience === "traveler" ? "h-full" : "hidden"}>
                  <SessionThread
                    audience="traveler"
                    clientId={clientId}
                    itineraryId={itineraryId}
                    apiBaseUrl={apiBaseUrl}
                    accessToken={accessToken}
                    intro="The client conversation — what you send here is visible to the traveler."
                  />
                </div>
              </div>
            </>
          ) : (
            <div className="min-h-0 flex-1">
              <SessionThread
                audience="traveler"
                clientId={clientId}
                itineraryId={itineraryId}
                apiBaseUrl={apiBaseUrl}
                accessToken={accessToken}
              />
            </div>
          )}
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

function PersonCircle({
  label,
  active = false,
  onSelect,
  title,
}: {
  label: string;
  active?: boolean;
  onSelect?: () => void;
  title?: string;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      disabled={!onSelect}
      className="flex flex-col items-center gap-1"
      data-testid={`person-${label.toLowerCase()}`}
      data-active={active ? "true" : undefined}
      aria-pressed={active}
      {...(title ? { title } : {})}
    >
      <span
        aria-hidden
        className={
          "flex h-8 w-8 items-center justify-center rounded-full border font-serif text-sm transition-colors " +
          (active
            ? "border-ink/30 bg-ink/10 text-ink"
            : "border-ink/15 text-ink/40 hover:border-ink/25 hover:text-ink/60")
        }
      >
        {label.charAt(0)}
      </span>
      <span
        className={
          "font-sans text-[9px] uppercase tracking-[0.14em] " +
          (active ? "text-ink/70" : "text-ink/40")
        }
      >
        {label}
      </span>
    </button>
  );
}
