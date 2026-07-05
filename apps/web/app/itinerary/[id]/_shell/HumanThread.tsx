"use client";

// The human messaging channel (M006/PS7) — the "Advisor" people-circle. A
// durable conversation between the traveler, their advisor, and (once party
// members have logins) that trip's party. Unlike the Artemis SessionThread this
// has NO agent turn and NO SSE stream: it get-or-creates the one human thread
// for the scope, lists its messages, and posts human messages. A light poll
// surfaces the other party's replies (no realtime yet).
//
// Artemis is summoned into this thread only in PS8 (@-mention); until then an
// `author_kind==='artemis'` message never appears here.

import { useCallback, useEffect, useRef, useState } from "react";

import {
  createApiClient,
  listMessages,
  openThread,
  sendMessage,
  type MessageSummary,
} from "@ov-black/api-client";

const POLL_MS = 6000;

type ViewerKind = "advisor" | "traveler";

export function HumanThread({
  clientId,
  itineraryId,
  apiBaseUrl,
  accessToken,
  viewerKind,
}: {
  clientId: string | null;
  itineraryId: string;
  apiBaseUrl: string | null;
  accessToken: string | null;
  viewerKind: ViewerKind;
}) {
  const [threadId, setThreadId] = useState<string | null>(null);
  const [messages, setMessages] = useState<MessageSummary[]>([]);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const scrollRef = useRef<HTMLDivElement>(null);
  const seeded = useRef(false);

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

  // Poll for the other party's messages while the channel is open.
  useEffect(() => {
    if (!threadId) return;
    const client = api();
    if (!client) return;
    const timer = setInterval(() => {
      void (async () => {
        const loaded = await listMessages(client, threadId);
        if (loaded.ok) setMessages(loaded.messages);
      })();
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [threadId, api]);

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
    setSending(true);
    const result = await sendMessage(client, threadId, { content: text });
    setSending(false);
    if (result.ok) {
      setDraft("");
      // Optimistic append; the next poll reconciles ordering with the server.
      setMessages((prev) => [...prev, result.message]);
    }
  }, [draft, threadId, sending, api]);

  const intro =
    viewerKind === "advisor"
      ? "The client conversation — messages here are visible to the traveler and their party. No agent replies."
      : "Message your advisor and travel party. This is a human conversation — the concierge answers when you ask Artemis.";

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
      </div>

      <div className="shrink-0 border-t border-ink/10 bg-paper/85 px-3 py-2 backdrop-blur-sm">
        <div className="flex items-end gap-2">
          <textarea
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
            className="max-h-28 min-h-[2.25rem] min-w-0 flex-1 resize-none rounded-md border border-ink/15 bg-paper px-2.5 py-1.5 font-serif text-[13px] text-ink placeholder:text-ink/35 focus:border-ink/40 focus:outline-none disabled:opacity-40"
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
  const label =
    message.author_kind === "advisor"
      ? "Advisor"
      : message.author_kind === "artemis"
        ? "Artemis"
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
          "max-w-[85%] whitespace-pre-wrap rounded-2xl px-3 py-2 font-serif text-[13px] leading-relaxed " +
          (mine
            ? "bg-ink/10 text-ink"
            : isArtemis
              ? "bg-[rgba(245,112,31,0.08)] text-ink"
              : "bg-paper text-ink ring-1 ring-ink/10")
        }
      >
        {message.content}
      </div>
    </div>
  );
}
