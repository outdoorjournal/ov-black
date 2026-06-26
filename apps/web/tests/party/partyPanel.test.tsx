// M003/V2 — advisor "who's traveling" PartyPanel (itinerary-aside Party tab).
//
// The party wrappers are mocked so we assert the panel's own wiring without a
// live backend:
//   - on mount it loads who's on the trip + the household roster,
//   - the picker offers only members not already attached,
//   - Attach calls attachItineraryPartyMember and re-renders from its result,
//   - Remove calls detachItineraryPartyMember with the durable member id.

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";

vi.mock("@ov-black/api-client", () => ({
  createApiClient: vi.fn(() => ({})),
  listItineraryParty: vi.fn(),
  listClientPartyMembers: vi.fn(),
  attachItineraryPartyMember: vi.fn(),
  detachItineraryPartyMember: vi.fn(),
}));

import {
  attachItineraryPartyMember,
  detachItineraryPartyMember,
  listClientPartyMembers,
  listItineraryParty,
  type ItineraryPartyEntry,
  type PartyMemberDetail,
} from "@ov-black/api-client";

import { PartyPanel } from "@/app/_components/itinerary-graph/views/horizontal/PartyPanel";

function member(id: string, full_name: string): PartyMemberDetail {
  return {
    id,
    client_id: "c-1",
    full_name,
    date_of_birth: null,
    nationality: null,
    dietary: null,
    medical: null,
    mobility: null,
    loyalty_programs: [],
    emergency_contact: {},
    relationship_to_primary: null,
    is_primary: false,
    notes: null,
    created_by_actor: "advisor",
    updated_by_actor: "advisor",
    archived_at: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  };
}

function entry(m: PartyMemberDetail): ItineraryPartyEntry {
  return {
    traveler_id: `trav-${m.id}`,
    party_id: "party-1",
    name: m.full_name,
    party_member_id: m.id,
    member: m,
  };
}

const ADA = member("m-ada", "Ada Lovelace");
const GRACE = member("m-grace", "Grace Hopper");

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(listItineraryParty).mockResolvedValue({
    ok: true,
    party: { itinerary_id: "it-1", members: [entry(ADA)] },
  });
  vi.mocked(listClientPartyMembers).mockResolvedValue({
    ok: true,
    members: [ADA, GRACE],
  });
});

function renderPanel() {
  return render(
    <PartyPanel
      clientId="c-1"
      itineraryId="it-1"
      apiBaseUrl="http://api.test"
      accessToken="tok"
    />,
  );
}

test("loads trip party + offers only un-attached household members", async () => {
  renderPanel();

  // Ada is on the trip; Grace is the only one offered to attach.
  await waitFor(() => expect(listItineraryParty).toHaveBeenCalledWith({}, "it-1"));
  expect(listClientPartyMembers).toHaveBeenCalledWith({}, "c-1");

  await screen.findByText("Ada Lovelace");
  // Grace appears once (in the picker); Ada is not offered again.
  const grace = await screen.findAllByText("Grace Hopper");
  expect(grace).toHaveLength(1);
});

test("Attach calls the wrapper and re-renders from its result", async () => {
  vi.mocked(attachItineraryPartyMember).mockResolvedValue({
    ok: true,
    party: { itinerary_id: "it-1", members: [entry(ADA), entry(GRACE)] },
  });
  renderPanel();

  const attachBtn = await screen.findByRole("button", { name: /attach/i });
  fireEvent.click(attachBtn);

  await waitFor(() =>
    expect(attachItineraryPartyMember).toHaveBeenCalledWith({}, "it-1", {
      party_member_id: "m-grace",
    }),
  );
  // After attach, everyone is on the trip → picker says so.
  await screen.findByText(/already on this trip/i);
});

test("Remove calls detach with the durable member id", async () => {
  vi.mocked(detachItineraryPartyMember).mockResolvedValue({
    ok: true,
    party: { itinerary_id: "it-1", members: [] },
  });
  renderPanel();

  const removeBtn = await screen.findByRole("button", { name: /remove/i });
  fireEvent.click(removeBtn);

  await waitFor(() =>
    expect(detachItineraryPartyMember).toHaveBeenCalledWith({}, "it-1", "m-ada"),
  );
});
