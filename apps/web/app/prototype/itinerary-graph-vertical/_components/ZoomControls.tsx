"use client";

import {
  verticalStore,
  ZOOM_MAX,
  ZOOM_MIN,
  ZOOM_PRESETS,
} from "../_state/verticalStore";

export function ZoomControls() {
  const pxPerMinute = verticalStore.useStore((s) => s.pxPerMinute);
  const storeApi = verticalStore.useStoreApi();

  return (
    <div className="flex items-center gap-2">
      <span className="text-[10px] uppercase tracking-[0.22em] text-ink/55">Zoom</span>
      <div className="flex overflow-hidden rounded-md border border-ink/15 text-[10px] uppercase tracking-[0.16em]">
        <ZoomPresetButton
          label="Day"
          onClick={() => storeApi.getState().setZoomPreset("day")}
          active={Math.abs(pxPerMinute - ZOOM_PRESETS.day) < 0.05}
        />
        <ZoomPresetButton
          label="Hour"
          onClick={() => storeApi.getState().setZoomPreset("hour")}
          active={Math.abs(pxPerMinute - ZOOM_PRESETS.hour) < 0.05}
        />
        <ZoomPresetButton
          label="15m"
          onClick={() => storeApi.getState().setZoomPreset("quarter")}
          active={Math.abs(pxPerMinute - ZOOM_PRESETS.quarter) < 0.05}
        />
      </div>
      <button
        type="button"
        onClick={() => storeApi.getState().zoomOut()}
        aria-label="Zoom out"
        className="flex h-6 w-6 items-center justify-center rounded-md border border-ink/15 text-ink/70 hover:bg-ink/5"
      >
        −
      </button>
      <input
        type="range"
        min={ZOOM_MIN}
        max={ZOOM_MAX}
        step={0.1}
        value={pxPerMinute}
        onChange={(e) => storeApi.getState().setPxPerMinute(Number(e.target.value))}
        className="h-1 w-28 cursor-pointer accent-ink/80"
        aria-label="Zoom slider"
      />
      <button
        type="button"
        onClick={() => storeApi.getState().zoomIn()}
        aria-label="Zoom in"
        className="flex h-6 w-6 items-center justify-center rounded-md border border-ink/15 text-ink/70 hover:bg-ink/5"
      >
        +
      </button>
      <button
        type="button"
        onClick={() => storeApi.getState().resetZoom()}
        className="rounded-md border border-ink/15 px-2 py-0.5 text-[10px] uppercase tracking-[0.18em] text-ink/60 hover:bg-ink/5"
      >
        Reset
      </button>
    </div>
  );
}

function ZoomPresetButton({
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
      className={[
        "px-2 py-0.5 transition",
        active ? "bg-ink text-paper" : "bg-paper text-ink/70 hover:bg-ink/5",
      ].join(" ")}
    >
      {label}
    </button>
  );
}
