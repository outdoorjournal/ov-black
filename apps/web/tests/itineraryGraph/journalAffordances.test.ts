import { describe, expect, test } from "vitest";

import type { NodeResponse } from "@/app/_components/itinerary-graph/model/types";
import type { ItineraryGraphState } from "@/app/_components/itinerary-graph/store/itineraryGraphStore";
import { resolveNodeAffordances } from "@/app/_components/itinerary-graph/views/journal/affordances";

// A minimal store-state fixture (the same partial-cast idiom journalEditing.test
// uses). Defaults: a credentialed TRAVELER on the OFFICIAL trunk, itinerary
// proposed to them (`with_traveler`) so per-node approve is meaningful.
function state(partial: Record<string, unknown> = {}): ItineraryGraphState {
  return {
    canEdit: false,
    status: "with_traveler",
    draftMine: false,
    lockStatus: "unlocked",
    apiBaseUrl: "http://api.test",
    accessToken: "tok",
    sample: { itinerary: { forked_from_id: null } },
    ...partial,
  } as unknown as ItineraryGraphState;
}

function node(
  status: NodeResponse["status"],
  extra: Partial<NodeResponse> = {},
): NodeResponse {
  return {
    id: "n1",
    type: "experience",
    title: "A thing",
    status,
    metadata: {},
    ...extra,
  } as unknown as NodeResponse;
}

const ownFork = { sample: { itinerary: { forked_from_id: "trunk-1" } } };
const advisor = { canEdit: true };
const advisorFork = { canEdit: true, sample: { itinerary: { forked_from_id: "trunk-1" } } };

describe("resolveNodeAffordances — traveler", () => {
  test("trunk · pending → approve is the ask; edits offer a fork", () => {
    const a = resolveNodeAffordances(state(), node("pending"));
    expect(a.approve).toBe(true);
    expect(a.ask).toBe("approve");
    expect(a.reschedule).toBe("fork-offer");
    expect(a.edit).toBe("fork-offer");
    expect(a.notes).toBe("to-advisor");
    expect(a.locked).toBeNull();
  });

  test("trunk · approved → locked-approved, settled", () => {
    const a = resolveNodeAffordances(state(), node("approved"));
    expect(a.approve).toBe(false);
    expect(a.ask).toBe("approved");
    expect(a.reschedule).toBe("locked-approved");
    expect(a.edit).toBe("locked-approved");
  });

  test("own fork · pending → freely editable, no approve", () => {
    const a = resolveNodeAffordances(state(ownFork), node("pending"));
    expect(a.approve).toBe(false);
    expect(a.reschedule).toBe("live");
    expect(a.edit).toBe("live");
    expect(a.ask).toBe("none");
  });

  test("own fork · approved → still locked (approved pins it like booked)", () => {
    const a = resolveNodeAffordances(state(ownFork), node("approved"));
    expect(a.reschedule).toBe("locked-approved");
    expect(a.edit).toBe("locked-approved");
  });

  test("booked / confirmed → hard lock, ask says booked", () => {
    for (const st of ["booked", "confirmed"] as const) {
      const a = resolveNodeAffordances(state(ownFork), node(st));
      expect(a.reschedule).toBe("locked-booked");
      expect(a.edit).toBe("locked-booked");
      expect(a.ask).toBe("booked");
      expect(a.locked).toBe("booked");
    }
  });

  test("schedule-pinned flight → reschedule is the airline's, fields still edit", () => {
    const flight = node("pending", {
      type: "flight",
      metadata: { depart_at: "2026-08-01T09:00:00Z" },
    });
    const a = resolveNodeAffordances(state(ownFork), flight);
    expect(a.reschedule).toBe("pinned-airline");
    expect(a.edit).toBe("live");
  });

  test("no credentials → everything read-only, no notes", () => {
    const a = resolveNodeAffordances(
      state({ apiBaseUrl: null, accessToken: null }),
      node("pending"),
    );
    expect(a.approve).toBe(false);
    expect(a.reschedule).toBe("none");
    expect(a.edit).toBe("none");
    expect(a.notes).toBe("none");
  });

  test("approve gate respects the itinerary bucket (in_studio → not yet)", () => {
    const a = resolveNodeAffordances(state({ status: "in_studio" }), node("pending"));
    expect(a.approve).toBe(false);
    expect(a.ask).toBe("none");
  });
});

describe("resolveNodeAffordances — advisor", () => {
  test("working-copy fork · pending → editable, internal notes, never approves", () => {
    const a = resolveNodeAffordances(state(advisorFork), node("pending"));
    expect(a.approve).toBe(false);
    expect(a.reschedule).toBe("live");
    expect(a.edit).toBe("live");
    expect(a.notes).toBe("internal");
    expect(a.ask).toBe("none");
  });

  test("working-copy fork · approved → editable with re-approval consequence", () => {
    const a = resolveNodeAffordances(state(advisorFork), node("approved"));
    expect(a.edit).toBe("advisor-demote");
    expect(a.reschedule).toBe("live");
    expect(a.ask).toBe("reapproval-warning");
  });

  test("trunk (not in workspace) → no in-rail edit; author in the fork", () => {
    const a = resolveNodeAffordances(state(advisor), node("pending"));
    expect(a.reschedule).toBe("none");
    expect(a.edit).toBe("none");
  });

  test("booked → hard lock even for an advisor", () => {
    const a = resolveNodeAffordances(state(advisorFork), node("booked"));
    expect(a.edit).toBe("locked-booked");
    expect(a.reschedule).toBe("locked-booked");
  });
});

describe("resolveNodeAffordances — modifiers", () => {
  test("a problem takes over the Zone-1 ask", () => {
    const a = resolveNodeAffordances(state(), node("pending"), {
      hasProblem: true,
    });
    expect(a.ask).toBe("needs-attention");
  });
});
