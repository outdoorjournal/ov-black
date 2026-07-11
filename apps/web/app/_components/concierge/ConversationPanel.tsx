"use client";

// The one concierge conversation surface, shared by every chat window so the
// advisor's trip-view concierge and the traveler's basecamp rail look and behave
// the same (M006/PS7 finish: unify the message rendering, not just the chrome).
//
// It renders the canonical "bubble" look lifted from the itinerary ChatPanel —
// ink user bubbles on the right, paper assistant bubbles on the left, an inline
// proposed-card stub, and a single-line composer. Callers normalise their own
// turn model into `ConversationMessage[]`; itinerary-specific extras (proposed
// cards, "show on timeline") are optional, so a surface with none just omits
// them.

import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useRef, useState } from "react";

import { MapCompassIndicator } from "@/app/_components/MapCompassIndicator";
import { CRAFTED_FALLBACK_COPY } from "@/app/chat/[client_id]/_components/ConversationStream";
import { OnboardingMilestoneCard } from "@/app/chat/[client_id]/_components/OnboardingMilestoneCard";
import { ProseMessage } from "@/app/chat/[client_id]/_components/ProseMessage";
import { AutoGrowTextarea } from "@/components/ui/auto-grow-textarea";
import { ScrollControls } from "@/components/ui/scroll-controls";
import { useSentHistory } from "@/lib/useSentHistory";

// A single conversation row. `role` is the union across every surface: the
// itinerary concierge only ever produces user/assistant/system; basecamp adds
// the client-synthesized `milestone` card and the `error` fallback row. `tool`
// rows are agent plumbing — rendered quietly, kept in the DOM for parity.
export type ConversationRole =
  "user" | "assistant" | "system" | "tool" | "error" | "milestone";

export type ConversationMessage = {
  id: string;
  role: ConversationRole;
  text: string;
  streaming?: boolean;
};

// A proposed graph node awaiting accept/dismiss. A structural subset of the
// itinerary NodeResponse, so the itinerary surface passes its rows straight in;
// surfaces without proposals omit the prop. `metadata` is the node's card-attrs
// dict (present on real graph proposals) — it lets a typed proposal (a flight)
// render as its own card instead of a bare title.
export type ConversationProposal = {
  id: string;
  type: string;
  title: string;
  metadata?: { [key: string]: unknown };
};

export interface ConversationPanelProps {
  messages: ConversationMessage[];
  onSubmit: (text: string) => void;
  proposals?: ConversationProposal[];
  onAccept?: (id: string) => void;
  onDismiss?: (id: string) => void;
  onScrollToNode?: (id: string) => void;
  // Fully inert: no chat context (missing token/client). The input is disabled
  // and nothing can be sent.
  disabled?: boolean;
  // A turn is streaming. Blocks a new submit and dims Send, but keeps the input
  // ENABLED so it never loses focus. A `disabled` input is blurred by the
  // browser the instant a turn starts and never regains focus on re-enable —
  // which is why the composer used to drop focus after every message.
  sending?: boolean;
  // Hide the panel's own "Concierge" header — used when a host already provides
  // one (the mobile bottom sheet's drag handle, or basecamp's people-circles).
  hideHeader?: boolean;
  // Composer placeholder — differs per surface ("Ask me to propose…" for the
  // advisor, "Write to your concierge" for the traveler).
  placeholder?: string;
  // The concierge is off calling tools (anonymous `activity` pulse) — the
  // streaming bubble shows the map-fold indicator instead of the text caret.
  working?: boolean;
}

