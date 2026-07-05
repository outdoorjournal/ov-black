"use client";

// A single MoodBoard card for an agent-proposed OV experience (S07 T05).
//
// The card is stateless — it renders whatever `card.status` the reducer
// holds and delegates every interaction to `onAction`. Three plain-text
// buttons cover the full status matrix:
//
//   Must Do         → pin     → PATCH status=approved
//   Thumbs Up       → keep    → optimistic only if already proposed (see ChatShell)
//   Not This Time   → discard → PATCH status=discarded (fades out of aside)
//
// Craft-feel invariants (R014): no icons, no spinners, no aria-busy, no
// skeletons. The only "loading" affordance is button `disabled` when the
// card's current status already matches the intended target (prevents
// redundant PATCH round-trips).
//
// Snapshot rendering intentionally exposes the OV public inventory fields in
// the DOM — R006 requires title/price/duration/difficulty/location/
// activities to be visible. There are no log calls here; snapshot data is
// DOM-only per T05 redaction constraints.

import Image from "next/image";

import type { CardView } from "./types";

export type CardActionKind = "pin" | "keep" | "discard";

export type CardProps = {
  card: CardView;
  onAction: (action: CardActionKind) => void;
};

export function Card({ card, onAction }: CardProps) {
  const { snapshot, status } = card;
  const hasCover =
    typeof snapshot.cover_image === "string" && snapshot.cover_image.length > 0;

  return (
    <article
      className="overflow-hidden rounded-lg border border-ink/10 bg-paper/90 shadow-[0_1px_0_rgba(0,0,0,0.03)] transition-opacity"
      data-testid="mood-board-card"
      data-node-id={card.node_id}
      data-source={card.source}
      data-source-id={card.source_id}
      data-card-status={status}
    >
      {hasCover ? (
        <div className="relative aspect-16/10 w-full bg-ink/5">
          <Image
            src={snapshot.cover_image as string}
            alt=""
            fill
            sizes="(max-width: 768px) 100vw, 480px"
            className="object-cover"
          />
        </div>
      ) : (
        // Palette-tone fallback when no cover is provided — keeps the card
        // footprint stable without pulling in any skeleton primitive.
        <div
          className="aspect-16/10 w-full bg-ink/5"
          data-testid="mood-board-card-cover-fallback"
        />
      )}

      <div className="space-y-3 px-5 py-4">
        <h3 className="font-serif text-xl leading-tight text-ink">
          {snapshot.title}
        </h3>
        <dl className="flex flex-wrap gap-x-4 gap-y-1 font-sans text-[13px] text-ink/60">
          {snapshot.price ? (
            <div className="flex gap-1">
              <dt className="sr-only">Price</dt>
              <dd>{snapshot.price}</dd>
            </div>
          ) : null}
          {typeof snapshot.duration_days === "number" ? (
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
          {snapshot.location ? (
            <div className="flex gap-1">
              <dt className="sr-only">Location</dt>
              <dd>{snapshot.location}</dd>
            </div>
          ) : null}
        </dl>
        {snapshot.activities && snapshot.activities.length > 0 ? (
          <p className="font-sans text-[12px] uppercase tracking-[0.18em] text-ink/50">
            {snapshot.activities.join(", ")}
          </p>
        ) : null}

        <div className="flex flex-wrap gap-2 pt-2">
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
            disabled={status === "proposed"}
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
      </div>
    </article>
  );
}
