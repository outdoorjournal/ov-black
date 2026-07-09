// The Ops queue's pure ranking (Wave F). The awareness rollup arrives grouped
// per client; the queue flattens it into rows and orders the ACTIONABLE tier
// by how overdue the advisor is — urgent first, then OLDEST-first (the
// longest-waiting traveler is the most neglected) — while the informational
// tier stays newest-first context under a "since you were away" hairline.

import type { AttentionItemOut, ClientAttentionOut } from "@ov-black/api-client";

export type RankedAttentionRow = {
  clientId: string;
  clientName: string;
  item: AttentionItemOut;
};

export type RankedAttention = {
  actionable: RankedAttentionRow[];
  recent: RankedAttentionRow[];
  /** Total actionable count across the roster (the "N waiting" figure). */
  waiting: number;
};

const ACTIONABLE = new Set([
  "changes_requested",
  "unread_messages",
  "offer_expiring",
  "invoice_unpaid",
  "booking_unconfirmed",
]);

export function rankAttention(
  clients: ClientAttentionOut[],
  { actionableCap = 8, recentCap = 4 }: { actionableCap?: number; recentCap?: number } = {},
): RankedAttention {
  const actionable: RankedAttentionRow[] = [];
  const recent: RankedAttentionRow[] = [];
  let waiting = 0;

  for (const client of clients) {
    waiting += client.attention_count;
    for (const item of client.items) {
      const row = {
        clientId: client.client_id,
        clientName: client.full_name,
        item,
      };
      if (ACTIONABLE.has(item.kind)) actionable.push(row);
      else recent.push(row);
    }
  }

  actionable.sort((a, b) => {
    const urgencyA = a.item.urgency === "urgent" ? 0 : 1;
    const urgencyB = b.item.urgency === "urgent" ? 0 : 1;
    if (urgencyA !== urgencyB) return urgencyA - urgencyB;
    // Oldest first: waiting the longest = most overdue.
    return new Date(a.item.at).getTime() - new Date(b.item.at).getTime();
  });
  recent.sort(
    (a, b) => new Date(b.item.at).getTime() - new Date(a.item.at).getTime(),
  );

  return {
    actionable: actionable.slice(0, actionableCap),
    recent: recent.slice(0, recentCap),
    waiting,
  };
}
