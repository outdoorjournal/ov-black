// Card detail as a route (M006/PS4). The full-bleed detail view assembles six
// facets over a single node; here we assert the WIRING — that each facet renders
// from the shared store, that "ask about this" scopes the persistent concierge
// with a chip, and that the money facet reads the per-node charges endpoint.
// The heavy leaves (next/link's router, the money read, the session thread) are
// stubbed so these test the CardDetailView's own composition, not their guts.

import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, test, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
  useParams: () => ({ id: "it-1" }),
  usePathname: () => "/itinerary/it-1/timeline",
}));

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...rest
  }: {
    href: string | { pathname?: string };
    children: ReactNode;
  }) => (
    <a href={typeof href === "string" ? href : (href.pathname ?? "#")} {...rest}>
      {children}
    </a>
  ),
}));

// The concierge's session thread fetches + streams; the chip integration test
// only needs the column shell around it, so stub the thread (it has its own test).
vi.mock("@/app/itinerary/[id]/_shell/SessionThread", () => ({
  SessionThread: ({ audience }: { audience: string }) => (
    <div data-testid={`thread-${audience}`} />
  ),
}));

const getNodeChargesMock = vi.fn();
const updateNodeStatusMock = vi.fn();
const updateNodeMock = vi.fn();
const deleteNodeMock = vi.fn();
const listInvoicesMock = vi.fn();
const getItineraryMock = vi.fn();
vi.mock("@ov-black/api-client", () => ({
  createApiClient: vi.fn(() => ({})),
  getNodeCharges: (...args: unknown[]) => getNodeChargesMock(...args),
  updateNodeStatus: (...args: unknown[]) => updateNodeStatusMock(...args),
  updateNode: (...args: unknown[]) => updateNodeMock(...args),
  deleteNode: (...args: unknown[]) => deleteNodeMock(...args),
  listInvoices: (...args: unknown[]) => listInvoicesMock(...args),
  getItinerary: (...args: unknown[]) => getItineraryMock(...args),
}));

import type { ItineraryResponse, NodeResponse } from "@ov-black/api-client";

import type { ItineraryTimeline } from "@/app/_components/itinerary-graph/model/types";
import {
  itineraryGraphStore,
  type ItineraryGraphInit,
} from "@/app/_components/itinerary-graph/store/itineraryGraphStore";
import { TimelineDataProvider } from "@/app/_components/itinerary-graph/TimelineDataContext";
import { CardDetailView } from "@/app/itinerary/[id]/_shell/CardDetailView";
import { ConciergeColumn } from "@/app/itinerary/[id]/_shell/ConciergeColumn";

// The advisor authoring surface is a WORKING COPY (a fork of the trunk) —
// trunk content only arrives via publish, so editable scenarios play out here.
const ITINERARY: ItineraryResponse = {
  id: "it-1",
  title: "Trip",
  client_id: "c-1",
  created_by: "u-1",
  display_status: "in_studio",
  forked_from_id: "trunk-0",
};

function node(id: string, over: Partial<NodeResponse> = {}): NodeResponse {
  return {
    id,
    itinerary_id: "it-1",
    parent_subgraph_id: null,
    type: "hotel",
    status: "approved",
    title: id,
    source: null,
    source_id: null,
    metadata: {},
    ...over,
  };
}

const HOTEL = node("n-1", {
  title: "Aman Tokyo",
  cost_amount: "1000.00",
  cost_currency: "USD",
  metadata: {
    start_time: "2024-06-20T15:00:00+09:00",
    location: { lat: 35.6, lng: 139.7, label: "Otemachi" },
  },
});

function timeline(nodes: NodeResponse[]): ItineraryTimeline {
  return {
    id: "it-1",
    label: "Trip",
    subtitle: "",
    mood: "verdant",
    timezoneOffsetHours: 9,
    windowStart: "2024-06-20T00:00:00+09:00",
    windowEnd: "2024-06-21T23:59:00+09:00",
    days: [
      { date: "2024-06-20", label: "Day 1" },
      { date: "2024-06-21", label: "Day 2" },
    ],
    itinerary: ITINERARY,
    nodes,
    edges: [],
  };
}

function charges(over: Record<string, unknown> = {}) {
  return {
    node_id: "n-1",
    node_status: "approved",
    currency: "USD",
    line_item_id: "li-1",
    invoice_id: "inv-1",
    invoice_status: "issued",
    billed_amount: "1000.00",
    paid_amount: "0.00",
    owed_amount: "1000.00",
    booking: null,
    ...over,
  };
}


