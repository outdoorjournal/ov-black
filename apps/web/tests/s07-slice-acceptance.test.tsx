// S07 slice-acceptance suite — six bullets, one test() each.
//
// The slice plan's verification section defines six MoodBoard invariants for
// the agent-proposed OV experience cards. This suite encodes each one as a
// single, independently failing assertion so verify-s07.sh can print
// PASS/FAIL per bullet and a future agent can localize a regression to
// exactly one invariant without reading the test body.
//
// Bullets:
//   (1) agent emits three cards during a test conversation
//   (2) a Card renders full detail from an ExperienceItem fixture
//   (3) pin / keep / discard dispatches the right status transitions
//   (4) reload hydration renders approved + proposed + discarded from
//       initialCards (discarded filtered out of the visible aside)
//   (5) craft-feel invariants in the mood-board subtree
//   (6) every card carries data-source='ov' and data-source-id matching
//       the OV fixture
//
// The tests mount ChatShell directly (not the RSC page) because RSC prop
// threading lives in page.tsx and is covered by build/typecheck; these
// bullets are client-side DOM invariants.

import { act, fireEvent, render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { Card } from "@/app/chat/[client_id]/_components/Card";
import { ChatShell } from "@/app/chat/[client_id]/_components/ChatShell";
import type {
  CardView,
  InitialCardPayload,
} from "@/app/chat/[client_id]/_components/types";

import ovFixture from "./fixtures/ov_card_snapshots.json";

// ── fixture typing ─────────────────────────────────────────────────────────

type OvFixtureEntry = {
  node_id: string;
  source: string;
  source_id: string;
  snapshot: {
    title: string;
    cover_image?: string | null;
    price?: string | null;
    duration_days?: number | null;
    difficulty?: string | null;
    location?: string | null;
    activities?: string[];
  };
};

const fixture = ovFixture as OvFixtureEntry[];

// ── SSE helpers (mirrors s05-slice-acceptance.test.tsx) ────────────────────

const encoder = new TextEncoder();

function sseLine(obj: unknown): Uint8Array {
  return encoder.encode(`data: ${JSON.stringify(obj)}\n\n`);
}

function makeStreamingResponse(chunks: Uint8Array[]): Response {
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) {
        controller.enqueue(chunk);
      }
      controller.close();
    },
  });
  return new Response(stream, {
    status: 200,
    headers: { "Content-Type": "text/event-stream" },
  });
}

function makeEmptyStreamResponse(): Response {
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.close();
    },
  });
  return new Response(stream, {
    status: 200,
    headers: { "Content-Type": "text/event-stream" },
  });
}

/**
 * Build a card SSE frame payload from a fixture entry.
 */
function cardFrameFromFixture(entry: OvFixtureEntry) {
  return {
    type: "card" as const,
    node_id: entry.node_id,
    source: entry.source,
    source_id: entry.source_id,
    snapshot: entry.snapshot,
  };
}

function toInitialCard(
  entry: OvFixtureEntry,
  status: InitialCardPayload["status"],
): InitialCardPayload {
  return {
    node_id: entry.node_id,
    source: entry.source,
    source_id: entry.source_id,
    status,
    snapshot: entry.snapshot,
  };
}

// ── lifecycle ──────────────────────────────────────────────────────────────

const originalFetch = globalThis.fetch;

beforeEach(() => {
  vi.restoreAllMocks();
});

afterEach(() => {
  globalThis.fetch = originalFetch;
});

// ── bullet 1: agent emits three cards during a test conversation ───────────

test("(1) agent emits three cards during a test conversation", async () => {
  const chunks = [
    sseLine({ type: "first_token", ms: 60 }),
    sseLine({ type: "delta", text: "Here are three ideas to try on. " }),
    sseLine(cardFrameFromFixture(fixture[0]!)),
    sseLine(cardFrameFromFixture(fixture[1]!)),
    sseLine(cardFrameFromFixture(fixture[2]!)),
    sseLine({
      type: "done",
      turn_id: "turn-1",
      model: "test-model",
      latency_ms: 800,
      first_token_ms: 60,
      retried: 0,
    }),
  ];
  const fetchMock = vi.fn().mockResolvedValue(makeStreamingResponse(chunks));
  globalThis.fetch = fetchMock as unknown as typeof fetch;

  render(
    <ChatShell
      sessionId="session-s07-1"
      accessToken="test-token"
      apiBaseUrl="http://api.test"
      client={{ id: "client-s07", full_name: "Test Client" }}
      initialTurns={[]}
      itineraryId="itin-s07-1"
    />,
  );

  await waitFor(() => {
    const board = document.querySelector('[data-testid="mood-board"]');
    expect(board).not.toBeNull();
    const cards = board!.querySelectorAll("[data-node-id]");
    expect(cards.length).toBe(3);
  });
});

// ── bullet 2: Card renders every ExperienceItem snapshot field ─────────────

