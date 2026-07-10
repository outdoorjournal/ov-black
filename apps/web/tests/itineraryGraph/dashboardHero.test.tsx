// Hero edit-in-place (traveler-journal design, phase 2). Each hero element —
// title, brief, timing — is its own inline editor styled like its display
// state. These pin the save semantics: title commits on blur/Enter, brief on
// blur, timing through the popover's Save; every commit PATCHes the itinerary
// and then router.refresh()es (brief/timing are a server prop). Escape always
// bails without a network call, and a credential-less viewer gets plain text —
// no editors at all.

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, test, vi } from "vitest";

const refreshMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: refreshMock }),
  usePathname: () => "/itinerary/it-1/dashboard",
}));

const updateItineraryMock = vi.fn();
vi.mock("@ov-black/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@ov-black/api-client")>();
  return {
    ...actual,
    createApiClient: vi.fn(() => ({})),
    updateItinerary: (...args: unknown[]) => updateItineraryMock(...args),
  };
});

import type { ItineraryResponse } from "@ov-black/api-client";

import type { ItineraryTimeline } from "@/app/_components/itinerary-graph/model/types";
import {
  itineraryGraphStore,
  type ItineraryGraphInit,
} from "@/app/_components/itinerary-graph/store/itineraryGraphStore";
import { TimelineDataProvider } from "@/app/_components/itinerary-graph/TimelineDataContext";
import { DashboardHero } from "@/app/itinerary/[id]/_shell/DashboardHero";

const ITINERARY: ItineraryResponse = {
  id: "it-1",
  title: "Sailing in Greece",
  client_id: "c-1",
  created_by: "u-1",
  display_status: "in_studio",
  brief: "Two weeks island-hopping with the family",
  timing_kind: "exact",
  date_start: "2024-06-20",
  date_end: "2024-07-04",
};

function timeline(): ItineraryTimeline {
  return {
    id: "it-1",
    label: "Sailing in Greece",
    subtitle: "",
    mood: "tidal",
    timezoneOffsetHours: 3,
    windowStart: "2024-06-20T00:00:00+03:00",
    windowEnd: "2024-07-04T23:59:00+03:00",
    days: [{ date: "2024-06-20", label: "Day 1" }],
    itinerary: ITINERARY,
    nodes: [],
    edges: [],
  };
}

function renderHero(partial: Partial<ItineraryGraphInit> = {}) {
  const init: ItineraryGraphInit = {
    timeline: timeline(),
    itineraryId: "it-1",
    status: "in_studio",
    role: "client",
    apiBaseUrl: "http://api.test",
    accessToken: "tok",
    ...partial,
  };
  return render(
    <itineraryGraphStore.Provider initial={init}>
      <TimelineDataProvider value={{ timeline: timeline(), baselineTitle: null }}>
        <DashboardHero />
      </TimelineDataProvider>
    </itineraryGraphStore.Provider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  updateItineraryMock.mockResolvedValue({ ok: true, itinerary: ITINERARY });
});

describe("DashboardHero · title", () => {
  test("click → an input prefilled with the title; Enter commits + refreshes", async () => {
    renderHero();
    fireEvent.click(screen.getByTestId("hero-title"));
    const input = screen.getByTestId("hero-title-input");
    expect(input).toHaveValue("Sailing in Greece");

    fireEvent.change(input, { target: { value: "Aegean drift" } });
    fireEvent.keyDown(input, { key: "Enter" });
    fireEvent.blur(input); // Enter blurs; jsdom needs the explicit event

    await waitFor(() =>
      expect(updateItineraryMock).toHaveBeenCalledWith(expect.anything(), "it-1", {
        title: "Aegean drift",
      }),
    );
    expect(updateItineraryMock).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(refreshMock).toHaveBeenCalled());
    // Optimistic: the new title shows before the server prop lands.
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Aegean drift");
  });

  test("an unchanged or emptied title saves nothing", () => {
    renderHero();
    fireEvent.click(screen.getByTestId("hero-title"));
    const input = screen.getByTestId("hero-title-input");
    fireEvent.change(input, { target: { value: "   " } });
    fireEvent.blur(input);
    expect(updateItineraryMock).not.toHaveBeenCalled();
    // Display falls back to what was there.
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Sailing in Greece");
  });

  test("Escape bails without saving", () => {
    renderHero();
    fireEvent.click(screen.getByTestId("hero-title"));
    const input = screen.getByTestId("hero-title-input");
    fireEvent.change(input, { target: { value: "Abandoned" } });
    fireEvent.keyDown(input, { key: "Escape" });
    expect(screen.queryByTestId("hero-title-input")).not.toBeInTheDocument();
    expect(updateItineraryMock).not.toHaveBeenCalled();
  });
});

describe("DashboardHero · brief", () => {
  test("click → a textarea; blur commits the new brief", async () => {
    renderHero();
    fireEvent.click(screen.getByTestId("hero-brief"));
    const area = screen.getByTestId("hero-brief-input");
    expect(area).toHaveValue("Two weeks island-hopping with the family");

    fireEvent.change(area, { target: { value: "Slow days on small islands" } });
    fireEvent.blur(area);

    await waitFor(() =>
      expect(updateItineraryMock).toHaveBeenCalledWith(expect.anything(), "it-1", {
        brief: "Slow days on small islands",
      }),
    );
    await waitFor(() => expect(refreshMock).toHaveBeenCalled());
  });
});

describe("DashboardHero · timing popover", () => {
  test("click → a popover with the shared timing controls; Save PATCHes timing", async () => {
    renderHero();
    fireEvent.click(screen.getByTestId("hero-timing"));
    const popover = screen.getByTestId("hero-timing-popover");
    expect(popover).toBeInTheDocument();

    // Switch to flexible + a constraints note — dates must clear (nulls).
    fireEvent.click(screen.getByTestId("timing-mode-flexible"));
    fireEvent.change(screen.getByTestId("hero-timing-note"), {
      target: { value: "not August" },
    });
    fireEvent.click(screen.getByTestId("hero-timing-save"));

    await waitFor(() =>
      expect(updateItineraryMock).toHaveBeenCalledWith(expect.anything(), "it-1", {
        timing_kind: "flexible",
        timing_note: "not August",
        date_start: null,
        date_end: null,
        duration_nights: null,
      }),
    );
    // A popover, not a page takeover — it closes itself after the save.
    await waitFor(() =>
      expect(screen.queryByTestId("hero-timing-popover")).not.toBeInTheDocument(),
    );
    await waitFor(() => expect(refreshMock).toHaveBeenCalled());
  });

  test("Escape closes the popover without saving", () => {
    renderHero();
    fireEvent.click(screen.getByTestId("hero-timing"));
    expect(screen.getByTestId("hero-timing-popover")).toBeInTheDocument();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByTestId("hero-timing-popover")).not.toBeInTheDocument();
    expect(updateItineraryMock).not.toHaveBeenCalled();
  });
});

describe("DashboardHero · credential-less viewer", () => {
  test("renders plain text — no inline editors at all", () => {
    renderHero({ apiBaseUrl: null, accessToken: null });
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Sailing in Greece");
    expect(screen.queryByTestId("hero-title")).not.toBeInTheDocument();
    expect(screen.queryByTestId("hero-brief")).not.toBeInTheDocument();
    expect(screen.queryByTestId("hero-timing")).not.toBeInTheDocument();
  });
});
