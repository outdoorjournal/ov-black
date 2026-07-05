"use client";

// The human messaging channel (M006/PS7 → PS8) — the "Advisor" people-circle. A
// durable conversation between the traveler, their advisor, and (once party
// members have logins) that trip's party. Unlike the Artemis SessionThread this
// has NO SSE stream: it get-or-creates the one human thread for the scope, lists
// its messages, and posts human messages. A light poll surfaces the other
// party's replies (no realtime yet).
//
// PS8 — @-mention bridge: mentioning `@Artemis` in a message summons the
// concierge into this thread. The backend runs the turn AFTER the send (so the
// human message lands instantly) and inserts one `author_kind==='artemis'`
// reply; the poll surfaces it. Disclosure follows the THREAD (client-safe even
// when an advisor summons), never the sender.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  createApiClient,
  listMessages,
  openThread,
  sendMessage,
  type MessageSummary,
} from "@ov-black/api-client";

import { ProseMessage } from "@/app/chat/[client_id]/_components/ProseMessage";

const POLL_MS = 6000;
// While a summoned Artemis reply is expected, poll harder so it lands promptly.
const POLL_AWAITING_MS = 2500;
// Give up the "composing" hint if no reply arrives — the human message stands.
const AWAIT_TIMEOUT_MS = 45000;

// Mirrors the backend trigger (services/agent.py `_MENTION_RE`): a standalone,
// case-insensitive `@artemis`. The lookbehind rejects an `@` glued to a word so
// `name@artemis.example` never fires.
const MENTION_RE = /(?<![\w@])@artemis\b/i;

function mentionsArtemis(text: string): boolean {
  return MENTION_RE.test(text);
}

type ViewerKind = "advisor" | "traveler";

