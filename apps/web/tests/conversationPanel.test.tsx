// The concierge conversation surface's proposal rendering. A typed proposal (a
// flight) must render as its own compact card — route + airport-local wall clock
// + cabin — not the bare "accept/dismiss" title stub the generic path shows.

import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";

import {
  ConversationPanel,
  type ConversationProposal,
} from "@/app/_components/concierge/ConversationPanel";

const FLIGHT: ConversationProposal = {
  id: "n1",
  type: "flight",
  title: "DTW → SCL · LATAM Airlines",
  metadata: {
    kind: "flight",
    iata_from: "DTW",
    iata_to: "SCL",
    cabin: "economy",
    depart_at: "2026-11-10T16:10:00-05:00",
    arrive_at: "2026-11-11T07:50:00-03:00",
    from_location: { label: "Detroit (DTW)" },
    to_location: { label: "Santiago (SCL)" },
  },
};

test("a flight proposal renders as a boarding-pass card, not a bare title", () => {
  render(
    <ConversationPanel messages={[]} onSubmit={() => {}} proposals={[FLIGHT]} />,
  );

  // Route codes + cities read like a boarding pass.
  expect(screen.getByText("DTW")).toBeTruthy();
  expect(screen.getByText("SCL")).toBeTruthy();
  expect(screen.getByText("Detroit")).toBeTruthy();
  expect(screen.getByText("Santiago")).toBeTruthy();

  // Each end shows its OWN airport-local wall clock (embedded offset, no
  // viewer-tz conversion): depart 16:10, arrive 07:50.
  expect(screen.getByText(/Nov 10 · 16:10/)).toBeTruthy();
  expect(screen.getByText(/Nov 11 · 07:50/)).toBeTruthy();

  // Cabin chip humanized.
  expect(screen.getByText("Economy")).toBeTruthy();

  // The raw title stub is NOT rendered for a typed flight proposal.
  expect(screen.queryByText("DTW → SCL · LATAM Airlines")).toBeNull();
});

test("a non-typed proposal falls back to the bare title", () => {
  const generic: ConversationProposal = {
    id: "n2",
    type: "experience",
    title: "Sunrise at Torres del Paine",
  };
  render(
    <ConversationPanel messages={[]} onSubmit={() => {}} proposals={[generic]} />,
  );
  expect(screen.getByText("Sunrise at Torres del Paine")).toBeTruthy();
});
