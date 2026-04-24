// Unit tests for the DIY SSE consumer in apps/web/lib/agentStream.ts.
//
// S07 T04 extends the consumer with a fifth frame type ('card'); these tests
// pin the parser contract for that frame and the hook's onCard dispatch. The
// existing slice-level tests exercise integration via the rendered chat page.

import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { parseFrames, useAgentStream } from "@/lib/agentStream";
import type { CardFrame } from "@/lib/agentStream.types";

function encodeFrame(obj: unknown): string {
  return `data: ${JSON.stringify(obj)}\n\n`;
}

describe("parseFrames (card frames)", () => {
  let warnSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
  });

  afterEach(() => {
    warnSpy.mockRestore();
  });

  test("accepts a well-formed card frame", () => {
    const card: CardFrame = {
      type: "card",
      source: "ov",
      source_id: "exp-001",
      node_id: "node-abc",
      snapshot: {
        title: "Patagonia trek",
        price: "$8,400",
        duration_days: 7,
      },
    };

    const { frames, remaining } = parseFrames(encodeFrame(card));

    expect(remaining).toBe("");
    expect(frames).toHaveLength(1);
    expect(frames[0]).toEqual(card);
    expect(warnSpy).not.toHaveBeenCalled();
  });

  test("drops a card frame missing node_id with a warn (no exception)", () => {
    const malformed = {
      type: "card",
      source: "ov",
      source_id: "exp-001",
      // node_id intentionally omitted
      snapshot: { title: "Broken" },
    };

    const { frames, remaining } = parseFrames(encodeFrame(malformed));

    expect(remaining).toBe("");
    expect(frames).toHaveLength(0);
    expect(warnSpy).toHaveBeenCalledWith(
      "[agentStream] dropping unknown SSE frame",
      expect.objectContaining({ shape: expect.any(Array) }),
    );
  });

  test("drops a card frame missing snapshot with a warn", () => {
    const malformed = {
      type: "card",
      source: "ov",
      source_id: "exp-001",
      node_id: "node-abc",
    };

    const { frames } = parseFrames(encodeFrame(malformed));

    expect(frames).toHaveLength(0);
    expect(warnSpy).toHaveBeenCalled();
  });

  test("still accepts previously supported frame types", () => {
    const buffer =
      encodeFrame({ type: "first_token", ms: 42 }) +
      encodeFrame({ type: "delta", text: "hi" });
    const { frames } = parseFrames(buffer);
    expect(frames.map((f) => f.type)).toEqual(["first_token", "delta"]);
  });
});

describe("useAgentStream (onCard dispatch)", () => {
  const originalFetch = globalThis.fetch;
  const fetchMock = vi.fn<typeof globalThis.fetch>();

  beforeEach(() => {
    fetchMock.mockReset();
    globalThis.fetch = fetchMock as unknown as typeof globalThis.fetch;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  function makeSseResponse(chunks: string[]): Response {
    const encoder = new TextEncoder();
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        for (const chunk of chunks) {
          controller.enqueue(encoder.encode(chunk));
        }
        controller.close();
      },
    });
    return new Response(stream, {
      status: 200,
      headers: { "Content-Type": "text/event-stream" },
    });
  }

  test("invokes onCard for card frames emitted in the stream", async () => {
    const card: CardFrame = {
      type: "card",
      source: "ov",
      source_id: "exp-042",
      node_id: "node-xyz",
      snapshot: { title: "Amalfi cruise", location: "Amalfi, IT" },
    };
    const done = {
      type: "done",
      turn_id: "turn-1",
      model: "claude-opus",
      latency_ms: 100,
      first_token_ms: 50,
      retried: 0,
    };

    fetchMock.mockResolvedValue(
      makeSseResponse([encodeFrame(card), encodeFrame(done)]),
    );

    const onCard = vi.fn();
    const onDone = vi.fn();

    const { result } = renderHook(() =>
      useAgentStream({
        sessionId: "sess-1",
        getAccessToken: async () => "tok",
        apiBaseUrl: "http://api.test",
        onCard,
        onDone,
      }),
    );

    await act(async () => {
      await result.current.sendTurn("hello");
    });

    expect(onCard).toHaveBeenCalledTimes(1);
    expect(onCard).toHaveBeenCalledWith(card);
    expect(onDone).toHaveBeenCalledTimes(1);
  });
});
