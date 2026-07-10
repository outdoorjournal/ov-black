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
//
// Phase 3 grows the active pane's action stack:
//   · problem explanation + "Get help" (chat pre-seeded with the node) when
//     the active node carries a problem (Analyze finding / metadata.problem);
//   · per-node "Approve this" on the trunk (`selectCanApprove` +
//     `approveNode` — approval locks the card per existing semantics);
//   · an EDITABLE detail on an editable fork — the fields a traveler owns
//     (title, note/body, time slot) edit in place (click → input, save on
//     blur, Escape cancels); deeper edits route to "ask Artemis";
//   · legibility over disabled buttons: on the official trunk the rail says
//     where content edits live instead of graying anything out.

import { useEffect, useMemo, useState } from "react";
import type { Route } from "next";
import Link from "next/link";

import { useConciergeControl } from "@/app/itinerary/[id]/_shell/ConciergeControl";

import { NodeZoomCard } from "../../shared/cards/NodeZoomCard";
import {
  formatClock,
  offsetHoursOr,
  tzDayKey,
} from "../../model/time";
import type { NodeResponse } from "../../model/types";
import { getVerticalMeta } from "../../model/types";
import {
  itineraryGraphStore,
  selectCanApprove,
  selectCanLeaveNote,
  selectEditable,
  selectTravelerEditable,
} from "../../store/itineraryGraphStore";
import { useTimelineData } from "../../TimelineDataContext";

import { journalProblems, type JournalProblem } from "./problems";

export function RightRail({ idle }: { idle: React.ReactNode }) {
  const { timeline } = useTimelineData();
  const itineraryId = itineraryGraphStore.useStore((s) => s.itineraryId);
  const focusedNodeId = itineraryGraphStore.useStore((s) => s.focusedNodeId);
  const focusSource = itineraryGraphStore.useStore((s) => s.focusSource);
  const nodes = itineraryGraphStore.useStore((s) => s.nodes);
  const findings = itineraryGraphStore.useStore((s) => s.findings);
  const role = itineraryGraphStore.useStore((s) => s.role);
  const status = itineraryGraphStore.useStore((s) => s.status);
  const hasCreds = itineraryGraphStore.useStore(selectCanLeaveNote);
  const editableFork = itineraryGraphStore.useStore(
    (s) => selectEditable(s) || selectTravelerEditable(s),
  );
  const onTrunk = !timeline.itinerary.forked_from_id;

  // Only a real Journal interaction (scroll or click) flips the rail to the
  // node detail — the store's seeded default focus keeps the idle glance.
  const active =
    focusSource !== null && focusedNodeId
      ? (nodes.find((n) => n.id === focusedNodeId) ?? null)
      : null;

  const problems = useMemo(
    () => journalProblems(nodes, findings),
    [nodes, findings],
  );
  const activeProblem = active ? (problems.get(active.id) ?? null) : null;

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
          {activeProblem ? (
            <RailProblem node={active} problem={activeProblem} />
          ) : null}
          <RailApprove node={active} />
          <div className="flex items-center gap-5">
            <Link
              href={`/itinerary/${itineraryId}/item/${active.id}` as Route}
              data-testid="journal-rail-open-detail"
              className="font-sans text-[11px] uppercase tracking-[0.16em] text-ink/50 underline-offset-4 transition-colors hover:text-ink hover:underline"
            >
              Open full detail →
            </Link>
          </div>
          {editableFork && active.type !== "note" ? (
            <RailEditPanel
              key={active.id}
              node={active}
              tz={timeline.timezoneOffsetHours}
            />
          ) : null}
          {/* Legibility, not disabled buttons: a traveler reading the OFFICIAL
              trunk is told where reshaping lives (notes stay open everywhere). */}
          {!editableFork &&
          role !== "advisor" &&
          onTrunk &&
          hasCreds &&
          status !== "approved" &&
          active.type !== "note" ? (
            <p
              data-testid="journal-rail-readonly"
              className="font-serif text-[12px] italic leading-snug text-ink/45"
            >
              This is the official trip — notes are yours everywhere; moving
              and reshaping happens in your version.
            </p>
          ) : null}
          <RailNoteAction nodeId={active.id} />
        </div>
      ) : null}
    </>
  );
}

