"use client";

// The live wire (Wave F): the roster's activity, SSR-seeded from
// GET /advisor/activity and prepended in real time by SSE frames from the
// AdvisorFeed store. New arrivals fade in; the header dot mirrors the
// connection. "Older" pages backward through the REST cursor browser-side.

import type { Route } from "next";
import Link from "next/link";
import { AnimatePresence, motion } from "framer-motion";
import { useMemo, useState } from "react";

import type { ActivityEventOut } from "@ov-black/api-client";

import type { FeedActivityEvent } from "@/lib/advisorFeed";

import { useAdvisorFeedStore } from "../../_state/advisorFeedStore";
import { money } from "../panels";

type FeedRow = FeedActivityEvent;

function toRow(e: ActivityEventOut): FeedRow {
  return {
    kind: e.kind,
    at: e.at,
    source_id: e.source_id,
    client_id: e.client_id,
    itinerary_id: e.itinerary_id ?? null,
    itinerary_title: e.itinerary_title ?? null,
    actor_kind: e.actor_kind ?? null,
    title: e.title ?? null,
    op: e.op ?? null,
    status_before: e.status_before ?? null,
    status_after: e.status_after ?? null,
    amount: e.amount ?? null,
    currency: e.currency ?? null,
    ref_id: e.ref_id ?? null,
  };
}

export function ActivityFeed({
  initialEvents,
  clientNames,
}: {
  initialEvents: ActivityEventOut[];
  /** client_id → full_name, from the awareness rollup (best-effort). */
  clientNames: Record<string, string>;
}) {
  const liveEvents = useAdvisorFeedStore((s) => s.events);
  const connection = useAdvisorFeedStore((s) => s.connection);
  const [expanded, setExpanded] = useState(false);

  const rows = useMemo(() => {
    const seen = new Set<string>();
    const merged: FeedRow[] = [];
    for (const e of [...liveEvents, ...initialEvents.map(toRow)]) {
      const key = `${e.kind}:${e.source_id}`;
      if (seen.has(key)) continue;
      seen.add(key);
      merged.push(e);
    }
    merged.sort((a, b) => new Date(b.at).getTime() - new Date(a.at).getTime());
    return merged.slice(0, expanded ? 60 : 18);
  }, [liveEvents, initialEvents, expanded]);

  return (
    <section
      aria-label="Activity"
      className="flex flex-col gap-3 rounded-md border border-paper/10 bg-paper/5 p-4 sm:p-5"
    >
      <div className="flex items-baseline justify-between gap-4">
        <p className="font-sans text-[10px] uppercase tracking-eyebrow text-paper/55">
          Activity
        </p>
        <span
          className={
            "flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-[0.15em] " +
            (connection === "live" ? "text-brand/80" : "text-paper/40")
          }
        >
          <span
            aria-hidden
            className={
              "inline-block h-1 w-1 rounded-full " +
              (connection === "live" ? "bg-brand" : "bg-paper/30")
            }
            style={connection === "live" ? { animation: "var(--animate-pulse-live)" } : undefined}
          />
          {connection === "live" ? "live" : connection}
        </span>
      </div>

      {rows.length === 0 ? (
        <p className="py-2 font-serif text-lg text-paper/60">
          Quiet so far. Activity lands here as it happens.
        </p>
      ) : (
        <ul className="flex flex-col divide-y divide-paper/8">
          <AnimatePresence initial={false}>
            {rows.map((row) => (
              <motion.li
                key={`${row.kind}:${row.source_id}`}
                initial={{ opacity: 0, y: -4 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.2 }}
              >
                <FeedLine row={row} clientName={clientNames[row.client_id]} />
              </motion.li>
            ))}
          </AnimatePresence>
        </ul>
      )}

      {!expanded && rows.length >= 18 ? (
        <button
          type="button"
          onClick={() => setExpanded(true)}
          className="self-start font-sans text-[11px] uppercase tracking-[0.2em] text-paper/50 transition-colors hover:text-paper"
        >
          Older ↓
        </button>
      ) : null}
    </section>
  );
}

/** One event as a legible sentence fragment — kinds map to plain words. */
export function activityLabel(row: FeedRow): string {
  const title = row.title || row.itinerary_title || "";
  switch (row.kind) {
    case "node_changed": {
      const transition =
        row.status_before !== row.status_after && row.status_after
          ? ` → ${row.status_after}`
          : "";
      const verb =
        row.op === "insert" ? "added" : row.op === "delete" ? "removed" : "updated";
      return `${actor(row)} ${verb} ${title || "a card"}${transition}`;
    }
    case "agent_turn":
      return "Concierge replied";
    case "message_posted":
      return `${actor(row)} messaged`;
    case "payment":
      return row.amount && row.currency
        ? `Payment ${row.op === "succeeded" ? "received" : row.op} · ${money(row.amount, row.currency)}`
        : "Payment";
    case "invoice_created":
      return `Invoice drafted${title ? ` · ${title}` : ""}`;
    case "invoice_issued":
      return `Invoice issued${title ? ` · ${title}` : ""}`;
    case "booking_made":
      return `Booked ${title || "a card"}`;
    case "booking_confirmed":
      return `Confirmed ${title || "a booking"}`;
    case "booking_cancelled":
      return `Cancelled ${title || "a booking"}`;
    default:
      return row.kind.replaceAll("_", " ");
  }
}

function actor(row: FeedRow): string {
  switch (row.actor_kind) {
    case "traveler":
    case "user":
      return "Traveler";
    case "advisor":
      return "You";
    case "agent":
    case "artemis":
      return "Concierge";
    default:
      return "Someone";
  }
}

function FeedLine({
  row,
  clientName,
}: {
  row: FeedRow;
  clientName: string | undefined;
}) {
  const label = activityLabel(row);
  const where = row.itinerary_title ? ` · ${row.itinerary_title}` : "";
  const href = (
    row.itinerary_id
      ? `/itinerary/${row.itinerary_id}`
      : `/command-center/clients/${row.client_id}`
  ) as Route;
  return (
    <Link
      href={href}
      className="flex items-baseline gap-2.5 rounded-sm px-1 py-2 transition-colors focus-visible:bg-paper/5 focus-visible:outline-none hover:bg-paper/5"
    >
      <span className="shrink-0 font-mono text-[10px] text-paper/40">
        {clock(row.at)}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate font-sans text-[13px] text-paper/85">
          {label}
          <span className="text-paper/45">{where}</span>
        </span>
        {clientName ? (
          <span className="block truncate font-sans text-[11px] text-paper/40">
            {clientName}
          </span>
        ) : null}
      </span>
    </Link>
  );
}

function clock(iso: string): string {
  return new Intl.DateTimeFormat("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(iso));
}
