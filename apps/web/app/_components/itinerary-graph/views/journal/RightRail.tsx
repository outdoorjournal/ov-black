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
//     blur, Escape cancels); deeper edits stay in Studio or the concierge;
//   · legibility over disabled buttons: on the official trunk the rail says
//     where content edits live instead of graying anything out.
//
// Phase 4 (diff mode) rethreads both states:
//   · IDLE becomes the divergence summary ("4 additions, 1 change") with the
//     role-decided CTA — the traveler's request-reconcile ask-path, or the
//     advisor's one-pass reconcile (accept_all stays the fast path when
//     nothing was kept);
//   · ACTIVE on a diffed node leads with the change: field-level before/after
//     for `changed`, old vs new time for `moved`, and — advisor only — the
//     accept / keep-the-original decision wired to the per-`change_id`
//     reconcile decisions. `refused_booked` (G1 immutable) renders as a lock
//     explanation, not an error. The edit panel stays out of diff mode — it's
//     a reading/deciding mode (notes stay open).

import { useEffect, useMemo, useState } from "react";
import type { Route } from "next";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { useConciergeControl } from "@/app/itinerary/[id]/_shell/ConciergeControl";

import { PartOfJourney } from "../../shared/PartOfJourney";
import { NotesPanel } from "../../shared/NotesPanel";
import { attachedNotesByHost } from "../../shared/attachedNotes";
import { inferCardKind } from "../../shared/cards/CardBody";
import { TYPE_TOKENS } from "../../shared/cards/tokens";
import { resolveNodeAffordances, type NodeAffordances } from "./affordances";
import {
  formatClock,
  offsetHoursOr,
  tzDayKey,
} from "../../model/time";
import type { NodeResponse } from "../../model/types";
import { getVerticalMeta } from "../../model/types";
import {
  isSchedulePinned,
  itineraryGraphStore,
  selectCanApprove,
  selectCanLeaveNote,
  selectEditable,
  selectTravelerEditable,
} from "../../store/itineraryGraphStore";
import { useTimelineData } from "../../TimelineDataContext";

import { journalProblems, type JournalProblem } from "./problems";
import {
  changedFieldRows,
  isGhostId,
  movedTimeLabels,
  type JournalDiffView,
  type JournalNodeDiff,
} from "./toJournalDiff";