// The OFFICIAL trunk variant — no forked_from_id: read-only for everyone
// (content arrives via publish; approval happens here).
function trunkTimeline(nodes: NodeResponse[]): ItineraryTimeline {
  const t = timeline(nodes);
  const { forked_from_id: _omit, ...trunk } = ITINERARY;
  return { ...t, itinerary: trunk };
}

function renderDetail(
  ui: ReactNode,
  nodes: NodeResponse[],
  partial: Partial<ItineraryGraphInit> = {},
) {
  const init: ItineraryGraphInit = {
    timeline: timeline(nodes),
    itineraryId: "it-1",
    status: "in_studio",
    role: "advisor",
    apiBaseUrl: "http://api.test",
    accessToken: "tok",
    ...partial,
  };
  const wrapper = ({ children }: { children: ReactNode }) => (
    <itineraryGraphStore.Provider initial={init}>
      <TimelineDataProvider value={{ timeline: timeline(nodes), baselineTitle: null }}>
        {children}
      </TimelineDataProvider>
    </itineraryGraphStore.Provider>
  );
  return render(<>{ui}</>, { wrapper });
}

beforeEach(() => {
  vi.clearAllMocks();
  getNodeChargesMock.mockResolvedValue({ ok: true, charges: charges() });
  updateNodeStatusMock.mockResolvedValue({ ok: true });
  updateNodeMock.mockImplementation((_c: unknown, args: { nodeId: string; patch: Record<string, unknown> }) =>
    Promise.resolve({ ok: true, node: { ...HOTEL, id: args.nodeId, ...args.patch } }),
  );
  deleteNodeMock.mockResolvedValue({ ok: true });
  // refreshBilling (fired after a cost edit) reads the ledger; an unhappy read
  // makes it a clean no-op for these wiring tests.
  listInvoicesMock.mockResolvedValue({ ok: false, detail: "network_error" });
  getItineraryMock.mockResolvedValue({ ok: false, detail: "network_error" });
});

describe("CardDetailView · remove", () => {
  test("a note shows Delete note and soft-deletes on click", () => {
    const n = node("note-1", { type: "note", title: "scratch" });
    renderDetail(<CardDetailView nodeId="note-1" />, [n], { role: "client" });
    const facet = screen.getByTestId("card-detail-remove");
    expect(within(facet).getByText("Delete note")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("card-detail-remove-node"));
    expect(deleteNodeMock).toHaveBeenCalledWith(
      expect.anything(),
      expect.objectContaining({ itineraryId: "it-1", nodeId: "note-1" }),
    );
  });

  test("a pre-firmed card shows Remove from itinerary", () => {
    const n = node("n-idea", { type: "hotel", status: "pending" });
    renderDetail(<CardDetailView nodeId="n-idea" />, [n], { role: "client" });
    const facet = screen.getByTestId("card-detail-remove");
    expect(within(facet).getByText("Remove from itinerary")).toBeInTheDocument();
  });

  test("a firmed card offers no remove facet (demote before delete)", () => {
    const n = node("n-firm", {
      type: "hotel",
      status: "approved",
      lock_reason: "status_locked",
    });
    renderDetail(<CardDetailView nodeId="n-firm" />, [n]);
    expect(screen.queryByTestId("card-detail-remove")).not.toBeInTheDocument();
    expect(deleteNodeMock).not.toHaveBeenCalled();
  });

  test("no remove facet without write credentials", () => {
    const n = node("note-2", { type: "note", title: "scratch" });
    renderDetail(<CardDetailView nodeId="note-2" />, [n], {
      role: "client",
      accessToken: null,
    });
    expect(screen.queryByTestId("card-detail-remove")).not.toBeInTheDocument();
  });
});

