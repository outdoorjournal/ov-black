"use client";

// The advisor feed transport (Wave F): a fetch-reader over GET /advisor/feed
// (EventSource can't send Authorization; the fetch reader can — the same
// choice agentStream made), dispatching frames into the AdvisorFeed store and
// nudging server-rendered data via a THROTTLED router.refresh().
//
// Lifecycle:
// - fresh Supabase token per (re)connect; resume from the store's cursor
// - exponential backoff 1s→30s (+jitter); after MAX_SSE_FAILURES straight
//   failures degrade to "polling" (refresh-only, PROBE_INTERVAL_MS re-probes)
// - heartbeat watchdog: no frame for WATCHDOG_MS ⇒ the stream is dead even
//   if the socket isn't — reconnect
// - visibility: hidden tab aborts the stream (and pauses refreshes); visible
//   reconnects immediately and refreshes once
//
// The 15s visible-only refresh throttle is LOAD-BEARING: every refresh
// re-runs a force-dynamic page's full server fetch set. Do not wire frames
// straight to router.refresh().

import { useRouter } from "next/navigation";
import { useEffect, useRef } from "react";

import { isAdvisorFrame } from "./advisorFeed";
import { parseSseJson } from "./sse";
import { useAdvisorFeedStoreApi } from "@/app/command-center/_state/advisorFeedStore";

const BACKOFF_BASE_MS = 1000;
const BACKOFF_CAP_MS = 30_000;
const MAX_SSE_FAILURES = 4;
const PROBE_INTERVAL_MS = 120_000;
const WATCHDOG_MS = 60_000;
const REFRESH_THROTTLE_MS = 15_000;

export function useAdvisorFeed({
  getAccessToken,
  apiBaseUrl,
}: {
  getAccessToken: () => Promise<string | null>;
  apiBaseUrl: string;
}): void {
  const router = useRouter();
  const storeApi = useAdvisorFeedStoreApi();
  // Everything lives in refs — the effect runs once per mount and manages its
  // own loop; re-renders must not tear the stream down.
  const opts = useRef({ getAccessToken, apiBaseUrl });
  opts.current = { getAccessToken, apiBaseUrl };

  useEffect(() => {
    let disposed = false;
    let controller: AbortController | null = null;
    let failures = 0;
    let lastFrameAt = Date.now();
    let lastRefreshAt = 0;
    let refreshTimer: ReturnType<typeof setTimeout> | null = null;
    let loopTimer: ReturnType<typeof setTimeout> | null = null;

    const requestRefresh = () => {
      // Coalesce bursts into at most one refresh per throttle window, and
      // only while the tab is visible (hidden tabs reconnect-and-refresh on
      // return instead).
      if (document.visibilityState !== "visible") return;
      const now = Date.now();
      const wait = Math.max(0, lastRefreshAt + REFRESH_THROTTLE_MS - now);
      if (refreshTimer) return;
      refreshTimer = setTimeout(() => {
        refreshTimer = null;
        lastRefreshAt = Date.now();
        router.refresh();
      }, wait);
    };

    const connectOnce = async (): Promise<"closed" | "failed"> => {
      const token = await opts.current.getAccessToken();
      if (!token) return "failed";
      controller = new AbortController();
      const watchdog = setInterval(() => {
        if (Date.now() - lastFrameAt > WATCHDOG_MS) controller?.abort();
      }, WATCHDOG_MS / 4);

      try {
        const cursor = storeApi.getState().cursor;
        const url = new URL("/advisor/feed", opts.current.apiBaseUrl);
        if (cursor) url.searchParams.set("cursor", cursor);
        const response = await fetch(url.toString(), {
          headers: {
            Authorization: `Bearer ${token}`,
            Accept: "text/event-stream",
          },
          signal: controller.signal,
        });
        if (!response.ok || !response.body) return "failed";

        failures = 0;
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const { payloads, remaining } = parseSseJson(buffer, "advisorFeed");
          buffer = remaining;
          for (const payload of payloads) {
            if (!isAdvisorFrame(payload)) continue;
            lastFrameAt = Date.now();
            storeApi.getState().applyFrame(payload);
            if (payload.type === "activity") requestRefresh();
            if (payload.type === "bye") return "closed";
          }
        }
        return "closed"; // server ended (deploy, lifetime cap) — reconnect
      } catch {
        return controller.signal.aborted ? "closed" : "failed";
      } finally {
        clearInterval(watchdog);
        controller = null;
      }
    };

    const loop = async () => {
      while (!disposed) {
        if (document.visibilityState !== "visible") {
          await new Promise<void>((resolve) => {
            const onVisible = () => {
              document.removeEventListener("visibilitychange", onVisible);
              resolve();
            };
            document.addEventListener("visibilitychange", onVisible);
          });
          if (disposed) return;
          // Back from a hidden tab: snapshot truth before streaming again.
          lastRefreshAt = 0;
          requestRefresh();
        }

        lastFrameAt = Date.now();
        const outcome = await connectOnce();
        if (disposed) return;

        if (outcome === "failed") {
          failures += 1;
          if (failures >= MAX_SSE_FAILURES) {
            storeApi.getState().setConnection("polling");
            // Degraded: throttled refreshes only, re-probe periodically.
            await new Promise<void>((resolve) => {
              loopTimer = setTimeout(resolve, PROBE_INTERVAL_MS);
            });
            requestRefresh();
            continue;
          }
          storeApi.getState().setConnection("connecting");
          const backoff =
            Math.min(BACKOFF_CAP_MS, BACKOFF_BASE_MS * 2 ** (failures - 1)) *
            (0.8 + Math.random() * 0.4);
          await new Promise<void>((resolve) => {
            loopTimer = setTimeout(resolve, backoff);
          });
        } else {
          // Clean close (bye / server end / visibility abort): refresh for
          // anything missed in the gap, then reconnect promptly.
          storeApi.getState().setConnection("connecting");
          requestRefresh();
        }
      }
    };

    const onVisibilityHide = () => {
      if (document.visibilityState !== "visible") controller?.abort();
    };
    document.addEventListener("visibilitychange", onVisibilityHide);
    void loop();

    return () => {
      disposed = true;
      document.removeEventListener("visibilitychange", onVisibilityHide);
      controller?.abort();
      if (refreshTimer) clearTimeout(refreshTimer);
      if (loopTimer) clearTimeout(loopTimer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- single long-lived loop; opts flow through refs
  }, []);
}
