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
  AgentNode,
  CardFrame,
  CardProposedFrame,
  DeltaFrame,
  DoneFrame,
  DraftAssembledFrame,
  ErrorFrame,
  ExperienceSnapshot,
  FirstTokenFrame,
  NodeUpdatedFrame,
  SseFrame,
} from "./agentStream.types";

export type {
  AgentNode,
  CardFrame,
  CardProposedFrame,
  DeltaFrame,
  DoneFrame,
  DraftAssembledFrame,
  ErrorFrame,
  ExperienceSnapshot,
  FirstTokenFrame,
  NodeUpdatedFrame,
  SseFrame,
} from "./agentStream.types";

export type ParseResult = {
  frames: SseFrame[];
  remaining: string;
};

// Truncate the unknown-frame warning payload so we never echo a full delta
// into the DevTools console by accident. 80 chars is enough to identify the
// shape during debugging without leaking content.
const UNKNOWN_FRAME_LOG_CAP = 80;

const KNOWN_FRAME_TYPES: ReadonlySet<SseFrame["type"]> = new Set([
  "first_token",
  "delta",
  "done",
  "error",
  "card",
  "card_proposed",
  "draft_assembled",
  "node_updated",
]);

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
  if (type === "card_proposed" || type === "node_updated") {
    const node = (value as { node?: unknown }).node;
    if (!node || typeof node !== "object") return false;
    const n = node as { id?: unknown; itinerary_id?: unknown };
    if (typeof n.id !== "string" || typeof n.itinerary_id !== "string") return false;
  }
  if (type === "draft_assembled") {
    const v = value as { edges_created?: unknown };
    if (typeof v.edges_created !== "number") return false;
  }

  return true;
}

/**
 * Split a UTF-8-decoded SSE buffer into complete frames plus the trailing
 * partial fragment that must be carried into the next read.
 *
 * A "complete frame" is anything up to the next `\n\n` delimiter. Inside a
 * frame we only honour lines that start with `data: ` — comments (`:`) and
 * unknown fields are silently ignored, matching the SSE spec subset the
 * backend actually uses.
 *
 * This function is pure: no fetch, no DOM, no timers. T06 reuses it as the
 * sole parser under unit test.
 */
export function parseFrames(buffer: string): ParseResult {
  const frames: SseFrame[] = [];
  let cursor = 0;

  while (true) {
    const delim = buffer.indexOf("\n\n", cursor);
    if (delim === -1) break;

    const rawFrame = buffer.slice(cursor, delim);
    cursor = delim + 2;

    // A frame is one or more lines; SSE allows multi-line `data:` payloads,
    // but the backend only emits single-line data frames. We still join
    // multiple `data:` lines with `\n` so we stay spec-correct if that ever
    // changes.
    const dataPieces: string[] = [];
    for (const line of rawFrame.split("\n")) {
      if (line.startsWith("data: ")) {
        dataPieces.push(line.slice(6));
      } else if (line.startsWith("data:")) {
        // `data:` with no space is also valid per spec.
        dataPieces.push(line.slice(5));
      }
      // Any other prefix (comment, event:, id:, blank) is ignored.
    }

    if (dataPieces.length === 0) continue;

    const payload = dataPieces.join("\n");
    let parsed: unknown;
    try {
      parsed = JSON.parse(payload);
    } catch {
      const excerpt = payload.slice(0, UNKNOWN_FRAME_LOG_CAP);
      console.warn("[agentStream] dropping non-JSON SSE frame", { excerpt });
      continue;
    }

    if (!isSseFrame(parsed)) {
      const shape =
        parsed && typeof parsed === "object"
          ? Object.keys(parsed as Record<string, unknown>).slice(0, 5)
          : typeof parsed;
      console.warn("[agentStream] dropping unknown SSE frame", { shape });
      continue;
    }

    frames.push(parsed);
  }

  return { frames, remaining: buffer.slice(cursor) };
}

export type UseAgentStreamOptions = {
  sessionId: string;
  accessToken: string;
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
  onDraftAssembled?: (frame: DraftAssembledFrame) => void;
  onNodeUpdated?: (node: AgentNode) => void;
  /**
   * Caller-owned abort controller ref. The hook writes a fresh
   * AbortController into this ref at the start of every stream so the caller
   * (composer cancel, unmount effect) can call `.abort()` without needing
   * hook state.
   */
  abortRef?: React.MutableRefObject<AbortController | null>;
};

export type SendTurnFn = (content: string) => Promise<void>;

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
  const { sessionId, accessToken, apiBaseUrl, onFirstToken, onDelta, onDone, onError, abortRef } =
    options;

  // Hold the latest options in a ref so sendTurn's identity is stable across
  // renders without stale-closure issues when the consumer re-renders with
  // new callbacks mid-stream.
  const optsRef = useRef(options);
  optsRef.current = options;

  const sendTurn = useCallback<SendTurnFn>(
    async (content: string) => {
      const current = optsRef.current;
      const controller = new AbortController();
      if (abortRef) {
        abortRef.current = controller;
      }

      const url = `${current.apiBaseUrl}/sessions/${current.sessionId}/turn`;
      const pathForLog = `/sessions/${current.sessionId}/turn`;

      let response: Response;
      try {
        response = await fetch(url, {
          method: "POST",
          headers: {
            Authorization: `Bearer ${current.accessToken}`,
            "Content-Type": "application/json",
            Accept: "text/event-stream",
          },
          body: JSON.stringify({ content }),
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
              case "draft_assembled":
                current.onDraftAssembled?.(frame);
                break;
              case "node_updated":
                current.onNodeUpdated?.(frame.node);
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
    // onFirstToken/onDelta/onDone/onError/sessionId/accessToken/apiBaseUrl
    // are all read off optsRef.current at call time, so sendTurn's identity
    // only needs to change when abortRef swaps.
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
      case "draft_assembled":
        current.onDraftAssembled?.(frame);
        break;
      case "node_updated":
        current.onNodeUpdated?.(frame.node);
        break;
    }
  }
}
