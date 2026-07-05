"use client";

// Same zoom controls as the vertical prototype — presets, +/-, slider, reset —
// but folded behind a "Zoom" dropdown so the header stays uncluttered. The
// trigger prints the current preset; clicking reveals the full control set in a
// popover that closes on outside-click or Escape. Kept as its own component so
// the import graph between prototypes stays clean.

import { useEffect, useRef, useState } from "react";
import { ChevronDown, Minus, Plus, RotateCcw, ZoomIn } from "lucide-react";

import {
  itineraryGraphStore,
  ZOOM_MAX,
  ZOOM_MIN,
  ZOOM_PRESETS,
} from "../../store/itineraryGraphStore";

export function ZoomControls() {
  const pxPerMinute = itineraryGraphStore.useStore((s) => s.pxPerMinute);
  const storeApi = itineraryGraphStore.useStoreApi();
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  // Dismiss on outside-click / Escape. Only wired while open, and the trigger
  // lives inside rootRef so clicking it to close doesn't double-fire.
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

  const near = (target: number) => Math.abs(pxPerMinute - target) < 0.05;
  const activeLabel = near(ZOOM_PRESETS.day)
    ? "Day"
    : near(ZOOM_PRESETS.hour)
      ? "Hour"
      : near(ZOOM_PRESETS.quarter)
        ? "15m"
        : "Custom";

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="dialog"
        aria-expanded={open}
        data-testid="itinerary-graph-zoom-trigger"
        className="inline-flex h-8 items-center gap-1.5 rounded-md border border-ink/20 bg-paper px-3 font-sans text-[11px] uppercase tracking-[0.16em] text-ink transition-colors hover:bg-ink/5"
      >
        <ZoomIn className="h-3.5 w-3.5" />
        Zoom
        <span className="text-ink/50">· {activeLabel}</span>
        <ChevronDown
          className={
            "h-3.5 w-3.5 transition-transform " + (open ? "rotate-180" : "")
          }
        />
      </button>
      {open ? (
        <div
          role="dialog"
          aria-label="Zoom"
          data-testid="itinerary-graph-zoom-panel"
          className="absolute right-0 z-40 mt-2 flex w-56 flex-col gap-3 rounded-lg border border-ink/15 bg-paper p-3 shadow-lg"
        >
          <div className="flex overflow-hidden rounded-md border border-ink/15 text-[10px] uppercase tracking-[0.16em]">
            <Preset
              label="Day"
              onClick={() => storeApi.getState().setZoomPreset("day")}
              active={near(ZOOM_PRESETS.day)}
            />
            <Preset
              label="Hour"
              onClick={() => storeApi.getState().setZoomPreset("hour")}
              active={near(ZOOM_PRESETS.hour)}
            />
            <Preset
              label="15m"
              onClick={() => storeApi.getState().setZoomPreset("quarter")}
              active={near(ZOOM_PRESETS.quarter)}
            />
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => storeApi.getState().zoomOut()}
              aria-label="Zoom out"
              className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md border border-ink/15 text-ink/70 hover:bg-ink/5"
            >
              <Minus className="h-3.5 w-3.5" />
            </button>
            <input
              type="range"
              min={ZOOM_MIN}
              max={ZOOM_MAX}
              step={0.1}
              value={pxPerMinute}
              onChange={(e) =>
                storeApi.getState().setPxPerMinute(Number(e.target.value))
              }
              className="h-1 flex-1 cursor-pointer accent-ink/80"
              aria-label="Zoom slider"
            />
            <button
              type="button"
              onClick={() => storeApi.getState().zoomIn()}
              aria-label="Zoom in"
              className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md border border-ink/15 text-ink/70 hover:bg-ink/5"
            >
              <Plus className="h-3.5 w-3.5" />
            </button>
          </div>
          <button
            type="button"
            onClick={() => storeApi.getState().resetZoom()}
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
