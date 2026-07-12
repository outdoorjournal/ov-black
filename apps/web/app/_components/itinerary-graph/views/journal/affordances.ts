// The Journal rail's affordance resolver (rail redesign, phase 2a). ONE pure
// selector over (store state, node) that answers "what can the viewer do with
// this card right now" — so the cockpit rail's zones render from a single
// resolved intent set instead of the pile of scattered conditionals the rail
// grew (selectCanApprove / selectEditable / onTrunk / node.status / …).
//
// It composes the EXISTING store selectors rather than re-deriving their rules:
//   · `s.canEdit` is the store's advisor flag (derived as role === "advisor");
//     role stays the source of truth, this is just its in-store form.
//   · `selectCanSchedule` is the real editable surface — an advisor on their
//     working-copy fork or a traveler on their own fork (draft-mine excluded on
//     purpose: its first edit lazily forks via the drag path, not the rail).
//   · `selectCanApprove` / `selectCanLeaveNote` / `isSchedulePinned` unchanged.
//
// The 3-axis matrix (role × node-state × fork-context) and the lock model live
// in doc/traveler-journal-rail-plan.md; this is that table as code. Diff mode is
// deliberately NOT an input — it's an orthogonal reading/deciding mode layered
// over the same zones, resolved elsewhere.
//
// The lock model (which pins forbid a mutation):
//   · booked / confirmed (G1)  → hard for everyone.
//   · schedule-pinned (flight) → reschedule is the airline's; other fields edit.
//   · approved                 → hard for the traveler; SOFT for an advisor in
//     an editable context (the edit demotes the node to pending → the traveler
//     re-approves; see the 2b backend path). Note a fork already demotes
//     approved→pending, so the reachable advisor-demote case is the in-place
//     one — until that lands it simply won't fire.

import type { NodeResponse } from "../../model/types";
import {
  isSchedulePinned,
  type ItineraryGraphState,
  selectCanApprove,
  selectCanLeaveNote,
  selectCanSchedule,
} from "../../store/itineraryGraphStore";

/** Whether the day/time reposition control is live, or why it isn't. */
export type RescheduleState =
  | "live" // editable context, freely movable
  | "fork-offer" // traveler on the trunk — moving offers "make this yours?"
  | "pinned-airline" // a flight's time is the airline's (read-only)
  | "locked-booked" // booked/confirmed — G1 immutable
  | "locked-approved" // approved pins it for the traveler
  | "none"; // no reschedule affordance here

/** Whether the field editor (title/note/…) is live, or why it isn't. */
export type EditState =
  | "live"
  | "advisor-demote" // advisor edit of an approved node → demotes to pending
  | "fork-offer"
  | "locked-booked"
  | "locked-approved"
  | "none";

/** Whose voice a note is written in (or that notes aren't available). */
export type NotesState = "to-advisor" | "internal" | "none";

/** The Zone-1 "ask" — the single primary thing about this card's state. */
export type AskState =
  | "approve" // traveler: this pending card awaits your approval
  | "approved" // settled ✓
  | "reapproval-warning" // advisor: editing will ask the traveler to re-approve
  | "booked" // locked, booked on the official trip
  | "needs-attention" // a problem/finding is attached
  | "none";

export type NodeAffordances = {
  /** The per-node Approve CTA is live (traveler, pending, proposed to them). */
  approve: boolean;
  reschedule: RescheduleState;
  edit: EditState;
  notes: NotesState;
  ask: AskState;
  /** Hard-lock reason for legibility copy (booked/confirmed only). */
  locked: "booked" | null;
};

export function resolveNodeAffordances(
  s: ItineraryGraphState,
  node: NodeResponse,
  opts: { hasProblem?: boolean } = {},
): NodeAffordances {
  const isAdvisor = s.canEdit;
  const hasCreds = selectCanLeaveNote(s);
  const onTrunk = !s.sample.itinerary?.forked_from_id;
  const editable = selectCanSchedule(s);

  const st = node.status;
  const booked = st === "booked" || st === "confirmed";
  const approved = st === "approved";
  const pinned = isSchedulePinned(node);

  const approve = selectCanApprove(s) && st === "pending";
  const notes: NotesState = !hasCreds
    ? "none"
    : isAdvisor
      ? "internal"
      : "to-advisor";

  // Pre-firmed (pending/discarded) mutation base — the same rule the drag path
  // encodes in `journalDropMode`, minus the draft-mine lazy-fork (the rail's
  // in-place edit needs a real fork; a trunk traveler is offered one).
  const preFirmed = (): "live" | "fork-offer" | "none" => {
    if (editable) return "live";
    if (!isAdvisor && onTrunk && hasCreds) return "fork-offer";
    return "none";
  };

  let edit: EditState;
  if (booked) edit = "locked-booked";
  else if (approved)
    edit =
      isAdvisor && editable
        ? "advisor-demote"
        : isAdvisor
          ? "none"
          : "locked-approved";
  else edit = preFirmed();

  let reschedule: RescheduleState;
  if (booked) reschedule = "locked-booked";
  else if (pinned) reschedule = "pinned-airline";
  else if (approved)
    reschedule =
      isAdvisor && editable ? "live" : isAdvisor ? "none" : "locked-approved";
  else reschedule = preFirmed();

  let ask: AskState;
  if (opts.hasProblem) ask = "needs-attention";
  else if (booked) ask = "booked";
  else if (approve) ask = "approve";
  else if (approved && isAdvisor && editable) ask = "reapproval-warning";
  else if (approved) ask = "approved";
  else ask = "none";

  return { approve, reschedule, edit, notes, ask, locked: booked ? "booked" : null };
}
