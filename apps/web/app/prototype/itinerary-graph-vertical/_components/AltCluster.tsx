"use client";

import type { ReactNode } from "react";

interface AltClusterProps {
  top: number;
  left: number;
  width: number;
  height: number;
  children: ReactNode;
}

export function AltCluster({ top, left, width, height, children }: AltClusterProps) {
  return (
    <div
      className="absolute rounded-xl border border-dashed border-ink/15"
      style={{
        top,
        left,
        width,
        height,
        backgroundColor: "rgba(247, 244, 238, 0.45)",
        boxShadow: "inset 0 0 0 1px rgba(255,255,255,0.35)",
      }}
    >
      <div className="absolute -top-3 left-4 bg-paper px-2 text-[9px] uppercase tracking-[0.22em] text-ink/55">
        Choose one
      </div>
      {children}
    </div>
  );
}
