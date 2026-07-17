// Tests for the view-agnostic itinerary graph store: the editable gate and the
// safety property that editing actions are inert for non-staff / no-credential
// viewers (so a traveler can never mutate, even if an action is invoked).

import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, test } from "vitest";

import type {
  EdgeResponse,
  ItineraryResponse,
  NodeResponse,
} from "@ov-black/api-client";

import type { ItineraryTimeline } from "@/app/_components/itinerary-graph/model/types";
import { journalProblems } from "@/app/_components/itinerary-graph/views/journal/problems";
import {
  itineraryGraphStore,
  seedFindingsFromGraph,
  selectCanApprove,
  selectCanLeaveNote,
  selectEditable,
  selectIsDraftMine,
  selectTravelerEditable,
  type ItineraryGraphInit,
  type ItineraryGraphState,
} from "@/app/_components/itinerary-graph/store/itineraryGraphStore";

const ITINERARY: ItineraryResponse = {
  id: "it-1",
  title: "Trip",
  client_id: "c-1",
  created_by: "u-1",
  display_status: "in_studio",
};

const NODE: NodeResponse = {
  id: "n1",
  itinerary_id: "it-1",
  parent_subgraph_id: null,
  type: "note",
  status: "approved",
  title: "Original",
  source: null,
  source_id: null,
  metadata: { start_time: "2024-06-20T09:00:00+09:00", duration_minutes: 60 },
};

function timeline(nodes: NodeResponse[], edges: EdgeResponse[] = []): ItineraryTimeline {
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
    edges,
  };
}

function renderStore(init: Partial<ItineraryGraphInit> = {}) {
  const full: ItineraryGraphInit = {
    timeline: timeline([NODE]),
    itineraryId: "it-1",
    status: "in_studio",
    role: "client",
    apiBaseUrl: null,
    accessToken: null,
    ...init,
  };
  const wrapper = ({ children }: { children: ReactNode }) => (
    <itineraryGraphStore.Provider initial={full}>
      {children}
    </itineraryGraphStore.Provider>
  );
  return renderHook(() => itineraryGraphStore.useStoreApi(), { wrapper });
}

describe("selectEditable (credentialed: advisor on their working copy)", () => {
  const creds = {
    canEdit: true,
    apiBaseUrl: "x",
    accessToken: "t",
  } as unknown as ItineraryGraphState;

  test("true on a fork — the advisor workspace", () => {
    expect(
      selectEditable({
        ...creds,
        sample: { itinerary: { forked_from_id: "trunk-1" } },
      } as unknown as ItineraryGraphState),
    ).toBe(true);
  });
  test("false on the official trunk (content arrives via publish)", () => {
    expect(
      selectEditable({
        ...creds,
        sample: { itinerary: { forked_from_id: null } },
      } as unknown as ItineraryGraphState),
    ).toBe(false);
  });
  test("false for travelers even on a fork (that's selectTravelerEditable)", () => {
    expect(
      selectEditable({
        ...creds,
        canEdit: false,
        sample: { itinerary: { forked_from_id: "trunk-1" } },
      } as unknown as ItineraryGraphState),
    ).toBe(false);
  });
});

describe("selectEditable (credential-less sandbox keeps the lock rule)", () => {
  const base = { status: "in_studio", lockStatus: "locked-by-me" } as ItineraryGraphState;
  test("requires canEdit", () => {
    expect(selectEditable({ ...base, canEdit: false } as ItineraryGraphState)).toBe(false);
  });
  test("requires the lock held by self", () => {
    expect(
      selectEditable({ ...base, canEdit: true, lockStatus: "unlocked" } as ItineraryGraphState),
    ).toBe(false);
    expect(
      selectEditable({ ...base, canEdit: true, lockStatus: "locked-by-other" } as ItineraryGraphState),
    ).toBe(false);
  });
  test("requires in_studio (not approved)", () => {
    expect(
      selectEditable({ ...base, canEdit: true, status: "approved" } as ItineraryGraphState),
    ).toBe(false);
  });
  test("true only when staff + locked-by-me + in_studio", () => {
    expect(selectEditable({ ...base, canEdit: true } as ItineraryGraphState)).toBe(true);
  });
  test("with_traveler freezes the build (not editable)", () => {
    expect(
      selectEditable({ ...base, canEdit: true, status: "with_traveler" } as ItineraryGraphState),
    ).toBe(false);
  });
});

