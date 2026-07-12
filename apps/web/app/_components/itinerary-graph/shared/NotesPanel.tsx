"use client";

// Notes attached to a host node, shown inside that node's expanded detail
// sheet. Read-only list of what's already there, plus (when `canAdd`) an inline
// composer so the traveler can leave a new note ("why are we doing this at
// 1:30?") for staff to act on. A note is feedback — it does not change the plan.

import { useState } from "react";

import { StickyNote, X } from "lucide-react";

import type { NodeResponse } from "../model/horizontalTypes";

interface NotesPanelProps {
  notes: NodeResponse[];
  /** When true (and `onAddNote` given), render the inline composer. */
  canAdd?: boolean;
  onAddNote?: (text: string) => void;
  /** When given, each note gets a delete (×) control that soft-deletes it. */
  onDeleteNote?: ((noteId: string) => void) | undefined;
  /** When set and the thread is longer than this, collapse to the most recent
   *  `collapseAfter` and offer a show-all/less toggle — the rail's compressible
   *  thread (the modal has room, so it leaves this unset and shows everything). */
  collapseAfter?: number | undefined;
  /** The viewer's own actor kind ("advisor" | "client"). A note by the viewer
   *  is attributed "You"; everyone else gets their role name. */
  viewerActorKind?: string | undefined;
}

// Who left a note, from the node's recorded `actor_kind`. The viewer's own
// notes read "You"; a fresh (optimistic, not-yet-persisted) note has no
// actor_kind yet and is the viewer's, so it's "You" too.
function noteAuthor(actorKind: string | null | undefined, viewer?: string): string {
  if (!actorKind) return "You";
  if (viewer && actorKind === viewer) return "You";
  if (actorKind === "advisor") return "Advisor";
  if (actorKind === "agent") return "Artemis";
  return "Traveler";
}

export function NotesPanel({
  notes,
  canAdd = false,
  onAddNote,
  onDeleteNote,
  collapseAfter,
  viewerActorKind,
}: NotesPanelProps) {
  const [text, setText] = useState("");
  const [expanded, setExpanded] = useState(false);
  const showComposer = canAdd && Boolean(onAddNote);
  const collapsible =
    collapseAfter != null && notes.length > collapseAfter && !expanded;
  // Compress to the MOST RECENT few (the tail) — a note thread reads newest-last.
  const shownNotes = collapsible ? notes.slice(-collapseAfter) : notes;

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

      {collapsible ? (
        <button
          type="button"
          data-testid="notes-panel-show-all"
          onClick={() => setExpanded(true)}
          className="mt-1.5 font-sans text-[10px] uppercase tracking-[0.16em] text-amber-900/60 underline-offset-4 transition-colors hover:text-amber-900 hover:underline"
        >
          Show all {notes.length}
        </button>
      ) : null}

      {notes.length > 0 ? (
        <ul className="mt-1.5 space-y-1.5">
          {shownNotes.map((n) => (
            <li
              key={n.id}
              className="flex items-start justify-between gap-2"
            >
              <div className="flex flex-col gap-0.5">
                <span className="font-sans text-[9px] uppercase tracking-[0.14em] text-amber-900/50">
                  {noteAuthor(
                    (n as { actor_kind?: string | null }).actor_kind,
                    viewerActorKind,
                  )}
                </span>
                <span className="font-serif text-[12px] leading-snug text-ink/85">
                  {n.title}
                </span>
              </div>
              {onDeleteNote ? (
                <button
                  type="button"
                  data-testid="note-delete"
                  aria-label="Delete note"
                  title="Delete note"
                  onClick={() => onDeleteNote(n.id)}
                  className="-mr-0.5 mt-0.5 shrink-0 rounded-full p-0.5 text-amber-900/50 transition-colors hover:bg-[#8b2a1d]/10 hover:text-[#8b2a1d]"
                >
                  <X className="h-3.5 w-3.5" aria-hidden />
                </button>
              ) : null}
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
            className="w-full resize-none rounded border border-amber-900/20 bg-paper/80 px-2 py-1.5 font-sans text-[12px] text-ink placeholder:text-ink/40 focus:outline-hidden focus:ring-1 focus:ring-amber-700/40"
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
