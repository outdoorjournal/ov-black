"use client";

// Fill a gap (B6), extracted from the old AuthoringPanel. Rank feasible
// candidates for a time window, then Accept one onto the timeline. Each
// candidate renders through the common Card model (`CardShell` + `CardBody`) with
// the proposed slot baked in, plus a rationale/feasibility caption beneath — no
// bespoke card markup. Reads only need `canEdit`; Accept needs the lock.

import { useState } from "react";

import type { FillProposalResponse } from "@ov-black/api-client";

import { CardBody, inferCardKind } from "../../../shared/cards/CardBody";
import { CardShell } from "../../../shared/cards/CardShell";
import {
  itineraryGraphStore,
  selectEditable,
} from "../../../store/itineraryGraphStore";

import { btn, fillProposalToNode, localToIso, sectionTitle } from "./shared";

type FillSectionProps = {
  tzOffsetHours: number;
  /** Trip day keys (YYYY-MM-DD), used to default the gap inputs. */
  days: ReadonlyArray<{ date: string }>;
  /** Print the section's own "Fill a gap" label (prototype aside). Hosts that
   *  already title the surface (composer Fill mode) pass false. */
  heading?: boolean;
};

export function FillSection({ tzOffsetHours, days, heading = true }: FillSectionProps) {
  const editable = itineraryGraphStore.useStore(selectEditable);
  const storeApi = itineraryGraphStore.useStoreApi();
  const fillProposals = itineraryGraphStore.useStore((s) => s.fillProposals);
  const fillPending = itineraryGraphStore.useStore((s) => s.fillPending);
  const addingInventoryId = itineraryGraphStore.useStore((s) => s.addingInventoryId);

  const firstDay = days[0]?.date ?? "";
  const [gapStart, setGapStart] = useState(firstDay ? `${firstDay}T09:00` : "");
  const [gapEnd, setGapEnd] = useState(firstDay ? `${firstDay}T13:00` : "");

  const onFill = () => {
    if (!gapStart || !gapEnd) return;
    storeApi.getState().runFill({
      start: localToIso(gapStart, tzOffsetHours),
      end: localToIso(gapEnd, tzOffsetHours),
    });
  };

  return (
    <section data-testid="itinerary-graph-fill">
      {heading ? <div className={sectionTitle}>Fill a gap</div> : null}
      <div className="mt-2 flex flex-col gap-2">
        <label className="flex items-center justify-between gap-2">
          <span className="font-sans text-[10px] uppercase tracking-[0.16em] text-ink/50">
            From
          </span>
          <input
            type="datetime-local"
            value={gapStart}
            onChange={(e) => setGapStart(e.target.value)}
            data-testid="itinerary-graph-fill-start"
            className="h-8 rounded-md border border-ink/15 bg-paper px-2 font-sans text-[12px] text-ink focus:border-ink/40 focus:outline-hidden"
          />
        </label>
        <label className="flex items-center justify-between gap-2">
          <span className="font-sans text-[10px] uppercase tracking-[0.16em] text-ink/50">
            Until
          </span>
          <input
            type="datetime-local"
            value={gapEnd}
            onChange={(e) => setGapEnd(e.target.value)}
            data-testid="itinerary-graph-fill-end"
            className="h-8 rounded-md border border-ink/15 bg-paper px-2 font-sans text-[12px] text-ink focus:border-ink/40 focus:outline-hidden"
          />
        </label>
        <button
          type="button"
          onClick={onFill}
          disabled={fillPending || !gapStart || !gapEnd}
          data-testid="itinerary-graph-fill-run"
          className={`${btn} self-start`}
        >
          {fillPending ? "Finding options" : "Find options"}
        </button>
      </div>

      <ul
        className="mt-3 flex flex-wrap gap-3"
        data-testid="itinerary-graph-fill-proposals"
      >
        {fillProposals.map((p: FillProposalResponse) => {
          const node = fillProposalToNode(p);
          const adding = addingInventoryId === p.inventory_id;
          return (
            <li
              key={`${p.inventory_source}:${p.inventory_id}`}
              data-testid="itinerary-graph-fill-proposal"
              className="flex w-[260px] flex-col gap-2"
            >
              <CardShell
                kind={inferCardKind(node)}
                status="proposed"
                width="glance"
                lockLabel={node.type}
              >
                <CardBody
                  node={node}
                  kind={inferCardKind(node)}
                  tzOffsetHours={tzOffsetHours}
                />
              </CardShell>
              <p className="px-0.5 font-sans text-[11px] leading-relaxed text-ink/60">
                {p.rationale}
              </p>
              <div className="px-0.5 font-sans text-[10px] uppercase tracking-[0.14em] text-ink/40">
                {p.feasibility_unknown
                  ? "Feasibility unconfirmed"
                  : p.fits_in_gap
                    ? "Fits the window"
                    : "Tight fit"}
              </div>
              <div className="flex gap-2 px-0.5">
                <button
                  type="button"
                  onClick={() => storeApi.getState().acceptFillProposal(p)}
                  disabled={!editable || adding}
                  data-testid="itinerary-graph-fill-accept"
                  className="h-7 rounded-md border border-ink/20 bg-paper px-2.5 font-sans text-[10px] uppercase tracking-[0.16em] text-ink transition-colors hover:bg-ink/5 disabled:cursor-default disabled:opacity-40"
                >
                  {adding ? "Adding" : "Accept"}
                </button>
                <button
                  type="button"
                  onClick={() => storeApi.getState().dismissFillProposal(p.inventory_id)}
                  data-testid="itinerary-graph-fill-dismiss"
                  className="h-7 rounded-md border border-ink/15 bg-paper px-2.5 font-sans text-[10px] uppercase tracking-[0.16em] text-ink/70 transition-colors hover:bg-ink/5"
                >
                  Dismiss
                </button>
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