describe("selectCanApprove", () => {
  const traveler = {
    canEdit: false,
    status: "with_traveler",
    apiBaseUrl: "x",
    accessToken: "t",
    sample: { itinerary: { forked_from_id: null } },
  } as unknown as ItineraryGraphState;

  test("traveler may approve a plan that's with them", () => {
    expect(selectCanApprove(traveler)).toBe(true);
  });
  test("traveler may NOT approve while in the studio (advisor still building)", () => {
    expect(selectCanApprove({ ...traveler, status: "in_studio" })).toBe(false);
  });
  test("advisor may NOT approve — approval is the traveler's gesture", () => {
    // The trunk+fork model makes approval traveler-only: the advisor proposes
    // (in_studio → with_traveler); the traveler approves. `canEdit` (advisor)
    // therefore disables the approve affordance in every display status.
    expect(selectCanApprove({ ...traveler, canEdit: true, status: "in_studio" })).toBe(false);
    expect(selectCanApprove({ ...traveler, canEdit: true, status: "with_traveler" })).toBe(false);
  });
  test("false once approved", () => {
    expect(selectCanApprove({ ...traveler, status: "approved" })).toBe(false);
    expect(selectCanApprove({ ...traveler, canEdit: true, status: "approved" })).toBe(false);
  });
  test("false on a fork (approval is on the baseline)", () => {
    expect(
      selectCanApprove({
        ...traveler,
        sample: { itinerary: { forked_from_id: "b" } },
      } as unknown as ItineraryGraphState),
    ).toBe(false);
  });
  test("false without creds", () => {
    expect(selectCanApprove({ ...traveler, accessToken: null })).toBe(false);
  });
});

describe("approval actions are inert without credentials", () => {
  test("approve / approveNode are no-ops with null creds", () => {
    const { result } = renderStore({
      role: "advisor",
      status: "in_studio",
      startLocked: true,
    });
    act(() => {
      result.current.getState().approve();
      result.current.getState().approveNode("n1");
    });
    // No credentials → guarded before any optimistic mutation; nothing changed.
    expect(result.current.getState().status).toBe("in_studio");
    expect(result.current.getState().nodes[0]!.status).toBe("approved");
  });
});

describe("totals thread through init (ADV-10)", () => {
  test("the graph read's per-currency totals are exposed on the store", () => {
    const { result } = renderStore({ totals: { USD: "1234.00", EUR: "50.00" } });
    expect(result.current.getState().totals).toEqual({ USD: "1234.00", EUR: "50.00" });
  });
  test("defaults to an empty map when omitted", () => {
    const { result } = renderStore();
    expect(result.current.getState().totals).toEqual({});
  });
});

