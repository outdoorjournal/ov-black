// S05 slice-acceptance suite — six bullets, one test() each.
//
// The slice plan's verification section defines six craft-feel invariants
// for the client chat shell. This suite encodes each one as a single,
// independently failing DOM/pure-function assertion so verify-s05.sh can
// print PASS/FAIL per bullet and a future agent can localize a regression
// to exactly one invariant without reading the test body.
//
// Bullets (mirroring S04 shape):
//   (1) parseFrames partial-buffer carry-over
//   (2) useAgentStream → ChatShell end-to-end: frames land as concatenated
//       delta text in the DOM via the reducer
//   (3) error frame renders D015 crafted-fallback copy AND re-enables composer
//   (4) craft-feel DOM invariants: no progressbar / aria-busy / spinner /
//       skeleton, and assistant turns use Cormorant serif (font-serif class
//       or computed fontFamily contains Cormorant)
//   (5) first_token_ms round-trip under the 2000 ms budget
//   (6) no emoji in the rendered conversation DOM after an innocuous turn

import { act, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { ChatShell } from "@/app/chat/[client_id]/_components/ChatShell";
import { parseFrames } from "@/lib/agentStream";

// ── helpers ────────────────────────────────────────────────────────────────

const encoder = new TextEncoder();

function sseLine(obj: unknown): Uint8Array {
  return encoder.encode(`data: ${JSON.stringify(obj)}\n\n`);
}

/**
 * Build a Response-like mock whose `body` is a ReadableStream that emits the
 * supplied chunks (each a Uint8Array) in order then closes. This matches the
 * shape useAgentStream reads via `response.body.getReader()`.
 */
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

function renderShell() {
  return render(
    <ChatShell
      sessionId="session-test"
      accessToken="test-token"
      apiBaseUrl="http://api.test"
      client={{ id: "client-test", full_name: "Test Client" }}
      initialTurns={[]}
    />,
  );
}

// ── lifecycle ──────────────────────────────────────────────────────────────

const originalFetch = globalThis.fetch;

beforeEach(() => {
  vi.restoreAllMocks();
});

afterEach(() => {
  globalThis.fetch = originalFetch;
});

// ── bullet 1: parseFrames partial-buffer carry-over ────────────────────────

test("(1) parseFrames splits one complete frame and carries the rest", () => {
  const first = parseFrames(
    'data: {"type":"first_token","ms":42}\n\ndata: {"type":"delta","text":"Hel',
  );
  expect(first.frames).toHaveLength(1);
  expect(first.frames[0]).toEqual({ type: "first_token", ms: 42 });
  expect(first.remaining).toBe('data: {"type":"delta","text":"Hel');

  const second = parseFrames(first.remaining + 'lo"}\n\n');
  expect(second.frames).toHaveLength(1);
  expect(second.frames[0]).toEqual({ type: "delta", text: "Hello" });
  expect(second.remaining).toBe("");
});

// ── bullet 2: useAgentStream → ChatShell renders concatenated delta text ───

test("(2) streamed deltas land as concatenated text in the ChatShell DOM", async () => {
  const chunks = [
    sseLine({ type: "first_token", ms: 80 }),
    sseLine({ type: "delta", text: "Hello " }),
    sseLine({ type: "delta", text: "there." }),
    sseLine({
      type: "done",
      turn_id: "turn-abc",
      model: "test-model",
      latency_ms: 1200,
      first_token_ms: 80,
      retried: 0,
    }),
  ];
  const fetchMock = vi.fn().mockResolvedValue(makeStreamingResponse(chunks));
  globalThis.fetch = fetchMock as unknown as typeof fetch;

  const { container } = renderShell();

  await waitFor(() => {
    expect(container.textContent ?? "").toContain("Hello there.");
  });
  expect(fetchMock).toHaveBeenCalledWith(
    "http://api.test/sessions/session-test/turn",
    expect.objectContaining({
      method: "POST",
      headers: expect.objectContaining({
        Authorization: "Bearer test-token",
        Accept: "text/event-stream",
      }),
    }),
  );
});

// ── bullet 3: error frame → D015 copy + composer re-enabled ────────────────

test("(3) error frame renders D015 crafted-fallback copy and re-enables composer", async () => {
  const chunks = [
    sseLine({ type: "first_token", ms: 120 }),
    sseLine({ type: "error", reason: "upstream_unavailable" }),
  ];
  globalThis.fetch = vi
    .fn()
    .mockResolvedValue(makeStreamingResponse(chunks)) as unknown as typeof fetch;

  const { container } = renderShell();

  await waitFor(() => {
    expect(container.textContent ?? "").toContain(
      "Our concierge is stepping away for a moment. Please try again.",
    );
  });

  const textarea = screen.getByTestId("chat-composer-textarea") as HTMLTextAreaElement;
  expect(textarea.disabled).toBe(false);
});

// ── bullet 4: craft-feel DOM invariants ────────────────────────────────────

test("(4) no progressbar / aria-busy / spinner / skeleton; assistant uses Cormorant", async () => {
  const chunks = [
    sseLine({ type: "first_token", ms: 60 }),
    sseLine({ type: "delta", text: "Good morning. " }),
    sseLine({ type: "delta", text: "A note from your concierge." }),
    sseLine({
      type: "done",
      turn_id: "turn-craft",
      model: "test-model",
      latency_ms: 800,
      first_token_ms: 60,
      retried: 0,
    }),
  ];
  globalThis.fetch = vi
    .fn()
    .mockResolvedValue(makeStreamingResponse(chunks)) as unknown as typeof fetch;

  const { container } = renderShell();

  await waitFor(() => {
    expect(container.textContent ?? "").toContain(
      "A note from your concierge.",
    );
  });

  expect(container.querySelectorAll('[role="progressbar"]').length).toBe(0);
  expect(container.querySelectorAll("[aria-busy]").length).toBe(0);
  expect(container.querySelectorAll('[class*="spinner" i]').length).toBe(0);
  expect(container.querySelectorAll('[class*="skeleton" i]').length).toBe(0);

  const assistantRows = container.querySelectorAll('[data-role="assistant"]');
  expect(assistantRows.length).toBeGreaterThan(0);
  for (const row of Array.from(assistantRows)) {
    const classAttr = row.getAttribute("class") ?? "";
    const fontFamily = window.getComputedStyle(row).fontFamily ?? "";
    const usesSerif =
      /font-serif/.test(classAttr) || /Cormorant/i.test(fontFamily);
    expect(
      usesSerif,
      `assistant row missing serif signal (class="${classAttr}", fontFamily="${fontFamily}")`,
    ).toBe(true);
  }
});

// ── bullet 5: first_token_ms under the 2000 ms budget ──────────────────────

test("(5) first delta text appears in the DOM within the 2000 ms budget", async () => {
  const chunks = [
    sseLine({ type: "first_token", ms: 150 }),
    sseLine({ type: "delta", text: "Opening line." }),
    sseLine({
      type: "done",
      turn_id: "turn-budget",
      model: "test-model",
      latency_ms: 500,
      first_token_ms: 150,
      retried: 0,
    }),
  ];
  globalThis.fetch = vi
    .fn()
    .mockResolvedValue(makeStreamingResponse(chunks)) as unknown as typeof fetch;

  const start = performance.now();
  const { container } = renderShell();

  await waitFor(() => {
    expect(container.textContent ?? "").toContain("Opening line.");
  });

  const elapsed = performance.now() - start;
  expect(elapsed).toBeLessThanOrEqual(2000);
});

// ── bullet 6: no emoji in rendered DOM ─────────────────────────────────────

test("(6) no emoji in the rendered conversation DOM after an innocuous turn", async () => {
  const chunks = [
    sseLine({ type: "first_token", ms: 90 }),
    sseLine({ type: "delta", text: "A quiet, considered opening " }),
    sseLine({ type: "delta", text: "about your travels." }),
    sseLine({
      type: "done",
      turn_id: "turn-plain",
      model: "test-model",
      latency_ms: 700,
      first_token_ms: 90,
      retried: 0,
    }),
  ];
  globalThis.fetch = vi
    .fn()
    .mockResolvedValue(makeStreamingResponse(chunks)) as unknown as typeof fetch;

  const { container } = renderShell();

  await waitFor(() => {
    expect(container.textContent ?? "").toContain("about your travels.");
  });

  const emojiRegex = /[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]/u;
  expect(emojiRegex.test(container.textContent ?? "")).toBe(false);
});

// Silence the "unused import" lint while keeping `act` available if a future
// bullet needs it — RTL's auto-wrap covers our current cases.
void act;
