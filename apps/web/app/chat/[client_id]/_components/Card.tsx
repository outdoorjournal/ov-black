"use client";

// A single MoodBoard card for an agent-proposed OV experience (S07 T05),
// harmonized onto the shared CardShell substrate (M006/PS-cards): the same
// paper/noise/type-stamp/status-footer as the timeline glance and the
// Collection card. The mood board's action row (Must Do / Thumbs Up / Not This
// Time) rides in the shell's `actions` slot; the R006 inventory fields the
// shared experience body doesn't itself surface (price / duration / difficulty)
// are shown as a small facts row beneath it.
//
// Craft-feel invariants (R014): no icons, no spinners, no aria-busy, no
// skeletons. The only "loading" affordance is button `disabled` when the card's
// current status already matches the intended target (prevents a redundant
// PATCH round-trip).
//
// R006: title / price / duration / difficulty / location / activities all stay
// visible in the DOM. Snapshot data is DOM-only per the T05 redaction
// constraints — there are no log calls here.

import type { NodeResponse } from "@ov-black/api-client";

import {
  CardBody,
  statusToKind,
} from "@/app/_components/itinerary-graph/shared/cards/CardBody";
import { CardShell } from "@/app/_components/itinerary-graph/shared/cards/CardShell";
import type { ExperienceSnapshot } from "@/lib/agentStream.types";

import type { CardView } from "./types";

export type CardActionKind = "pin" | "keep" | "discard";

export type CardProps = {
  card: CardView;
  onAction: (action: CardActionKind) => void;
};

// Adapt the flat mood-board snapshot into the NodeResponse shape CardBody reads.
// Every chat card is an OV experience (see cardFromNode in ./types), so the kind
// is fixed and the shared experience body renders cover + title + location +
// activities — identical to how the same node reads on the timeline.
function nodeFromCardView(card: CardView): NodeResponse {
  const snap = card.snapshot;
  return {
    id: card.node_id,
    itinerary_id: "",
    parent_subgraph_id: null,
    type: "experience",
    status: card.status,
    title: snap.title,
    source: card.source,
    source_id: card.source_id,
    metadata: {
      snapshot: snap,
      ...(snap.location ? { location: { label: snap.location } } : {}),
    },
  };
}

export function Card({ card, onAction }: CardProps) {
  const { snapshot, status } = card;
  const node = nodeFromCardView(card);

  return (
    <article
      data-testid="mood-board-card"
      data-node-id={card.node_id}
      data-source={card.source}
      data-source-id={card.source_id}
      data-card-status={status}
      className="transition-opacity"
    >
      <CardShell
        kind="experience"
        status={statusToKind(status)}
        width="glance"
        actions={<MoodActions status={status} onAction={onAction} />}
      >
        <CardBody node={node} kind="experience" tzOffsetHours={0} />
        <MoodFacts snapshot={snapshot} />
      </CardShell>
    </article>
  );
}

// The R006 inventory fields the shared experience body doesn't surface itself
// (it shows title / location / activities / cover). A small definition list so
// price / duration / difficulty stay visible and screen-readable.
function MoodFacts({ snapshot }: { snapshot: ExperienceSnapshot }) {
  const hasDuration = typeof snapshot.duration_days === "number";
  if (!snapshot.price && !hasDuration && !snapshot.difficulty) return null;
  return (
    <dl className="mt-2 flex flex-wrap gap-x-4 gap-y-1 font-sans text-[12px] text-ink/60">
      {snapshot.price ? (
        <div className="flex gap-1">
          <dt className="sr-only">Price</dt>
          <dd>{snapshot.price}</dd>
        </div>
      ) : null}
      {hasDuration ? (
        <div className="flex gap-1">
          <dt className="sr-only">Duration</dt>
          <dd>
            {snapshot.duration_days}{" "}
            {snapshot.duration_days === 1 ? "day" : "days"}
          </dd>
        </div>
      ) : null}
      {snapshot.difficulty ? (
        <div className="flex gap-1">
          <dt className="sr-only">Difficulty</dt>
          <dd>{snapshot.difficulty}</dd>
        </div>
      ) : null}
    </dl>
  );
}

// The status-matrix action row, rendered in the CardShell `actions` slot. Three
// plain-text buttons; each disables when the card already holds the target
// status. Pin -> approved; Keep -> optimistic (no PATCH when already proposed);
// Discard -> discarded.
function MoodActions({
  status,
  onAction,
}: {
  status: CardView["status"];
  onAction: (action: CardActionKind) => void;
}) {
  return (
    <div className="flex flex-wrap gap-2 px-3 pb-3 pt-3">
      <button
        type="button"
        onClick={() => onAction("pin")}
        disabled={status === "approved"}
        className="h-9 rounded-md border border-ink/20 bg-paper px-3 font-sans text-[11px] uppercase tracking-[0.18em] text-ink transition-colors hover:bg-ink/5 disabled:cursor-default disabled:opacity-50"
        data-testid="mood-board-card-pin"
      >
        Must Do
      </button>
      <button
        type="button"
        onClick={() => onAction("keep")}
        disabled={status === "pending"}
        className="h-9 rounded-md border border-ink/15 bg-paper px-3 font-sans text-[11px] uppercase tracking-[0.18em] text-ink/80 transition-colors hover:bg-ink/5 disabled:cursor-default disabled:opacity-50"
        data-testid="mood-board-card-keep"
      >
        Thumbs Up
      </button>
      <button
        type="button"
        onClick={() => onAction("discard")}
        disabled={status === "discarded"}
        className="h-9 rounded-md border border-ink/15 bg-paper px-3 font-sans text-[11px] uppercase tracking-[0.18em] text-ink/60 transition-colors hover:bg-ink/5 disabled:cursor-default disabled:opacity-50"
        data-testid="mood-board-card-discard"
      >
        Not This Time
      </button>
    </div>
  );
}