describe("editing actions are inert for non-editable viewers", () => {
  test("traveler (role=client) cannot edit a field, add, or remove", () => {
    const { result } = renderStore({ role: "client" });
    act(() => {
      result.current.getState().editNodeField("n1", "title", "Hacked");
      result.current.getState().addNode({ type: "note", title: "Sneaky" });
      result.current.getState().removeNode("n1");
      result.current.getState().updateCardDetails("n1", { description: "Sneaky" });
    });
    const { nodes } = result.current.getState();
    expect(nodes).toHaveLength(1);
    expect(nodes[0]!.title).toBe("Original");
    expect(nodes[0]!.metadata["description"]).toBeUndefined();
  });

  test("staff with the lock but no credentials cannot mutate (no token → no-op)", () => {
    // Mirrors the prototype sandbox: advisor + startLocked but null creds.
    const { result } = renderStore({ role: "advisor", startLocked: true });
    expect(selectEditable(result.current.getState())).toBe(true);
    act(() => {
      result.current.getState().editNodeField("n1", "title", "Hacked");
      result.current.getState().addNode({ type: "note", title: "Sneaky" });
      result.current.getState().removeNode("n1");
      result.current.getState().updateCardDetails("n1", { description: "Sneaky" });
    });
    const { nodes } = result.current.getState();
    expect(nodes).toHaveLength(1);
    expect(nodes[0]!.title).toBe("Original");
    expect(nodes[0]!.metadata["description"]).toBeUndefined();
  });

  test("a credentialed traveler cannot remove a firmed non-note card", () => {
    // The client-side G1 guard mirrors the backend: an approved/booked/confirmed
    // regular card must be demoted first, so removeNode bails BEFORE the network
    // call even though the traveler holds write credentials.
    const firmed: NodeResponse = {
      ...NODE,
      id: "card-1",
      type: "hotel",
      status: "approved",
      lock_reason: "status_locked",
    };
    const { result } = renderStore({
      timeline: timeline([firmed]),
      role: "client",
      apiBaseUrl: "http://x",
      accessToken: "t",
    });
    act(() => result.current.getState().removeNode("card-1"));
    expect(result.current.getState().nodes).toHaveLength(1);
  });

  test("startLocked seeds locked-by-me; default leaves it unlocked", () => {
    const locked = renderStore({ role: "advisor", startLocked: true });
    expect(locked.result.current.getState().lockStatus).toBe("locked-by-me");
    const unlocked = renderStore({ role: "advisor" });
    expect(unlocked.result.current.getState().lockStatus).toBe("unlocked");
  });

  test("a traveler note action is inert without credentials (no token → no-op)", () => {
    const { result } = renderStore({ role: "client" }); // accessToken null by default
    act(() => {
      result.current.getState().addAttachedNote("n1", "why 1:30?");
    });
    expect(result.current.getState().nodes).toHaveLength(1);
  });
});

describe("editNoteText (the Journal's tap-to-edit margin notes)", () => {
  test("inert without credentials", () => {
    const { result } = renderStore({ role: "client" });
    act(() => result.current.getState().editNoteText("n1", "rewritten"));
    expect(result.current.getState().nodes[0]!.title).toBe("Original");
  });

  test("only note nodes are rewritable through this path", () => {
    // A credentialed viewer on a non-note card bails BEFORE any optimistic
    // mutation or network call — content fields keep their own gates.
    const hotel: NodeResponse = { ...NODE, id: "card-1", type: "hotel" };
    const { result } = renderStore({
      timeline: timeline([hotel]),
      role: "client",
      apiBaseUrl: "http://x",
      accessToken: "t",
    });
    act(() => result.current.getState().editNoteText("card-1", "rewritten"));
    expect(result.current.getState().nodes[0]!.title).toBe("Original");
  });

  test("empty or unchanged text is a no-op (no optimistic churn)", () => {
    const { result } = renderStore({
      role: "client",
      apiBaseUrl: "http://x",
      accessToken: "t",
    });
    act(() => {
      result.current.getState().editNoteText("n1", "   ");
      result.current.getState().editNoteText("n1", "Original");
    });
    expect(result.current.getState().nodes[0]!.title).toBe("Original");
  });
});

describe("selectCanLeaveNote", () => {
  test("needs both apiBaseUrl and accessToken", () => {
    const base = {} as ItineraryGraphState;
    expect(selectCanLeaveNote({ ...base, apiBaseUrl: null, accessToken: null })).toBe(false);
    expect(selectCanLeaveNote({ ...base, apiBaseUrl: "x", accessToken: null })).toBe(false);
    expect(selectCanLeaveNote({ ...base, apiBaseUrl: "x", accessToken: "t" })).toBe(true);
  });
});

