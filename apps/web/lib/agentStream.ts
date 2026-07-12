// DIY SSE consumer for POST /sessions/{id}/turn.
//
// S04 intentionally kept the SSE wire protocol minimal (data-only frames,
// delimited by a blank line) so the browser does not need any streaming
// client dependency. This module owns both halves:
//
//   1. parseFrames(buffer)   — pure string→frames+remaining splitter used by
//                              the hook AND by unit tests (T06 load-bearing).
//   2. useAgentStream(opts)  — React hook that POSTs a turn, reads the
//                              response body as a stream, and fans frames out
//                              to per-type callbacks.
//
// Failure-mode alignment: the backend emits `data: {"type":"error", ...}\n\n`
// as its in-stream fallback, and we mirror that shape for client-origin
// failures (network error, non-2xx) so downstream code only has to handle
// one error surface.

"use client";

import { useCallback, useRef } from "react";

import type {
  ActivityFrame,
  AgentNode,
  CardFrame,
  CardProposedFrame,
  DeltaFrame,
  DoneFrame,
  DraftAssembledFrame,
  ErrorFrame,
  ExperienceSnapshot,
  FirstTokenFrame,
  IntakeCompleteFrame,
  ItineraryUpdatedFrame,
  MoodFrame,
  NodeCreatedFrame,
  NodeUpdatedFrame,
  PartyUpdatedFrame,
  ProfileUpdatedFrame,
  SseFrame,
  SurfaceFrame,
} from "./agentStream.types";

export type {
  ActivityFrame,
  AgentNode,
  CardFrame,
  CardProposedFrame,
  DeltaFrame,
  DoneFrame,
  DraftAssembledFrame,
  ErrorFrame,
  ExperienceSnapshot,
  FirstTokenFrame,
  IntakeCompleteFrame,
  ItineraryUpdatedFrame,
  MoodFrame,
  NodeCreatedFrame,
  NodeUpdatedFrame,
  PartyUpdatedFrame,
  ProfileUpdatedFrame,
  SseFrame,
  SurfaceFrame,
} from "./agentStream.types";

import { parseSseJson } from "./sse";

export type ParseResult = {
  frames: SseFrame[];
  remaining: string;
};

const KNOWN_FRAME_TYPES: ReadonlySet<SseFrame["type"]> = new Set([
  "first_token",
  "delta",
  "done",
  "error",
  "card",
  "card_proposed",
  "node_created",
  "draft_assembled",
  "node_updated",
  "itinerary_updated",
  "party_updated",
  "profile_updated",
  "intake_complete",
  "mood",
  "activity",
  "surface",
]);

// Frames the agent emits for harness clients (ovb / the eval runner), not for
// the browser. Known-and-discarded: dropped without the unknown-frame warning
// so a dev stack running EMIT_TOOL_TRACE=1 doesn't spam the console.
const IGNORED_FRAME_TYPES: ReadonlySet<string> = new Set(["tool_trace"]);

function isSseFrame(value: unknown): value is SseFrame {
  if (!value || typeof value !== "object") return false;
  const type = (value as { type?: unknown }).type;
  if (typeof type !== "string") return false;
  if (!KNOWN_FRAME_TYPES.has(type as SseFrame["type"])) return false;

  // Card frames carry structured payload that downstream consumers dereference
  // immediately (graph node id, source lookups). Missing any required field
  // means it's not a usable frame — drop at the parser boundary.
  if (type === "card") {
    const v = value as {
      source?: unknown;
      source_id?: unknown;
      node_id?: unknown;
      snapshot?: unknown;
    };
    if (typeof v.source !== "string") return false;
    if (typeof v.source_id !== "string") return false;
    if (typeof v.node_id !== "string") return false;
    if (!v.snapshot || typeof v.snapshot !== "object") return false;
  }
  if (
    type === "card_proposed" ||
    type === "node_created" ||
    type === "node_updated"
  ) {
    const node = (value as { node?: unknown }).node;
    if (!node || typeof node !== "object") return false;
    const n = node as { id?: unknown; itinerary_id?: unknown };
    if (typeof n.id !== "string" || typeof n.itinerary_id !== "string") return false;
  }
  if (type === "draft_assembled") {
    const v = value as { edges_created?: unknown };
    if (typeof v.edges_created !== "number") return false;
  }
  if (type === "mood") {
    const v = value as { mood_id?: unknown };
    if (typeof v.mood_id !== "string") return false;
  }
  if (type === "party_updated") {
    const member = (value as { member?: unknown }).member;
    if (!member || typeof member !== "object") return false;
    if (typeof (member as { id?: unknown }).id !== "string") return false;
  }
  if (type === "profile_updated") {
    const v = value as { kind?: unknown };
    if (typeof v.kind !== "string" || v.kind.length === 0) return false;
  }
  if (type === "activity") {
    const v = value as { phase?: unknown };
    if (v.phase !== "call" && v.phase !== "result") return false;
  }
  if (type === "surface") {
    const v = value as { surface_id?: unknown; kind?: unknown; payload?: unknown };
    if (typeof v.surface_id !== "string") return false;
    if (typeof v.kind !== "string" || v.kind.length === 0) return false;
    if (!v.payload || typeof v.payload !== "object" || Array.isArray(v.payload)) return false;
  }

  return true;
}