// ── Problem explanation + "get help" (chat pre-seeded with the node) ─────────
function RailProblem({
  node,
  problem,
}: {
  node: NodeResponse;
  problem: JournalProblem;
}) {
  const setAskContext = itineraryGraphStore.useStore((s) => s.setAskContext);
  const { openConcierge } = useConciergeControl();
  return (
    <div
      data-testid="journal-rail-problem"
      data-severity={problem.severity}
      className="rounded-md border border-[#b3261e]/30 bg-[#b3261e]/5 p-3"
    >
      <p className="flex items-start gap-1.5 font-sans text-[12px] leading-snug text-[#8b2a1d]">
        <span aria-hidden>⚠</span>
        <span>{problem.message}</span>
      </p>
      <button
        type="button"
        data-testid="journal-rail-get-help"
        onClick={() => {
          setAskContext({ nodeId: node.id, title: node.title || "this card" });
          openConcierge();
        }}
        className="mt-2 rounded-full border border-[#8b2a1d]/40 px-3 py-1 font-sans text-[10px] uppercase tracking-[0.16em] text-[#8b2a1d] transition-colors hover:bg-[#8b2a1d]/10"
      >
        Get help
      </button>
    </div>
  );
}

// ── Per-node approve from the rail (trunk; locks the card on success) ────────
function RailApprove({ node }: { node: NodeResponse }) {
  const canApprove = itineraryGraphStore.useStore(selectCanApprove);
  const approvingNodeId = itineraryGraphStore.useStore(
    (s) => s.approvingNodeId,
  );
  const storeApi = itineraryGraphStore.useStoreApi();
  if (!canApprove || node.status !== "pending") return null;
  return (
    <button
      type="button"
      data-testid="journal-rail-approve"
      onClick={() => storeApi.getState().approveNode(node.id)}
      disabled={approvingNodeId === node.id}
      className="h-9 self-start rounded-full bg-ink px-5 font-sans text-[11px] uppercase tracking-[0.18em] text-paper transition-opacity hover:opacity-90 disabled:cursor-default disabled:opacity-50"
    >
      Approve this
    </button>
  );
}

// ── The editable rail detail (editable fork only) ────────────────────────────
// The fields a traveler owns — title, note/body (description), time slot —
// edit in place with the phase-2 idiom: click → input, save on blur, Escape
// cancels. Everything deeper routes to "ask Artemis" (the existing chat
// surface); durations/lanes/bulk ops stay in Studio.
function RailEditPanel({ node, tz }: { node: NodeResponse; tz: number }) {
  const storeApi = itineraryGraphStore.useStoreApi();
  const setAskContext = itineraryGraphStore.useStore((s) => s.setAskContext);
  const { openConcierge } = useConciergeControl();

  const meta = getVerticalMeta(node);
  const description =
    typeof (node.metadata as { description?: unknown }).description === "string"
      ? ((node.metadata as { description?: string }).description ?? "")
      : "";
  const start = meta.start_time ?? null;

  return (
    <div
      data-testid="journal-rail-edit"
      className="flex flex-col gap-2.5 rounded-md border border-ink/10 bg-white/60 p-3"
    >
      <p className="font-sans text-[9px] uppercase tracking-[0.22em] text-ink/40">
        Your version — tap to edit
      </p>
      <InlineField
        label="Title"
        value={node.title}
        testid="journal-rail-edit-title"
        onSave={(v) => storeApi.getState().editNodeField(node.id, "title", v)}
      />
      <InlineField
        label="Note"
        value={description}
        placeholder="Add a note to this card…"
        multiline
        allowEmpty
        testid="journal-rail-edit-description"
        onSave={(v) =>
          storeApi.getState().updateCardDetails(node.id, { description: v })
        }
      />
      {start ? (
        <InlineTime
          iso={start}
          tz={tz}
          testid="journal-rail-edit-time"
          onSave={(minute) => {
            const off = offsetHoursOr(start, tz);
            storeApi.getState().moveNode(node.id, tzDayKey(start, off), minute);
          }}
        />
      ) : null}
      <button
        type="button"
        data-testid="journal-rail-ask-artemis"
        onClick={() => {
          setAskContext({ nodeId: node.id, title: node.title || "this card" });
          openConcierge();
        }}
        className="self-start font-sans text-[10px] uppercase tracking-[0.16em] text-ink/50 underline-offset-4 transition-colors hover:text-ink hover:underline"
      >
        Deeper changes? Ask Artemis →
      </button>
    </div>
  );
}

