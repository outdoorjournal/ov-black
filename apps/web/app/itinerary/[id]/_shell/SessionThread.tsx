"use client";

// One Artemis audience as a resumable session LIST (M006/PS2). Un-collapses the
// old single re-pinned session: the concierge scope now holds many named,
// scoped conversations you can browse, resume, start, rename, and archive.
//
// The active thread is a <ConciergeChat> bound to a specific session id. A
// `chatKey` forces a clean remount (fresh buffer + history replay) ONLY on an
// explicit switch/new — never when the draft thread lazily opens its own
// session mid-turn (that would abort the stream), so a first message is safe.

import { useCallback, useEffect, useRef, useState } from "react";

import {
  createApiClient,
  createSessionEndpoint,
  listSessions,
  patchSession,
  type SessionSummary,
} from "@ov-black/api-client";

import { ConciergeChat } from "@/app/_components/itinerary-graph/views/horizontal/ConciergeChat";

type Audience = "advisor" | "traveler";

export function SessionThread({
  audience,
  clientId,
  itineraryId,
  apiBaseUrl,
  accessToken,
  intro,
  autoKickoff = false,
}: {
  audience: Audience;
  clientId: string | null;
  itineraryId: string;
  apiBaseUrl: string | null;
  accessToken: string | null;
  intro?: string;
  /** Campaign dashboard: the agent speaks first + builds the skeleton once. */
  autoKickoff?: boolean;
}) {
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  // `chatKey` remounts the bound chat; `boundId` is the resume target (undefined
  // = a fresh draft that opens its own session on the first turn).
  const [chatKey, setChatKey] = useState("draft");
  const [boundId, setBoundId] = useState<string | undefined>(undefined);
  const [listOpen, setListOpen] = useState(false);
  // Has the mount-time "resume latest" pass finished? The campaign kickoff must
  // NOT fire until it has: otherwise ConciergeChat's autoKickoff races the
  // async resume, opens a throwaway session, and gets aborted when the resume
  // remounts it onto the real one — spawning an empty conversation and building
  // nothing. Gating the kickoff on this makes it a single clean turn in the
  // resumed (intake) session.
  const [resolved, setResolved] = useState(false);
  const seeded = useRef(false);

  const canApi = Boolean(apiBaseUrl && accessToken && clientId);
  const api = useCallback(() => {
    if (!apiBaseUrl || !accessToken) return null;
    return createApiClient({ baseUrl: apiBaseUrl, accessToken });
  }, [apiBaseUrl, accessToken]);

  const refetch = useCallback(async (): Promise<SessionSummary[]> => {
    const client = api();
    if (!client || !clientId) return [];
    const result = await listSessions(client, {
      clientId,
      audience,
      itineraryId,
    });
    const rows = result.ok ? result.sessions : [];
    setSessions(rows);
    return rows;
  }, [api, clientId, audience, itineraryId]);

  // On mount, load the list and resume the most-recent session (if any).
  useEffect(() => {
    if (!canApi || seeded.current) return;
    seeded.current = true;
    void (async () => {
      const rows = await refetch();
      const latest = rows[0];
      if (latest) {
        setActiveId(latest.session_id);
        setBoundId(latest.session_id);
        setChatKey(latest.session_id);
      }
      // Kickoff is now free to fire — into the resumed session if there was one,
      // or a fresh draft as the backstop when there genuinely isn't.
      setResolved(true);
    })();
  }, [canApi, refetch]);

  const resume = useCallback((id: string) => {
    setActiveId(id);
    setBoundId(id);
    setChatKey(id);
    setListOpen(false);
  }, []);

  const startNew = useCallback(async () => {
    const client = api();
    if (!client || !clientId) return;
    const result = await createSessionEndpoint(client, {
      client_id: clientId,
      itinerary_id: itineraryId,
      audience,
      force_new: true,
    });
    if (!result.ok) return;
    await refetch();
    resume(result.session_id);
  }, [api, clientId, itineraryId, audience, refetch, resume]);

  const rename = useCallback(
    async (id: string, title: string) => {
      const client = api();
      if (!client) return;
      await patchSession(client, id, { title });
      await refetch();
    },
    [api, refetch],
  );

  const archive = useCallback(
    async (id: string) => {
      const client = api();
      if (!client) return;
      await patchSession(client, id, { archived: true });
      const rows = await refetch();
      if (id === activeId) {
        // Fall back to the next live session, or a fresh draft.
        const next = rows[0];
        if (next) resume(next.session_id);
        else {
          setActiveId(null);
          setBoundId(undefined);
          setChatKey(`draft-${id}`);
        }
      }
    },
    [api, refetch, activeId, resume],
  );

  // A draft thread lazily opened its own session — surface it in the list, but
  // DON'T remount (the turn is streaming). The chat's own ref now holds the id.
  const handleOpened = useCallback(
    (id: string) => {
      setActiveId((prev) => prev ?? id);
      void refetch();
    },
    [refetch],
  );

  const activeTitle =
    sessions.find((s) => s.session_id === activeId)?.title ?? null;

  return (
    // h-full (not flex-1): the host wrappers in ConciergeColumn are plain block
    // divs with a definite height, so flex-1 would be inert here and the thread
    // would size to its content and overflow the column instead of filling it.
    <div className="flex h-full min-h-0 flex-col">
      {/* Session bar doubles as the concierge masthead (the old static
          "Concierge / Conversation" header is dropped — ConciergeChat gets
          hideHeader below): the eyebrow + the active conversation name in the
          serif title slot (tap to browse), with New reclaiming the right-side
          space that header used to waste. */}
      <div className="flex shrink-0 items-center gap-3 border-b border-ink/10 bg-paper/85 px-4 py-2 backdrop-blur-xs">
        <button
          type="button"
          onClick={() => setListOpen((v) => !v)}
          data-testid="session-bar"
          aria-expanded={listOpen}
          className="flex min-w-0 flex-1 flex-col items-start text-left"
        >
          <span className="text-[10px] uppercase tracking-[0.24em] text-ink/55">
            Concierge
          </span>
          <span className="flex w-full min-w-0 items-center gap-1.5">
            <span className="truncate font-serif text-lg text-ink">
              {activeTitle ?? "New conversation"}
            </span>
            <span
              aria-hidden
              className={
                "shrink-0 text-ink/40 transition-transform " +
                (listOpen ? "rotate-180" : "")
              }
            >
              ⌄
            </span>
          </span>
        </button>
        <button
          type="button"
          onClick={() => void startNew()}
          disabled={!canApi}
          data-testid="session-new"
          className="h-7 shrink-0 rounded-md border border-ink/20 px-2 font-sans text-[10px] uppercase tracking-[0.16em] text-ink/70 transition-colors hover:bg-ink/5 disabled:opacity-40"
        >
          New
        </button>
      </div>

      {listOpen ? (
        <div
          data-testid="session-list"
          className="max-h-56 shrink-0 overflow-y-auto border-b border-ink/10 bg-paper/60"
        >
          {sessions.length === 0 ? (
            <p className="px-3 py-3 font-serif text-[13px] italic text-ink/45">
              No conversations yet. Start one below, or tap New.
            </p>
          ) : (
            sessions.map((s) => (
              <SessionRow
                key={s.session_id}
                session={s}
                active={s.session_id === activeId}
                onResume={() => resume(s.session_id)}
                onRename={(title) => void rename(s.session_id, title)}
                onArchive={() => void archive(s.session_id)}
              />
            ))
          )}
        </div>
      ) : null}

      <div className="min-h-0 flex-1">
        <ConciergeChat
          key={chatKey}
          audience={audience}
          apiBaseUrl={apiBaseUrl}
          accessToken={accessToken}
          clientId={clientId}
          itineraryId={itineraryId}
          hideHeader
          hydrateHistory={Boolean(boundId)}
          autoKickoff={autoKickoff && resolved}
          {...(boundId ? { sessionId: boundId } : {})}
          {...(intro ? { intro } : {})}
          onSessionOpened={handleOpened}
          surfaceSide="right"
        />
      </div>
    </div>
  );
}