/**
 * Split a UTF-8-decoded SSE buffer into complete agent frames plus the
 * trailing partial fragment that must be carried into the next read.
 *
 * The transport-level splitting lives in lib/sse.ts (shared with the Wave F
 * advisor feed); this wrapper applies the agent channel's KNOWN_FRAME_TYPES
 * guard. Pure: no fetch, no DOM, no timers. T06 reuses it as the sole parser
 * under unit test.
 */
export function parseFrames(buffer: string): ParseResult {
  const { payloads, remaining } = parseSseJson(buffer, "agentStream");
  const frames: SseFrame[] = [];

  for (const parsed of payloads) {
    if (!isSseFrame(parsed)) {
      const type =
        parsed && typeof parsed === "object"
          ? (parsed as { type?: unknown }).type
          : undefined;
      if (typeof type === "string" && IGNORED_FRAME_TYPES.has(type)) continue;
      const shape =
        parsed && typeof parsed === "object"
          ? Object.keys(parsed as Record<string, unknown>).slice(0, 5)
          : typeof parsed;
      console.warn("[agentStream] dropping unknown SSE frame", { shape });
      continue;
    }
    frames.push(parsed);
  }

  return { frames, remaining };
}

export type UseAgentStreamOptions = {
  // Either a stable sessionId known at hook-construction time OR a getter
  // that is consulted at send-time. The getter form is required when the
  // session is opened lazily (basecamp's first-touch submit) — React state
  // updates do not propagate to optsRef synchronously, so a `sessionId:
  // sessionId ?? ""` binding fires `/sessions//turn` on the very first
  // submit. Callers in that flow point getSessionId at a ref they update
  // alongside setSessionId so the URL is built from the freshest value.
  sessionId?: string;
  getSessionId?: () => string | null;
  // Called immediately before each fetch so we pick up a token refreshed by
  // @supabase/ssr since the last turn. Returning null aborts the turn with the
  // same `upstream_unavailable` surface as a network failure — the user is
  // logged out or cookies are gone, and the page should bounce back through
  // /auth on next nav anyway.
  getAccessToken: () => Promise<string | null>;
  apiBaseUrl: string;
  onFirstToken?: (frame: FirstTokenFrame) => void;
  onDelta?: (frame: DeltaFrame) => void;
  onDone?: (frame: DoneFrame) => void;
  onError?: (frame: ErrorFrame) => void;
  /**
   * Legacy handler — fires for the ``card`` SSE frame emitted by the
   * pre-agent-workspace runtime path in FastAPI's stream_turn. Kept for
   * back-compat while the new runtime rolls out; once the legacy
   * dispatch is deleted this handler should be removed alongside the
   * old frame type.
   */
  onCard?: (frame: CardFrame) => void;
  /**
   * New handler — fires for ``card_proposed`` frames emitted by the
   * apps/agent runtime after a ``propose_card`` tool call persists a
   * node. The payload is the full persisted node.
   */
  onCardProposed?: (node: AgentNode) => void;
  /**
   * Fires for ``node_created`` frames — a node the agent BUILT and persisted
   * server-side (e.g. a campaign-spine card). Unlike ``card_proposed`` (a
   * proposal awaiting accept) this node is already the trip, so consumers drop
   * it straight onto the canvas. A spine reveals as one frame per node.
   */
  onNodeCreated?: (node: AgentNode) => void;
  onDraftAssembled?: (frame: DraftAssembledFrame) => void;
  onNodeUpdated?: (node: AgentNode) => void;
  /**
   * Fires when the agent calls ``update_trip_timing`` — the trip's dates
   * changed. Timing is server-rendered onto the timeline, so surfaces that
   * show it wire this to ``router.refresh()`` to re-pull the fresh window
   * while keeping in-session graph state.
   */
  onItineraryUpdated?: (frame: ItineraryUpdatedFrame) => void;
  /**
   * Fires when the agent records/updates a party member (whitelisted subset —
   * name + relationship only). The intake details card renders "who's coming"
   * from it; other surfaces can ignore.
   */
  onPartyUpdated?: (frame: PartyUpdatedFrame) => void;
  /**
   * Fires when the agent records a profile fact during onboarding (carries the
   * fact ``kind`` only, never the text). The basecamp first-touch ledger lights
   * its "dream destination" / "something about you" checkmarks off the kind.
   */
  onProfileUpdated?: (frame: ProfileUpdatedFrame) => void;
  /**
   * Fires when the agent calls ``complete_intake`` — the immersive first
   * conversation is done. The intake surface docks the chat and navigates to
   * the trip dashboard.
   */
  onIntakeComplete?: (frame: IntakeCompleteFrame) => void;
  /**
   * Extra fields merged into the turn POST body alongside ``content``. The
   * immersive intake surface sends ``{surface: "intake"}`` so the backend
   * keeps the agent in intake mode for the whole screen.
   */
  extraBody?: Record<string, unknown>;
  /**
   * Fires when the agent calls ``set_mood`` to shift basecamp ambience.
   * The basecamp shell wires this to its current-mood state which
   * AtmosFrame then crossfades to. Off-basecamp surfaces can ignore.
   */
  onMood?: (frame: MoodFrame) => void;
  /**
   * Fires on every anonymous tool-activity pulse (``phase: "call" |
   * "result"``). Chat surfaces use it to show a working indicator during a
   * tool-first preamble — the pulse carries no tool identity by design, so
   * there is nothing to render beyond "the concierge is doing something".
   * Clear the indicator on the next delta / done / error.
   */
  onActivity?: (frame: ActivityFrame) => void;
  /**
   * Fires when the agent presents a drawer surface (``present_route`` /
   * ``present_options``). The payload is wire-shaped and unparsed — the chat
   * shell runs it through the per-kind tolerant parser before opening the
   * panel, so consumers that don't host a drawer can simply omit this.
   */
  onSurface?: (frame: SurfaceFrame) => void;
  /**
   * Caller-owned abort controller ref. The hook writes a fresh
   * AbortController into this ref at the start of every stream so the caller
   * (composer cancel, unmount effect) can call `.abort()` without needing
   * hook state.
   */
  abortRef?: React.MutableRefObject<AbortController | null>;
};

