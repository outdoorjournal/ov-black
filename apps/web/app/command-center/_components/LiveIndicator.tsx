"use client";

// The masthead's connection tell (Wave F): a pulsing brand dot while agent
// sessions are live, a hollow dot when the feed is connected but idle, and a
// mono POLLING tag when SSE has degraded. Diagnostic chrome — quiet by design.

import { useEffect, useState } from "react";

import { liveClientIds } from "@/lib/advisorFeed";

import { useAdvisorFeedStore } from "../_state/advisorFeedStore";

export function LiveIndicator() {
  const connection = useAdvisorFeedStore((s) => s.connection);
  const liveSessions = useAdvisorFeedStore((s) => s.liveSessions);
  // The live window decays with wall-clock time, not just on new frames.
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const tick = setInterval(() => setNow(Date.now()), 30_000);
    return () => clearInterval(tick);
  }, []);

  const active = liveClientIds({ connection, liveSessions, events: [], cursor: null }, now);

  if (connection === "polling") {
    return (
      <span
        title="Live stream unavailable — refreshing periodically"
        className="font-mono text-[10px] uppercase tracking-[0.2em] text-paper/40"
      >
        polling
      </span>
    );
  }

  if (active.length > 0) {
    return (
      <span
        title={`${active.length} live session${active.length === 1 ? "" : "s"}`}
        className="flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-[0.2em] text-brand"
      >
        <span
          aria-hidden
          className="inline-block h-1.5 w-1.5 rounded-full bg-brand"
          style={{ animation: "var(--animate-pulse-live)" }}
        />
        live
      </span>
    );
  }

  return (
    <span
      title={connection === "live" ? "Feed connected" : "Feed connecting…"}
      className="flex items-center gap-1.5 font-mono text-[10px] uppercase tracking-[0.2em] text-paper/40"
    >
      <span
        aria-hidden
        className={
          "inline-block h-1.5 w-1.5 rounded-full border " +
          (connection === "live" ? "border-paper/50" : "border-paper/25")
        }
      />
      {connection === "live" ? "live" : "…"}
    </span>
  );
}
