// M003/V2 — advisor ClientPartySection (the "advisor sees completeness" panel
// on the client detail page). Reuses the same PartyMemberForm as the traveler;
// only the actions differ, so we mock those and assert the wiring:
//   - the roster renders with provenance,
//   - Add maps the form and calls createClientPartyMemberAction(clientId, …),
//   - Remove (confirmed) calls archiveClientPartyMemberAction(clientId, …).

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";

vi.mock("@/app/command-center/clients/[id]/actions", () => ({
  createClientPartyMemberAction: vi.fn(async () => ({ ok: true })),
  updateClientPartyMemberAction: vi.fn(async () => ({ ok: true })),
  archiveClientPartyMemberAction: vi.fn(async () => ({ ok: true })),
}));

import {
  archiveClientPartyMemberAction,
  createClientPartyMemberAction,
} from "@/app/command-center/clients/[id]/actions";
import { ClientPartySection } from "@/app/command-center/clients/[id]/_components/ClientPartySection";

import type { PartyMemberDetail } from "@ov-black/api-client";

function member(over: Partial<PartyMemberDetail> = {}): PartyMemberDetail {
  return {
    id: "m-1",
    client_id: "c-1",
    full_name: "Ada Lovelace",
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
    created_by_actor: "agent",
    updated_by_actor: "agent",
    archived_at: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...over,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
});

test("renders the roster with provenance", () => {
  render(<ClientPartySection clientId="c-1" members={[member()]} />);
  expect(screen.getByText("Ada Lovelace")).toBeInTheDocument();
  expect(screen.getByText(/via agent/i)).toBeInTheDocument();
});

test("Add maps the form and calls create with the client id", async () => {
  render(<ClientPartySection clientId="c-1" members={[]} />);
  fireEvent.click(screen.getByRole("button", { name: "Add traveler" }));

  fireEvent.change(
    screen.getByPlaceholderText(/as it appears on their passport/i),
    { target: { value: "Grace Hopper" } },
  );
  fireEvent.click(screen.getByRole("button", { name: "Add traveler" }));

  await waitFor(() =>
    expect(createClientPartyMemberAction).toHaveBeenCalledTimes(1),
  );
  const [clientId, payload] = vi.mocked(createClientPartyMemberAction).mock
    .calls[0]!;
  expect(clientId).toBe("c-1");
  expect(payload.full_name).toBe("Grace Hopper");
});

test("Remove (confirmed) archives with the client id", async () => {
  vi.spyOn(window, "confirm").mockReturnValue(true);
  render(<ClientPartySection clientId="c-1" members={[member()]} />);

  fireEvent.click(screen.getByRole("button", { name: "Remove" }));

  await waitFor(() =>
    expect(archiveClientPartyMemberAction).toHaveBeenCalledWith("c-1", "m-1"),
  );
});
