// The advisor live feed's pure half (Wave F): frame types matching
// apps/api/app/services/feed.py's v1 contract, the channel guard, and the
// reducer that folds frames into feed state. No fetch, no DOM, no timers —
// unit-tested directly. The transport lives in useAdvisorFeed.ts.

export type FeedActivityEvent = {
  kind: string;
  at: string;
  source_id: string;
  client_id: string;
  itinerary_id: string | null;
  itinerary_title: string | null;
  actor_kind: string | null;
  title: string | null;
  op: string | null;
  status_before: string | null;
  status_after: string | null;
  amount: string | null;
  currency: string | null;
  ref_id: string | null;
};

export type AdvisorFrame =
  | { type: "hello"; v: 1; cursor: string; heartbeat_ms: number }
  | { type: "activity"; v: 1; event: FeedActivityEvent; cursor: string }
  | { type: "heartbeat"; at: string }
  | { type: "bye"; reason: string }
  | { type: "error"; reason: string };

export function isAdvisorFrame(value: unknown): value is AdvisorFrame {
  if (!value || typeof value !== "object") return false;
  const type = (value as { type?: unknown }).type;
  if (typeof type !== "string") return false;
  switch (type) {
    case "hello":
      return typeof (value as { cursor?: unknown }).cursor === "string";
    case "activity": {
      const v = value as { event?: unknown; cursor?: unknown };
      if (typeof v.cursor !== "string") return false;
      if (!v.event || typeof v.event !== "object") return false;
      const e = v.event as { kind?: unknown; source_id?: unknown; client_id?: unknown };
      return (
        typeof e.kind === "string" &&
        typeof e.source_id === "string" &&
        typeof e.client_id === "string"
      );
    }
    case "heartbeat":
    case "bye":
    case "error":
      return true;
    default:
      return false;
  }
}

export type FeedConnection = "connecting" | "live" | "polling";

export type FeedState = {
  connection: FeedConnection;
  /** Newest-first ring buffer of live events (cap EVENT_BUFFER_CAP). */
  events: FeedActivityEvent[];
  /** client_id → ISO timestamp of their last agent turn (the LIVE pulse). */
  liveSessions: Record<string, string>;
  /** Resume watermark for the next (re)connect. */
  cursor: string | null;
};

export const EVENT_BUFFER_CAP = 100;

// An agent session reads as "live" while its last turn is inside this window.
export const LIVE_SESSION_WINDOW_MS = 5 * 60 * 1000;

export function initialFeedState(): FeedState {
  return { connection: "connecting", events: [], liveSessions: {}, cursor: null };
}

function eventKey(e: FeedActivityEvent): string {
  return `${e.kind}:${e.source_id}`;
}

/** Fold one frame into the state. Pure; returns the same object when inert. */
export function feedReducer(state: FeedState, frame: AdvisorFrame): FeedState {
  switch (frame.type) {
    case "hello":
      return { ...state, connection: "live", cursor: frame.cursor };
    case "heartbeat":
      return state.connection === "live" ? state : { ...state, connection: "live" };
    case "activity": {
      const seen = new Set(state.events.map(eventKey));
      if (seen.has(eventKey(frame.event))) {
        return { ...state, cursor: frame.cursor };
      }
      const events = [frame.event, ...state.events].slice(0, EVENT_BUFFER_CAP);
      const liveSessions =
        frame.event.kind === "agent_turn"
          ? { ...state.liveSessions, [frame.event.client_id]: frame.event.at }
          : state.liveSessions;
      return { ...state, events, liveSessions, cursor: frame.cursor };
    }
    case "bye":
    case "error":
      // The transport decides what happens next (reconnect/backoff); the
      // state just stops claiming liveness.
      return { ...state, connection: "connecting" };
    default:
      return state;
  }
}

/** Client ids whose sessions turned inside the live window, as of `now`. */
export function liveClientIds(state: FeedState, now: number): string[] {
  return Object.entries(state.liveSessions)
    .filter(([, at]) => now - new Date(at).getTime() < LIVE_SESSION_WINDOW_MS)
    .map(([clientId]) => clientId);
}
