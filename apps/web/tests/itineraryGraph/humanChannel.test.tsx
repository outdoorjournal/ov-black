// M006/PS7 — the human messaging channel: the HumanThread transcript/composer
// and the human people-circle that summons it (labelled "Client" advisor-side,
// "Advisor" traveler-side — the other party in the conversation). The network
// wrappers (openThread / listMessages / sendMessage) are stubbed so these assert
// the UI behaviour; the service + RLS have their own pytest suite.

import type { ReactNode } from "react";

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, test, vi } from "vitest";

const openThread = vi.fn();
const listMessages = vi.fn();
const sendMessage = vi.fn();

vi.mock("@ov-black/api-client", () => ({
  createApiClient: () => ({}),
  openThread: (...args: unknown[]) => openThread(...args),
  listMessages: (...args: unknown[]) => listMessages(...args),
  sendMessage: (...args: unknown[]) => sendMessage(...args),
}));

// The Artemis session list has its own suite; stub it to its audience so the
// ConciergeColumn switch test doesn't drive its fetch/stream.
vi.mock("@/app/itinerary/[id]/_shell/SessionThread", () => ({
  SessionThread: ({ audience }: { audience: string }) => (
    <div data-testid={`thread-${audience}`} />
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

import { ConciergeColumn } from "@/app/itinerary/[id]/_shell/ConciergeColumn";
import { HumanThread } from "@/app/itinerary/[id]/_shell/HumanThread";

const ITINERARY: ItineraryResponse = {
  id: "it-1",
  title: "Trip",
  client_id: "c-1",
  created_by: "u-1",
  display_status: "in_studio",
};

function timeline(): ItineraryTimeline {
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
    nodes: [] as NodeResponse[],
    edges: [],
  };
}

function init(role: UserRole): ItineraryGraphInit {
  return {
    timeline: timeline(),
    itineraryId: "it-1",
    status: "in_studio",
    role,
    apiBaseUrl: "http://api.test",
    accessToken: "tok",
  };
}

function withProviders(role: UserRole, ui: ReactNode) {
  return (
    <itineraryGraphStore.Provider initial={init(role)}>
      <TimelineDataProvider value={{ timeline: timeline(), baselineTitle: null }}>
        {ui}
      </TimelineDataProvider>
    </itineraryGraphStore.Provider>
  );
}

function msg(over: Partial<Record<string, unknown>>) {
  return {
    id: "m",
    thread_id: "th-1",
    author_kind: "advisor",
    author_id: "u1",
    content: "hi",
    proposed_node_id: null,
    parent_message_id: null,
    created_at: "2024-01-01T00:00:00Z",
    edited_at: null,
    ...over,
  };
}

beforeEach(() => {
  openThread.mockReset();
  listMessages.mockReset();
  sendMessage.mockReset();
  openThread.mockResolvedValue({ ok: true, thread: { thread_id: "th-1" } });
  listMessages.mockResolvedValue({ ok: true, messages: [] });
});

describe("HumanThread", () => {
  test("resolves the thread, loads history, and aligns the viewer's own messages", async () => {
    listMessages.mockResolvedValue({
      ok: true,
      messages: [
        msg({ id: "m1", author_kind: "advisor", content: "Welcome aboard" }),
        msg({ id: "m2", author_kind: "traveler", content: "Thank you!" }),
      ],
    });
    render(
      <HumanThread
        clientId="c-1"
        itineraryId="it-1"
        apiBaseUrl="http://api.test"
        accessToken="tok"
        viewerKind="advisor"
      />,
    );
    await waitFor(() =>
      expect(screen.getAllByTestId("human-message")).toHaveLength(2),
    );
    // get-or-create was scoped to this client + itinerary.
    expect(openThread).toHaveBeenCalledWith(expect.anything(), {
      clientId: "c-1",
      itineraryId: "it-1",
    });
    const rows = screen.getAllByTestId("human-message");
    // The advisor viewer's own (advisor) message is "mine"; the traveler's isn't.
    expect(rows[0]?.getAttribute("data-mine")).toBe("true");
    expect(rows[1]?.getAttribute("data-mine")).toBe("false");
  });

  test("sending posts a human message, appends it, and clears the composer", async () => {
    sendMessage.mockResolvedValue({
      ok: true,
      message: msg({ id: "m3", author_kind: "advisor", content: "On my way" }),
    });
    render(
      <HumanThread
        clientId="c-1"
        itineraryId="it-1"
        apiBaseUrl="http://api.test"
        accessToken="tok"
        viewerKind="advisor"
      />,
    );
    const composer = (await screen.findByTestId(
      "human-composer",
    )) as HTMLTextAreaElement;
    fireEvent.change(composer, { target: { value: "On my way" } });
    fireEvent.click(screen.getByTestId("human-send"));

    await waitFor(() =>
      expect(sendMessage).toHaveBeenCalledWith(expect.anything(), "th-1", {
        content: "On my way",
      }),
    );
    await waitFor(() => expect(screen.getByText("On my way")).toBeTruthy());
    expect(composer.value).toBe("");
  });

  test("basecamp scope (no itineraryId) resolves the you-↔-advisor thread", async () => {
    render(
      <HumanThread
        clientId="c-1"
        apiBaseUrl="http://api.test"
        accessToken="tok"
        viewerKind="traveler"
      />,
    );
    // No itineraryId passed → the backend resolves the basecamp thread; the
    // wrapper is called with a null itinerary scope.
    await waitFor(() =>
      expect(openThread).toHaveBeenCalledWith(expect.anything(), {
        clientId: "c-1",
        itineraryId: null,
      }),
    );
  });

  test("a resolve failure shows the unavailable state and disables the composer", async () => {
    openThread.mockResolvedValue({
      ok: false,
      status: 404,
      detail: "thread_not_found",
    });
    render(
      <HumanThread
        clientId="c-1"
        itineraryId="it-1"
        apiBaseUrl="http://api.test"
        accessToken="tok"
        viewerKind="traveler"
      />,
    );
    await waitFor(() => expect(screen.getByTestId("human-error")).toBeTruthy());
    expect(
      (screen.getByTestId("human-composer") as HTMLTextAreaElement).disabled,
    ).toBe(true);
  });
});

describe("HumanThread · @Artemis summon (PS8)", () => {
  test("Ask Artemis prepends the mention (once) and keeps the typed text", async () => {
    render(
      <HumanThread
        clientId="c-1"
        itineraryId="it-1"
        apiBaseUrl="http://api.test"
        accessToken="tok"
        viewerKind="traveler"
      />,
    );
    const composer = (await screen.findByTestId(
      "human-composer",
    )) as HTMLTextAreaElement;
    fireEvent.change(composer, { target: { value: "what about dinner?" } });
    fireEvent.click(screen.getByTestId("human-ask-artemis"));
    expect(composer.value).toBe("@Artemis what about dinner?");
    // Idempotent — a second click never doubles the mention.
    fireEvent.click(screen.getByTestId("human-ask-artemis"));
    expect(composer.value).toBe("@Artemis what about dinner?");
  });

  test("sending an @Artemis message shows the composing hint until the reply lands", async () => {
    sendMessage.mockResolvedValue({
      ok: true,
      message: msg({ id: "u1", author_kind: "traveler", content: "@Artemis dinner ideas?" }),
    });
    render(
      <HumanThread
        clientId="c-1"
        itineraryId="it-1"
        apiBaseUrl="http://api.test"
        accessToken="tok"
        viewerKind="traveler"
      />,
    );
    const composer = (await screen.findByTestId(
      "human-composer",
    )) as HTMLTextAreaElement;
    fireEvent.change(composer, { target: { value: "@Artemis dinner ideas?" } });
    fireEvent.click(screen.getByTestId("human-send"));

    // The composing hint appears once the send resolves.
    await waitFor(() =>
      expect(screen.getByTestId("human-artemis-pending")).toBeTruthy(),
    );

    // The summoned reply lands on the next (faster) poll → hint clears, reply renders.
    listMessages.mockResolvedValue({
      ok: true,
      messages: [
        msg({ id: "u1", author_kind: "traveler", content: "@Artemis dinner ideas?" }),
        msg({ id: "a1", author_kind: "artemis", content: "A quiet kaiseki would suit." }),
      ],
    });
    await waitFor(
      () => expect(screen.queryByTestId("human-artemis-pending")).toBeNull(),
      { timeout: 4000 },
    );
    expect(screen.getByText("A quiet kaiseki would suit.")).toBeTruthy();
  });

  test("an Artemis message renders explicit AI attribution + rich prose", async () => {
    listMessages.mockResolvedValue({
      ok: true,
      messages: [
        // A human message stays plain; the Artemis one flows through ProseMessage.
        msg({ id: "u0", author_kind: "traveler", content: "where next?" }),
        msg({ id: "a1", author_kind: "artemis", content: "Consider a private onsen." }),
      ],
    });
    render(
      <HumanThread
        clientId="c-1"
        itineraryId="it-1"
        apiBaseUrl="http://api.test"
        accessToken="tok"
        viewerKind="traveler"
      />,
    );
    await waitFor(() =>
      expect(screen.getByText("Consider a private onsen.")).toBeTruthy(),
    );
    const rows = screen.getAllByTestId("human-message");
    const artemisRow = rows.find((r) => r.getAttribute("data-author") === "artemis");
    expect(artemisRow).toBeTruthy();
    // Named, distinct from the human "Advisor" — unmistakably the concierge AI.
    expect(screen.getByText("Artemis · concierge")).toBeTruthy();
    // Same renderer as the Artemis chat (markdown + place: chips), only for Artemis.
    const proses = screen.getAllByTestId("prose-message");
    expect(proses).toHaveLength(1);
    expect(artemisRow?.contains(proses[0]!)).toBe(true);
  });
});

describe("ConciergeColumn · Client people-circle summons the human channel", () => {
  test("clicking Client mounts the human thread; Artemis switches back", async () => {
    render(withProviders("advisor", <ConciergeColumn onClose={() => {}} />));

    // Defaults to Artemis — no human thread yet.
    expect(screen.queryByTestId("human-thread")).toBeNull();
    expect(screen.getByTestId("person-artemis").getAttribute("data-active")).toBe(
      "true",
    );

    // The advisor's human channel is labelled by the other party — the Client.
    fireEvent.click(screen.getByTestId("person-client"));
    await waitFor(() => expect(screen.getByTestId("human-thread")).toBeTruthy());
    expect(screen.getByTestId("person-client").getAttribute("data-active")).toBe(
      "true",
    );

    // Back to Artemis unmounts the (streamless) human body.
    fireEvent.click(screen.getByTestId("person-artemis"));
    expect(screen.queryByTestId("human-thread")).toBeNull();
  });
});
