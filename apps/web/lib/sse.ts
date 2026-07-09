// Generic SSE frame splitting — the transport-level half shared by every
// data-only SSE consumer (the agent turn stream in agentStream.ts, the Wave F
// advisor feed in advisorFeed.ts). Channel-specific frame validation stays
// with each consumer: the agent stream keeps its KNOWN_FRAME_TYPES guard, the
// advisor feed has its own — this module only turns bytes-decoded text into
// parsed JSON payloads plus the trailing partial fragment.

export type SseJsonResult = {
  payloads: unknown[];
  remaining: string;
};

// Truncate the malformed-frame warning payload so we never echo a full delta
// into the DevTools console by accident.
const MALFORMED_FRAME_LOG_CAP = 80;

/**
 * Split a UTF-8-decoded SSE buffer into parsed JSON payloads plus the
 * trailing partial frame that must be carried into the next read.
 *
 * A "complete frame" is anything up to the next `\n\n` delimiter. Inside a
 * frame we only honour lines that start with `data: ` (or bare `data:`) —
 * comments (`:`) and unknown fields are silently ignored, matching the SSE
 * spec subset the backend actually emits. Multi-line `data:` payloads join
 * with `\n` for spec-correctness. Non-JSON payloads are dropped with a capped
 * console warning.
 *
 * Pure: no fetch, no DOM, no timers — unit-tested directly.
 */
export function parseSseJson(buffer: string, channel = "sse"): SseJsonResult {
  const payloads: unknown[] = [];
  let cursor = 0;

  while (true) {
    const delim = buffer.indexOf("\n\n", cursor);
    if (delim === -1) break;

    const rawFrame = buffer.slice(cursor, delim);
    cursor = delim + 2;

    const dataPieces: string[] = [];
    for (const line of rawFrame.split("\n")) {
      if (line.startsWith("data: ")) {
        dataPieces.push(line.slice(6));
      } else if (line.startsWith("data:")) {
        dataPieces.push(line.slice(5));
      }
      // Any other prefix (comment, event:, id:, blank) is ignored.
    }

    if (dataPieces.length === 0) continue;

    const payload = dataPieces.join("\n");
    try {
      payloads.push(JSON.parse(payload));
    } catch {
      const excerpt = payload.slice(0, MALFORMED_FRAME_LOG_CAP);
      console.warn(`[${channel}] dropping non-JSON SSE frame`, { excerpt });
    }
  }

  return { payloads, remaining: buffer.slice(cursor) };
}
