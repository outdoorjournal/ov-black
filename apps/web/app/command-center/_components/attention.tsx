import Link from "next/link";

import type { AttentionItemOut, ClientAttentionOut } from "@ov-black/api-client";

// ADV-14 (Wave D) — the advisor awareness layer's presentation. One place maps
// a derived signal to its copy + tone so the roster badge and the client-detail
// strip stay in sync. Pure/presentational (server-renderable): the data comes
// from GET /awareness, computed server-side in app/services/awareness.py.

type Tone = "action" | "info";

/** Human copy + tone for one attention signal. */
export function attentionLine(item: AttentionItemOut): {
  label: string;
  tone: Tone;
} {
  const where = item.itinerary_title ? ` · ${item.itinerary_title}` : "";
  switch (item.kind) {
    case "changes_requested":
      return { label: `Changes requested${where}`, tone: "action" };
    case "unread_messages": {
      const s = item.count === 1 ? "" : "s";
      const scope = item.itinerary_title ? ` · ${item.itinerary_title}` : " · Basecamp";
      return { label: `${item.count} new message${s}${scope}`, tone: "action" };
    }
    case "traveler_approved": {
      const s = item.count === 1 ? "" : "s";
      return { label: `Approved ${item.count} card${s}${where}`, tone: "info" };
    }
    case "payment_received":
      return { label: `Payment received${where}`, tone: "info" };
  }
}

/**
 * The roster badge — a brand pill counting the *actionable* signals (things the
 * traveler is waiting on the advisor for). Renders nothing when the badge is
 * dark, so recent-activity-only clients don't wear a false alarm.
 */
export function AttentionBadge({
  attention,
}: {
  attention: ClientAttentionOut | undefined;
}) {
  if (!attention?.needs_attention || attention.attention_count <= 0) return null;
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full border border-brand/50 bg-brand/10 px-2 py-0.5 font-sans text-[10px] uppercase tracking-[0.2em] text-brand"
      title="Waiting on you"
    >
      <span aria-hidden className="inline-block h-1.5 w-1.5 rounded-full bg-brand" />
      {attention.attention_count} waiting
    </span>
  );
}

/**
 * The per-client "what's happened" strip — actionable signals first, then recent
 * activity, each deep-linking to the trip it belongs to. Renders nothing when
 * the feed is empty (the page stays quiet when there's nothing to say).
 */
export function AttentionStrip({
  attention,
}: {
  attention: ClientAttentionOut | undefined;
}) {
  if (!attention || attention.items.length === 0) return null;
  return (
    <section
      aria-label="Needs attention"
      className="flex flex-col gap-3 rounded-md border border-brand/20 bg-brand/5 p-4 sm:p-5"
    >
      <div className="flex items-baseline justify-between gap-4">
        <p className="font-sans text-[10px] uppercase tracking-eyebrow text-brand">
          {attention.needs_attention ? "Needs attention" : "Since you were away"}
        </p>
        {attention.needs_attention ? (
          <span className="font-sans text-[10px] uppercase tracking-label text-brand/70">
            {attention.attention_count} waiting on you
          </span>
        ) : null}
      </div>
      <ul className="flex flex-col divide-y divide-paper/10">
        {attention.items.map((item, i) => (
          <AttentionRow key={`${item.kind}-${item.itinerary_id ?? "basecamp"}-${i}`} item={item} />
        ))}
      </ul>
    </section>
  );
}

function AttentionRow({ item }: { item: AttentionItemOut }) {
  const { label, tone } = attentionLine(item);
  const dot = tone === "action" ? "bg-brand" : "bg-paper/40";
  const body = (
    <span className="flex items-center gap-2.5 py-2">
      <span aria-hidden className={`inline-block h-1.5 w-1.5 shrink-0 rounded-full ${dot}`} />
      <span className="min-w-0 flex-1 truncate font-sans text-sm text-paper/85">{label}</span>
      <span className="shrink-0 whitespace-nowrap font-sans text-[11px] text-paper/45">
        {relativeSince(item.at)}
      </span>
    </span>
  );
  if (item.itinerary_id) {
    return (
      <li>
        <Link
          href={`/itinerary/${item.itinerary_id}`}
          className="block rounded-sm px-1 transition-colors hover:bg-paper/5"
        >
          {body}
        </Link>
      </li>
    );
  }
  return <li className="px-1">{body}</li>;
}

/** Compact "how long ago" for an ISO timestamp (mirrors the roster's cadence). */
function relativeSince(iso: string): string {
  const then = new Date(iso).getTime();
  const mins = Math.floor((Date.now() - then) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  if (days < 7) return `${days}d ago`;
  if (days < 30) return `${Math.floor(days / 7)}w ago`;
  return new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric" }).format(
    new Date(then),
  );
}
