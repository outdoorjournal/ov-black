import { expect, test } from "vitest";

import type { AttentionItemOut, ClientAttentionOut } from "@ov-black/api-client";

import { rankAttention } from "@/app/command-center/_lib/attentionQueue";

function item(over: Partial<AttentionItemOut> = {}): AttentionItemOut {
  return {
    kind: "changes_requested",
    itinerary_id: "i-1",
    itinerary_title: "Kyoto",
    count: 1,
    at: "2026-07-08T12:00:00+00:00",
    node_id: null,
    urgency: "normal",
    deadline: null,
    ...over,
  };
}

function client(over: Partial<ClientAttentionOut> = {}): ClientAttentionOut {
  return {
    client_id: "c-1",
    full_name: "Margaret Chen",
    needs_attention: true,
    attention_count: 1,
    items: [],
    latest_at: null,
    ...over,
  };
}

test("actionable ranks urgent first then oldest-first; recent stays newest-first", () => {
  const ranked = rankAttention([
    client({
      client_id: "c-1",
      attention_count: 3,
      items: [
        item({ kind: "unread_messages", at: "2026-07-08T11:00:00+00:00" }),
        item({ kind: "changes_requested", at: "2026-07-05T09:00:00+00:00" }),
        item({
          kind: "offer_expiring",
          urgency: "urgent",
          at: "2026-07-08T11:30:00+00:00",
        }),
        item({ kind: "payment_received", at: "2026-07-08T10:00:00+00:00" }),
        item({ kind: "traveler_approved", at: "2026-07-08T11:59:00+00:00" }),
      ],
    }),
  ]);

  expect(ranked.actionable.map((r) => r.item.kind)).toEqual([
    "offer_expiring", // urgent outranks everything
    "changes_requested", // then oldest-first (most neglected)
    "unread_messages",
  ]);
  expect(ranked.recent.map((r) => r.item.kind)).toEqual([
    "traveler_approved", // informational stays newest-first
    "payment_received",
  ]);
  expect(ranked.waiting).toBe(3);
});

test("caps apply per tier and rows carry the client identity", () => {
  const many = Array.from({ length: 12 }, (_, i) =>
    item({ kind: "unread_messages", at: `2026-07-0${(i % 7) + 1}T0${i % 9}:00:00+00:00` }),
  );
  const ranked = rankAttention(
    [client({ client_id: "c-7", full_name: "R. Whitfield", items: many, attention_count: 12 })],
    { actionableCap: 8, recentCap: 4 },
  );
  expect(ranked.actionable).toHaveLength(8);
  expect(ranked.actionable[0]?.clientName).toBe("R. Whitfield");
  expect(ranked.waiting).toBe(12);
});
