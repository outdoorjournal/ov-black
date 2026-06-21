// Render proof for the flight Node card (M002/B2): a flight node whose
// metadata is the FlightCardAttrs shape the API's card_mapping emits from a
// Duffel offer must render its route, cabin, seat and depart→arrive times —
// the "a flight node renders with cabin/seat/times" acceptance — and escalate
// its substrate/footer with status.

import { render, screen } from "@testing-library/react";
import { describe, expect, test } from "vitest";

import type { NodeResponse } from "@ov-black/api-client";

import { NodeCard } from "@/app/_components/itinerary-graph/views/horizontal/NodeCard";

// Mirrors apps/api card_mapping.flight_item_to_card_attrs(...).model_dump():
// the exact node.metadata a Duffel-sourced flight node carries.
function flightNode(overrides: Partial<NodeResponse> = {}): NodeResponse {
  return {
    id: "n-flight",
    itinerary_id: "it-1",
    parent_subgraph_id: null,
    type: "flight",
    status: "proposed",
    title: "LAX → HND · ANA",
    source: "duffel",
    source_id: "off_0000ANA105",
    metadata: {
      kind: "flight",
      iata_from: "LAX",
      iata_to: "HND",
      flight_code: "NH105",
      cabin: "business",
      seat: "2A",
      depart_at: "2026-07-10T11:05:00+09:00",
      arrive_at: "2026-07-11T15:40:00+09:00",
      from_location: { lat: 33.9425, lng: -118.408, label: "Los Angeles (LAX)" },
      to_location: { lat: 35.5533, lng: 139.7811, label: "Tokyo (HND)" },
      start_time: "2026-07-10T11:05:00+09:00",
      duration_minutes: 695,
    },
    ...overrides,
  } as NodeResponse;
}

describe("flight Node card", () => {
  test("renders route, cities, cabin, seat and depart→arrive times", () => {
    render(<NodeCard node={flightNode()} tzOffsetHours={9} />);

    // Route codes.
    expect(screen.getByText("LAX")).toBeInTheDocument();
    expect(screen.getByText("HND")).toBeInTheDocument();
    // City labels (parenthetical IATA stripped).
    expect(screen.getByText("Los Angeles")).toBeInTheDocument();
    expect(screen.getByText("Tokyo")).toBeInTheDocument();
    // Flight number.
    expect(screen.getByText("NH105")).toBeInTheDocument();
    // Cabin is humanized; seat shown.
    expect(screen.getByText("Business")).toBeInTheDocument();
    expect(screen.getByText("2A")).toBeInTheDocument();
    // Times read each end's own wall-clock offset (+09:00 here).
    expect(screen.getByText("11:05")).toBeInTheDocument();
    expect(screen.getByText("15:40")).toBeInTheDocument();
  });

  test("falls back to node start when the flight carries no depart_at", () => {
    const node = flightNode({
      metadata: {
        kind: "flight",
        iata_from: "LAX",
        iata_to: "HND",
        start_time: "2026-07-10T11:05:00+09:00",
        duration_minutes: 695,
      },
    });
    render(<NodeCard node={node} tzOffsetHours={9} />);
    // No depart_at → the node's scheduled start fills the depart slot.
    expect(screen.getByText("11:05")).toBeInTheDocument();
    // No cabin → no cabin chip; "Direct" stands in for a missing flight code.
    expect(screen.queryByText("Business")).not.toBeInTheDocument();
    expect(screen.getByText("Direct")).toBeInTheDocument();
  });

  test("status reaches the shell (booked card exposes its status label)", () => {
    render(<NodeCard node={flightNode({ status: "booked" })} tzOffsetHours={9} />);
    // CardShell labels the group with the status; booked must surface.
    expect(
      screen.getByRole("group", { name: /booked/i }),
    ).toBeInTheDocument();
  });
});
