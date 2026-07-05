// Planner shell (M006/PS1): the routed three-region shell — places (Rail) ·
// people (ConciergeColumn) · the planning space (children) — plus the first-run
// intake gate. Heavy leaves (the real chat, the intake form, next/link's router)
// are stubbed so these assert the SHELL's structure + gating, not their guts.

import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, test, vi } from "vitest";

// usePathname is mutated per-test to drive the rail's active state.
const nav = vi.hoisted(() => ({ pathname: "/itinerary/it-1/timeline" }));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
  usePathname: () => nav.pathname,
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

// The concierge's session thread fetches + streams; stub it to its audience so
// these assert the ConciergeColumn STRUCTURE (SessionThread has its own test).
vi.mock("@/app/itinerary/[id]/_shell/SessionThread", () => ({
  SessionThread: ({ audience }: { audience: string }) => (
    <div data-testid={`thread-${audience}`} />
  ),
}));

// The intake is exercised elsewhere; here it only needs to prove the gate flips.
vi.mock("@/app/_components/itinerary-graph/intake/ItineraryIntake", () => ({
  ItineraryIntake: ({ onSaved }: { onSaved: () => void }) => (
    <button type="button" data-testid="intake-save" onClick={onSaved}>
      save
    </button>
  ),
}));

import type {
  ItineraryResponse,
  NodeResponse,
} from "@ov-black/api-client";

import type { ItineraryTimeline } from "@/app/_components/itinerary-graph/model/types";
import {
  itineraryGraphStore,
  type ItineraryGraphInit,
} from "@/app/_components/itinerary-graph/store/itineraryGraphStore";
import { TimelineDataProvider } from "@/app/_components/itinerary-graph/TimelineDataContext";
import type { UserRole } from "@/lib/role";

import { ItineraryShell } from "@/app/itinerary/[id]/_shell/ItineraryShell";
import { Rail } from "@/app/itinerary/[id]/_shell/Rail";
import { ConciergeColumn } from "@/app/itinerary/[id]/_shell/ConciergeColumn";

const ITINERARY: ItineraryResponse = {
  id: "it-1",
  title: "Trip",
  client_id: "c-1",
  created_by: "u-1",
  status: "draft",
};

function timeline(forkedFromId?: string): ItineraryTimeline {
  return {
    id: "it-1",
    label: "Trip",
    subtitle: "",
    mood: "verdant",
    timezoneOffsetHours: 9,
    windowStart: "2024-06-20T00:00:00+09:00",
    windowEnd: "2024-06-20T23:59:00+09:00",
    days: [{ date: "2024-06-20", label: "Day 1" }],
    itinerary: forkedFromId
      ? { ...ITINERARY, forked_from_id: forkedFromId }
      : ITINERARY,
    nodes: [] as NodeResponse[],
    edges: [],
  };
}

function init(role: UserRole, forkedFromId?: string): ItineraryGraphInit {
  return {
    timeline: timeline(forkedFromId),
    itineraryId: "it-1",
    status: "draft",
    role,
    apiBaseUrl: "http://api.test",
    accessToken: "tok",
  };
}

/** Wrap a shell child in the same two providers the shell mounts. Pass a
 *  `forkedFromId` to make the trip an alternative version (surfaces Studio). */
function withProviders(role: UserRole, ui: ReactNode, forkedFromId?: string) {
  return (
    <itineraryGraphStore.Provider initial={init(role, forkedFromId)}>
      <TimelineDataProvider
        value={{ timeline: timeline(forkedFromId), baselineTitle: null }}
      >
        {ui}
      </TimelineDataProvider>
    </itineraryGraphStore.Provider>
  );
}

function renderShell(
  role: UserRole,
  overrides: Partial<React.ComponentProps<typeof ItineraryShell>> = {},
) {
  return render(
    <ItineraryShell
      timeline={timeline()}
      baselineTitle={null}
      itineraryId="it-1"
      status="draft"
      role={role}
      apiBaseUrl="http://api.test"
      accessToken="tok"
      viewerOpenForkId={null}
      needsBrief={false}
      audience={role === "advisor" ? "advisor" : "traveler"}
      {...overrides}
    >
      <div data-testid="planning-child">the view</div>
    </ItineraryShell>,
  );
}

describe("ItineraryShell · three regions", () => {
  test("renders rail, concierge, planning space, mobile tab bar, and the child view", () => {
    renderShell("client");
    expect(screen.getByTestId("planner-rail")).toBeTruthy();
    expect(screen.getByTestId("concierge")).toBeTruthy();
    const space = screen.getByTestId("planning-space");
    expect(within(space).getByTestId("planning-child")).toBeTruthy();
    expect(screen.getByTestId("mobile-tab-bar")).toBeTruthy();
  });

  test("the routed child renders under the shared graph store", () => {
    // A probe child reading the store proves children sit under the Provider the
    // shell lifted up — the same instance the concierge reads.
    function Probe() {
      const id = itineraryGraphStore.useStore((s) => s.itineraryId);
      return <div data-testid="probe">{id}</div>;
    }
    render(
      <ItineraryShell
        timeline={timeline()}
        baselineTitle={null}
        itineraryId="it-1"
        status="draft"
        role="client"
        apiBaseUrl="http://api.test"
        accessToken="tok"
        viewerOpenForkId={null}
        needsBrief={false}
        audience="traveler"
      >
        <Probe />
      </ItineraryShell>,
    );
    expect(screen.getByTestId("probe").textContent).toBe("it-1");
  });
});

