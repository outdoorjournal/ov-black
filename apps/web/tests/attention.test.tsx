// ADV-14 (Wave D) — the advisor awareness layer's presentation.
//
// Asserts the one place that maps a derived signal to copy/tone, plus the two
// surfaces it feeds: the roster badge (lights only on actionable, open-state
// signals) and the client-detail strip (feed + deep links, actionable header
// vs. recent-activity header). The GET /awareness data is computed server-side
// (app/services/awareness.py) — here we only test the rendering contract.

import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { expect, test, vi } from "vitest";

import type { AttentionItemOut, ClientAttentionOut } from "@ov-black/api-client";

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

import {
  AttentionBadge,
  AttentionStrip,
  attentionLine,
} from "@/app/command-center/_components/attention";

const NOW = new Date().toISOString();

function item(over: Partial<AttentionItemOut> = {}): AttentionItemOut {
  return {
    kind: "changes_requested",
    itinerary_id: "itin-1",
    itinerary_title: "Kyoto",
    count: 1,
    at: NOW,
    ...over,
  };
}

function client(over: Partial<ClientAttentionOut> = {}): ClientAttentionOut {
  return {
    client_id: "c-1",
    full_name: "Margaret Chen",
    needs_attention: false,
    attention_count: 0,
    items: [],
    latest_at: null,
    ...over,
  };
}

// ── attentionLine: copy + tone per kind ──────────────────────────────────────

test("changes_requested and unread are actionable; approvals + payments are info", () => {
  expect(attentionLine(item({ kind: "changes_requested" }))).toEqual({
    label: "Changes requested · Kyoto",
    tone: "action",
  });
  expect(attentionLine(item({ kind: "unread_messages", count: 2 }))).toEqual({
    label: "2 new messages · Kyoto",
    tone: "action",
  });
  expect(attentionLine(item({ kind: "traveler_approved", count: 3 }))).toEqual({
    label: "Approved 3 cards · Kyoto",
    tone: "info",
  });
  expect(attentionLine(item({ kind: "payment_received" }))).toEqual({
    label: "Payment received · Kyoto",
    tone: "info",
  });
});

test("unread with no itinerary falls back to the Basecamp scope", () => {
  const { label } = attentionLine(
    item({ kind: "unread_messages", count: 1, itinerary_id: null, itinerary_title: null }),
  );
  expect(label).toBe("1 new message · Basecamp");
});

// ── AttentionBadge: lights only on an actionable badge ───────────────────────

test("badge shows the actionable count when the client needs attention", () => {
  render(<AttentionBadge attention={client({ needs_attention: true, attention_count: 3 })} />);
  expect(screen.getByText(/3 waiting/i)).toBeInTheDocument();
});

test("badge is dark for an informational-only or absent client", () => {
  const { container: infoOnly } = render(
    <AttentionBadge
      attention={client({ needs_attention: false, attention_count: 0, items: [item()] })}
    />,
  );
  expect(infoOnly).toBeEmptyDOMElement();

  const { container: absent } = render(<AttentionBadge attention={undefined} />);
  expect(absent).toBeEmptyDOMElement();
});

// ── AttentionStrip: feed, deep links, header framing ─────────────────────────

test("strip renders each signal, deep-linked to its trip, actionable-first header", () => {
  render(
    <AttentionStrip
      attention={client({
        needs_attention: true,
        attention_count: 1,
        items: [
          item({ kind: "changes_requested", itinerary_id: "itin-1", itinerary_title: "Kyoto" }),
          item({
            kind: "payment_received",
            itinerary_id: "itin-2",
            itinerary_title: "Bali",
            count: 1,
          }),
        ],
        latest_at: NOW,
      })}
    />,
  );

  expect(screen.getByText("Needs attention")).toBeInTheDocument();
  expect(screen.getByText(/1 waiting on you/i)).toBeInTheDocument();

  const changes = screen.getByText("Changes requested · Kyoto");
  expect(changes.closest("a")).toHaveAttribute("href", "/itinerary/itin-1");
  const payment = screen.getByText("Payment received · Bali");
  expect(payment.closest("a")).toHaveAttribute("href", "/itinerary/itin-2");
});

test("strip reads 'Since you were away' when only recent activity, and hides when empty", () => {
  render(
    <AttentionStrip
      attention={client({
        needs_attention: false,
        attention_count: 0,
        items: [item({ kind: "traveler_approved", count: 2 })],
        latest_at: NOW,
      })}
    />,
  );
  expect(screen.getByText("Since you were away")).toBeInTheDocument();

  const { container } = render(<AttentionStrip attention={client()} />);
  expect(container).toBeEmptyDOMElement();
});
