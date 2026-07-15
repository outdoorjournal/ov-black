// B7 — ConciergeChat: the self-contained, audience-scoped agent conversation
// the itinerary view mounts twice (private advisor workspace + shared client
// thread). The api-client session wrappers, the SSE hook, and the browser
// Supabase client are mocked so we assert the component's own wiring without a
// live backend:
//   - lazy session open (nothing on mount; opens on first submit),
//   - the `audience` prop plumbs straight into POST /sessions,
//   - `hydrateHistory` eagerly opens + replays prior turns with role mapping,
//   - a missing chat context (no token) keeps the composer inert.
// The streaming itself (frames → DOM) is covered by s05; here useAgentStream is
// a stub so we only check that a submitted turn is handed to it.

import { fireEvent, render, screen, waitFor, act } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";

// The SSE hook is stubbed: `sendTurn` records the submitted text and then fires
// the captured `onDone` so the component clears its `streaming` flag exactly as
// a real `done` frame would — otherwise the composer would stay disabled and a
// follow-up turn couldn't be sent.
const { sendTurnMock, lastConfigRef } = vi.hoisted(() => {
  const lastConfigRef = {
    current: null as null | {
      onDone?: () => void;
      onDelta?: (frame: { text: string }) => void;
    },
  };
  const sendTurnMock = vi.fn(async () => {
    lastConfigRef.current?.onDone?.();
  });
  return { sendTurnMock, lastConfigRef };
});

vi.mock("@ov-black/api-client", () => ({
  createApiClient: vi.fn(() => ({})),
  createSessionEndpoint: vi.fn(),
  listTurns: vi.fn(),
  campaignKickoff: vi.fn(),
}));

vi.mock("@/lib/agentStream", () => ({
  useAgentStream: (config: { onDone?: () => void }) => {
    lastConfigRef.current = config;
    return { sendTurn: sendTurnMock };
  },
}));

// The component creates a browser Supabase client inside a try/catch and falls
// back to the `accessToken` prop; force the catch so the test never touches env.
vi.mock("@/lib/supabase/client", () => ({
  createBrowserSupabase: () => {
    throw new Error("no Supabase client in jsdom test");
  },
}));

// ConciergeChat calls useRouter().refresh() on the `itinerary_updated` frame to
// re-pull server-rendered trip timing. jsdom has no app-router context, so stub
// it; the stubbed useAgentStream never fires that frame, so refresh is unused.
vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: vi.fn(), push: vi.fn(), replace: vi.fn() }),
}));

import {
  campaignKickoff,
  createSessionEndpoint,
  listTurns,
  type AgentTurnSummary,
  type EdgeResponse,
  type ItineraryResponse,
  type NodeResponse,
  type TurnRole,
} from "@ov-black/api-client";

import type { ItineraryTimeline } from "@/app/_components/itinerary-graph/model/types";
import {
  itineraryGraphStore,
  type ItineraryGraphInit,
} from "@/app/_components/itinerary-graph/store/itineraryGraphStore";
import { ConciergeChat } from "@/app/_components/itinerary-graph/views/horizontal/ConciergeChat";

// ── store scaffolding (a minimal valid graph so the Provider mounts) ─────────

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
  metadata: {},
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
    nodes: [NODE],
    edges: [] as EdgeResponse[],
  };
}

function storeInit(): ItineraryGraphInit {
  return {
    timeline: timeline(),
    itineraryId: "it-1",
    status: "in_studio",
    role: "advisor",
    apiBaseUrl: "http://api.test",
    accessToken: "tok",
    startLocked: true,
  };
}

function turn(id: string, role: TurnRole, content: string): AgentTurnSummary {
  return {
    id,
    turn_index: 0,
    role,
    content,
    model: null,
    latency_ms: null,
    first_token_ms: null,
    retried: 0,
    error_reason: null,
    created_at: "2024-06-20T00:00:00Z",
  };
}