export function ConversationPanel({
  messages,
  onSubmit,
  proposals = [],
  onAccept,
  onDismiss,
  onScrollToNode,
  disabled = false,
  sending = false,
  hideHeader = false,
  placeholder = "Ask me to propose, assemble, or swap…",
  working = false,
}: ConversationPanelProps) {
  const [text, setText] = useState("");
  const history = useSentHistory(setText);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, proposals.length]);

  const submitText = () => {
    const trimmed = text.trim();
    if (!trimmed || disabled || sending) return;
    onSubmit(trimmed);
    history.record(trimmed);
    setText("");
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    submitText();
  };

  return (
    <div
      data-testid="conversation-panel"
      className="relative z-20 flex h-full min-h-0 flex-col bg-paper/80 backdrop-blur-md"
    >
      {hideHeader ? null : (
        <div className="border-b border-ink/10 px-4 py-2.5">
          <div className="text-[10px] uppercase tracking-[0.24em] text-ink/55">
            Concierge
          </div>
          <div className="font-serif text-lg text-ink">Conversation</div>
        </div>
      )}
      {/* Relative viewport wrapper so the scroll jump-buttons pin to the scroll
          area (not the composer below). min-h-0 lets it shrink below its content
          so overflow-y-auto actually scrolls, instead of growing past the panel. */}
      <div className="relative flex min-h-0 flex-1 flex-col">
        <div
          ref={scrollRef}
          className="min-h-0 flex-1 space-y-3 overflow-y-auto px-4 py-3 bg-white"
        >
          <AnimatePresence initial={false}>
            {messages.map((m) => (
              <MessageBubble key={m.id} message={m} working={working} />
            ))}
            {proposals.map((p) => (
              <motion.div
                key={`inline-${p.id}`}
                initial={{ opacity: 0, y: 6 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -6 }}
                className="rounded-md border border-dashed border-ink/25 bg-paper p-2.5 text-[12px]"
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="text-[10px] uppercase tracking-[0.18em] text-ink/55">
                    Proposed · {p.type}
                  </div>
                  {onScrollToNode ? (
                    <button
                      type="button"
                      onClick={() => onScrollToNode(p.id)}
                      title="Show on timeline"
                      aria-label="Show on timeline"
                      className="shrink-0 rounded-md border border-ink/15 px-1.5 py-0.5 text-[10px] uppercase tracking-[0.18em] text-ink/65 hover:border-ink/40 hover:text-ink"
                    >
                      Show ↗
                    </button>
                  ) : null}
                </div>
                {/* A typed proposal renders as its own card; everything else keeps
                  the bare title. Flights read their FlightCardAttrs metadata. */}
                {p.type === "flight" && p.metadata ? (
                  <FlightProposalBody meta={p.metadata} />
                ) : (
                  <div className="mt-0.5 font-serif text-[15px] text-ink">
                    {p.title}
                  </div>
                )}
                <div className="mt-2 flex gap-1.5">
                  <button
                    type="button"
                    onClick={() => onAccept?.(p.id)}
                    className="rounded-md bg-ink px-2 py-1 text-[10px] uppercase tracking-[0.18em] text-paper"
                  >
                    Accept
                  </button>
                  <button
                    type="button"
                    onClick={() => onDismiss?.(p.id)}
                    className="rounded-md border border-ink/20 px-2 py-1 text-[10px] uppercase tracking-[0.18em] text-ink/70"
                  >
                    Dismiss
                  </button>
                </div>
              </motion.div>
            ))}
          </AnimatePresence>
        </div>
        <ScrollControls targetRef={scrollRef} />
      </div>
      <form
        onSubmit={handleSubmit}
        className="flex items-end gap-2 border-t border-ink/10 px-3 py-2"
      >
        <AutoGrowTextarea
          className="min-w-0 flex-1 rounded-md border border-ink/15 bg-paper/90 px-3 py-2 text-[13px] outline-hidden focus:border-ink/40"
          maxHeightPx={160}
          placeholder={placeholder}
          value={text}
          onValueChange={history.onValueChange}
          onKeyDown={history.onKeyDown}
          onSubmit={submitText}
          disabled={disabled}
        />
        <button
          type="submit"
          disabled={disabled || sending || text.trim().length === 0}
          className="rounded-md bg-ink px-3 py-2 text-[11px] uppercase tracking-[0.18em] text-paper disabled:opacity-40"
        >
          Send
        </button>
      </form>
    </div>
  );
}

// ── Flight proposal card ──────────────────────────────────────────────────────
// A compact boarding-pass read of a proposed flight so the concierge's flight
// proposals render as a real flight card (route + wall-clock + cabin) instead of
// a bare title. Reads the node's FlightCardAttrs metadata directly; each end
// shows its OWN airport-local wall clock straight off the ISO string's embedded
// offset (a leg crosses zones), with no viewer-tz round-trip. Price isn't in the
// card frame, so it's intentionally omitted here.
const MONTHS = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
];

function asStr(v: unknown): string | null {
  return typeof v === "string" && v.length > 0 ? v : null;
}

// Strip a trailing " (IATA)" parenthetical so the city reads cleanly under its
// code, then return it (or null when there's nothing worth showing).
function cityLabel(v: unknown): string | null {
  if (!v || typeof v !== "object" || !("label" in v)) return null;
  const s = asStr((v as { label?: unknown }).label);
  return s ? s.replace(/\s*\([^)]*\)\s*$/, "").trim() || null : null;
}

