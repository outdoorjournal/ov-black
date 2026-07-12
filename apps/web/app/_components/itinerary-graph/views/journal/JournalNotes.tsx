"use client";

// The Journal's note affordances (traveler-journal design). Notes are the one
// write that works EVERYWHERE, including the official trunk — a note is
// feedback for staff, not a graph edit, so every affordance here gates on
// `selectCanLeaveNote` (credentials), never on role or the fork/approve gates.
// The backend's write authorization stays the real authority; the store's
// optimistic adds/edits revert on failure.
//
// Attached notes (annotations on a specific card) live in the right rail's
// notes thread (RightRail → NotesPanel), not beside the card. What remains
// here are the two spine shapes, wearing the note tokens (yellow tint, ✎
// glyph, handwritten serif-italic register):
//
//   SpineNoteCard  a free-standing day note ON the spine (it IS a node)
//   AddNoteOnLine  the `+`-on-the-line at a day's end. On the trunk, Note is
//                  the ONLY thing the line offers (feedback is trunk-safe by
//                  design). On an EDITABLE fork (phase 3) the offer grows into
//                  the insert picker: the Collection first (placing wish-list
//                  items is the #1 traveler edit), then "describe it to
//                  Artemis" (deep-link to the existing chat surface), then
//                  Note, then a blank card. Content writes go through the
//                  existing store flows (moveNode / authorNode) — no new
//                  persistence paths.
//
// A viewer's own notes are editable in place (tap → textarea, save on blur)
// and always deletable — mirroring the backend's notes-always-removable rule.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { useConciergeControl } from "@/app/itinerary/[id]/_shell/ConciergeControl";

import type { NodeResponse } from "../../model/types";
import {
  collectionItemsOf,
  isNodeScheduled,
  itineraryGraphStore,
  selectCanLeaveNote,
  selectEditable,
  selectTravelerEditable,
} from "../../store/itineraryGraphStore";

import { SLOT_EMPTY_DAY_MIN } from "./journalEditing";
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
// On the trunk the line offers exactly one thing — Note — which keeps the
// feedback channel discoverable where the urge strikes AND makes the edit
// boundary legible (content inserts live on your version, not here). On an
// editable fork the `offering` state grows into the full insert picker,
// Collection first. The Note chip is the constant across both.
const OPTION_CHIP =
  "rounded-full border px-3 py-1 font-sans text-[10px] uppercase tracking-[0.16em] transition-colors";

