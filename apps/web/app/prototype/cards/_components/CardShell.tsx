"use client";

import type { ReactNode } from "react";

import {
  NOISE_BG,
  STATUS_TOKENS,
  TYPE_TOKENS,
  type CardKind,
  type StatusKind,
} from "../_lib/tokens";

export type CardWidth = "compact" | "glance" | "zoom";

interface CardShellProps {
  kind: CardKind;
  status?: StatusKind;
  width?: CardWidth;
  children: ReactNode;
  noteOverride?: boolean;
  // Surfaced in the Booked / Confirmed footer band as the operator's
  // confirmation string. Omit and the band still renders with just the
  // status label.
  serial?: string;
  // Surfaced in the Approved / Confirmed footer band as a short date stamp.
  statusDate?: string;
}

interface SubstrateStyle {
  bg: string;
  border: string;
  shadow: string;
}

// Status escalates the substrate itself — paper darkens, border thickens,
// shadow deepens, Confirmed gains an inner ring to read as heavier stock.
// Mirrors HYBRID_CFG in StatusAlternatives.tsx (the chosen Alt C+D direction).
const SUBSTRATE_BY_STATUS: Record<StatusKind, SubstrateStyle> = {
  idea: {
    bg: "#f7f4ee",
    border: "1px dashed rgba(10,10,10,0.18)",
    shadow: "0 1px 0 rgba(0,0,0,0.04)",
  },
  proposed: {
    bg: "#f7f4ee",
    border: "1px solid rgba(10,10,10,0.10)",
    shadow:
      "0 1px 0 rgba(0,0,0,0.04), 0 8px 24px -12px rgba(0,0,0,0.25), inset 0 1px 0 rgba(255,255,255,0.6)",
  },
  approved: {
    bg: "#f5f1e7",
    border: "1px solid rgba(10,10,10,0.14)",
    shadow:
      "0 1px 0 rgba(0,0,0,0.05), 0 10px 26px -12px rgba(0,0,0,0.28), inset 0 1px 0 rgba(255,255,255,0.55)",
  },
  booked: {
    bg: "#ede6d6",
    border: "1.5px solid rgba(10,10,10,0.20)",
    shadow:
      "0 2px 0 rgba(0,0,0,0.06), 0 14px 32px -10px rgba(0,0,0,0.35), inset 0 1px 0 rgba(255,255,255,0.5)",
  },
  confirmed: {
    bg: "#e6dcc4",
    border: "2px solid rgba(10,10,10,0.32)",
    shadow:
      "0 0 0 1px rgba(10,10,10,0.10), 0 3px 0 rgba(0,0,0,0.08), 0 22px 44px -12px rgba(0,0,0,0.45), inset 0 1px 0 rgba(255,255,255,0.55), inset 0 0 0 3px rgba(247,244,238,0.7), inset 0 0 0 4px rgba(10,10,10,0.10)",
  },
  discarded: {
    bg: "#f7f4ee",
    border: "1px solid rgba(10,10,10,0.10)",
    shadow: "0 1px 0 rgba(0,0,0,0.04)",
  },
};

export function CardShell({
  kind,
  status = "proposed",
  width = "glance",
  children,
  noteOverride,
  serial,
  statusDate,
}: CardShellProps) {
  const token = TYPE_TOKENS[kind];
  const isNote = noteOverride ?? kind === "note";

  const substrate = SUBSTRATE_BY_STATUS[status];

  // Notes keep their yellow paper substrate regardless of status — they are
  // commentary, not booked inventory, so the substrate-weight cue would
  // mis-signal a lifecycle they don't have.
  const bg = isNote ? "#fbf1c7" : substrate.bg;
  const border = isNote
    ? "1px solid rgba(180,140,30,0.22)"
    : substrate.border;

  const style = {
    backgroundImage: `${NOISE_BG}, linear-gradient(180deg, rgba(255,255,255,0.35) 0%, rgba(255,255,255,0) 40%)`,
    backgroundColor: bg,
    border,
    boxShadow: substrate.shadow,
  };

  // Padding lives on the body wrapper, not the shell, so the footer band can
  // run edge-to-edge. Compact matches glance's 260px footprint — the variant
  // collapses *vertically*, not horizontally; it's triggered by low zoom
  // density on the timeline, where horizontal room isn't the constraint.
  const widthClass =
    width === "compact" || width === "glance"
      ? "w-[260px]"
      : "w-full max-w-[640px]";
  const wrapClass = [
    "relative rounded-lg overflow-hidden font-sans text-ink text-left",
    widthClass,
    status === "idea" ? "opacity-80" : "",
    status === "discarded" ? "opacity-50 grayscale" : "",
  ].join(" ");

  const bodyClass =
    width === "compact"
      ? "px-2.5 py-1.5"
      : width === "glance"
        ? "p-3 pb-0"
        : "p-5 pb-0";

  // Compact mode is a strip — no full type-label header, no status footer.
  // Compact shows the type icon inline with the body and relies on the
  // corner stamp + substrate weight to carry status.
  const isCompact = width === "compact";

  return (
    <div
      role="group"
      aria-label={`${token.label} card, ${STATUS_TOKENS[status].label}`}
      className={wrapClass}
      style={style}
    >
      {status !== "idea" && status !== "discarded" ? (
        <span
          aria-hidden
          className={`pointer-events-none absolute -top-0.5 ${
            isCompact ? "left-2 h-2 w-8" : "-top-1 left-3 h-3 w-12"
          } rotate-[-3deg] opacity-80`}
          style={{
            backgroundColor: token.accent,
            boxShadow: "0 1px 2px rgba(0,0,0,0.2)",
            mixBlendMode: "multiply",
          }}
        />
      ) : null}

      <div className={bodyClass}>
        {isCompact ? null : (
          <div className="flex items-center gap-2 text-[10px] uppercase tracking-[0.18em] text-ink/60">
            <token.Icon size={12} strokeWidth={1.6} aria-hidden />
            <span>{token.label}</span>
          </div>
        )}
        {children}
      </div>

      {isCompact ? null : (
        <StatusFooter status={status} serial={serial} statusDate={statusDate} />
      )}
    </div>
  );
}

