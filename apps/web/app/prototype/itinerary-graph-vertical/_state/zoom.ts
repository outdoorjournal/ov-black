"use client";

import { useCallback, useEffect, useState } from "react";

export const ZOOM_MIN = 0.6;
export const ZOOM_MAX = 6.0;
export const ZOOM_PRESETS = {
  day: 1.2,
  hour: 2.5,
  quarter: 6.0,
} as const;
export type ZoomPreset = keyof typeof ZOOM_PRESETS;

export function clampZoom(value: number): number {
  return Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, value));
}

export interface UseZoomApi {
  pxPerMinute: number;
  setPxPerMinute: (v: number) => void;
  zoomIn: () => void;
  zoomOut: () => void;
  reset: () => void;
  setPreset: (p: ZoomPreset) => void;
}

export function useZoom(initial: number = ZOOM_PRESETS.day): UseZoomApi {
  const [pxPerMinute, setPxPerMinuteRaw] = useState<number>(initial);

  const setPxPerMinute = useCallback((v: number) => {
    setPxPerMinuteRaw(clampZoom(v));
  }, []);

  const zoomIn = useCallback(() => {
    setPxPerMinuteRaw((p) => clampZoom(p * 1.35));
  }, []);
  const zoomOut = useCallback(() => {
    setPxPerMinuteRaw((p) => clampZoom(p / 1.35));
  }, []);
  const reset = useCallback(() => {
    setPxPerMinuteRaw(ZOOM_PRESETS.day);
  }, []);
  const setPreset = useCallback((p: ZoomPreset) => {
    setPxPerMinuteRaw(ZOOM_PRESETS[p]);
  }, []);

  // Keyboard shortcuts: ⌘+ / ⌘- / ⌘0
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (!(e.metaKey || e.ctrlKey)) return;
      if (e.key === "=" || e.key === "+") {
        e.preventDefault();
        zoomIn();
      } else if (e.key === "-") {
        e.preventDefault();
        zoomOut();
      } else if (e.key === "0") {
        e.preventDefault();
        reset();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [zoomIn, zoomOut, reset]);

  return { pxPerMinute, setPxPerMinute, zoomIn, zoomOut, reset, setPreset };
}
