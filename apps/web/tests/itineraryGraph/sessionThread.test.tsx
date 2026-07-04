// SessionThread (M006/PS2) — the scoped Artemis session LIST: browse, resume,
// start (force_new), rename, archive, and bind the active thread to a session
// id. The chat leaf + the api-client are stubbed so these assert the list
// behaviour without a backend or a real stream.

import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, test, vi } from "vitest";

const apiState = vi.hoisted(() => ({
  sessions: [] as Array<{ session_id: string; title: string | null; started_at: string }>,
  listCalls: [] as unknown[],
  created: [] as Array<{ force_new?: boolean }>,
  patched: [] as Array<{ id: string; body: { title?: string; archived?: boolean } }>,
}));

vi.mock("@ov-black/api-client", () => ({
  createApiClient: vi.fn(() => ({})),
  listSessions: vi.fn(async (_c: unknown, q: unknown) => {
    apiState.listCalls.push(q);
    return { ok: true, sessions: apiState.sessions };
  }),
  createSessionEndpoint: vi.fn(async (_c: unknown, body: { force_new?: boolean }) => {
    apiState.created.push(body);
    const id = `new-${apiState.created.length}`;
    apiState.sessions = [
      { session_id: id, title: null, started_at: "2024-01-03T00:00:00Z" },
      ...apiState.sessions,
    ];
    return { ok: true, session_id: id, agentcore_session_id: "ac", itinerary_id: null, seeded_opener: null };
  }),
  patchSession: vi.fn(
    async (_c: unknown, id: string, body: { title?: string; archived?: boolean }) => {
      apiState.patched.push({ id, body });
      if (body.archived) {
        apiState.sessions = apiState.sessions.filter((s) => s.session_id !== id);
      }
      return { ok: true, session: { session_id: id, title: body.title ?? null, started_at: "x" } };
    },
  ),
}));

vi.mock(
  "@/app/_components/itinerary-graph/views/horizontal/ConciergeChat",
  () => ({
    ConciergeChat: ({ sessionId }: { sessionId?: string }) => (
      <div data-testid="chat" data-session={sessionId ?? "draft"} />
    ),
  }),
);

import { SessionThread } from "@/app/itinerary/[id]/_shell/SessionThread";

function renderThread() {
  return render(
    <SessionThread
      audience="traveler"
      clientId="c-1"
      itineraryId="it-1"
      apiBaseUrl="http://api.test"
      accessToken="tok"
    />,
  );
}

beforeEach(() => {
  apiState.sessions = [
    { session_id: "s-2", title: "Kaiseki plans", started_at: "2024-01-02T00:00:00Z" },
    { session_id: "s-1", title: "First ideas", started_at: "2024-01-01T00:00:00Z" },
  ];
  apiState.listCalls = [];
  apiState.created = [];
  apiState.patched = [];
});

describe("SessionThread", () => {
  test("resumes the most-recent session and binds the chat to it", async () => {
    renderThread();
    expect(await screen.findByText("Kaiseki plans")).toBeTruthy();
    expect(screen.getByTestId("chat").getAttribute("data-session")).toBe("s-2");
    // The list is scope-filtered by (client, audience, itinerary).
    expect(apiState.listCalls[0]).toMatchObject({
      clientId: "c-1",
      audience: "traveler",
      itineraryId: "it-1",
    });
  });

  test("browsing the list and resuming an older session rebinds the chat", async () => {
    renderThread();
    await screen.findByText("Kaiseki plans");
    fireEvent.click(screen.getByTestId("session-bar"));
    const rows = screen.getAllByTestId("session-row");
    expect(rows).toHaveLength(2);
    fireEvent.click(within(rows[1]!).getByTestId("session-resume"));
    await waitFor(() =>
      expect(screen.getByTestId("chat").getAttribute("data-session")).toBe("s-1"),
    );
  });

  test("New starts a fresh session with force_new and binds to it", async () => {
    renderThread();
    await screen.findByText("Kaiseki plans");
    fireEvent.click(screen.getByTestId("session-new"));
    await waitFor(() => expect(apiState.created).toHaveLength(1));
    expect(apiState.created[0]!.force_new).toBe(true);
    await waitFor(() =>
      expect(screen.getByTestId("chat").getAttribute("data-session")).toBe("new-1"),
    );
  });

  test("Rename patches the title", async () => {
    renderThread();
    await screen.findByText("Kaiseki plans");
    fireEvent.click(screen.getByTestId("session-bar"));
    const rows = screen.getAllByTestId("session-row");
    fireEvent.click(within(rows[1]!).getByTestId("session-rename"));
    const input = screen.getByTestId("session-rename-input");
    fireEvent.change(input, { target: { value: "Onsen weekend" } });
    fireEvent.blur(input);
    await waitFor(() =>
      expect(
        apiState.patched.some((p) => p.id === "s-1" && p.body.title === "Onsen weekend"),
      ).toBe(true),
    );
  });

  test("Archive soft-hides a session", async () => {
    renderThread();
    await screen.findByText("Kaiseki plans");
    fireEvent.click(screen.getByTestId("session-bar"));
    const rows = screen.getAllByTestId("session-row");
    fireEvent.click(within(rows[0]!).getByTestId("session-archive"));
    await waitFor(() =>
      expect(
        apiState.patched.some((p) => p.id === "s-2" && p.body.archived === true),
      ).toBe(true),
    );
  });

  test("an empty scope shows a fresh draft thread", async () => {
    apiState.sessions = [];
    renderThread();
    await waitFor(() => expect(apiState.listCalls.length).toBeGreaterThan(0));
    expect(screen.getByTestId("chat").getAttribute("data-session")).toBe("draft");
    expect(screen.getByText("New conversation")).toBeTruthy();
  });
});