function StatusFooter({
  status,
  serial,
  statusDate,
}: {
  status: StatusKind;
  serial: string | undefined;
  statusDate: string | undefined;
}) {
  if (status === "approved") {
    return (
      <div
        className="mt-3 flex items-center justify-between border-t border-ink/15 px-3 py-1.5"
        aria-label="Status: approved"
      >
        <span className="inline-flex items-center gap-1.5 text-[10px] uppercase tracking-[0.18em] text-ink/70">
          <span aria-hidden>✓</span> Approved
        </span>
        {statusDate ? (
          <span className="font-mono text-[10px] text-ink/45">{statusDate}</span>
        ) : null}
      </div>
    );
  }
  if (status === "booked") {
    return (
      <div
        className="mt-3 flex items-center justify-between px-3 py-2"
        style={{ backgroundColor: "rgba(10,10,10,0.08)" }}
        aria-label="Status: booked"
      >
        <span className="inline-flex items-center gap-1.5 text-[10px] uppercase tracking-[0.2em] text-ink/85">
          <span aria-hidden>⚿</span> Booked
        </span>
        {serial ? (
          <span className="font-mono text-[10px] text-ink/65">{serial}</span>
        ) : null}
      </div>
    );
  }
  if (status === "confirmed") {
    return (
      <div
        className="mt-3 flex flex-col px-3 py-2.5"
        style={{ backgroundColor: "#0a0a0a", color: "#f7f4ee" }}
        aria-label="Status: confirmed"
      >
        <div className="flex items-center justify-between">
          <span className="inline-flex items-center gap-2 text-[10px] uppercase tracking-[0.32em]">
            <span aria-hidden>◉</span> Confirmed
          </span>
          {statusDate ? (
            <span className="font-mono text-[9px] tracking-wider text-paper/55">
              {statusDate}
            </span>
          ) : null}
        </div>
        {serial ? (
          <span className="mt-0.5 font-mono text-[10px] tracking-wide text-paper/80">
            {serial}
          </span>
        ) : null}
      </div>
    );
  }
  // idea / proposed / discarded carry their state via the substrate alone.
  return null;
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

// Compact-card content row. Type icon + tight title + optional time and
// duration. Designed for ~180px shells where every pixel of vertical and
// horizontal space matters; longer titles truncate to one line.
export function CompactBody({
  kind,
  title,
  time,
  duration,
  trailing,
}: {
  kind: CardKind;
  title: ReactNode;
  time?: string | null;
  duration?: string | null;
  // Optional inline trailing slot (e.g. flight "DTW → HND" arc). Replaces
  // the default time/duration row when provided.
  trailing?: ReactNode;
}) {
  const token = TYPE_TOKENS[kind];
  return (
    <div className="flex items-start gap-2">
      <token.Icon
        size={14}
        strokeWidth={1.6}
        aria-hidden
        className="mt-0.5 shrink-0 text-ink/70"
      />
      <div className="min-w-0 flex-1">
        <p className="truncate font-serif text-[13px] leading-snug text-ink">
          {title}
        </p>
        {trailing ?? (
          <p className="mt-0.5 flex items-center gap-1.5 truncate font-mono text-[10px] text-ink/60">
            {time ? <span>{time}</span> : null}
            {time && duration ? <span aria-hidden>·</span> : null}
            {duration ? <span>{duration}</span> : null}
          </p>
        )}
      </div>
    </div>
  );
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
