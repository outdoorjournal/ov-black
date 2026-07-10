"use client";

// The Journal's right rail — the page's reactive margin. Two states:
//   idle    nothing activated yet → the trip at a glance (next action,
//           approve-all, balance — composed by the dashboard and passed in).
//   active  a node is scroll-active or click-pinned → its detail, reusing the
//           same NodeZoomCard the /item/[nodeId] destination renders, plus a
//           deep link to that full detail surface.
//
// Same screen, responsive: the detail state is desktop-only (below lg a card
// tap deep-links to /item/[nodeId] instead), so the idle glance renders ONCE
// and simply stays visible on small screens even while a node is active.
//
// Phase 2: whenever a node is active the rail also offers "Leave a note" —
// the margin channel's second entry point (beside the card's hover ✎), gated
// by `selectCanLeaveNote` so it works everywhere, including the trunk.

import { useEffect, useState } from "react";
import type { Route } from "next";
import Link from "next/link";

import { NodeZoomCard } from "../../shared/cards/NodeZoomCard";
import {
  itineraryGraphStore,
  selectCanLeaveNote,
} from "../../store/itineraryGraphStore";
import { useTimelineData } from "../../TimelineDataContext";

export function RightRail({ idle }: { idle: React.ReactNode }) {
  const { timeline } = useTimelineData();
  const itineraryId = itineraryGraphStore.useStore((s) => s.itineraryId);
  const focusedNodeId = itineraryGraphStore.useStore((s) => s.focusedNodeId);
  const focusSource = itineraryGraphStore.useStore((s) => s.focusSource);
  const nodes = itineraryGraphStore.useStore((s) => s.nodes);

  // Only a real Journal interaction (scroll or click) flips the rail to the
  // node detail — the store's seeded default focus keeps the idle glance.
  const active =
    focusSource !== null && focusedNodeId
      ? (nodes.find((n) => n.id === focusedNodeId) ?? null)
      : null;

  return (
    <>
      <div
        data-testid="journal-rail-idle"
        className={[
          "flex-col gap-4",
          active ? "flex lg:hidden" : "flex",
        ].join(" ")}
      >
        {idle}
      </div>
      {active ? (
        <div
          data-testid="journal-rail-detail"
          className="hidden flex-col gap-3 lg:flex"
        >
          <NodeZoomCard
            node={active}
            tzOffsetHours={timeline.timezoneOffsetHours}
          />
          <div className="flex items-center gap-5">
            <Link
              href={`/itinerary/${itineraryId}/item/${active.id}` as Route}
              data-testid="journal-rail-open-detail"
              className="font-sans text-[11px] uppercase tracking-[0.16em] text-ink/50 underline-offset-4 transition-colors hover:text-ink hover:underline"
            >
              Open full detail →
            </Link>
          </div>
          <RailNoteAction nodeId={active.id} />
        </div>
      ) : null}
    </>
  );
}

// "Leave a note" for the active node — a quiet action that expands into the
// margin composer. The note it creates is an ATTACHED note, so it appears in
// the host card's margin channel immediately (optimistic add).
function RailNoteAction({ nodeId }: { nodeId: string }) {
  const canWrite = itineraryGraphStore.useStore(selectCanLeaveNote);
  const storeApi = itineraryGraphStore.useStoreApi();
  const [composing, setComposing] = useState(false);
  const [text, setText] = useState("");

  // A new active node starts a fresh thought — collapse any half-typed note.
  useEffect(() => {
    setComposing(false);
    setText("");
  }, [nodeId]);

  if (!canWrite) return null;

  if (!composing) {
    return (
      <button
        type="button"
        data-testid="journal-rail-leave-note"
        onClick={() => setComposing(true)}
        className="self-start font-sans text-[11px] uppercase tracking-[0.16em] text-amber-900/70 underline-offset-4 transition-colors hover:text-amber-900 hover:underline"
      >
        ✎ Leave a note
      </button>
    );
  }

  const submit = () => {
    const trimmed = text.trim();
    if (!trimmed) return;
    storeApi.getState().addAttachedNote(nodeId, trimmed);
    setComposing(false);
    setText("");
  };

  return (
    <div
      data-testid="journal-rail-note-composer"
      className="rounded-md border border-amber-900/20 bg-[#fbf1c7]/80 p-2 shadow-xs"
    >
      <textarea
        autoFocus
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Escape") {
            setComposing(false);
            setText("");
          } else if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
            e.preventDefault();
            submit();
          }
        }}
        rows={2}
        placeholder="Leave a note for your advisor…"
        data-testid="journal-rail-note-input"
        className="w-full resize-none border-0 bg-transparent p-0 font-serif text-[12px] italic leading-snug text-ink/85 outline-none placeholder:text-amber-900/40 focus:ring-0"
      />
      <div className="mt-1 flex items-center justify-end gap-3">
        <button
          type="button"
          onClick={() => {
            setComposing(false);
            setText("");
          }}
          className="font-sans text-[10px] uppercase tracking-[0.14em] text-amber-900/50 transition-colors hover:text-amber-900"
        >
          Cancel
        </button>
        <button
          type="button"
          onClick={submit}
          disabled={text.trim().length === 0}
          data-testid="journal-rail-note-submit"
          className="rounded-full bg-amber-800/90 px-2.5 py-1 font-sans text-[10px] uppercase tracking-[0.14em] text-paper transition-opacity hover:opacity-90 disabled:opacity-40"
        >
          Leave a note
        </button>
      </div>
    </div>
  );
}