describe("ItineraryShell · first-run intake gate", () => {
  test("needsBrief shows the intake and withholds the shell until saved", () => {
    renderShell("advisor", { needsBrief: true });
    // Gated: intake up, no shell chrome yet.
    expect(screen.getByTestId("intake-save")).toBeTruthy();
    expect(screen.queryByTestId("planner-rail")).toBeNull();
    // Saving the brief drops the gate and mounts the shell.
    fireEvent.click(screen.getByTestId("intake-save"));
    expect(screen.getByTestId("planner-rail")).toBeTruthy();
    expect(screen.queryByTestId("intake-save")).toBeNull();
  });
});

describe("ItineraryShell · concierge collapse (Q5)", () => {
  test("collapses the ≥1100px column to an edge tab and reopens", () => {
    renderShell("client");
    const aside = screen.getByTestId("concierge-column");
    expect(aside.getAttribute("data-collapsed")).toBe("false");
    expect(screen.queryByTestId("concierge-reopen")).toBeNull();

    fireEvent.click(screen.getByTestId("concierge-collapse"));
    expect(aside.getAttribute("data-collapsed")).toBe("true");

    fireEvent.click(screen.getByTestId("concierge-reopen"));
    expect(aside.getAttribute("data-collapsed")).toBe("false");
    expect(screen.queryByTestId("concierge-reopen")).toBeNull();
  });
});

describe("Rail · places axis", () => {
  test("advisor on a normal trip sees Home, Timeline, Collection — but no Studio (Diff-only now)", () => {
    render(withProviders("advisor", <Rail onOpenConcierge={() => {}} />));
    const rail = screen.getByTestId("planner-rail");
    expect(within(rail).getByTestId("rail-home").getAttribute("href")).toBe(
      "/itinerary/it-1/dashboard",
    );
    expect(within(rail).getByTestId("rail-timeline").getAttribute("href")).toBe(
      "/itinerary/it-1/timeline",
    );
    expect(
      within(rail).getByTestId("rail-collection").getAttribute("href"),
    ).toBe("/itinerary/it-1/collection");
    // Studio is Diff-only — nothing to reconcile on a non-alternative trip.
    expect(within(rail).queryByTestId("rail-studio")).toBeNull();
  });

  test("advisor on an alternative version sees the Studio (reconcile) noun", () => {
    render(withProviders("advisor", <Rail onOpenConcierge={() => {}} />, "base-1"));
    const rail = screen.getByTestId("planner-rail");
    expect(within(rail).getByTestId("rail-studio").getAttribute("href")).toBe(
      "/itinerary/it-1/studio",
    );
  });

  test("a traveler never sees Studio, even on an alternative", () => {
    render(withProviders("client", <Rail onOpenConcierge={() => {}} />, "base-1"));
    expect(screen.queryByTestId("rail-studio")).toBeNull();
    expect(screen.getByTestId("rail-timeline")).toBeTruthy();
  });

  test("the top item is a role-aware return home (PS7 — replaces the header crumb)", () => {
    render(withProviders("client", <Rail onOpenConcierge={() => {}} />));
    const back = screen.getByTestId("rail-back");
    expect(back.getAttribute("href")).toBe("/basecamp");
    expect(back.textContent).toContain("Basecamp");

    cleanup();
    render(withProviders("advisor", <Rail onOpenConcierge={() => {}} />));
    const advisorBack = screen.getByTestId("rail-back");
    expect(advisorBack.getAttribute("href")).toBe("/command-center/clients");
    expect(advisorBack.textContent).toContain("Clients");
  });

  test("the active destination is marked from the pathname", () => {
    nav.pathname = "/itinerary/it-1/collection";
    render(withProviders("client", <Rail onOpenConcierge={() => {}} />));
    expect(
      screen.getByTestId("rail-collection").getAttribute("aria-current"),
    ).toBe("page");
    expect(
      screen.getByTestId("rail-timeline").getAttribute("aria-current"),
    ).toBeNull();
    nav.pathname = "/itinerary/it-1/timeline"; // reset for other tests
  });
});

describe("ConciergeColumn · people axis", () => {
  test("an advisor gets a single PRIVATE Artemis thread + people circles (no audience tabs)", () => {
    render(withProviders("advisor", <ConciergeColumn onClose={() => {}} />));
    expect(screen.getByTestId("people-circles")).toBeTruthy();
    expect(screen.getByTestId("person-artemis")).toBeTruthy();
    // The private/shared audience split is gone — the client-facing conversation
    // is the human "Client" circle, not a second AI tab.
    expect(screen.queryByTestId("concierge-thread-tabs")).toBeNull();
    expect(screen.getByTestId("thread-advisor")).toBeTruthy();
    expect(screen.queryByTestId("thread-traveler")).toBeNull();
  });

  test("a traveler gets a single shared thread, no audience tabs", () => {
    render(withProviders("client", <ConciergeColumn onClose={() => {}} />));
    expect(screen.queryByTestId("concierge-thread-tabs")).toBeNull();
    expect(screen.getByTestId("thread-traveler")).toBeTruthy();
    expect(screen.queryByTestId("thread-advisor")).toBeNull();
  });
});