// `extra` is merged into the turn POST body for THIS call only (e.g.
// `{ surface: "kickoff" }` for the campaign dashboard's first, agent-first turn)
// — distinct from `extraBody`, which rides every turn of the stream.
export type SendTurnFn = (
  content: string,
  extra?: Record<string, unknown>,
) => Promise<void>;

export type UseAgentStreamResult = {
  sendTurn: SendTurnFn;
};

function isAbortError(err: unknown): boolean {
  if (err instanceof DOMException && err.name === "AbortError") return true;
  if (err && typeof err === "object" && (err as { name?: string }).name === "AbortError") {
    return true;
  }
  return false;
}

/**
 * React hook around the DIY fetch+ReadableStream consumer.
 *
 * Returns `sendTurn(content)` which performs one POST and resolves when the
 * stream reaches a terminal `done` or `error` frame (including the
 * backend-origin `upstream_unavailable` fallback). AbortError returns
 * silently — the caller decided to cancel, so there is nothing to report.
 * Network failures and non-2xx responses are surfaced via onError with the
 * same `{ reason: "upstream_unavailable" }` shape the backend uses, so
 * downstream UI code only handles one error path.
 */
export function useAgentStream(options: UseAgentStreamOptions): UseAgentStreamResult {
  const { abortRef } = options;

  // Hold the latest options in a ref so sendTurn's identity is stable across
  // renders without stale-closure issues when the consumer re-renders with
  // new callbacks mid-stream.
  const optsRef = useRef(options);
  optsRef.current = options;

  const sendTurn = useCallback<SendTurnFn>(
    async (content: string, extra?: Record<string, unknown>) => {
      const current = optsRef.current;
      const controller = new AbortController();
      if (abortRef) {
        abortRef.current = controller;
      }

      const sessionId = current.getSessionId?.() ?? current.sessionId ?? "";
      if (!sessionId) {
        console.error("[agentStream] no sessionId available at send time");
        current.onError?.({ type: "error", reason: "upstream_unavailable" });
        return;
      }
      const url = `${current.apiBaseUrl}/sessions/${sessionId}/turn`;
      const pathForLog = `/sessions/${sessionId}/turn`;

      // Pull the freshest token right before the fetch. @supabase/ssr's
      // browser client keeps the in-memory session auto-refreshed, so this
      // returns a newly-minted JWT when the previous one expired while the
      // user was idle between turns.
      const token = await current.getAccessToken();
      if (!token) {
        console.error("[agentStream] no access token available", { path: pathForLog });
        current.onError?.({ type: "error", reason: "upstream_unavailable" });
        return;
      }

      let response: Response;
      try {
        response = await fetch(url, {
          method: "POST",
          headers: {
            Authorization: `Bearer ${token}`,
            "Content-Type": "application/json",
            Accept: "text/event-stream",
          },
          body: JSON.stringify({ ...current.extraBody, ...extra, content }),
          signal: controller.signal,
        });
      } catch (err) {
        if (isAbortError(err)) return;
        console.error("[agentStream] fetch failed", { path: pathForLog });
        current.onError?.({ type: "error", reason: "upstream_unavailable" });
        return;
      }

      if (!response.ok || !response.body) {
        console.error("[agentStream] non-2xx response", {
          path: pathForLog,
          status: response.status,
        });
        current.onError?.({ type: "error", reason: "upstream_unavailable" });
        return;
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder("utf-8");
      let buffer = "";
      let terminated = false;

      try {
        while (!terminated) {
          const { value, done } = await reader.read();
          if (done) {
            // Flush any trailing bytes in the decoder.
            buffer += decoder.decode();
            const { frames } = parseFrames(buffer);
            dispatch(frames, current);
            break;
          }

          buffer += decoder.decode(value, { stream: true });
          const { frames, remaining } = parseFrames(buffer);
          buffer = remaining;

          for (const frame of frames) {
            switch (frame.type) {
              case "first_token":
                current.onFirstToken?.(frame);
                break;
              case "delta":
                current.onDelta?.(frame);
                break;
              case "done":
                current.onDone?.(frame);
                terminated = true;
                break;
              case "error":
                current.onError?.(frame);
                terminated = true;
                break;
              case "card":
                current.onCard?.(frame);
                break;
              case "card_proposed":
                current.onCardProposed?.(frame.node);
                break;
              case "node_created":
                current.onNodeCreated?.(frame.node);
                break;
              case "draft_assembled":
                current.onDraftAssembled?.(frame);
                break;
              case "node_updated":
                current.onNodeUpdated?.(frame.node);
                break;
              case "itinerary_updated":
                current.onItineraryUpdated?.(frame);
                break;
              case "party_updated":
                current.onPartyUpdated?.(frame);
                break;
              case "profile_updated":
                current.onProfileUpdated?.(frame);
                break;
              case "intake_complete":
                current.onIntakeComplete?.(frame);
                break;
              case "mood":
                current.onMood?.(frame);
                break;
              case "activity":
                current.onActivity?.(frame);
                break;
              case "surface":
                current.onSurface?.(frame);
                break;
            }
            if (terminated) break;
          }
        }
      } catch (err) {
        if (isAbortError(err)) return;
        console.error("[agentStream] stream read failed", { path: pathForLog });
        current.onError?.({ type: "error", reason: "upstream_unavailable" });
      } finally {
        if (abortRef && abortRef.current === controller) {
          abortRef.current = null;
        }
        try {
          reader.releaseLock();
        } catch {
          // Lock may already be released if the reader errored — harmless.
        }
      }
    },
    // All options (callbacks, sessionId, getAccessToken, apiBaseUrl) are read
    // off optsRef.current at call time, so sendTurn's identity only needs to
    // change when abortRef swaps.
    [abortRef],
  );

  return { sendTurn };
}

function dispatch(frames: SseFrame[], current: UseAgentStreamOptions): void {
  for (const frame of frames) {
    switch (frame.type) {
      case "first_token":
        current.onFirstToken?.(frame);
        break;
      case "delta":
        current.onDelta?.(frame);
        break;
      case "done":
        current.onDone?.(frame);
        break;
      case "error":
        current.onError?.(frame);
        break;
      case "card":
        current.onCard?.(frame);
        break;
      case "card_proposed":
        current.onCardProposed?.(frame.node);
        break;
      case "node_created":
        current.onNodeCreated?.(frame.node);
        break;
      case "draft_assembled":
        current.onDraftAssembled?.(frame);
        break;
      case "node_updated":
        current.onNodeUpdated?.(frame.node);
        break;
      case "itinerary_updated":
        current.onItineraryUpdated?.(frame);
        break;
      case "party_updated":
        current.onPartyUpdated?.(frame);
        break;
      case "profile_updated":
        current.onProfileUpdated?.(frame);
        break;
      case "intake_complete":
        current.onIntakeComplete?.(frame);
        break;
      case "mood":
        current.onMood?.(frame);
        break;
      case "activity":
        current.onActivity?.(frame);
        break;
      case "surface":
        current.onSurface?.(frame);
        break;
    }
  }
}