test("(2) a Card renders full detail from an ExperienceItem fixture", () => {
  const entry = fixture[0]!;
  const card: CardView = {
    node_id: entry.node_id,
    source: entry.source,
    source_id: entry.source_id,
    status: "proposed",
    snapshot: entry.snapshot,
  };

  const { container } = render(<Card card={card} onAction={() => {}} />);

  const text = container.textContent ?? "";
  expect(text).toContain(entry.snapshot.title);
  expect(text).toContain(entry.snapshot.price!);
  expect(text).toContain(`${entry.snapshot.duration_days!} days`);
  expect(text).toContain(entry.snapshot.difficulty!);
  expect(text).toContain(entry.snapshot.location!);
  for (const activity of entry.snapshot.activities!) {
    expect(text).toContain(activity);
  }

  // next/image renders an <img>; assert the cover URL made it into the DOM
  // via <img src>. next/image rewrites the src through its loader which
  // URL-encodes the source, so we decode before checking containment.
  const img = container.querySelector("img");
  expect(img).not.toBeNull();
  const decodedSrc = decodeURIComponent(img!.getAttribute("src") ?? "");
  expect(decodedSrc).toContain(entry.snapshot.cover_image!);
});

// ── bullet 3: pin / keep / discard dispatches right status transitions ─────

test("(3) pin / keep / discard dispatches the right status transitions", async () => {
  const entry = fixture[0]!;
  // Each sub-scenario starts from a fresh "proposed" card so the three button
  // behaviours can be asserted independently — mirrors the plan's "pin →
  // approved, keep → no PATCH (optimistic-only when already proposed),
  // discard → discarded" matrix.
  const seen: Array<{ method: string; url: string; body: unknown }> = [];

  const makeFetchMock = () =>
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      // The SDK client calls fetch(request) with a Request object; the SSE
      // consumer calls fetch(url, init). Normalize both shapes.
      let url: string;
      let method: string;
      let bodyText: string | null = null;
      if (input instanceof Request) {
        url = input.url;
        method = input.method.toUpperCase();
        try {
          bodyText = await input.clone().text();
        } catch {
          bodyText = null;
        }
      } else {
        url = typeof input === "string" ? input : input.toString();
        method = (init?.method ?? "GET").toUpperCase();
        bodyText = init?.body ? String(init.body) : null;
      }
      if (method === "POST" && url.endsWith("/turn")) {
        return makeEmptyStreamResponse();
      }
      if (method === "PATCH") {
        const body = bodyText ? JSON.parse(bodyText) : null;
        seen.push({ method, url, body });
        return new Response(
          JSON.stringify({
            id: entry.node_id,
            itinerary_id: "itin-s07-3",
            type: "experience",
            title: entry.snapshot.title,
            source: "ov",
            source_id: entry.source_id,
            status: body?.status ?? "proposed",
            metadata: {},
            created_at: new Date(0).toISOString(),
            updated_at: new Date(0).toISOString(),
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        );
      }
      return new Response("not found", { status: 404 });
    });

  const initialTurns = [
    {
      id: "t0",
      turn_index: 0,
      role: "user" as const,
      content: "seed",
      model: null,
      latency_ms: null,
      first_token_ms: null,
      retried: 0,
      error_reason: null,
      created_at: new Date(0).toISOString(),
    },
  ];

  async function clickAndUnmount(testid: string) {
    globalThis.fetch = makeFetchMock() as unknown as typeof fetch;
    const { unmount } = render(
      <ChatShell
        sessionId="session-s07-3"
        accessToken="test-token"
        apiBaseUrl="http://api.test"
        client={{ id: "client-s07", full_name: "Test Client" }}
        initialTurns={initialTurns}
        itineraryId="itin-s07-3"
        initialCards={[toInitialCard(entry, "proposed")]}
      />,
    );
    const btn = document.querySelector(
      `[data-testid="mood-board"] [data-node-id="${entry.node_id}"] [data-testid="${testid}"]`,
    ) as HTMLButtonElement;
    await act(async () => {
      fireEvent.click(btn);
    });
    // Let any pending microtasks (the PATCH promise chain) settle before
    // the next render overwrites globalThis.fetch.
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    unmount();
  }

  // 1. Pin on proposed → PATCH {status:"approved"}
  await clickAndUnmount("mood-board-card-pin");
  // 2. Keep on proposed → no PATCH (button disabled + reducer short-circuits)
  await clickAndUnmount("mood-board-card-keep");
  // 3. Discard on proposed → PATCH {status:"discarded"}
  await clickAndUnmount("mood-board-card-discard");

  const patchCalls = seen.filter((e) => e.method === "PATCH");
  expect(patchCalls.length).toBe(2);
  expect((patchCalls[0]!.body as { status: string }).status).toBe("approved");
  expect((patchCalls[1]!.body as { status: string }).status).toBe("discarded");
});

// ── bullet 4: reload hydration renders approved + proposed; discarded out ──