describe("CardDetailView · facets", () => {
  test("an editable advisor sees all six facets over the node", async () => {
    renderDetail(<CardDetailView nodeId="n-1" />, [HOTEL], { startLocked: true });

    // Header names the card.
    expect(screen.getByTestId("card-detail")).toHaveAttribute("data-node-id", "n-1");
    expect(
      screen.getByRole("heading", { level: 1, name: "Aman Tokyo" }),
    ).toBeInTheDocument();

    // (a) actions — a Maps link built from the node's location.
    const actions = screen.getByTestId("card-detail-actions");
    expect(within(actions).getByText("Open in Google Maps")).toHaveAttribute(
      "href",
      expect.stringContaining("35.6,139.7"),
    );
    // (c) notes, (d) ask, (e) scheduling (advisor holds the lock).
    expect(screen.getByTestId("notes-panel")).toBeInTheDocument();
    expect(screen.getByTestId("card-detail-ask")).toBeInTheDocument();
    expect(screen.getByTestId("card-detail-schedule")).toBeInTheDocument();
    expect(screen.getByTestId("card-detail-unschedule")).toBeInTheDocument();

    // (f) money — the per-node charges read fills in the ledger line.
    await waitFor(() => {
      const money = screen.getByTestId("card-detail-money");
      expect(money).toHaveTextContent("USD 1000.00");
    });
    expect(getNodeChargesMock).toHaveBeenCalledWith(expect.anything(), "it-1", "n-1");
  });

  test("a read-only viewer (traveler on the trunk) gets no scheduling facet, still asks + sees money", async () => {
    renderDetail(<CardDetailView nodeId="n-1" />, [HOTEL], {
      role: "client",
      timeline: trunkTimeline([HOTEL]),
    });
    expect(screen.queryByTestId("card-detail-schedule")).not.toBeInTheDocument();
    expect(screen.getByTestId("card-detail-ask")).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByTestId("card-detail-money")).toHaveTextContent("USD 1000.00"),
    );
  });

  test("a priced item with no invoice still shows its price to a traveler", async () => {
    // The item is quoted (node.cost_amount) but nothing has been billed yet:
    // the charges read comes back empty. A traveler must still see what it costs.
    getNodeChargesMock.mockResolvedValue({
      ok: true,
      charges: charges({
        currency: null,
        line_item_id: null,
        invoice_id: null,
        invoice_status: null,
        billed_amount: "0.00",
        owed_amount: "0.00",
      }),
    });
    renderDetail(<CardDetailView nodeId="n-1" />, [HOTEL], {
      role: "client",
      timeline: trunkTimeline([HOTEL]),
    });
    await waitFor(() =>
      expect(screen.getByTestId("card-detail-money-price")).toHaveTextContent("USD 1000.00"),
    );
    // …and can't edit it — the edit affordance is advisor-only.
    expect(screen.queryByTestId("card-detail-edit")).not.toBeInTheDocument();
  });

  test("the money facet surfaces this item's booking status", async () => {
    getNodeChargesMock.mockResolvedValue({
      ok: true,
      charges: charges({
        node_status: "booked",
        paid_amount: "1000.00",
        owed_amount: "0.00",
        invoice_status: "paid",
        booking: { node_id: "n-1", node_status: "booked", supplier_ref: "ABC123" },
      }),
    });
    renderDetail(<CardDetailView nodeId="n-1" />, [HOTEL]);
    await waitFor(() => {
      const booking = screen.getByTestId("card-detail-booking");
      expect(booking).toHaveTextContent("Booked");
      expect(booking).toHaveTextContent("ABC123");
    });
  });

  test("a missing node resolves to a graceful not-here state", () => {
    renderDetail(<CardDetailView nodeId="ghost" />, [HOTEL]);
    expect(screen.getByTestId("card-detail-missing")).toBeInTheDocument();
    expect(screen.queryByTestId("card-detail")).not.toBeInTheDocument();
  });
});

describe("CardDetailView · per-card approve", () => {
  const PENDING = node("prop-1", { title: "Kaiseki dinner", status: "pending" });

  test("traveler sees 'Approve this' on a pending card", () => {
    renderDetail(<CardDetailView nodeId="prop-1" />, [PENDING], {
      role: "client",
      status: "with_traveler",
      timeline: trunkTimeline([PENDING]),
    });
    expect(screen.getByTestId("card-detail-approval")).toBeInTheDocument();
  });

  test("advisor gets no per-card approve facet (traveler gesture)", () => {
    renderDetail(<CardDetailView nodeId="prop-1" />, [PENDING], {
      role: "advisor",
      status: "in_studio",
    });
    expect(screen.queryByTestId("card-detail-approval")).not.toBeInTheDocument();
  });
});

describe("CardDetailView · ask about this", () => {
  test("scopes the persistent concierge with a Re: chip, clearable", async () => {
    renderDetail(
      <>
        <ConciergeColumn onClose={() => {}} />
        <CardDetailView nodeId="n-1" />
      </>,
      [HOTEL],
      { startLocked: true },
    );

    // No chip until a card asks.
    expect(screen.queryByTestId("concierge-context-chip")).not.toBeInTheDocument();

    fireEvent.click(screen.getByTestId("card-detail-ask"));

    const chip = await screen.findByTestId("concierge-context-chip");
    expect(chip).toHaveTextContent("Aman Tokyo");

    // The ✕ clears the scope.
    fireEvent.click(screen.getByTestId("concierge-context-clear"));
    expect(screen.queryByTestId("concierge-context-chip")).not.toBeInTheDocument();
  });
});

