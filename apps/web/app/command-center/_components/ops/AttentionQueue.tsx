// The mission-control queue (Wave F): what's waiting on the advisor, ranked
// by overdue-ness, each row deep-linking to where the work happens. Server-
// rendered from the awareness rollup — the live feed's throttled
// router.refresh() keeps it honest without client state.

import type { Route } from "next";
import Link from "next/link";

import type { ClientAttentionOut } from "@ov-black/api-client";

import { attentionLine } from "../attention";
import {
  type RankedAttentionRow,
  rankAttention,
} from "../../_lib/attentionQueue";

export function AttentionQueue({ clients }: { clients: ClientAttentionOut[] }) {
  const { actionable, recent, waiting } = rankAttention(clients);

  return (
    <section
      aria-label="Needs attention"
      className="flex flex-col gap-3 rounded-md border border-brand/20 bg-brand/5 p-4 sm:p-5"
    >
      <div className="flex items-baseline justify-between gap-4">
        <p className="font-sans text-[10px] uppercase tracking-eyebrow text-brand">
          Needs attention
        </p>
        {waiting > 0 ? (
          <span className="font-mono text-[11px] uppercase tracking-[0.15em] text-brand/70">
            {waiting} waiting
          </span>
        ) : null}
      </div>

      {actionable.length === 0 && recent.length === 0 ? (
        <p className="py-2 font-serif text-lg text-paper/70">
          All clear. Nothing is waiting on you.
        </p>
      ) : (
        <ul className="flex flex-col divide-y divide-paper/10">
          {actionable.map((row) => (
            <QueueRow key={rowKey(row)} row={row} />
          ))}
          {recent.length > 0 ? (
            <li aria-hidden className="flex items-center gap-3 py-2">
              <span className="h-px flex-1 bg-paper/10" />
              <span className="font-sans text-[9px] uppercase tracking-[0.3em] text-paper/40">
                since you were away
              </span>
              <span className="h-px flex-1 bg-paper/10" />
            </li>
          ) : null}
          {recent.map((row) => (
            <QueueRow key={rowKey(row)} row={row} dim />
          ))}
        </ul>
      )}
    </section>
  );
}

function rowKey(row: RankedAttentionRow): string {
  return `${row.clientId}:${row.item.kind}:${row.item.itinerary_id ?? "basecamp"}:${row.item.node_id ?? ""}:${row.item.at}`;
}

function QueueRow({ row, dim = false }: { row: RankedAttentionRow; dim?: boolean }) {
  const { label, tone } = attentionLine(row.item);
  const href = (
    row.item.itinerary_id
      ? `/itinerary/${row.item.itinerary_id}`
      : `/command-center/clients/${row.clientId}`
  ) as Route;
  const dot =
    tone === "action"
      ? row.item.urgency === "urgent"
        ? "bg-brand"
        : "bg-brand/60"
      : "bg-paper/40";

  return (
    <li>
      <Link
        href={href}
        className="flex items-center gap-2.5 rounded-sm px-1 py-2 transition-colors focus-visible:bg-paper/5 focus-visible:outline-none hover:bg-paper/5"
      >
        <span aria-hidden className={`inline-block h-1.5 w-1.5 shrink-0 rounded-full ${dot}`} />
        <span className="min-w-0 flex-1">
          <span className={`block truncate font-sans text-sm ${dim ? "text-paper/60" : "text-paper/90"}`}>
            {label}
          </span>
          <span className="block truncate font-sans text-[11px] text-paper/45">
            {row.clientName}
          </span>
        </span>
        <span className="shrink-0 whitespace-nowrap font-mono text-[10px] text-paper/40">
          {relativeSince(row.item.at)}
        </span>
      </Link>
    </li>
  );
}

/** Compact "how long ago" (mirrors the strip's cadence). */
function relativeSince(iso: string): string {
  const mins = Math.floor((Date.now() - new Date(iso).getTime()) / 60000);
  if (mins < 1) return "now";
  if (mins < 60) return `${mins}m`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h`;
  const days = Math.floor(hrs / 24);
  if (days < 7) return `${days}d`;
  return `${Math.floor(days / 7)}w`;
}
