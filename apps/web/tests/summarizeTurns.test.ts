import { expect, test } from "vitest";

import type { AgentTurnSummary } from "@ov-black/api-client";

import {
  formatMs,
  summarizeTurns,
} from "@/app/command-center/_lib/summarizeTurns";

let seq = 0;
function turn(over: Partial<AgentTurnSummary> = {}): AgentTurnSummary {
  seq += 1;
  return {
    id: `t-${seq}`,
    turn_index: seq,
    role: "assistant",
    content: "…",
    model: null,
    latency_ms: null,
    first_token_ms: null,
    retried: 0,
    error_reason: null,
    created_at: "2026-07-08T12:00:00+00:00",
    ...over,
  };
}

test("empty session summarizes to zeros and nulls", () => {
  expect(summarizeTurns([])).toEqual({
    turnCount: 0,
    assistantTurns: 0,
    spanMs: 0,
    avgLatencyMs: null,
    maxLatencyMs: null,
    firstTokenP50Ms: null,
    retries: 0,
    errors: 0,
  });
});

test("latency stats consider assistant turns only", () => {
  const turns = [
    turn({ role: "user", latency_ms: 9999 }),
    turn({ role: "assistant", latency_ms: 1000, first_token_ms: 200 }),
    turn({ role: "assistant", latency_ms: 3000, first_token_ms: 400 }),
  ];
  const s = summarizeTurns(turns);
  expect(s.turnCount).toBe(3);
  expect(s.assistantTurns).toBe(2);
  expect(s.avgLatencyMs).toBe(2000);
  expect(s.maxLatencyMs).toBe(3000);
  expect(s.firstTokenP50Ms).toBe(300);
});

test("first-token p50 is the middle value for odd counts", () => {
  const turns = [
    turn({ first_token_ms: 100 }),
    turn({ first_token_ms: 900 }),
    turn({ first_token_ms: 300 }),
  ];
  expect(summarizeTurns(turns).firstTokenP50Ms).toBe(300);
});

test("span is first→last created_at; single turn has no span", () => {
  const turns = [
    turn({ created_at: "2026-07-08T12:00:00+00:00" }),
    turn({ created_at: "2026-07-08T12:05:30+00:00" }),
  ];
  expect(summarizeTurns(turns).spanMs).toBe(330_000);
  expect(summarizeTurns([turn()]).spanMs).toBe(0);
});

test("retries sum across turns; errors count reason or error role", () => {
  const turns = [
    turn({ retried: 2 }),
    turn({ retried: 1, error_reason: "upstream_timeout" }),
    turn({ role: "error", content: "boom" }),
    turn({ role: "user" }),
  ];
  const s = summarizeTurns(turns);
  expect(s.retries).toBe(3);
  expect(s.errors).toBe(2);
});

test("null latencies are skipped, not treated as zero", () => {
  const turns = [
    turn({ latency_ms: null }),
    turn({ latency_ms: 500 }),
  ];
  const s = summarizeTurns(turns);
  expect(s.avgLatencyMs).toBe(500);
  expect(s.maxLatencyMs).toBe(500);
});

test("formatMs renders the chips' compact durations", () => {
  expect(formatMs(320)).toBe("320ms");
  expect(formatMs(1400)).toBe("1.4s");
  expect(formatMs(12_600)).toBe("13s");
  expect(formatMs(90_000)).toBe("1m 30s");
  expect(formatMs(3_720_000)).toBe("1h 2m");
});