// Click → input (styled like the display), save on blur, Escape cancels.
function InlineField({
  label,
  value,
  onSave,
  testid,
  placeholder,
  multiline = false,
  allowEmpty = false,
}: {
  label: string;
  value: string;
  onSave: (next: string) => void;
  testid: string;
  placeholder?: string;
  multiline?: boolean;
  allowEmpty?: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);
  useEffect(() => setDraft(value), [value]);

  const commit = () => {
    setEditing(false);
    const next = draft.trim();
    if (next === value.trim()) return;
    if (!next && !allowEmpty) {
      setDraft(value);
      return;
    }
    onSave(next);
  };
  const cancel = () => {
    setDraft(value);
    setEditing(false);
  };

  const sharedProps = {
    autoFocus: true,
    value: draft,
    "data-testid": `${testid}-input`,
    onBlur: commit,
  } as const;

  return (
    <div className="flex flex-col gap-0.5">
      <span className="font-sans text-[9px] uppercase tracking-[0.18em] text-ink/40">
        {label}
      </span>
      {editing ? (
        multiline ? (
          <textarea
            {...sharedProps}
            rows={2}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Escape") {
                e.stopPropagation();
                cancel();
              } else if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
                e.preventDefault();
                e.currentTarget.blur();
              }
            }}
            className="w-full resize-none border-0 border-b border-ink/20 bg-transparent p-0 font-serif text-[13px] leading-snug text-ink outline-none focus:border-ink/40 focus:ring-0"
          />
        ) : (
          <input
            {...sharedProps}
            type="text"
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Escape") {
                e.stopPropagation();
                cancel();
              } else if (e.key === "Enter") {
                e.preventDefault();
                e.currentTarget.blur();
              }
            }}
            className="w-full border-0 border-b border-ink/20 bg-transparent p-0 font-serif text-[13px] text-ink outline-none focus:border-ink/40 focus:ring-0"
          />
        )
      ) : (
        <button
          type="button"
          data-testid={testid}
          aria-label={`Edit ${label.toLowerCase()}`}
          onClick={() => setEditing(true)}
          className="w-full cursor-text text-left font-serif text-[13px] leading-snug text-ink/85"
        >
          {value.trim() ? (
            value
          ) : (
            <span className="italic text-ink/40">{placeholder ?? "—"}</span>
          )}
        </button>
      )}
    </div>
  );
}

// The time slot: display the clock; click → a time input; save on blur.
// Day moves stay a drag (the spine's gesture) — this owns the within-day slot.
function InlineTime({
  iso,
  tz,
  onSave,
  testid,
}: {
  iso: string;
  tz: number;
  onSave: (minuteOfDay: number) => void;
  testid: string;
}) {
  const off = offsetHoursOr(iso, tz);
  const display = formatClock(iso, off);
  // "HH:MM" for the input's value, from the node's own local clock.
  const d = new Date(new Date(iso).getTime() + off * 3_600_000);
  const hhmm = `${String(d.getUTCHours()).padStart(2, "0")}:${String(
    d.getUTCMinutes(),
  ).padStart(2, "0")}`;

  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(hhmm);
  useEffect(() => setDraft(hhmm), [hhmm]);

  const commit = () => {
    setEditing(false);
    if (draft === hhmm) return;
    const m = draft.match(/^(\d{1,2}):(\d{2})$/);
    if (!m) {
      setDraft(hhmm);
      return;
    }
    const minute = Number(m[1]) * 60 + Number(m[2]);
    if (Number.isNaN(minute) || minute < 0 || minute > 1439) {
      setDraft(hhmm);
      return;
    }
    onSave(minute);
  };

  return (
    <div className="flex flex-col gap-0.5">
      <span className="font-sans text-[9px] uppercase tracking-[0.18em] text-ink/40">
        Time
      </span>
      {editing ? (
        <input
          autoFocus
          type="time"
          value={draft}
          data-testid={`${testid}-input`}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={commit}
          onKeyDown={(e) => {
            if (e.key === "Escape") {
              e.stopPropagation();
              setDraft(hhmm);
              setEditing(false);
            } else if (e.key === "Enter") {
              e.preventDefault();
              e.currentTarget.blur();
            }
          }}
          className="w-32 border-0 border-b border-ink/20 bg-transparent p-0 font-serif text-[13px] text-ink outline-none focus:border-ink/40 focus:ring-0"
        />
      ) : (
        <button
          type="button"
          data-testid={testid}
          aria-label="Edit time"
          onClick={() => setEditing(true)}
          className="cursor-text self-start text-left font-serif text-[13px] text-ink/85"
        >
          {display}
        </button>
      )}
    </div>
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
