// Pure telemetry rollup for the session replay header (Wave F). Takes the
// turns exactly as GET /sessions/{id}/turns returns them (ascending
// turn_index) and derives the strip's figures. Latency statistics consider
// assistant turns only — user turns have no generation latency; diagnostic
// counters (retries, errors) sweep every role.

import type { AgentTurnSummary } from "@ov-black/api-client";

export type TurnsSummary = {
  /** All turns in the window, every role. */
  turnCount: number;
  assistantTurns: number;
  /** First → last created_at, ms; 0 for empty or single-turn sessions. */
  spanMs: number;
  /** Mean assistant latency_ms; null when no assistant turn carries one. */
  avgLatencyMs: number | null;
  maxLatencyMs: number | null;
  /** Median assistant first_token_ms; null when none recorded. */
  firstTokenP50Ms: number | null;
  /** Sum of per-turn retry counts. */
  retries: number;
  /** Turns that ended in an error (error_reason set or role "error"). */
  errors: number;
};

export function summarizeTurns(turns: AgentTurnSummary[]): TurnsSummary {
  const assistant = turns.filter((t) => t.role === "assistant");
  const latencies = assistant
    .map((t) => t.latency_ms)
    .filter((v): v is number => v != null);
  const firstTokens = assistant
    .map((t) => t.first_token_ms)
    .filter((v): v is number => v != null);

  let spanMs = 0;
  if (turns.length > 1) {
    const first = turns[0];
    const last = turns[turns.length - 1];
    if (first && last) {
      spanMs = Math.max(
        0,
        new Date(last.created_at).getTime() -
          new Date(first.created_at).getTime(),
      );
    }
  }

  return {
    turnCount: turns.length,
    assistantTurns: assistant.length,
    spanMs,
    avgLatencyMs: latencies.length
      ? Math.round(latencies.reduce((a, b) => a + b, 0) / latencies.length)
      : null,
    maxLatencyMs: latencies.length ? Math.max(...latencies) : null,
    firstTokenP50Ms: median(firstTokens),
    retries: turns.reduce((sum, t) => sum + t.retried, 0),
    errors: turns.filter((t) => t.error_reason != null || t.role === "error")
      .length,
  };
}

function median(values: number[]): number | null {
  if (values.length === 0) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  if (sorted.length % 2 === 1) return sorted[mid] ?? null;
  const lo = sorted[mid - 1];
  const hi = sorted[mid];
  return lo !== undefined && hi !== undefined ? Math.round((lo + hi) / 2) : null;
}

/** "1.4s" / "320ms" — the replay chips' compact duration. */
export function formatMs(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)}ms`;
  const seconds = ms / 1000;
  if (seconds < 60) {
    return `${seconds.toFixed(seconds < 10 ? 1 : 0)}s`;
  }
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ${Math.round(seconds % 60)}s`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ${minutes % 60}m`;
}
