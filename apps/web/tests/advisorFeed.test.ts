import { expect, test } from "vitest";

import {
  EVENT_BUFFER_CAP,
  type AdvisorFrame,
  type FeedActivityEvent,
  feedReducer,
  initialFeedState,
  isAdvisorFrame,
  liveClientIds,
} from "@/lib/advisorFeed";
import { parseSseJson } from "@/lib/sse";

function event(over: Partial<FeedActivityEvent> = {}): FeedActivityEvent {
  return {
    kind: "payment",
    at: "2026-07-08T12:00:00+00:00",
    source_id: "1",
    client_id: "c-1",
    itinerary_id: null,
    itinerary_title: null,
    actor_kind: null,
    title: null,
    op: null,
    status_before: null,
    status_after: null,
    amount: null,
    currency: null,
    ref_id: null,
    ...over,
  };
}

function activity(e: FeedActivityEvent): AdvisorFrame {
  return { type: "activity", v: 1, event: e, cursor: e.at };
}

test("guard accepts the v1 contract and rejects strangers", () => {
  expect(isAdvisorFrame({ type: "hello", v: 1, cursor: "c", heartbeat_ms: 1 })).toBe(true);
  expect(isAdvisorFrame(activity(event()))).toBe(true);
  expect(isAdvisorFrame({ type: "heartbeat", at: "x" })).toBe(true);
  expect(isAdvisorFrame({ type: "delta", text: "agent frame" })).toBe(false);
  expect(isAdvisorFrame({ type: "activity", v: 1 })).toBe(false); // no event
  expect(isAdvisorFrame(null)).toBe(false);
});

test("hello goes live and seeds the cursor", () => {
  const s = feedReducer(initialFeedState(), {
    type: "hello",
    v: 1,
    cursor: "2026-07-08T12:00:00+00:00",
    heartbeat_ms: 20000,
  });
  expect(s.connection).toBe("live");
  expect(s.cursor).toBe("2026-07-08T12:00:00+00:00");
});

test("activity prepends, dedups by kind+source_id, advances the cursor", () => {
  let s = feedReducer(initialFeedState(), activity(event({ source_id: "1" })));
  s = feedReducer(s, activity(event({ source_id: "2", at: "2026-07-08T12:01:00+00:00" })));
  s = feedReducer(s, activity(event({ source_id: "1" }))); // duplicate
  expect(s.events.map((e) => e.source_id)).toEqual(["2", "1"]);
  expect(s.cursor).toBe("2026-07-08T12:00:00+00:00"); // dup still advanced cursor
});

test("the ring buffer caps", () => {
  let s = initialFeedState();
  for (let i = 0; i < EVENT_BUFFER_CAP + 20; i++) {
    s = feedReducer(s, activity(event({ source_id: String(i) })));
  }
  expect(s.events).toHaveLength(EVENT_BUFFER_CAP);
});

test("agent turns pulse the client's live session inside the window", () => {
  const now = new Date("2026-07-08T12:04:00+00:00").getTime();
  let s = feedReducer(
    initialFeedState(),
    activity(event({ kind: "agent_turn", client_id: "c-9", at: "2026-07-08T12:00:00+00:00" })),
  );
  expect(liveClientIds(s, now)).toEqual(["c-9"]);
  // …and decays once the window passes.
  const later = new Date("2026-07-08T12:20:00+00:00").getTime();
  expect(liveClientIds(s, later)).toEqual([]);
  // Non-turn events never pulse.
  s = feedReducer(s, activity(event({ kind: "payment", client_id: "c-2", source_id: "77" })));
  expect(liveClientIds(s, now)).toEqual(["c-9"]);
});

test("bye/error drop the liveness claim", () => {
  const live = feedReducer(initialFeedState(), {
    type: "hello",
    v: 1,
    cursor: "c",
    heartbeat_ms: 1,
  });
  expect(feedReducer(live, { type: "bye", reason: "reauth" }).connection).toBe("connecting");
});

test("frames round-trip through the shared SSE splitter", () => {
  const wire =
    'data: {"type":"hello","v":1,"cursor":"c","heartbeat_ms":20000}\n\n' +
    'data: {"type":"heartbeat","at":"x"}\n\ndata: {"type":"act';
  const { payloads, remaining } = parseSseJson(wire, "advisorFeed");
  expect(payloads).toHaveLength(2);
  expect(payloads.every(isAdvisorFrame)).toBe(true);
  expect(remaining).toBe('data: {"type":"act');
});
