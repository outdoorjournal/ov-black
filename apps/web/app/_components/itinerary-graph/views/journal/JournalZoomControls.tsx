"use client";

// The Journal's time-scale control (traveler-journal). The Journal is
// event-proportional, not a clock — but the duration bars on the cards and the
// gaps between them are sized by `journalPxPerMinute`, so this dial lets the
// reader breathe the timeline in and out: "Cozy" packs the story tight, "Detail"
// lets a long afternoon stretch and its hour ticks spread. Modeled on the
// horizontal view's ZoomControls (same popover idiom) but wired to the journal
// zoom state and kept whisper-quiet to suit the reading surface.

import { useEffect, useRef, useState } from "react";
import { ChevronDown, Minus, Plus, RotateCcw, Clock } from "lucide-react";

import {
  itineraryGraphStore,
  JOURNAL_ZOOM_MAX,
  JOURNAL_ZOOM_MIN,
  JOURNAL_ZOOM_PRESETS,
} from "../../store/itineraryGraphStore";

export function JournalZoomControls() {
  const px = itineraryGraphStore.useStore((s) => s.journalPxPerMinute);
  const cinemaMode = itineraryGraphStore.useStore((s) => s.cinemaMode);
  const storeApi = itineraryGraphStore.useStoreApi();
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  // Dismiss on outside-click / Escape — only wired while open.
  useEffect(() => {
    if (!open) return;
    function onPointerDown(e: PointerEvent) {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  const near = (target: number) => Math.abs(px - target) < 0.02;
  const activeLabel = near(JOURNAL_ZOOM_PRESETS.cozy)
    ? "Cozy"
    : near(JOURNAL_ZOOM_PRESETS.hour)
      ? "Hour"
      : near(JOURNAL_ZOOM_PRESETS.detail)
        ? "Detail"
        : "Custom";

  // Cinema is pure reading — the chrome fades away with the rest.
  if (cinemaMode) return null;

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="dialog"
        aria-expanded={open}
        data-testid="journal-zoom-trigger"
        className="inline-flex h-7 items-center gap-1.5 rounded-full border border-ink/15 bg-paper/80 px-3 font-sans text-[10px] uppercase tracking-[0.16em] text-ink/60 transition-colors hover:bg-ink/5 hover:text-ink"
      >
        <Clock className="h-3 w-3" />
        <span className="text-ink/45">{activeLabel}</span>
        <ChevronDown
          className={"h-3 w-3 transition-transform " + (open ? "rotate-180" : "")}
        />
      </button>
      {open ? (
        <div
          role="dialog"
          aria-label="Timeline scale"
          data-testid="journal-zoom-panel"
          className="absolute right-0 z-40 mt-2 flex w-56 flex-col gap-3 rounded-lg border border-ink/15 bg-paper p-3 shadow-lg"
        >
          <div className="flex overflow-hidden rounded-md border border-ink/15 text-[10px] uppercase tracking-[0.16em]">
            <Preset
              label="Cozy"
              onClick={() => storeApi.getState().setJournalZoomPreset("cozy")}
              active={near(JOURNAL_ZOOM_PRESETS.cozy)}
            />
            <Preset
              label="Hour"
              onClick={() => storeApi.getState().setJournalZoomPreset("hour")}
              active={near(JOURNAL_ZOOM_PRESETS.hour)}
            />
            <Preset
              label="Detail"
              onClick={() => storeApi.getState().setJournalZoomPreset("detail")}
              active={near(JOURNAL_ZOOM_PRESETS.detail)}
            />
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => storeApi.getState().journalZoomOut()}
              aria-label="Compress the timeline"
              className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md border border-ink/15 text-ink/70 hover:bg-ink/5"
            >
              <Minus className="h-3.5 w-3.5" />
            </button>
            <input
              type="range"
              min={JOURNAL_ZOOM_MIN}
              max={JOURNAL_ZOOM_MAX}
              step={0.02}
              value={px}
              onChange={(e) =>
                storeApi.getState().setJournalPxPerMinute(Number(e.target.value))
              }
              className="h-1 flex-1 cursor-pointer accent-ink/80"
              aria-label="Timeline scale"
            />
            <button
              type="button"
              onClick={() => storeApi.getState().journalZoomIn()}
              aria-label="Stretch the timeline"
              className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md border border-ink/15 text-ink/70 hover:bg-ink/5"
            >
              <Plus className="h-3.5 w-3.5" />
            </button>
          </div>
          <button
            type="button"
            onClick={() => storeApi.getState().resetJournalZoom()}
            className="inline-flex items-center gap-1.5 self-start rounded-md border border-ink/15 px-2 py-0.5 text-[10px] uppercase tracking-[0.18em] text-ink/60 hover:bg-ink/5"
          >
            <RotateCcw className="h-3 w-3" />
            Reset
          </button>
        </div>
      ) : null}
    </div>
  );
}

function Preset({
  label,
  onClick,
  active,
}: {
  label: string;
  onClick: () => void;
  active: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={[
        "flex-1 px-2 py-1 transition",
        active ? "bg-ink text-paper" : "bg-paper text-ink/70 hover:bg-ink/5",
      ].join(" ")}
    >
      {label}
    </button>
  );
}
