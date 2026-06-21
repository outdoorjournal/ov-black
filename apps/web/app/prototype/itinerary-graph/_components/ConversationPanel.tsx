"use client";

import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useRef, useState } from "react";

import type { MoodId, NodeResponse } from "@/app/_components/itinerary-graph/model/baseTypes";
import type { ChatMessage } from "../_state/timelineStore";

interface ConversationPanelProps {
  mood: MoodId;
  messages: ChatMessage[];
  pendingProposals: NodeResponse[];
  onAccept: (id: string) => void;
  onDismiss: (id: string) => void;
  onSubmit: (text: string) => void;
  disabled?: boolean;
}

export function ConversationPanel({
  messages,
  pendingProposals,
  onAccept,
  onDismiss,
  onSubmit,
  disabled = false,
}: ConversationPanelProps) {
  const [text, setText] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, pendingProposals.length]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = text.trim();
    if (!trimmed || disabled) return;
    onSubmit(trimmed);
    setText("");
  };

  return (
    <div className="flex h-full flex-col border border-ink/10 bg-paper">
      <div className="border-b border-ink/10 px-4 py-2.5">
        <div className="text-[10px] uppercase tracking-[0.24em] text-ink/55">
          Concierge
        </div>
        <div className="font-serif text-lg text-ink">Conversation</div>
      </div>
      <div
        ref={scrollRef}
        className="flex-1 space-y-3 overflow-y-auto px-4 py-3"
      >
        <AnimatePresence initial={false}>
          {messages.map((m) => (
            <MessageBubble key={m.id} message={m} />
          ))}
          {pendingProposals.map((p) => (
            <motion.div
              key={`inline-${p.id}`}
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -6 }}
              className="rounded-md border border-dashed border-ink/25 bg-paper p-2.5 text-[12px]"
            >
              <div className="text-[10px] uppercase tracking-[0.18em] text-ink/55">
                Proposed · {p.type}
              </div>
              <div className="mt-0.5 font-serif text-[15px] text-ink">
                {p.title}
              </div>
              <div className="mt-2 flex gap-1.5">
                <button
                  type="button"
                  onClick={() => onAccept(p.id)}
                  className="rounded-md bg-ink px-2 py-1 text-[10px] uppercase tracking-[0.18em] text-paper"
                >
                  Accept
                </button>
                <button
                  type="button"
                  onClick={() => onDismiss(p.id)}
                  className="rounded-md border border-ink/20 px-2 py-1 text-[10px] uppercase tracking-[0.18em] text-ink/70"
                >
                  Dismiss
                </button>
              </div>
            </motion.div>
          ))}
        </AnimatePresence>
      </div>
      <form
        onSubmit={handleSubmit}
        className="flex items-center gap-2 border-t border-ink/10 px-3 py-2"
      >
        <input
          className="flex-1 rounded-md border border-ink/15 bg-paper px-3 py-2 text-[13px] outline-none focus:border-ink/40"
          placeholder="Ask me to propose, assemble, or swap…"
          value={text}
          onChange={(e) => setText(e.target.value)}
          disabled={disabled}
        />
        <button
          type="submit"
          disabled={disabled || text.trim().length === 0}
          className="rounded-md bg-ink px-3 py-2 text-[11px] uppercase tracking-[0.18em] text-paper disabled:opacity-40"
        >
          Send
        </button>
      </form>
    </div>
  );
}

function MessageBubble({ message }: { message: ChatMessage }) {
  if (message.role === "system") {
    return (
      <div className="rounded-md border border-dashed border-ink/15 bg-paper px-3 py-2 text-[11px] italic text-ink/60">
        {message.text}
      </div>
    );
  }
  const isUser = message.role === "user";
  return (
    <motion.div
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      className={[
        "max-w-[86%] rounded-lg px-3 py-2 text-[13px] leading-relaxed",
        isUser ? "ml-auto bg-ink text-paper" : "bg-ink/5 text-ink",
      ].join(" ")}
    >
      {message.text}
      {message.streaming ? (
        <span className="ml-0.5 inline-block h-3 w-[6px] translate-y-[1px] bg-current align-middle opacity-70" />
      ) : null}
    </motion.div>
  );
}