export function HumanThread({
  clientId,
  itineraryId = null,
  apiBaseUrl,
  accessToken,
  viewerKind,
}: {
  clientId: string | null;
  /** Omit / null for the basecamp channel (you ↔ advisor); a trip id scopes it
   *  to that itinerary's thread (you ↔ advisor ↔ party). */
  itineraryId?: string | null;
  apiBaseUrl: string | null;
  accessToken: string | null;
  viewerKind: ViewerKind;
}) {
  const [threadId, setThreadId] = useState<string | null>(null);
  const [messages, setMessages] = useState<MessageSummary[]>([]);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  // PS8: after summoning Artemis, show a quiet "composing" hint until the reply
  // lands (or the timeout lapses). `pendingSinceRef` snapshots the Artemis-message
  // count at summon time so the next one that arrives clears the hint.
  const [awaitingArtemis, setAwaitingArtemis] = useState(false);
  const pendingSinceRef = useRef<number | null>(null);
  const awaitTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const composerRef = useRef<HTMLTextAreaElement>(null);
  const seeded = useRef(false);

  const artemisCount = useMemo(
    () => messages.filter((m) => m.author_kind === "artemis").length,
    [messages],
  );

  const canApi = Boolean(apiBaseUrl && accessToken && clientId);
  const api = useCallback(() => {
    if (!apiBaseUrl || !accessToken) return null;
    return createApiClient({ baseUrl: apiBaseUrl, accessToken });
  }, [apiBaseUrl, accessToken]);

  // Resolve (get-or-create) the human thread for this scope, then load history.
  useEffect(() => {
    if (!canApi || seeded.current) return;
    seeded.current = true;
    void (async () => {
      const client = api();
      if (!client || !clientId) return;
      const resolved = await openThread(client, { clientId, itineraryId });
      // itineraryId=null → the basecamp thread (you ↔ advisor); openThread omits
      // it from the request body so the backend resolves the basecamp scope.
      if (!resolved.ok) {
        setStatus("error");
        return;
      }
      setThreadId(resolved.thread.thread_id);
      const loaded = await listMessages(client, resolved.thread.thread_id);
      if (loaded.ok) setMessages(loaded.messages);
      setStatus("ready");
    })();
  }, [canApi, api, clientId, itineraryId]);

  // Poll for the other party's messages while the channel is open. Poll harder
  // while a summoned Artemis reply is expected so it lands promptly.
  useEffect(() => {
    if (!threadId) return;
    const client = api();
    if (!client) return;
    const timer = setInterval(
      () => {
        void (async () => {
          const loaded = await listMessages(client, threadId);
          if (loaded.ok) setMessages(loaded.messages);
        })();
      },
      awaitingArtemis ? POLL_AWAITING_MS : POLL_MS,
    );
    return () => clearInterval(timer);
  }, [threadId, api, awaitingArtemis]);

  // Clear the "composing" hint the moment a new Artemis message arrives.
  useEffect(() => {
    if (!awaitingArtemis || pendingSinceRef.current === null) return;
    if (artemisCount > pendingSinceRef.current) {
      setAwaitingArtemis(false);
      pendingSinceRef.current = null;
      if (awaitTimerRef.current) clearTimeout(awaitTimerRef.current);
    }
  }, [artemisCount, awaitingArtemis]);

  // Drop any pending timer on unmount.
  useEffect(
    () => () => {
      if (awaitTimerRef.current) clearTimeout(awaitTimerRef.current);
    },
    [],
  );

  // Keep the transcript pinned to the newest message.
  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages]);

  const send = useCallback(async () => {
    const text = draft.trim();
    if (!text || !threadId || sending) return;
    const client = api();
    if (!client) return;
    const summoning = mentionsArtemis(text);
    setSending(true);
    const result = await sendMessage(client, threadId, { content: text });
    setSending(false);
    if (result.ok) {
      setDraft("");
      // Optimistic append; the next poll reconciles ordering with the server.
      setMessages((prev) => [...prev, result.message]);
      if (summoning) {
        // The backend runs the summon after the send; the reply lands on a
        // later poll. Snapshot the current Artemis count so the arrival clears
        // the hint, and arm a safety timeout.
        pendingSinceRef.current = artemisCount;
        setAwaitingArtemis(true);
        if (awaitTimerRef.current) clearTimeout(awaitTimerRef.current);
        awaitTimerRef.current = setTimeout(() => {
          setAwaitingArtemis(false);
          pendingSinceRef.current = null;
        }, AWAIT_TIMEOUT_MS);
      }
    }
  }, [draft, threadId, sending, api, artemisCount]);

  // Prepend the @Artemis mention (once) and focus the composer so the human can
  // finish their question. Summoning is the mention itself — the send does the rest.
  const askArtemis = useCallback(() => {
    setDraft((d) => (mentionsArtemis(d) ? d : `@Artemis ${d.trimStart()}`));
    composerRef.current?.focus();
  }, []);

  const intro =
    viewerKind === "advisor"
      ? "The client conversation — visible to the traveler and their party. Mention @Artemis to bring the concierge in; its reply is client-safe."
      : "Message your advisor and travel party. Mention @Artemis to bring the concierge into the conversation.";

  return (
    <div data-testid="human-thread" className="flex h-full min-h-0 flex-col">
      <div
        ref={scrollRef}
        data-testid="human-messages"
        className="min-h-0 flex-1 space-y-3 overflow-y-auto px-3 py-3"
      >
        <p className="font-serif text-[13px] italic leading-relaxed text-ink/45">
          {intro}
        </p>
        {status === "error" ? (
          <p
            data-testid="human-error"
            className="font-serif text-[13px] italic text-ink/45"
          >
            This conversation isn&rsquo;t available right now.
          </p>
        ) : null}
        {messages.map((m) => (
          <HumanMessage key={m.id} message={m} viewerKind={viewerKind} />
        ))}
        {awaitingArtemis ? (
          <p
            data-testid="human-artemis-pending"
            className="font-serif text-[13px] italic leading-relaxed text-[rgba(245,112,31,0.75)]"
          >
            Artemis is composing a reply…
          </p>
        ) : null}
      </div>

      <div className="shrink-0 border-t border-ink/10 bg-paper/85 px-3 py-2 backdrop-blur-xs">
        <div className="flex items-end gap-2">
          <button
            type="button"
            onClick={askArtemis}
            disabled={!canApi || status === "error"}
            data-testid="human-ask-artemis"
            aria-label="Ask Artemis in this conversation"
            title="Bring the concierge into this conversation"
            className="h-9 shrink-0 rounded-md border border-[rgba(245,112,31,0.35)] px-3 font-sans text-[10px] uppercase tracking-[0.16em] text-[rgba(245,112,31,0.9)] transition-colors hover:bg-[rgba(245,112,31,0.08)] disabled:opacity-40"
          >
            @ Artemis
          </button>
          <textarea
            ref={composerRef}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void send();
              }
            }}
            rows={1}
            placeholder={
              viewerKind === "advisor" ? "Message the traveler…" : "Message your advisor…"
            }
            disabled={!canApi || status === "error"}
            data-testid="human-composer"
            className="max-h-28 min-h-9 min-w-0 flex-1 resize-none rounded-md border border-ink/15 bg-paper px-2.5 py-1.5 font-serif text-[13px] text-ink placeholder:text-ink/35 focus:border-ink/40 focus:outline-hidden disabled:opacity-40"
          />
          <button
            type="button"
            onClick={() => void send()}
            disabled={!draft.trim() || sending || !threadId}
            data-testid="human-send"
            className="h-9 shrink-0 rounded-md border border-ink/20 px-3 font-sans text-[10px] uppercase tracking-[0.16em] text-ink/70 transition-colors hover:bg-ink/5 disabled:opacity-40"
          >
            Send
          </button>
        </div>
      </div>
    </div>
  );
}

function HumanMessage({
  message,
  viewerKind,
}: {
  message: MessageSummary;
  viewerKind: ViewerKind;
}) {
  const mine = message.author_kind === viewerKind;
  const isArtemis = message.author_kind === "artemis";
  // Explicit AI attribution (PS8): the concierge reply is unmistakably Artemis,
  // distinct from the human "Advisor" — and tinted below.
  const label =
    message.author_kind === "advisor"
      ? "Advisor"
      : message.author_kind === "artemis"
        ? "Artemis · concierge"
        : message.author_kind === "system"
          ? "Update"
          : "Traveler";

  return (
    <div
      data-testid="human-message"
      data-author={message.author_kind}
      data-mine={mine ? "true" : "false"}
      className={"flex flex-col " + (mine ? "items-end" : "items-start")}
    >
      {!mine ? (
        <span className="mb-0.5 font-sans text-[9px] uppercase tracking-[0.16em] text-ink/40">
          {label}
        </span>
      ) : null}
      <div
        className={
          "max-w-[85%] rounded-2xl px-3 py-2 font-serif text-[13px] leading-relaxed " +
          // Artemis prose flows through ProseMessage (block markdown + place chips);
          // human messages are plain text, so preserve their line breaks.
          (isArtemis ? "" : "whitespace-pre-wrap ") +
          (mine
            ? "bg-ink/10 text-ink"
            : isArtemis
              ? "bg-[rgba(245,112,31,0.08)] text-ink"
              : "bg-paper text-ink ring-1 ring-ink/10")
        }
      >
        {isArtemis ? <ProseMessage content={message.content} /> : message.content}
      </div>
    </div>
  );
}
