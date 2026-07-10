"use client";

// The Journal's margin channel (traveler-journal design, phase 2). Notes are
// the one write that works EVERYWHERE, including the official trunk — a note
// is feedback for staff, not a graph edit, so every affordance here gates on
// `selectCanLeaveNote` (credentials), never on role or the fork/approve gates.
// The backend's write authorization stays the real authority; the store's
// optimistic adds/edits revert on failure.
//
// Three shapes, all wearing the existing note tokens (yellow tint, ✎ glyph,
// handwritten serif-italic register):
//
//   MarginNotes    attached notes as annotations in the host card's margin
//                  (beside it on desktop, tucked under it below lg) + the
//                  quiet ✎ hover affordance to leave a new one
//   SpineNoteCard  a free-standing day note ON the spine (it IS a node)
//   AddNoteOnLine  the `+`-on-the-line at a day's end — on the trunk, Note is
//                  the ONLY thing the line offers a traveler (phase 3 extends
//                  the offer with content inserts on an editable fork)
//
// A viewer's own notes are editable in place (tap → textarea, save on blur)
// and always deletable — mirroring the backend's notes-always-removable rule.

import { useCallback, useEffect, useRef, useState } from "react";

import type { NodeResponse } from "../../model/types";
import {
  itineraryGraphStore,
  selectCanLeaveNote,
} from "../../store/itineraryGraphStore";

import { SPINE_COL_PX } from "./Spine";

const spineColStyle = {
  "--spine-col": `${SPINE_COL_PX}px`,
} as React.CSSProperties;

// ── The shared in-place editor: tap → textarea, save on blur ─────────────────
function NoteEditor({
  initial,
  onSave,
  onCancel,
  testid,
}: {
  initial: string;
  onSave: (text: string) => void;
  onCancel: () => void;
  testid: string;
}) {
  const [draft, setDraft] = useState(initial);
  const ref = useRef<HTMLTextAreaElement | null>(null);

  const autogrow = useCallback(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "0px";
    el.style.height = `${el.scrollHeight}px`;
  }, []);
  useEffect(() => autogrow(), [autogrow]);

  const commit = () => {
    const next = draft.trim();
    if (!next || next === initial.trim()) {
      onCancel();
      return;
    }
    onSave(next);
  };

  return (
    <textarea
      ref={ref}
      autoFocus
      value={draft}
      onChange={(e) => {
        setDraft(e.target.value);
        autogrow();
      }}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          e.stopPropagation();
          onCancel();
        } else if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
          e.preventDefault();
          e.currentTarget.blur();
        }
      }}
      rows={1}
      aria-label="Edit note"
      data-testid={testid}
      className="w-full resize-none overflow-hidden border-0 bg-transparent p-0 font-serif text-[12px] italic leading-snug text-ink/85 outline-none focus:ring-0"
    />
  );
}

// ── The composer for a NEW note (explicit submit, ⌘⏎ shortcut) ───────────────
function NoteComposer({
  placeholder,
  submitLabel,
  onSubmit,
  onCancel,
  testid,
}: {
  placeholder: string;
  submitLabel: string;
  onSubmit: (text: string) => void;
  onCancel: () => void;
  testid: string;
}) {
  const [text, setText] = useState("");

  const submit = () => {
    const trimmed = text.trim();
    if (!trimmed) return;
    onSubmit(trimmed);
  };

  return (
    <div
      data-testid={testid}
      className="w-full rounded-md border border-amber-900/20 bg-[#fbf1c7]/80 p-2 shadow-xs"
    >
      <textarea
        autoFocus
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Escape") {
            e.stopPropagation();
            onCancel();
          } else if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
            e.preventDefault();
            submit();
          }
        }}
        rows={2}
        placeholder={placeholder}
        data-testid={`${testid}-input`}
        className="w-full resize-none border-0 bg-transparent p-0 font-serif text-[12px] italic leading-snug text-ink/85 outline-none placeholder:text-amber-900/40 focus:ring-0"
      />
      <div className="mt-1 flex items-center justify-end gap-3">
        <button
          type="button"
          onClick={onCancel}
          className="font-sans text-[10px] uppercase tracking-[0.14em] text-amber-900/50 transition-colors hover:text-amber-900"
        >
          Cancel
        </button>
        <button
          type="button"
          onClick={submit}
          disabled={text.trim().length === 0}
          data-testid={`${testid}-submit`}
          className="rounded-full bg-amber-800/90 px-2.5 py-1 font-sans text-[10px] uppercase tracking-[0.14em] text-paper transition-opacity hover:opacity-90 disabled:opacity-40"
        >
          {submitLabel}
        </button>
      </div>
    </div>
  );
}