describe("CardDetailView \u00b7 edit facet (ADV-13)", () => {
  test("an editable advisor patches description, price, and confirmation #", async () => {
    renderDetail(<CardDetailView nodeId="n-1" />, [HOTEL], { startLocked: true });
    const facet = screen.getByTestId("card-detail-edit");

    // Pristine → save disabled.
    const save = within(facet).getByTestId("card-edit-save");
    expect(save).toBeDisabled();

    fireEvent.change(within(facet).getByTestId("card-edit-description"), {
      target: { value: "Corner suite, garden view" },
    });
    fireEvent.change(within(facet).getByTestId("card-edit-amount"), {
      target: { value: "1450.00" },
    });
    fireEvent.change(within(facet).getByTestId("card-edit-kind"), {
      target: { value: "per_person" },
    });
    fireEvent.change(within(facet).getByTestId("card-edit-confirmation"), {
      target: { value: "HX7KQ2" },
    });
    expect(save).toBeEnabled();
    fireEvent.click(save);

    await waitFor(() => expect(updateNodeMock).toHaveBeenCalledTimes(1));
    const { itineraryId, nodeId, patch } = updateNodeMock.mock.calls[0]![1] as {
      itineraryId: string;
      nodeId: string;
      patch: Record<string, unknown>;
    };
    expect(itineraryId).toBe("it-1");
    expect(nodeId).toBe("n-1");
    // Metadata is MERGED — the schedule + location keys survive the patch.
    expect(patch["metadata"]).toMatchObject({
      description: "Corner suite, garden view",
      confirmation_number: "HX7KQ2",
      start_time: "2024-06-20T15:00:00+09:00",
    });
    expect(patch["cost_amount"]).toBe("1450.00");
    expect(patch["cost_currency"]).toBe("USD");
    expect(patch["cost_kind"]).toBe("per_person");
  });

  test("clearing the amount clears the whole cost trio", async () => {
    renderDetail(<CardDetailView nodeId="n-1" />, [HOTEL], { startLocked: true });
    const facet = screen.getByTestId("card-detail-edit");
    fireEvent.change(within(facet).getByTestId("card-edit-amount"), {
      target: { value: "" },
    });
    fireEvent.click(within(facet).getByTestId("card-edit-save"));
    await waitFor(() => expect(updateNodeMock).toHaveBeenCalledTimes(1));
    const { patch } = updateNodeMock.mock.calls[0]![1] as {
      patch: Record<string, unknown>;
    };
    expect(patch["cost_amount"]).toBeNull();
    expect(patch["cost_currency"]).toBeNull();
    expect(patch["cost_kind"]).toBeNull();
    expect(patch["metadata"]).toBeUndefined();
  });

  test("a read-only viewer (traveler on the trunk) gets no edit facet", () => {
    renderDetail(<CardDetailView nodeId="n-1" />, [HOTEL], {
      role: "client",
      timeline: trunkTimeline([HOTEL]),
    });
    expect(screen.queryByTestId("card-detail-edit")).not.toBeInTheDocument();
  });

  test("a traveler on their own fork can edit details but NOT the price", () => {
    // Default fixture is a fork (forked_from_id set), so a client here is a
    // traveler on their own working copy: the edit facet renders for the
    // description/confirmation, but price is advisor-only and stays hidden.
    renderDetail(<CardDetailView nodeId="n-1" />, [HOTEL], { role: "client" });
    const facet = screen.getByTestId("card-detail-edit");
    expect(within(facet).getByTestId("card-edit-description")).toBeInTheDocument();
    expect(within(facet).getByTestId("card-edit-confirmation")).toBeInTheDocument();
    expect(within(facet).queryByTestId("card-edit-amount")).not.toBeInTheDocument();
    expect(within(facet).queryByTestId("card-edit-currency")).not.toBeInTheDocument();
    expect(within(facet).queryByTestId("card-edit-kind")).not.toBeInTheDocument();
    // They still SEE the price (read-only) in the money facet.
    expect(screen.getByTestId("card-detail-money-price")).toHaveTextContent("USD 1000.00");
  });
});