export function RightRail({
  idle,
  diffView = null,
  onToggleFull = null,
  fullOpen = false,
}: {
  idle: React.ReactNode;
  /** Diff mode's derived view (annotations + ghosts) — null when reading
   *  normally. Presence flips the rail into compare register. */
  diffView?: JournalDiffView | null;
  /** 2xl inline tier: "Open full" TOGGLES the full detail open beneath the
   *  cockpit (and locks focus), instead of soft-navigating to the modal. When
   *  null (≤2xl) the handle stays the modal deep link. */
  onToggleFull?: (() => void) | null;
  /** Whether the full detail is currently expanded beneath (flips the label). */
  fullOpen?: boolean;
}) {
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
  const storeApi = itineraryGraphStore.useStoreApi();

  // Only a real Journal interaction (scroll or click) flips the rail to the
  // node detail — the store's seeded default focus keeps the idle glance.
  // In diff mode the active node may be a GHOST (trunk-only, synthesized by
  // toJournalDiff) — it never lives in the store's nodes.
  const active =
    focusSource !== null && focusedNodeId
      ? (nodes.find((n) => n.id === focusedNodeId) ??
        diffView?.ghosts.get(focusedNodeId) ??
        null)
      : null;
  const activeIsGhost = active ? isGhostId(active.id) : false;
  const activeDiff = active
    ? (diffView?.annotations.get(active.id) ?? null)
    : null;
  const focusNode = itineraryGraphStore.useStore((s) => s.focusNode);
  // A journey beat (subgraph child) carries its parent's card above its own
  // detail — the package anchoring the day being looked at.
  const activeParent =
    active && !activeIsGhost && active.parent_subgraph_id
      ? (nodes.find((n) => n.id === active.parent_subgraph_id) ?? null)
      : null;
  const activeSiblingCount = activeParent
    ? nodes.filter(
        (n) =>
          n.parent_subgraph_id === activeParent.id && n.status !== "discarded",
      ).length
    : 0;

  const problems = useMemo(
    () => journalProblems(nodes, findings),
    [nodes, findings],
  );
  const activeProblem = active ? (problems.get(active.id) ?? null) : null;

  // The active card's attached notes — rendered as the rail's compressible
  // thread (Zone 2), so the traveler reads the whole back-and-forth here, not
  // just a "leave a note" button (the card only badges that notes exist).
  const attachedNotes = useMemo(() => attachedNotesByHost(nodes), [nodes]);
  const activeNotes = active ? (attachedNotes.get(active.id) ?? []) : [];

  // The single resolved intent set the zones read (rail redesign, phase 2a).
  // Computed from live store state; the component already re-renders on the
  // fields the resolver depends on (role/status/creds/fork/node.status).
  const affordances = active
    ? resolveNodeAffordances(storeApi.getState(), active, {
        hasProblem: Boolean(activeProblem),
      })
    : null;

  return (
    <>
      <div
        data-testid="journal-rail-idle"
        className={[
          "relative flex-col gap-4",
          active ? "flex lg:hidden" : "flex",
        ].join(" ")}
      >
        {/* Atmosphere: a faint editorial wash behind the resting glance so the
            idle rail reads as alive, not empty. An image-backed treatment is a
            follow-up (plan open items); this restrained gradient is the base. */}
        {!active ? (
          <span
            aria-hidden
            data-testid="journal-rail-atmosphere"
            className="pointer-events-none absolute -inset-2 -z-10 rounded-xl bg-gradient-to-b from-ink/[0.02] to-transparent"
          />
        ) : null}
        {diffView ? <RailDiffSummary diffView={diffView} /> : idle}
      </div>
      {active && affordances ? (
        <div
          data-testid="journal-rail-detail"
          className="hidden flex-col gap-5 lg:flex"
        >
          {/* ── Zone 1 — identity + the ask (stable top) ─────────────────────
              Compact identity (accent · type · time · title) replaces the old
              NodeZoomCard duplicate; the primary action rides here. */}
          <div data-testid="journal-rail-zone1" className="flex flex-col gap-3">
            <RailIdentity
              node={active}
              tz={timeline.timezoneOffsetHours}
              affordances={affordances}
            />
            <RailApprove node={active} />
            {!activeIsGhost ? (
              onToggleFull ? (
                // 2xl: a prominent toggle that expands the full detail BENEATH
                // the cockpit (locks focus) rather than opening the modal.
                <button
                  type="button"
                  onClick={onToggleFull}
                  data-testid="journal-rail-open-detail"
                  aria-expanded={fullOpen}
                  className="inline-flex items-center gap-1.5 self-start rounded-full border border-ink/20 bg-ink/[0.04] px-3.5 py-1.5 font-sans text-[11px] uppercase tracking-[0.16em] text-ink/70 transition-colors hover:border-ink/40 hover:bg-ink/[0.08] hover:text-ink"
                >
                  {fullOpen ? "Hide full detail" : "Open full detail"}
                  <span aria-hidden>{fullOpen ? "▴" : "▾"}</span>
                </button>
              ) : (
                <Link
                  href={`/itinerary/${itineraryId}/item/${active.id}` as Route}
                  data-testid="journal-rail-open-detail"
                  className="self-start font-sans text-[11px] uppercase tracking-[0.16em] text-ink/50 underline-offset-4 transition-colors hover:text-ink hover:underline"
                >
                  Open full detail →
                </Link>
              )
            ) : null}
          </div>

          {/* ── Zone 2 — detail + actions (edit · price · notes) ─────────────
              Stable-ordered; each section renders or collapses. */}
          <div data-testid="journal-rail-zone2" className="flex flex-col gap-3">
            {activeDiff ? (
              <RailDiffChange
                nodeDiff={activeDiff}
                isAdvisor={role === "advisor"}
                tz={timeline.timezoneOffsetHours}
              />
            ) : null}
            {/* Diff mode is a reading/deciding mode — the in-place editors sit
                out; notes stay open (below). */}
            {editableFork && !diffView && active.type !== "note" ? (
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
            <RailPrice node={active} />
            {/* The notes thread — the whole back-and-forth for this card, not
                just a compose button. Compressible when long (the modal shows
                all; the rail collapses to the most recent few). */}
            {!activeIsGhost ? (
              <div data-testid="journal-rail-notes">
                <NotesPanel
                  notes={activeNotes}
                  canAdd={hasCreds}
                  collapseAfter={3}
                  viewerActorKind={role === "advisor" ? "advisor" : "client"}
                  onAddNote={(text) =>
                    storeApi.getState().addAttachedNote(active.id, text)
                  }
                  onDeleteNote={
                    hasCreds
                      ? (noteId) => storeApi.getState().removeNode(noteId)
                      : undefined
                  }
                />
              </div>
            ) : null}
          </div>

          {/* ── Zone 3 — enrichment (blooms below; may be empty) ─────────────
              Second-class: part-of-journey, problem detail, (map slot, TODO). */}
          {activeParent || activeProblem ? (
            <div
              data-testid="journal-rail-zone3"
              className="flex flex-col gap-3"
            >
              {activeParent && active ? (
                <PartOfJourney
                  parent={activeParent}
                  child={active}
                  siblingCount={activeSiblingCount}
                  tzOffsetHours={timeline.timezoneOffsetHours}
                  onOpenParent={() => focusNode(activeParent.id, "click")}
                />
              ) : null}
              {activeProblem ? (
                <RailProblem problem={activeProblem} />
              ) : null}
              {/* Map slot (coords-gated) — deferred; see plan open items. */}
            </div>
          ) : null}
        </div>
      ) : null}
    </>
  );
}

// ── Zone 1: the compact identity + the ask ───────────────────────────────────
// Replaces the old NodeZoomCard duplicate. Uses the SAME per-type token the
// cards + spine circle wear (TYPE_TOKENS, keyed by inferCardKind) — the icon in
// its accent, the type label beside it, the time, then the title and the ask.
function RailIdentity({
  node,
  tz,
  affordances,
}: {
  node: NodeResponse;
  tz: number;
  affordances: NodeAffordances;
}) {
  const meta = getVerticalMeta(node);
  const token = TYPE_TOKENS[inferCardKind(node)];
  const start = meta.start_time
    ? formatClock(meta.start_time, offsetHoursOr(meta.start_time, tz))
    : null;
  return (
    <div data-testid="journal-rail-identity" className="flex flex-col gap-1.5">
      <div className="flex items-center gap-2">
        <span
          aria-hidden
          className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full"
          style={{ backgroundColor: token.tint, color: token.accent }}
        >
          <token.Icon size={13} strokeWidth={1.8} />
        </span>
        <span
          className="font-sans text-[10px] uppercase tracking-[0.2em]"
          style={{ color: token.accent }}
        >
          {token.label}
        </span>
        {start ? (
          <span className="ml-auto font-sans text-[11px] tabular-nums text-ink/55">
            {start}
          </span>
        ) : null}
      </div>
      <h2 className="font-serif text-lg leading-snug text-ink">{node.title}</h2>
      <RailAsk affordances={affordances} />
    </div>
  );
}

// The Zone-1 "ask" — only the settled/locked status registers here; the live
// actions (approve, problem→get-help) render as their own components so this
// never duplicates a button.
function RailAsk({ affordances }: { affordances: NodeAffordances }) {
  const chip =
    "self-start rounded-full bg-ink/5 px-2.5 py-0.5 font-sans text-[10px] uppercase tracking-[0.16em] text-ink/55";
  if (affordances.locked === "booked") {
    return (
      <span data-testid="journal-rail-ask" data-ask="booked" className={chip}>
        ⚿ Booked
      </span>
    );
  }
  if (affordances.ask === "approved") {
    return (
      <span data-testid="journal-rail-ask" data-ask="approved" className={chip}>
        Approved ✓
      </span>
    );
  }
  if (affordances.ask === "reapproval-warning") {
    return (
      <p
        data-testid="journal-rail-ask"
        data-ask="reapproval-warning"
        className="font-serif text-[12px] italic leading-snug text-ink/50"
      >
        Editing will ask the traveler to re-approve.
      </p>
    );
  }
  return null;
}

// ── Zone 2: price ────────────────────────────────────────────────────────────
// The card's headline price when it carries one. A collapsible breakdown awaits
// the billing wiring (plan open items) — a single figure is shown honestly for
// now rather than a fake expando.
function RailPrice({ node }: { node: NodeResponse }) {
  const raw = (node.metadata as { price?: unknown }).price;
  const price = typeof raw === "string" && raw.trim() ? raw : null;
  if (!price) return null;
  return (
    <div
      data-testid="journal-rail-price"
      className="flex items-baseline justify-between border-t border-ink/10 pt-2.5"
    >
      <span className="font-sans text-[9px] uppercase tracking-[0.22em] text-ink/40">
        Price
      </span>
      <span className="font-serif text-[15px] text-ink/85">{price}</span>
    </div>
  );
}

// ── Diff mode: the idle divergence summary + the role-decided CTA ────────────
function RailDiffSummary({ diffView }: { diffView: JournalDiffView }) {
  const router = useRouter();
  const role = itineraryGraphStore.useStore((s) => s.role);
  const diffLoading = itineraryGraphStore.useStore((s) => s.diffLoading);
  const diffError = itineraryGraphStore.useStore((s) => s.diffError);
  const diffBlocked = itineraryGraphStore.useStore((s) => s.diffBlocked);
  const diffApplying = itineraryGraphStore.useStore((s) => s.diffApplying);
  const diffDecisions = itineraryGraphStore.useStore((s) => s.diffDecisions);
  const requestingMerge = itineraryGraphStore.useStore((s) => s.requestingMerge);
  const mergeRequested = itineraryGraphStore.useStore((s) => s.mergeRequested);
  const cancelingMerge = itineraryGraphStore.useStore((s) => s.cancelingMerge);
  const storeApi = itineraryGraphStore.useStoreApi();

  const isAdvisor = role === "advisor";
  const keptCount = Object.values(diffDecisions).filter((a) => !a).length;

  return (
    <section
      data-testid="journal-rail-diff-summary"
      className="rounded-lg border border-ink/10 bg-white/60 p-4 sm:p-5"
    >
      <h2 className="mb-3 font-sans text-[10px] uppercase tracking-[0.2em] text-ink/45">
        Compared with the trip
      </h2>
      {diffError ? (
        <p className="font-serif text-[13px] italic text-ink/45">
          The comparison isn&rsquo;t available right now.
        </p>
      ) : diffLoading && diffView.total === 0 ? (
        <p className="font-serif text-[13px] italic text-ink/45">
          Reading the two versions…
        </p>
      ) : diffView.total === 0 ? (
        <p
          data-testid="journal-rail-diff-agree"
          className="font-serif text-[13px] italic text-ink/45"
        >
          {isAdvisor
            ? "This version matches the official trip — nothing to fold in."
            : "Your version matches the official trip."}
        </p>
      ) : (
        <div className="flex flex-col gap-3">
          <p
            data-testid="journal-rail-diff-counts"
            className="font-serif text-xl text-ink"
          >
            {diffView.summary}
          </p>
          <p className="font-sans text-[12px] leading-snug text-ink/55">
            {isAdvisor
              ? "Read the story below — activate a marked card to accept it or keep the original."
              : "The marks below show where your version diverges from the official trip."}
          </p>
          {isAdvisor ? (
            <>
              <button
                type="button"
                data-testid="journal-rail-reconcile"
                onClick={() =>
                  storeApi
                    .getState()
                    .applyDiffDecisions((id) => router.push(`/itinerary/${id}`))
                }
                disabled={diffApplying}
                className="h-9 self-start rounded-full bg-ink px-5 font-sans text-[11px] uppercase tracking-[0.18em] text-paper transition-opacity hover:opacity-90 disabled:cursor-default disabled:opacity-50"
              >
                {diffApplying
                  ? "Reconciling…"
                  : keptCount > 0
                    ? "Reconcile the decisions"
                    : "Accept all into the trip"}
              </button>
              {keptCount > 0 ? (
                <p className="font-sans text-[11px] text-ink/50">
                  {keptCount} kept as the original
                </p>
              ) : null}
              {diffBlocked ? (
                <p
                  data-testid="journal-rail-diff-blocked"
                  className="font-sans text-[12px] leading-snug text-[#8b2a1d]"
                >
                  A blocking feasibility finding refused the reconcile — review
                  and override it from the Timeline&rsquo;s Diff tab.
                </p>
              ) : null}
            </>
          ) : mergeRequested ? (
            <div className="flex flex-col gap-1.5">
              <p
                data-testid="journal-rail-merge-requested"
                className="font-sans text-[12px] text-ink/60"
              >
                Reconcile requested ✓ — your advisor will fold this in.
              </p>
              <button
                type="button"
                data-testid="journal-rail-cancel-reconcile"
                onClick={() => storeApi.getState().cancelMerge()}
                disabled={cancelingMerge}
                className="self-start font-sans text-[10px] uppercase tracking-[0.16em] text-ink/50 underline-offset-4 transition-colors hover:text-ink hover:underline disabled:opacity-50"
              >
                {cancelingMerge ? "Cancelling…" : "Cancel the request"}
              </button>
            </div>
          ) : (
            <button
              type="button"
              data-testid="journal-rail-request-reconcile"
              onClick={() => storeApi.getState().requestMerge()}
              disabled={requestingMerge}
              className="h-9 self-start rounded-full bg-ink px-5 font-sans text-[11px] uppercase tracking-[0.18em] text-paper transition-opacity hover:opacity-90 disabled:cursor-default disabled:opacity-50"
            >
              {requestingMerge ? "Sending…" : "Request reconcile"}
            </button>
          )}
        </div>
      )}
    </section>
  );
}

// ── Diff mode: the active node's change — before/after + accept / keep ───────
const DIFF_KIND_LABEL: Record<JournalNodeDiff["kind"], string> = {
  added: "New in this version",
  removed: "Not in this version",
  changed: "Changed in this version",
  moved: "Moved in this version",
};

function RailDiffChange({
  nodeDiff,
  isAdvisor,
  tz,
}: {
  nodeDiff: JournalNodeDiff;
  isAdvisor: boolean;
  tz: number;
}) {
  const diffDecisions = itineraryGraphStore.useStore((s) => s.diffDecisions);
  const diffOutcomes = itineraryGraphStore.useStore((s) => s.diffOutcomes);
  const storeApi = itineraryGraphStore.useStoreApi();

  const { kind, change } = nodeDiff;
  const accepted = diffDecisions[change.change_id] ?? true;
  const outcome = diffOutcomes[change.change_id];

  // G1: a booked/confirmed node on the official trip is immutable — the
  // decision is a LOCK explanation, not a pair of buttons (and a reconcile
  // pass that already refused it says so too).
  const beforeStatus =
    typeof change.before?.["status"] === "string"
      ? change.before["status"]
      : null;
  const locked =
    outcome === "refused_booked" ||
    beforeStatus === "booked" ||
    beforeStatus === "confirmed";

  const fieldRows = kind === "changed" ? changedFieldRows(change, tz) : [];
  const movedTimes = kind === "moved" ? movedTimeLabels(change, tz) : null;
  const detailsUpdated =
    kind === "changed" && (change.fields ?? []).includes("metadata");

  const decisionBtn = (isActive: boolean) =>
    [
      "rounded-full border px-3.5 py-1 font-sans text-[10px] uppercase tracking-[0.16em] transition-colors",
      isActive
        ? "border-ink bg-ink text-paper"
        : "border-ink/25 text-ink/60 hover:border-ink/50 hover:text-ink",
    ].join(" ");

  return (
    <div
      data-testid="journal-rail-diff-change"
      data-kind={kind}
      className="flex flex-col gap-2.5 rounded-md border border-brand/30 bg-[rgba(245,112,31,0.04)] p-3"
    >
      <p className="font-sans text-[9px] uppercase tracking-[0.22em] text-brand">
        {DIFF_KIND_LABEL[kind]}
      </p>

      {fieldRows.length > 0 ? (
        <dl className="flex flex-col gap-1.5">
          {fieldRows.map((row) => (
            <div
              key={row.field}
              data-testid="journal-rail-diff-field"
              data-field={row.field}
              className="flex flex-col gap-0.5"
            >
              <dt className="font-sans text-[9px] uppercase tracking-[0.18em] text-ink/40">
                {row.label}
              </dt>
              <dd className="font-serif text-[13px] leading-snug text-ink/85">
                <span className="text-ink/50 line-through decoration-ink/25">
                  {row.before}
                </span>
                <span aria-hidden className="px-1.5 text-ink/35">
                  →
                </span>
                {row.after}
              </dd>
            </div>
          ))}
        </dl>
      ) : null}
      {detailsUpdated ? (
        <p className="font-sans text-[11px] italic text-ink/50">
          Details updated
        </p>
      ) : null}
      {movedTimes ? (
        <p
          data-testid="journal-rail-diff-times"
          className="font-serif text-[13px] leading-snug text-ink/85"
        >
          <span className="text-ink/50 line-through decoration-ink/25">
            {movedTimes.before}
          </span>
          <span aria-hidden className="px-1.5 text-ink/35">
            →
          </span>
          {movedTimes.after}
        </p>
      ) : null}

      {locked ? (
        <p
          data-testid="journal-rail-diff-locked"
          className="flex items-start gap-1.5 font-sans text-[12px] leading-snug text-ink/60"
        >
          <span aria-hidden>⚿</span>
          <span>
            This card is booked on the official trip — booked cards stay as
            they are, so this change can&rsquo;t be folded in.
          </span>
        </p>
      ) : isAdvisor ? (
        <div className="flex flex-wrap items-center gap-1.5">
          <button
            type="button"
            data-testid="journal-rail-diff-accept"
            aria-pressed={accepted}
            onClick={() =>
              storeApi.getState().setDiffDecision(change.change_id, true)
            }
            className={decisionBtn(accepted)}
          >
            Accept
          </button>
          <button
            type="button"
            data-testid="journal-rail-diff-keep"
            aria-pressed={!accepted}
            onClick={() =>
              storeApi.getState().setDiffDecision(change.change_id, false)
            }
            className={decisionBtn(!accepted)}
          >
            Keep the original
          </button>
        </div>
      ) : null}
    </div>
  );
}

// ── Problem explanation + "get help" (summons the concierge) ─────────────────
function RailProblem({ problem }: { problem: JournalProblem }) {
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
        // The concierge learns which card this problem is on silently (it's the
        // focused card), so "Get help" just summons it — no manual scope.
        onClick={openConcierge}
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
// cancels. Deeper changes (durations/lanes/bulk ops) stay in Studio or go
// through the concierge, which already knows which card is on screen.
function RailEditPanel({ node, tz }: { node: NodeResponse; tz: number }) {
  const storeApi = itineraryGraphStore.useStoreApi();

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
        Your version
      </p>
      <InlineField
        label="Title"
        value={node.title}
        testid="journal-rail-edit-title"
        onSave={(v) => storeApi.getState().editNodeField(node.id, "title", v)}
      />
      {start ? (
        isSchedulePinned(node) ? (
          // A flight's time is the airline's, not the traveler's — show it
          // read-only (no editable input that would silently no-op) and say why.
          <div className="flex flex-col gap-0.5" data-testid="journal-rail-time-pinned">
            <span className="font-sans text-[9px] uppercase tracking-[0.18em] text-ink/40">
              Time
            </span>
            <span className="self-start font-serif text-[13px] text-ink/85">
              {formatClock(start, offsetHoursOr(start, tz))}
            </span>
            <span className="font-sans text-[10px] italic text-ink/45">
              Set by the airline
            </span>
          </div>
        ) : (
          <InlineTime
            iso={start}
            tz={tz}
            testid="journal-rail-edit-time"
            onSave={(minute) => {
              const off = offsetHoursOr(start, tz);
              storeApi.getState().moveNode(node.id, tzDayKey(start, off), minute);
            }}
          />
        )
      ) : null}
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

// (RailNoteAction removed — the rail now renders the full notes thread via
// NotesPanel in Zone 2, not just a compose button.)