// Shared row markup for a resumable session (name / rename / archive). Also
// consumed by basecamp's RightRailChat, whose session rail lists the unpinned
// (itinerary_id NULL) scope with the same affordances.
export function SessionRow({
  session,
  active,
  onResume,
  onRename,
  onArchive,
}: {
  session: SessionSummary;
  active: boolean;
  onResume: () => void;
  onRename: (title: string) => void;
  onArchive: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(session.title ?? "");

  return (
    <div
      data-testid="session-row"
      data-active={active ? "true" : "false"}
      className={
        "group flex items-center gap-2 px-3 py-2 " +
        (active ? "bg-ink/6" : "hover:bg-ink/3")
      }
    >
      {editing ? (
        <input
          autoFocus
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={() => {
            setEditing(false);
            const next = draft.trim();
            if (next && next !== session.title) onRename(next);
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter") e.currentTarget.blur();
            if (e.key === "Escape") {
              setDraft(session.title ?? "");
              setEditing(false);
            }
          }}
          data-testid="session-rename-input"
          className="h-6 min-w-0 flex-1 rounded border border-ink/20 bg-paper-white px-1.5 font-serif text-[13px] text-ink focus:border-ink/40 focus:outline-hidden"
        />
      ) : (
        <button
          type="button"
          onClick={onResume}
          data-testid="session-resume"
          className="min-w-0 flex-1 truncate text-left font-serif text-[13px] text-ink"
        >
          {session.title || "Untitled conversation"}
        </button>
      )}
      <button
        type="button"
        onClick={() => {
          setDraft(session.title ?? "");
          setEditing(true);
        }}
        data-testid="session-rename"
        className="shrink-0 font-sans text-[9px] uppercase tracking-[0.16em] text-ink/40 opacity-0 transition-opacity hover:text-ink group-hover:opacity-100"
      >
        Rename
      </button>
      <button
        type="button"
        onClick={onArchive}
        data-testid="session-archive"
        className="shrink-0 font-sans text-[9px] uppercase tracking-[0.16em] text-ink/40 opacity-0 transition-opacity hover:text-ink group-hover:opacity-100"
      >
        Archive
      </button>
    </div>
  );
}
