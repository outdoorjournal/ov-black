// Card harmonization invariant (M006/PS-cards). The same domain object — an
// itinerary node — must render as the SAME card across every surface: the
// timeline glance (NodeCard), the Collection wish-list (CollectionRail), and the
// chat proposal (mood-board Card). "The same" = the shared CardShell substrate
// (`.card-substrate` keyed on [data-status]) filled with the shared CardBody
// (the type label + serif title). If a future edit re-forks one surface onto a
// bespoke card, this fails loudly.

import { DndContext } from "@dnd-kit/core";
import { render, screen, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, test, vi } from "vitest";

vi.mock("@ov-black/api-client", () => ({
  createApiClient: vi.fn(() => ({})),
  createNode: vi.fn(async () => ({ ok: true })),
  createNodeFromLink: vi.fn(async () => ({ ok: true })),
  updateNode: vi.fn(async () => ({ ok: true })),
}));

import type { ItineraryResponse, NodeResponse } from "@ov-black/api-client";

import { Card } from "@/app/chat/[client_id]/_components/Card";
import { CollectionRail } from "@/app/_components/itinerary-graph/collection/CollectionRail";
import { NodeCard } from "@/app/_components/itinerary-graph/views/horizontal/NodeCard";
import type { ItineraryTimeline } from "@/app/_components/itinerary-graph/model/types";
import {
  itineraryGraphStore,
  type ItineraryGraphInit,
} from "@/app/_components/itinerary-graph/store/itineraryGraphStore";

const TITLE = "Sunrise at Fushimi Inari";

const EXPERIENCE: NodeResponse = {
  id: "exp-parity",
  itinerary_id: "it-1",
  parent_subgraph_id: null,
  type: "experience",
  status: "proposed",
  title: TITLE,
  source: "ov",
  source_id: "ov-123",
  metadata: {
    snapshot: {
      title: TITLE,
      location: "Kyoto",
      activities: ["shrine", "hike"],
    },
    location: { label: "Kyoto" },
  },
};

// The one substrate element every surface must produce for a proposed node.
function assertSharedSubstrate(root: HTMLElement) {
  const substrate = root.querySelector<HTMLElement>(".card-substrate");
  expect(substrate).not.toBeNull();
  expect(substrate!.getAttribute("data-status")).toBe("proposed");
  // The shared CardBody header carries the type label + the serif title.
  const text = substrate!.textContent ?? "";
  expect(text).toContain("Experience");
  expect(text).toContain(TITLE);
}

const ITINERARY: ItineraryResponse = {
  id: "it-1",
  title: "Trip",
  client_id: "c-1",
  created_by: "u-1",
  status: "draft",
};

function timeline(nodes: NodeResponse[]): ItineraryTimeline {
  return {
    id: "it-1",
    label: "Trip",
    subtitle: "",
    mood: "verdant",
    timezoneOffsetHours: 9,
    windowStart: "2024-06-20T00:00:00+09:00",
    windowEnd: "2024-06-20T23:59:00+09:00",
    days: [{ date: "2024-06-20", label: "Day 1" }],
    itinerary: ITINERARY,
    nodes,
    edges: [],
  };
}

describe("card harmonization · one node, one card across surfaces", () => {
  test("timeline glance (NodeCard) wears the shared substrate", () => {
    const { container } = render(
      <NodeCard node={EXPERIENCE} tzOffsetHours={9} />,
    );
    assertSharedSubstrate(container);
  });

  test("chat proposal (mood-board Card) wears the shared substrate", () => {
    const { container } = render(
      <Card
        card={{
          node_id: EXPERIENCE.id,
          source: "ov",
          source_id: "ov-123",
          status: "proposed",
          snapshot: {
            title: TITLE,
            location: "Kyoto",
            activities: ["shrine", "hike"],
            price: "$$$",
            duration_days: 2,
            difficulty: "moderate",
          },
        }}
        onAction={() => {}}
      />,
    );
    assertSharedSubstrate(container);
  });

  test("collection card (CollectionRail) wears the shared substrate", () => {
    const init: ItineraryGraphInit = {
      timeline: timeline([EXPERIENCE]),
      itineraryId: "it-1",
      status: "draft",
      role: "client",
      apiBaseUrl: "http://api.test",
      accessToken: "tok",
    };
    const wrapper = ({ children }: { children: ReactNode }) => (
      <itineraryGraphStore.Provider initial={init}>
        <DndContext>{children}</DndContext>
      </itineraryGraphStore.Provider>
    );
    render(<CollectionRail variant="board" />, { wrapper });
    const card = screen.getByTestId("collection-card");
    assertSharedSubstrate(card);
    // Sanity: the collection body reuses the same type label the others show.
    expect(within(card).getByText(TITLE)).toBeInTheDocument();
  });
});
