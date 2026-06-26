// M003/V2 — traveler self-service PartyManager + PartyMemberForm.
//
// The server actions are mocked so we assert the component wiring + the form's
// value→payload mapping without a backend:
//   - empty roster renders the empty state,
//   - required-name validation blocks submit (no action call),
//   - a valid add maps the form to a PartyMemberCreate (loyalty + emergency
//     folded) and calls createMyPartyMemberAction,
//   - editing pre-fills and calls updateMyPartyMemberAction,
//   - Remove (confirmed) calls archiveMyPartyMemberAction.

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";

vi.mock("@/app/basecamp/party/actions", () => ({
  createMyPartyMemberAction: vi.fn(async () => ({ ok: true })),
  updateMyPartyMemberAction: vi.fn(async () => ({ ok: true })),
  archiveMyPartyMemberAction: vi.fn(async () => ({ ok: true })),
}));

import {
  archiveMyPartyMemberAction,
  createMyPartyMemberAction,
  updateMyPartyMemberAction,
} from "@/app/basecamp/party/actions";
import { PartyManager } from "@/app/basecamp/party/_components/PartyManager";

import type { PartyMemberDetail } from "@ov-black/api-client";

function member(over: Partial<PartyMemberDetail> = {}): PartyMemberDetail {
  return {
    id: "m-1",
    client_id: "c-1",
    full_name: "Ada Lovelace",
    date_of_birth: "1990-05-01",
    nationality: "British",
    dietary: null,
    medical: null,
    mobility: null,
    loyalty_programs: [],
    emergency_contact: {},
    relationship_to_primary: "Spouse",
    is_primary: true,
    notes: null,
    created_by_actor: "traveler",
    updated_by_actor: "traveler",
    archived_at: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...over,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
});

test("empty roster shows the empty state", () => {
  render(<PartyManager members={[]} />);
  expect(screen.getByText(/no travelers yet/i)).toBeInTheDocument();
});

test("required name blocks submit — no action fires", async () => {
  render(<PartyManager members={[]} />);
  fireEvent.click(screen.getByRole("button", { name: "Add a traveler" }));

  // Submit with an empty name.
  fireEvent.click(screen.getByRole("button", { name: "Add traveler" }));

  expect(await screen.findByText("Required")).toBeInTheDocument();
  expect(createMyPartyMemberAction).not.toHaveBeenCalled();
});

test("valid add maps the form to a create payload", async () => {
  render(<PartyManager members={[]} />);
  fireEvent.click(screen.getByRole("button", { name: "Add a traveler" }));

  fireEvent.change(
    screen.getByPlaceholderText(/as it appears on their passport/i),
    { target: { value: "Grace Hopper" } },
  );
  fireEvent.change(screen.getByPlaceholderText(/e\.g\. United States/i), {
    target: { value: "American" },
  });
  // Add a loyalty programme.
  fireEvent.click(screen.getByRole("button", { name: /add programme/i }));
  fireEvent.change(screen.getByPlaceholderText(/Programme/i), {
    target: { value: "AAdvantage" },
  });
  fireEvent.change(screen.getByPlaceholderText(/Membership number/i), {
    target: { value: "12345" },
  });
  // Emergency contact name.
  fireEvent.change(screen.getByPlaceholderText("Name"), {
    target: { value: "Augusta" },
  });

  fireEvent.click(screen.getByRole("button", { name: "Add traveler" }));

  await waitFor(() => expect(createMyPartyMemberAction).toHaveBeenCalledTimes(1));
  const payload = vi.mocked(createMyPartyMemberAction).mock.calls[0]![0];
  expect(payload.full_name).toBe("Grace Hopper");
  expect(payload.nationality).toBe("American");
  expect(payload.loyalty_programs).toEqual([
    { program: "AAdvantage", number: "12345" },
  ]);
  expect(payload.emergency_contact).toMatchObject({ name: "Augusta" });
});

test("editing a member pre-fills and patches", async () => {
  render(<PartyManager members={[member()]} />);
  fireEvent.click(screen.getByRole("button", { name: "Edit" }));

  const name = screen.getByPlaceholderText(
    /as it appears on their passport/i,
  ) as HTMLInputElement;
  expect(name.value).toBe("Ada Lovelace");

  fireEvent.change(name, { target: { value: "Ada L." } });
  fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

  await waitFor(() => expect(updateMyPartyMemberAction).toHaveBeenCalledTimes(1));
  const [memberId, payload] = vi.mocked(updateMyPartyMemberAction).mock
    .calls[0]!;
  expect(memberId).toBe("m-1");
  expect(payload.full_name).toBe("Ada L.");
});

test("Remove (confirmed) archives the member", async () => {
  vi.spyOn(window, "confirm").mockReturnValue(true);
  render(<PartyManager members={[member()]} />);

  fireEvent.click(screen.getByRole("button", { name: "Remove" }));

  await waitFor(() =>
    expect(archiveMyPartyMemberAction).toHaveBeenCalledWith("m-1"),
  );
});