describe("selectTravelerEditable", () => {
  const fork = {
    canEdit: false,
    status: "draft",
    apiBaseUrl: "x",
    accessToken: "t",
    sample: { itinerary: { forked_from_id: "base-1" } },
  } as unknown as ItineraryGraphState;

  test("true on the traveler's own draft alternative with creds", () => {
    expect(selectTravelerEditable(fork)).toBe(true);
  });
  test("false for advisors (they use the lock path)", () => {
    expect(selectTravelerEditable({ ...fork, canEdit: true })).toBe(false);
  });
  test("false on the agreed plan (not a fork)", () => {
    const baseline = {
      ...fork,
      sample: { itinerary: { forked_from_id: null } },
    } as unknown as ItineraryGraphState;
    expect(selectTravelerEditable(baseline)).toBe(false);
  });
  test("false once approved, or without creds", () => {
    expect(selectTravelerEditable({ ...fork, status: "approved" })).toBe(false);
    expect(selectTravelerEditable({ ...fork, accessToken: null })).toBe(false);
  });
});

describe("selectIsDraftMine", () => {
  // Baseline (no fork) + draft-mine preview toggled on + creds → editable, and
  // the first edit lazily forks via forkAndMove.
  const draft = {
    canEdit: false,
    status: "draft",
    apiBaseUrl: "x",
    accessToken: "t",
    draftMine: true,
    sample: { itinerary: { forked_from_id: null } },
  } as unknown as ItineraryGraphState;

  test("true on the Official baseline once draft-mine is entered", () => {
    expect(selectIsDraftMine(draft)).toBe(true);
  });
  test("false until draft-mine is entered", () => {
    expect(selectIsDraftMine({ ...draft, draftMine: false })).toBe(false);
  });
  test("false on a real fork (that's the selectTravelerEditable path)", () => {
    const onFork = {
      ...draft,
      sample: { itinerary: { forked_from_id: "base-1" } },
    } as unknown as ItineraryGraphState;
    expect(selectIsDraftMine(onFork)).toBe(false);
  });
  test("role-agnostic: advisors get the same lazy-fork preview", () => {
    // The advisor workspace enters through the same gesture as the traveler's
    // "My version" — one shape for every working copy.
    expect(selectIsDraftMine({ ...draft, canEdit: true })).toBe(true);
  });
  test("false when approved or without creds", () => {
    expect(selectIsDraftMine({ ...draft, status: "approved" })).toBe(false);
    expect(selectIsDraftMine({ ...draft, accessToken: null })).toBe(false);
  });
});

describe("seedFindingsFromGraph (Phase 5 — kernel findings on the graph read)", () => {
  test("expands one kernel finding into one store finding per node", () => {
    const seeded = seedFindingsFromGraph([
      {
        code: "overlap",
        severity: "warn",
        message: "'Lunch' overlaps 'Tour'",
        node_ids: ["n-lunch", "n-tour"],
      },
      {
        code: "flight_infeasible",
        severity: "block",
        message: "arrives after the first item",
        node_ids: ["n-flight"],
      },
    ]);
    expect(seeded).toHaveLength(3);
    const byNode = new Map(seeded.map((f) => [f.node_id, f]));
    expect(byNode.get("n-lunch")?.severity).toBe("warn");
    expect(byNode.get("n-lunch")?.category).toBe("overlap");
    expect(byNode.get("n-flight")?.severity).toBe("block");
    // Synthetic ids are stable + unique so React keys don't collide.
    expect(new Set(seeded.map((f) => f.id)).size).toBe(3);
  });

  test("feeds journalProblems: warn/block become card problems, info does not", () => {
    const seeded = seedFindingsFromGraph([
      {
        code: "flight_tight",
        severity: "warn",
        message: "only 90 min of margin",
        node_ids: ["n1"],
      },
      { code: "stale", severity: "info", message: "re-check", node_ids: ["n2"] },
    ]);
    const problems = journalProblems(
      [NODE, { ...NODE, id: "n2" }],
      seeded,
    );
    expect(problems.get("n1")?.severity).toBe("warn");
    expect(problems.get("n1")?.message).toBe("only 90 min of margin");
    expect(problems.has("n2")).toBe(false); // info is advisory, not a badge
  });
});
