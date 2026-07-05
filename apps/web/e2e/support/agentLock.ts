// A cross-process mutex for the single LOCAL concierge agent.
//
// This is a TEST-INFRA concern, NOT a product limitation. In production the
// agent runs on managed Bedrock AgentCore, invoked per session — it fields many
// concurrent, distinct sessions by design (each turn is an independent async
// task; the agent carries per-turn state in contextvars + a fresh Agent, with no
// shared mutable state). The local dev stack, by contrast, runs ONE
// `python -m agent` process on :8080 that every e2e spec shares, against one set
// of local Bedrock creds — so two browser tests firing a live turn at the same
// instant contend on that single process / throttle the shared creds, which
// surfaces as a flaky turn error. This lock serialises live turns so the suite
// is deterministic; it says nothing about how many turns prod can field.
//
// Playwright spreads specs across projects + worker PROCESSES, so an in-memory
// guard can't coordinate them. We serialise through an exclusive lock FILE that
// every live-agent turn (traveler `chat.spec`, advisor `concierge.spec`)
// acquires, whatever project/worker it runs in.

import { closeSync, openSync, statSync, unlinkSync } from "node:fs";
import os from "node:os";
import path from "node:path";

const LOCK = path.join(os.tmpdir(), "ovb-e2e-agent-turn.lock");
// A real turn runs well under a minute; a lock older than this belongs to a
// crashed worker (killed mid-turn on a timeout) and is safe to steal.
const STALE_MS = 90_000;
// Final backstop so a pathological state never deadlocks the whole run.
const WAIT_DEADLINE_MS = 180_000;

const delay = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

function tryAcquire(): boolean {
  try {
    closeSync(openSync(LOCK, "wx")); // atomic create-or-fail (O_EXCL)
    return true;
  } catch {
    return false;
  }
}

function release(): void {
  try {
    unlinkSync(LOCK);
  } catch {
    /* already gone — fine */
  }
}

// Age of the current lock file, or null if it vanished between attempts.
function heldMs(): number | null {
  try {
    return Date.now() - statSync(LOCK).mtimeMs;
  } catch {
    return null;
  }
}

/**
 * Run `turn` while holding the exclusive agent lock, so no other live-agent turn
 * runs concurrently against the single local agent. Steals a stale lock (crashed
 * holder) after STALE_MS, and always releases — even if `turn` throws.
 *
 * Hold the lock for the turn only (send → reply settled), not the whole test, so
 * the non-agent parts of specs still overlap freely.
 */
export async function withAgentTurnLock<T>(turn: () => Promise<T>): Promise<T> {
  const deadline = Date.now() + WAIT_DEADLINE_MS;
  while (!tryAcquire()) {
    const age = heldMs();
    if ((age !== null && age > STALE_MS) || Date.now() > deadline) {
      release(); // steal a lock a crashed holder never freed
      continue;
    }
    await delay(250);
  }
  try {
    return await turn();
  } finally {
    release();
  }
}
