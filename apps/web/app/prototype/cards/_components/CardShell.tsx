"use client";

import type { ReactNode } from "react";

import {
  NOISE_BG,
  STATUS_TOKENS,
  TYPE_TOKENS,
  type CardKind,
  type StatusKind,
} from "../_lib/tokens";

interface CardShellProps {
  kind: CardKind;
  status?: StatusKind;
  width?: "glance" | "zoom";
  children: ReactNode;
  noteOverride?: boolean;
}

export function CardShell({
  kind,
  status = "proposed",
  width = "glance",
  children,
  noteOverride,
}: CardShellProps) {
  const token = TYPE_TOKENS[kind];
  const isNote = noteOverride ?? kind === "note";

  const style = {
    backgroundImage: `${NOISE_BG}, linear-gradient(180deg, rgba(255,255,255,0.35) 0%, rgba(255,255,255,0) 40%)`,
    backgroundColor: isNote ? "#fbf1c7" : "#f7f4ee",
    borderColor: isNote ? "rgba(180,140,30,0.22)" : "rgba(10,10,10,0.10)",
    boxShadow:
      status === "discarded"
        ? "0 1px 0 rgba(0,0,0,0.04)"
        : "0 1px 0 rgba(0,0,0,0.04), 0 8px 24px -12px rgba(0,0,0,0.25), inset 0 1px 0 rgba(255,255,255,0.6)",
  };

  const wrapClass = [
    "relative rounded-lg border overflow-hidden font-sans text-ink text-left",
    width === "glance" ? "p-3 w-[260px]" : "p-5 w-full max-w-[640px]",
    status === "idea" ? "border-dashed opacity-80" : "",
    status === "discarded" ? "opacity-50 grayscale" : "",
    status === "confirmed" ? "ring-1 ring-ink/20 ring-offset-2 ring-offset-paper" : "",
  ].join(" ");

  return (
    <div role="group" aria-label={`${token.label} card, ${STATUS_TOKENS[status].label}`} className={wrapClass} style={style}>
      {status !== "idea" && status !== "discarded" ? (
        <span
          aria-hidden
          className="pointer-events-none absolute -top-1 left-3 h-3 w-12 rotate-[-3deg] opacity-80"
          style={{
            backgroundColor: token.accent,
            boxShadow: "0 1px 2px rgba(0,0,0,0.2)",
            mixBlendMode: "multiply",
          }}
        />
      ) : null}

      <StatusBadge status={status} />

      <div className="flex items-center gap-2 text-[10px] uppercase tracking-[0.18em] text-ink/60">
        <token.Icon size={12} strokeWidth={1.6} aria-hidden />
        <span>{token.label}</span>
      </div>

      {children}
    </div>
  );
}

function StatusBadge({ status }: { status: StatusKind }) {
  if (status === "idea") return null;
  const label = STATUS_TOKENS[status].label;
  const glyph =
    status === "approved"
      ? "✓"
      : status === "booked"
      ? "🔒"
      : status === "confirmed"
      ? "✓✓"
      : status === "discarded"
      ? "—"
      : "·";
  return (
    <span
      className="absolute bottom-1.5 right-2 inline-flex items-center gap-1 text-[9px] uppercase tracking-[0.2em] text-ink/45"
      aria-label={`Status: ${label}`}
    >
      <span aria-hidden>{glyph}</span>
      <span>{label}</span>
    </span>
  );
}

export function Title({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <h3 className={`mt-1.5 font-serif text-[17px] leading-snug text-ink ${className}`}>
      {children}
    </h3>
  );
}

export function Sub({ children }: { children: ReactNode }) {
  return <p className="mt-0.5 text-[11px] text-ink/65">{children}</p>;
}

export function Chip({
  children,
  tint,
  outlined = false,
}: {
  children: ReactNode;
  tint: string;
  outlined?: boolean;
}) {
  return (
    <span
      className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] text-ink/80"
      style={
        outlined
          ? { boxShadow: `inset 0 0 0 1px ${tint}`, color: "#0a0a0a" }
          : { backgroundColor: tint }
      }
    >
      {children}
    </span>
  );
}