test("(4) reload hydration renders approved + proposed + discarded from initialCards", async () => {
  globalThis.fetch = vi
    .fn()
    .mockResolvedValue(makeEmptyStreamResponse()) as unknown as typeof fetch;

  const initialCards: InitialCardPayload[] = [
    toInitialCard(fixture[0]!, "approved"),
    toInitialCard(fixture[1]!, "proposed"),
    toInitialCard(fixture[2]!, "discarded"),
  ];

  render(
    <ChatShell
      sessionId="session-s07-4"
      accessToken="test-token"
      apiBaseUrl="http://api.test"
      client={{ id: "client-s07", full_name: "Test Client" }}
      initialTurns={[
        {
          id: "t0",
          turn_index: 0,
          role: "user",
          content: "seed",
          model: null,
          latency_ms: null,
          first_token_ms: null,
          retried: 0,
          error_reason: null,
          created_at: new Date(0).toISOString(),
        },
      ]}
      itineraryId="itin-s07-4"
      initialCards={initialCards}
    />,
  );

  const board = document.querySelector('[data-testid="mood-board"]')!;

  const approved = board.querySelector(
    `[data-node-id="${fixture[0]!.node_id}"]`,
  );
  expect(approved).not.toBeNull();
  expect(approved!.getAttribute("data-card-status")).toBe("approved");

  const proposed = board.querySelector(
    `[data-node-id="${fixture[1]!.node_id}"]`,
  );
  expect(proposed).not.toBeNull();
  expect(proposed!.getAttribute("data-card-status")).toBe("proposed");

  const discarded = board.querySelector(
    `[data-node-id="${fixture[2]!.node_id}"]`,
  );
  expect(discarded).toBeNull();
});

// ── bullet 5: craft-feel invariants in the mood-board subtree ──────────────

test("(5) craft-feel invariants in the mood-board subtree", async () => {
  globalThis.fetch = vi
    .fn()
    .mockResolvedValue(makeEmptyStreamResponse()) as unknown as typeof fetch;

  const initialCards: InitialCardPayload[] = fixture
    .slice(0, 3)
    .map((entry) => toInitialCard(entry, "proposed"));

  render(
    <ChatShell
      sessionId="session-s07-5"
      accessToken="test-token"
      apiBaseUrl="http://api.test"
      client={{ id: "client-s07", full_name: "Test Client" }}
      initialTurns={[
        {
          id: "t0",
          turn_index: 0,
          role: "user",
          content: "seed",
          model: null,
          latency_ms: null,
          first_token_ms: null,
          retried: 0,
          error_reason: null,
          created_at: new Date(0).toISOString(),
        },
      ]}
      itineraryId="itin-s07-5"
      initialCards={initialCards}
    />,
  );

  const board = document.querySelector('[data-testid="mood-board"]') as HTMLElement;
  expect(board).not.toBeNull();

  // Emoji: anything outside the BMP ASCII/Latin-1 range used as decoration.
  // We use the unicode Emoji property via \p{Extended_Pictographic}.
  const emojiRe = /\p{Extended_Pictographic}/u;
  expect(emojiRe.test(board.textContent ?? "")).toBe(false);

  expect(board.querySelector('[role="progressbar"]')).toBeNull();
  expect(board.querySelector("[aria-busy]")).toBeNull();
  expect(board.querySelector(".Skeleton, [class*='Skeleton']")).toBeNull();
  expect(board.querySelector(".spinner, [class*='spinner']")).toBeNull();
});

// ── bullet 6: every card carries data-source='ov' + matching data-source-id ─

test("(6) every card carries data-source='ov' and data-source-id matching the OV fixture", async () => {
  const chunks = [
    sseLine(cardFrameFromFixture(fixture[0]!)),
    sseLine(cardFrameFromFixture(fixture[1]!)),
    sseLine(cardFrameFromFixture(fixture[2]!)),
    sseLine({
      type: "done",
      turn_id: "turn-6",
      model: "test-model",
      latency_ms: 100,
      first_token_ms: 10,
      retried: 0,
    }),
  ];
  globalThis.fetch = vi
    .fn()
    .mockResolvedValue(makeStreamingResponse(chunks)) as unknown as typeof fetch;

  render(
    <ChatShell
      sessionId="session-s07-6"
      accessToken="test-token"
      apiBaseUrl="http://api.test"
      client={{ id: "client-s07", full_name: "Test Client" }}
      initialTurns={[]}
      itineraryId="itin-s07-6"
    />,
  );

  await waitFor(() => {
    const board = document.querySelector('[data-testid="mood-board"]');
    expect(board).not.toBeNull();
    const cards = board!.querySelectorAll("[data-node-id]");
    expect(cards.length).toBe(3);
  });

  const board = document.querySelector('[data-testid="mood-board"]')!;
  const expectedIds = new Set(fixture.slice(0, 3).map((e) => e.source_id));
  const renderedIds = new Set<string>();

  for (const cardEl of Array.from(board.querySelectorAll("[data-node-id]"))) {
    expect(cardEl.getAttribute("data-source")).toBe("ov");
    const sid = cardEl.getAttribute("data-source-id");
    expect(sid).not.toBeNull();
    expect(expectedIds.has(sid!)).toBe(true);
    renderedIds.add(sid!);
  }
  expect(renderedIds).toEqual(expectedIds);
});
