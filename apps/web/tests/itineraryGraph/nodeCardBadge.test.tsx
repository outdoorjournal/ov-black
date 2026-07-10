// The per-card attached-note badge (shown only when a host has notes riding
// it) and the ADV-15 billing chip (the board's read of the card's money state).

import { render, screen } from "@testing-library/react";
import { describe, expect, test } from "vitest";

import type { NodeResponse } from "@ov-black/api-client";

import { NodeCard } from "@/app/_components/itinerary-graph/views/horizontal/NodeCard";

function host(): NodeResponse {
  return {
    id: "host",
    itinerary_id: "it-1",
    parent_subgraph_id: null,
    type: "experience",
    status: "pending",
    title: "Tea at 1:30",
    source: null,
    source_id: null,
    metadata: { start_time: "2024-06-20T13:30:00+09:00" },
  };
}

describe("NodeCard attached-note badge", () => {
  test("shows a count badge when notes are attached", () => {
    render(<NodeCard node={host()} tzOffsetHours={9} attachedNoteCount={2} />);
    const badge = screen.getByTestId("attached-note-badge");
    expect(badge).toHaveTextContent("2");
    expect(badge).toHaveAttribute("aria-label", "2 notes");
  });

  test("renders no badge when there are none", () => {
    render(<NodeCard node={host()} tzOffsetHours={9} />);
    expect(screen.queryByTestId("attached-note-badge")).toBeNull();
  });
});

describe("NodeCard billing chip (ADV-15)", () => {
  test("wears the billing state in the type-label row when provided", () => {
    render(
      <NodeCard
        node={host()}
        tzOffsetHours={9}
        billingChip={{ state: "unbilled", invoiceId: null }}
      />,
    );
    const chip = screen.getByTestId("billing-chip-host");
    expect(chip).toHaveTextContent("Unbilled");
    expect(chip).toHaveAttribute("data-billing-state", "unbilled");
  });

  test("wears nothing without a chip (traveler surfaces, costless cards)", () => {
    render(<NodeCard node={host()} tzOffsetHours={9} />);
    expect(screen.queryByTestId("billing-chip-host")).toBeNull();
  });
});