function wallClock(iso: unknown): { day: string; time: string } | null {
  const s = asStr(iso);
  const m = s ? /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(s) : null;
  if (!m) return null;
  return {
    day: `${MONTHS[Number(m[2]) - 1]} ${Number(m[3])}`,
    time: `${m[4]}:${m[5]}`,
  };
}

function cabinLabel(v: unknown): string | null {
  const s = asStr(v);
  if (!s) return null;
  const words = s.replace(/_/g, " ").trim();
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : null;
}

function FlightProposalBody({ meta }: { meta: { [key: string]: unknown } }) {
  const from = asStr(meta["iata_from"]) ?? "—";
  const to = asStr(meta["iata_to"]) ?? "—";
  const fromCity = cityLabel(meta["from_location"]);
  const toCity = cityLabel(meta["to_location"]);
  const depart = wallClock(meta["depart_at"]);
  const arrive = wallClock(meta["arrive_at"]);
  const cabin = cabinLabel(meta["cabin"]);

  return (
    <div className="mt-1.5">
      <div className="flex items-baseline justify-between gap-3">
        <div className="min-w-0">
          <div className="font-serif text-[17px] leading-none text-ink">
            {from}
          </div>
          {fromCity ? (
            <div className="mt-0.5 truncate text-[10px] text-ink/55">
              {fromCity}
            </div>
          ) : null}
        </div>
        <div className="shrink-0 translate-y-px text-[12px] text-ink/40">✈</div>
        <div className="min-w-0 text-right">
          <div className="font-serif text-[17px] leading-none text-ink">
            {to}
          </div>
          {toCity ? (
            <div className="mt-0.5 truncate text-[10px] text-ink/55">
              {toCity}
            </div>
          ) : null}
        </div>
      </div>
      {depart || arrive ? (
        <div className="mt-1.5 flex items-baseline justify-between gap-3 text-[11px] text-ink/70">
          <span>{depart ? `${depart.day} · ${depart.time}` : "—"}</span>
          <span>{arrive ? `${arrive.day} · ${arrive.time}` : ""}</span>
        </div>
      ) : null}
      {cabin ? (
        <div className="mt-1.5 inline-block rounded-full border border-ink/15 px-2 py-0.5 text-[9px] uppercase tracking-[0.16em] text-ink/60">
          {cabin}
        </div>
      ) : null}
    </div>
  );
}

function MessageBubble({
  message,
  working = false,
}: {
  message: ConversationMessage;
  working?: boolean;
}) {
  // The client-synthesized onboarding celebration — a card, not a bubble.
  if (message.role === "milestone") {
    return <OnboardingMilestoneCard />;
  }

  // The D015 fallback row: render the crafted copy, never the raw reason code.
  if (message.role === "error") {
    return (
      <div
        data-role="error"
        className="font-sans text-[12px] leading-relaxed text-ink/70"
      >
        {CRAFTED_FALLBACK_COPY}
      </div>
    );
  }

  if (message.role === "system") {
    return (
      <div className="rounded-md border border-dashed border-ink/15 bg-paper/60 px-3 py-2 text-[11px] italic text-ink/60">
        {message.text}
      </div>
    );
  }

  // `tool` rows are agent plumbing — kept quiet, mirroring the craft shell.
  if (message.role === "tool") {
    return (
      <div className="font-sans text-[10px] uppercase tracking-[0.2em] text-ink/40">
        {message.text}
      </div>
    );
  }

  const isUser = message.role === "user";
  return (
    <motion.div
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      data-role={message.role}
      data-streaming={message.streaming ? "true" : undefined}
      className={[
        "max-w-[86%] rounded-lg px-3 py-2 text-[13px] leading-relaxed",
        isUser ? "ml-auto bg-ink text-paper" : "bg-ink/5 text-ink",
      ].join(" ")}
    >
      {/* User bubbles stay literal (they typed it); the concierge's replies
          render as markdown + embeds. */}
      {isUser ? message.text : <ProseMessage content={message.text} />}
      {message.streaming ? (
        working ? (
          <span className={message.text ? "mt-1 block" : "block"}>
            <MapCompassIndicator />
          </span>
        ) : (
          <span className="ml-0.5 inline-block h-3 w-[6px] translate-y-px bg-current align-middle opacity-70" />
        )
      ) : null}
    </motion.div>
  );
}
