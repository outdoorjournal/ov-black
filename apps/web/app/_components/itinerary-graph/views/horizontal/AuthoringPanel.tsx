"use client";

// B7 — advisor authoring panel (standalone-prototype "Build" aside).
//
// Since the M006 harmonization the authoring actions are the single source of
// truth under `authoring/` and render in three hosts: the unified Add composer
// (Find/Fill modes), the Analyze modal on the routed timeline, and — here — the
// prototype's in-canvas aside, which still stacks all three sections plus the
// "Add a card" composer entry point. This file is now a thin composition; the
// logic lives in the section components.
//
// Reads (search / analyze / fill) only need `canEdit`; the writes (Add / Accept)
// need the lock, so those buttons gate on `editable` (selectEditable) inside the
// sections. Craft-feel (R014): plain text + `disabled`, serif titles, uppercase
// sans labels, warm red `#8b2a1d` only for destructive.

import { useComposerControl } from "@/app/itinerary/[id]/_shell/ComposerControl";

import {
  itineraryGraphStore,
  selectEditable,
} from "../../store/itineraryGraphStore";

import { AnalyzeSection } from "./authoring/AnalyzeSection";
import { FillSection } from "./authoring/FillSection";
import { SearchSection } from "./authoring/SearchSection";
import { btn } from "./authoring/shared";

type AuthoringPanelProps = {
  tzOffsetHours: number;
  /** Trip day keys (YYYY-MM-DD), used to default the Fill gap inputs. */
  days: ReadonlyArray<{ date: string }>;
};

export function AuthoringPanel({ tzOffsetHours, days }: AuthoringPanelProps) {
  const editable = itineraryGraphStore.useStore(selectEditable);
  const { openComposer } = useComposerControl();

  return (
    <div
      data-testid="itinerary-graph-authoring"
      className="flex h-full flex-col gap-6 overflow-y-auto bg-paper/70 px-4 py-4"
    >
      {!editable ? (
        <p
          data-testid="itinerary-graph-authoring-locked"
          className="font-sans text-[11px] leading-relaxed text-ink/55"
        >
          Adding to the itinerary needs the edit lock — press{" "}
          <span className="uppercase tracking-[0.16em]">Edit</span> above. You can
          still search, analyze, and find options.
        </p>
      ) : null}

      {/* ── 0. Add a card (hand-author) ─────────────────────────────────── */}
      <section data-testid="itinerary-graph-add-card">
        <button
          type="button"
          onClick={() => openComposer()}
          disabled={!editable}
          data-testid="add-card-open"
          className={`${btn} w-full justify-center`}
        >
          Add a card
        </button>
      </section>

      {/* ── 1. Inventory search ─────────────────────────────────────────── */}
      <SearchSection />

      {/* ── 2. Analyze ──────────────────────────────────────────────────── */}
      <AnalyzeSection />

      {/* ── 3. Fill a gap ───────────────────────────────────────────────── */}
      <FillSection tzOffsetHours={tzOffsetHours} days={days} />
    </div>
  );
}