export function AddNoteOnLine({
  dayKey,
  insertMinute = SLOT_EMPTY_DAY_MIN,
}: {
  dayKey: string;
  /** Where a content insert lands in the day — the sensible after-the-last-
   *  card slot the view derives (`endOfDayMinute`); defaults to noon. */
  insertMinute?: number;
}) {
  const canWrite = itineraryGraphStore.useStore(selectCanLeaveNote);
  // Content inserts need an editable fork — advisor working copy or the
  // traveler's own version. Role (via the selectors) is the source of truth.
  const contentEditable = itineraryGraphStore.useStore(
    (s) => selectEditable(s) || selectTravelerEditable(s),
  );
  const nodes = itineraryGraphStore.useStore((s) => s.nodes);
  const pendingProposals = itineraryGraphStore.useStore(
    (s) => s.pendingProposals,
  );
  const storeApi = itineraryGraphStore.useStoreApi();
  const { openConcierge } = useConciergeControl();
  const [state, setState] = useState<
    "idle" | "offering" | "composing" | "collection" | "blank"
  >("idle");
  const [blankTitle, setBlankTitle] = useState("");

  // The Collection (wish list) = unscheduled, non-discarded nodes — placing
  // one is the #1 traveler edit, so it leads the picker. Placed items STAY in
  // the Collection view (it's a view over the graph, not a parallel store);
  // `isNodeScheduled` (start_synthesized-aware) is what "unscheduled" means.
  const collection = useMemo(
    () =>
      collectionItemsOf(nodes, pendingProposals).filter(
        (n) => !isNodeScheduled(n) && n.type !== "note",
      ),
    [nodes, pendingProposals],
  );

  if (!canWrite) return null;

  const placeFromCollection = (nodeId: string) => {
    storeApi.getState().moveNode(nodeId, dayKey, insertMinute);
    setState("idle");
  };

  const addBlankCard = () => {
    const title = blankTitle.trim();
    if (!title) return;
    storeApi.getState().authorNode({
      type: "experience",
      title,
      schedule: { dayKey, minute: insertMinute },
    });
    setBlankTitle("");
    setState("idle");
  };

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
          <div className="flex flex-wrap items-center gap-1.5">
            {contentEditable ? (
              <>
                <button
                  type="button"
                  data-testid="journal-insert-collection"
                  onClick={() => setState("collection")}
                  className={`${OPTION_CHIP} border-ink/25 bg-paper text-ink/70 hover:border-brand hover:text-brand`}
                >
                  From your collection
                  {collection.length > 0 ? ` · ${collection.length}` : ""}
                </button>
                <button
                  type="button"
                  data-testid="journal-insert-artemis"
                  onClick={() => {
                    openConcierge();
                    setState("idle");
                  }}
                  className={`${OPTION_CHIP} border-ink/25 bg-paper text-ink/70 hover:border-brand hover:text-brand`}
                >
                  Describe it to Artemis
                </button>
              </>
            ) : null}
            <button
              type="button"
              data-testid="journal-add-note-option"
              onClick={() => setState("composing")}
              className={`${OPTION_CHIP} border-amber-900/25 bg-[#fbf1c7]/70 text-amber-900/80 hover:border-amber-900/50`}
            >
              ✎ Note
            </button>
            {contentEditable ? (
              <button
                type="button"
                data-testid="journal-insert-blank"
                onClick={() => setState("blank")}
                className={`${OPTION_CHIP} border-ink/20 bg-paper text-ink/55 hover:border-ink/45 hover:text-ink`}
              >
                Blank card
              </button>
            ) : null}
          </div>
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
        ) : state === "collection" ? (
          <div
            data-testid="journal-insert-collection-list"
            className="flex w-full flex-col gap-1 rounded-md border border-ink/10 bg-white/70 p-2"
          >
            {collection.length === 0 ? (
              <p className="px-1 py-0.5 font-serif text-[12px] italic text-ink/45">
                Your collection is empty — save ideas as you find them, and
                they&rsquo;ll be here to place.
              </p>
            ) : (
              collection.map((n) => (
                <button
                  key={n.id}
                  type="button"
                  data-testid="journal-insert-collection-item"
                  data-node-id={n.id}
                  onClick={() => placeFromCollection(n.id)}
                  className="flex items-baseline justify-between gap-2 rounded px-2 py-1 text-left transition-colors hover:bg-ink/5"
                >
                  <span className="min-w-0 truncate font-serif text-[13px] text-ink/85">
                    {n.title || n.type}
                  </span>
                  <span className="shrink-0 font-sans text-[9px] uppercase tracking-[0.16em] text-ink/40">
                    {n.type}
                  </span>
                </button>
              ))
            )}
            <button
              type="button"
              onClick={() => setState("idle")}
              className="self-end px-1 font-sans text-[10px] uppercase tracking-[0.14em] text-ink/45 transition-colors hover:text-ink"
            >
              Cancel
            </button>
          </div>
        ) : state === "blank" ? (
          <div
            data-testid="journal-insert-blank-form"
            className="flex w-full items-center gap-2 rounded-md border border-ink/10 bg-white/70 p-2"
          >
            <input
              autoFocus
              type="text"
              value={blankTitle}
              onChange={(e) => setBlankTitle(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Escape") {
                  e.stopPropagation();
                  setBlankTitle("");
                  setState("idle");
                } else if (e.key === "Enter") {
                  e.preventDefault();
                  addBlankCard();
                }
              }}
              placeholder="Name the idea…"
              data-testid="journal-insert-blank-title"
              className="h-7 w-full border-0 border-b border-ink/15 bg-transparent p-0 font-serif text-[13px] text-ink outline-none placeholder:text-ink/35 focus:border-ink/40 focus:ring-0"
            />
            <button
              type="button"
              onClick={addBlankCard}
              disabled={blankTitle.trim().length === 0}
              data-testid="journal-insert-blank-submit"
              className="shrink-0 rounded-full bg-ink px-3 py-1 font-sans text-[10px] uppercase tracking-[0.14em] text-paper transition-opacity hover:opacity-90 disabled:opacity-40"
            >
              Add
            </button>
          </div>
        ) : null}
      </div>
    </div>
  );
}