// ── One margin annotation (or spine-note body): text · edit · delete ─────────
function NoteBody({ note }: { note: NodeResponse }) {
  const canWrite = itineraryGraphStore.useStore(selectCanLeaveNote);
  const storeApi = itineraryGraphStore.useStoreApi();
  const [editing, setEditing] = useState(false);

  if (editing) {
    return (
      <NoteEditor
        initial={note.title}
        testid="journal-note-editor"
        onSave={(text) => {
          storeApi.getState().editNoteText(note.id, text);
          setEditing(false);
        }}
        onCancel={() => setEditing(false)}
      />
    );
  }
  if (!canWrite) {
    return (
      <p className="font-serif text-[12px] italic leading-snug text-ink/85">
        {note.title}
      </p>
    );
  }
  return (
    <button
      type="button"
      data-testid="journal-note-text"
      aria-label="Edit this note"
      onClick={() => setEditing(true)}
      className="block w-full cursor-text text-left font-serif text-[12px] italic leading-snug text-ink/85"
    >
      {note.title}
    </button>
  );
}

function NoteDelete({ noteId }: { noteId: string }) {
  const canWrite = itineraryGraphStore.useStore(selectCanLeaveNote);
  const storeApi = itineraryGraphStore.useStoreApi();
  if (!canWrite) return null;
  return (
    <button
      type="button"
      data-testid="journal-note-delete"
      aria-label="Delete note"
      title="Delete note"
      onClick={() => storeApi.getState().removeNode(noteId)}
      className="-mr-0.5 -mt-0.5 shrink-0 rounded-full px-1 font-sans text-[12px] leading-none text-amber-900/45 transition-colors hover:bg-[#8b2a1d]/10 hover:text-[#8b2a1d]"
    >
      ×
    </button>
  );
}

// ── Attached notes: the margin beside the host card ──────────────────────────
export function MarginNotes({
  hostId,
  notes,
}: {
  hostId: string;
  notes: NodeResponse[];
}) {
  const canWrite = itineraryGraphStore.useStore(selectCanLeaveNote);
  const storeApi = itineraryGraphStore.useStoreApi();
  const [composing, setComposing] = useState(false);

  if (notes.length === 0 && !canWrite) return null;

  return (
    <div
      data-testid="journal-margin"
      data-host-id={hostId}
      className="mt-1.5 flex w-full flex-col items-start gap-1.5 lg:absolute lg:left-full lg:top-2 lg:ml-5 lg:mt-0 lg:w-[220px]"
    >
      {notes.map((n) => (
        <div
          key={n.id}
          data-testid="journal-margin-note"
          className="flex w-full items-start gap-1.5 rounded-md border border-amber-900/15 bg-[#fbf1c7]/80 px-2.5 py-2 shadow-xs lg:-rotate-[0.4deg]"
        >
          <span aria-hidden className="pt-px text-[11px] leading-none text-amber-900/60">
            ✎
          </span>
          <div className="min-w-0 flex-1">
            <NoteBody note={n} />
          </div>
          <NoteDelete noteId={n.id} />
        </div>
      ))}

      {canWrite ? (
        composing ? (
          <NoteComposer
            placeholder="Leave a note for your advisor…"
            submitLabel="Leave a note"
            testid="journal-margin-composer"
            onSubmit={(text) => {
              storeApi.getState().addAttachedNote(hostId, text);
              setComposing(false);
            }}
            onCancel={() => setComposing(false)}
          />
        ) : (
          // The quiet ✎ — invisible until the card row is hovered/focused on
          // desktop; always (faintly) present below lg where hover doesn't
          // exist. The rail's "Leave a note" covers the active node too.
          <button
            type="button"
            data-testid="journal-margin-add"
            aria-label="Leave a note on this card"
            onClick={() => setComposing(true)}
            className="rounded-full px-1.5 py-0.5 font-sans text-[10px] uppercase tracking-[0.14em] text-amber-900/60 opacity-60 transition-opacity hover:opacity-100 focus-visible:opacity-100 lg:opacity-0 lg:group-hover/jnode:opacity-100 lg:group-focus-within/jnode:opacity-100"
          >
            ✎ note
          </button>
        )
      ) : null}
    </div>
  );
}