function renderConcierge(
  props: Partial<React.ComponentProps<typeof ConciergeChat>> = {},
) {
  return render(
    <itineraryGraphStore.Provider initial={storeInit()}>
      <ConciergeChat
        audience="advisor"
        apiBaseUrl="http://api.test"
        accessToken="tok"
        clientId="c-1"
        itineraryId="it-1"
        {...props}
      />
    </itineraryGraphStore.Provider>,
  );
}

// Let the component's fire-and-forget open/hydrate promise chains settle.
async function flush() {
  await act(async () => {
    await new Promise((r) => setTimeout(r, 0));
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(createSessionEndpoint).mockResolvedValue({
    ok: true,
    session_id: "sess-1",
    agentcore_session_id: "ac-1",
    itinerary_id: "it-1",
    seeded_opener: null,
  });
  vi.mocked(listTurns).mockResolvedValue({ ok: true, turns: [] });
  vi.mocked(campaignKickoff).mockResolvedValue({
    ok: true,
    kickoff: {
      itinerary_id: "it-1",
      campaign_id: "olympus",
      requested_nights: null,
      snapped_length: 14,
      reason: "",
      node_count: 0,
      edge_count: 0,
      created_nodes: [],
    },
  });
});

// ── lazy open + audience plumbing ────────────────────────────────────────────

test("opens no session on mount, then opens lazily with the audience on first submit", async () => {
  renderConcierge({ audience: "advisor" });

  // Lazy: a non-hydrating concierge must not touch the backend until used.
  expect(createSessionEndpoint).not.toHaveBeenCalled();

  fireEvent.change(screen.getByPlaceholderText(/Ask me to propose/i), {
    target: { value: "What do we know, privately?" },
  });
  fireEvent.click(screen.getByRole("button", { name: /send/i }));

  await waitFor(() => expect(createSessionEndpoint).toHaveBeenCalledTimes(1));
  // The `audience` prop plumbs straight into POST /sessions alongside the ids.
  expect(createSessionEndpoint).toHaveBeenCalledWith(expect.anything(), {
    client_id: "c-1",
    itinerary_id: "it-1",
    audience: "advisor",
  });
  // The submitted text is handed to the SSE turn loop verbatim (no prefixing),
  // with no ambient card context when nothing is focused.
  await waitFor(() =>
    expect(sendTurnMock).toHaveBeenCalledWith(
      "What do we know, privately?",
      undefined,
    ),
  );
});

test("the focused card rides along as silent viewing context (no text prefix)", async () => {
  // A probe inside the SAME Provider captures the live store api, so the test
  // can focus a node exactly as the Journal's scroll tracking would.
  let storeApi: ReturnType<typeof itineraryGraphStore.useStoreApi> | null = null;
  function Probe() {
    storeApi = itineraryGraphStore.useStoreApi();
    return null;
  }
  render(
    <itineraryGraphStore.Provider initial={storeInit()}>
      <Probe />
      <ConciergeChat
        audience="traveler"
        apiBaseUrl="http://api.test"
        accessToken="tok"
        clientId="c-1"
        itineraryId="it-1"
      />
    </itineraryGraphStore.Provider>,
  );

  // Simulate the Journal focusing a card as the user scrolls it into view.
  act(() => {
    storeApi!.getState().focusNode("n1", "scroll");
  });

  fireEvent.change(screen.getByPlaceholderText(/Ask me to propose/i), {
    target: { value: "How much is this?" },
  });
  fireEvent.click(screen.getByRole("button", { name: /send/i }));

  await waitFor(() =>
    // The message text is untouched; the card id travels silently alongside it.
    expect(sendTurnMock).toHaveBeenCalledWith("How much is this?", {
      viewing_node_id: "n1",
    }),
  );
});

test("a second submit reuses the already-open session (no re-open)", async () => {
  renderConcierge({ audience: "advisor" });

  const send = () => {
    fireEvent.change(screen.getByPlaceholderText(/Ask me to propose/i), {
      target: { value: "hello" },
    });
    fireEvent.click(screen.getByRole("button", { name: /send/i }));
  };

  send();
  await waitFor(() => expect(createSessionEndpoint).toHaveBeenCalledTimes(1));
  send();
  await flush();
  // sessionIdRef short-circuits ensureSession — still exactly one open.
  expect(createSessionEndpoint).toHaveBeenCalledTimes(1);
  expect(sendTurnMock).toHaveBeenCalledTimes(2);
});

// ── eager hydration + turn→message role mapping ──────────────────────────────

test("hydrateHistory eagerly opens the traveler thread and replays mapped turns, keeping the intro", async () => {
  vi.mocked(listTurns).mockResolvedValue({
    ok: true,
    turns: [
      turn("t1", "user", "From the traveler"),
      turn("t2", "assistant", "A grounded reply"),
      // anything that is not user/assistant maps to a system bubble.
      turn("t3", "tool", "internal tool note"),
    ],
  });

  renderConcierge({
    audience: "traveler",
    hydrateHistory: true,
    intro: "Shared client thread.",
  });

  // Eager open on mount, carrying the traveler audience.
  await waitFor(() =>
    expect(createSessionEndpoint).toHaveBeenCalledWith(
      expect.anything(),
      expect.objectContaining({ audience: "traveler" }),
    ),
  );

  // Prior turns are replayed into the conversation…
  await waitFor(() => {
    expect(screen.getByText("From the traveler")).toBeInTheDocument();
    expect(screen.getByText("A grounded reply")).toBeInTheDocument();
  });
  expect(screen.getByText("internal tool note")).toBeInTheDocument();
  // …and the seeded intro system line is preserved at the head.
  expect(screen.getByText("Shared client thread.")).toBeInTheDocument();
});

// ── gating: no chat context → inert composer, no session ─────────────────────

test("is inert without a full chat context (missing token): composer disabled, no open", async () => {
  renderConcierge({ accessToken: null });

  const input = screen.getByPlaceholderText(/Ask me to propose/i) as HTMLInputElement;
  expect(input.disabled).toBe(true);

  // Even forcing a form submit opens nothing — canChat short-circuits.
  const form = input.closest("form");
  expect(form).not.toBeNull();
  fireEvent.submit(form as HTMLFormElement);
  await flush();

  expect(createSessionEndpoint).not.toHaveBeenCalled();
  expect(sendTurnMock).not.toHaveBeenCalled();
});

// ── campaign kickoff greeting must survive history hydration ─────────────────

test("campaign kickoff greeting is not clobbered by history hydration on the same mount", async () => {
  // The dashboard resumes the intake session (hydrateHistory) AND fires the
  // agent kickoff (autoKickoff) on ONE mount. listTurns resolves well before the
  // LLM greeting finishes, so the hydrate replace must preserve the streaming
  // greeting bubble — otherwise the reading-list line + article chips silently
  // vanish and the traveler sees only the replayed intake opener.
  vi.mocked(listTurns).mockResolvedValue({
    ok: true,
    turns: [turn("t-open", "assistant", "Mount Olympus has been waiting for you.")],
  });
  // The kickoff turn streams a greeting delta, then completes.
  sendTurnMock.mockImplementationOnce(async () => {
    lastConfigRef.current?.onDelta?.({
      text: "I've also dropped a few reads into your reading list.",
    });
    lastConfigRef.current?.onDone?.();
  });

  renderConcierge({
    audience: "traveler",
    hydrateHistory: true,
    autoKickoff: true,
  });

  // The deterministic spine is laid, then the agent opener fires (surface=kickoff).
  await waitFor(() => expect(campaignKickoff).toHaveBeenCalled());
  await waitFor(() =>
    expect(sendTurnMock).toHaveBeenCalledWith("Let's build it out.", { surface: "kickoff" }),
  );

  // BOTH the replayed intake opener AND the freshly-streamed greeting are on
  // screen — the greeting survived the hydrate replace.
  await waitFor(() => {
    expect(screen.getByText("Mount Olympus has been waiting for you.")).toBeInTheDocument();
    expect(screen.getByText(/dropped a few reads into your reading list/i)).toBeInTheDocument();
  });
});
