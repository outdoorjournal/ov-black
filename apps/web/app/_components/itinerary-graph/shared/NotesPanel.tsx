"use client";

// Notes attached to a host node, shown inside that node's expanded detail
// sheet. Read-only list of what's already there, plus (when `canAdd`) an inline
// composer so the traveler can leave a new note ("why are we doing this at
// 1:30?") for staff to act on. A note is feedback — it does not change the plan.

import { useState } from "react";

import { StickyNote } from "lucide-react";

import type { NodeResponse } from "../model/horizontalTypes";

interface NotesPanelProps {
  notes: NodeResponse[];
  /** When true (and `onAddNote` given), render the inline composer. */
  canAdd?: boolean;
  onAddNote?: (text: string) => void;
}

export function NotesPanel({ notes, canAdd = false, onAddNote }: NotesPanelProps) {
  const [text, setText] = useState("");
  const showComposer = canAdd && Boolean(onAddNote);

  if (notes.length === 0 && !showComposer) return null;

  const submit = () => {
    const trimmed = text.trim();
    if (!trimmed || !onAddNote) return;
    onAddNote(trimmed);
    setText("");
  };

  return (
    <div
      data-testid="notes-panel"
      className="mt-3 rounded-md border border-amber-900/15 bg-[#fbf1c7]/60 px-3 py-2.5"
    >
      <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-[0.18em] text-amber-900/70">
        <StickyNote className="h-3 w-3" aria-hidden />
        <span>Notes{notes.length > 0 ? ` · ${notes.length}` : ""}</span>
      </div>

      {notes.length > 0 ? (
        <ul className="mt-1.5 space-y-1.5">
          {notes.map((n) => (
            <li
              key={n.id}
              className="font-serif text-[12px] leading-snug text-ink/85"
            >
              {n.title}
            </li>
          ))}
        </ul>
      ) : null}

      {showComposer ? (
        <div className="mt-2">
          <textarea
            data-testid="note-composer-input"
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
                e.preventDefault();
                submit();
              }
            }}
            rows={2}
            placeholder="Leave a note for your advisor…"
            className="w-full resize-none rounded border border-amber-900/20 bg-paper/80 px-2 py-1.5 font-sans text-[12px] text-ink placeholder:text-ink/40 focus:outline-none focus:ring-1 focus:ring-amber-700/40"
          />
          <div className="mt-1.5 flex justify-end">
            <button
              type="button"
              data-testid="note-composer-submit"
              onClick={submit}
              disabled={text.trim().length === 0}
              className="rounded bg-amber-800/90 px-2.5 py-1 font-sans text-[11px] font-medium text-paper disabled:opacity-40"
            >
              Leave a note
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