// ── A free-standing day note on the spine (it IS a node) ─────────────────────
export function SpineNoteCard({ node }: { node: NodeResponse }) {
  return (
    <div
      data-testid="journal-note-card"
      className="w-full rounded-lg border border-amber-900/20 bg-[#fbf1c7]/80 px-3.5 py-2.5 shadow-xs"
    >
      <div className="flex items-start gap-2">
        <span aria-hidden className="pt-px text-[12px] leading-none text-amber-900/60">
          ✎
        </span>
        <div className="min-w-0 flex-1">
          <p className="mb-1 font-sans text-[9px] uppercase tracking-[0.18em] text-amber-900/60">
            Note
          </p>
          <NoteBody note={node} />
        </div>
        <NoteDelete noteId={node.id} />
      </div>
    </div>
  );
}

// ── The `+`-on-the-line: a day's insert affordance ───────────────────────────
// Phase 2 offers exactly one thing — Note — which is also everything the trunk
// ever offers a traveler. Phase 3 extends the `offering` state with content
// inserts (Collection-first picker) on an editable fork; add options there,
// keep the Note chip as the constant.
export function AddNoteOnLine({ dayKey }: { dayKey: string }) {
  const canWrite = itineraryGraphStore.useStore(selectCanLeaveNote);
  const storeApi = itineraryGraphStore.useStoreApi();
  const [state, setState] = useState<"idle" | "offering" | "composing">("idle");

  if (!canWrite) return null;

  return (
    <div
      data-testid="journal-add-on-line"
      data-date={dayKey}
      className="grid grid-cols-[var(--spine-col)_minmax(0,1fr)] items-start gap-x-4 py-1"
      style={spineColStyle}
    >
      <div className="flex justify-center pt-0.5">
        <button
          type="button"
          data-testid="journal-add-plus"
          aria-label="Add to this day"
          aria-expanded={state !== "idle"}
          onClick={() => setState(state === "idle" ? "offering" : "idle")}
          className="relative z-10 flex h-5 w-5 items-center justify-center rounded-full border border-ink/20 bg-paper font-sans text-[13px] leading-none text-ink/35 transition-colors hover:border-brand hover:text-brand"
        >
          +
        </button>
      </div>
      <div className="max-w-[420px]">
        {state === "offering" ? (
          <button
            type="button"
            data-testid="journal-add-note-option"
            onClick={() => setState("composing")}
            className="rounded-full border border-amber-900/25 bg-[#fbf1c7]/70 px-3 py-1 font-sans text-[10px] uppercase tracking-[0.16em] text-amber-900/80 transition-colors hover:border-amber-900/50"
          >
            ✎ Note
          </button>
        ) : state === "composing" ? (
          <NoteComposer
            placeholder="Something for this day? Tell your advisor…"
            submitLabel="Leave a note"
            testid="journal-day-note-composer"
            onSubmit={(text) => {
              storeApi.getState().addFreeStandingNote(dayKey, text);
              setState("idle");
            }}
            onCancel={() => setState("idle")}
          />
        ) : null}
      </div>
    </div>
  );
}
