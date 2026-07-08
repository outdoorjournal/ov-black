"use client";

import type { CSSProperties, ReactNode } from "react";
import { tv } from "tailwind-variants";

import {
  NOISE_BG,
  STATUS_TOKENS,
  TYPE_TOKENS,
  lockCopy,
  type CardKind,
  type StatusKind,
} from "./tokens";

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
  // G1: the server-computed lock reason (e.g. "status_locked") for a firmed
  // node. When set, the booked/confirmed footer reads as a lock badge with a
  // crafted "an advisor would need to move it" tooltip + accessible label.
  lockReason?: string | null;
  // A friendly noun for the locked item (the node type), used in the copy.
  lockLabel?: string;
  // A form-factor slot rendered at the very bottom of the card, below the
  // status footer band. The chat proposal card uses it for its Must Do /
  // Thumbs Up / Not This Time action row; the timeline/collection cards omit it.
  actions?: ReactNode;
  // A small right-aligned slot in the type-label header row (glance/zoom only).
  // ADV-15 uses it for the advisor's per-card billing chip.
  headerExtra?: ReactNode;
}

// The card substrate as a tailwind-variants recipe. Structure only — `width`
// sets the footprint + body padding; `status` carries the idea/discarded
// opacity cues. The status-escalating *material* (paper colour, border weight,
// shadow depth) lives in globals.css keyed on [data-status] (the .card-substrate
// layer), so every surface that renders a CardShell gets the identical paper.
const cardShell = tv({
  slots: {
    root: "card-substrate relative overflow-hidden rounded-lg text-left font-sans text-ink",
    body: "",
  },
  variants: {
    width: {
      // Compact matches glance's 260px footprint — the variant collapses
      // vertically, not horizontally (low-zoom density on the timeline).
      // Bottom padding is applied by the component (see `bottomPad`) so a card
      // with no status-footer band still closes with even inset all around.
      compact: { root: "w-[260px]", body: "px-2.5 py-1.5" },
      glance: { root: "w-[260px]", body: "px-3 pt-3" },
      zoom: { root: "w-full max-w-[640px]", body: "px-5 pt-5" },
    },
    status: {
      idea: { root: "opacity-80" },
      proposed: {},
      approved: {},
      booked: {},
      confirmed: {},
      discarded: { root: "opacity-50 grayscale" },
    },
  },
  defaultVariants: { width: "glance", status: "proposed" },
});

// Noise texture + a soft top sheen — a static image identical on every card, so
// it stays an inline background-image (not a per-status CSS var). The status
// colour/border/shadow underneath come from the .card-substrate CSS layer.
const SUBSTRATE_IMAGE = `${NOISE_BG}, linear-gradient(180deg, rgba(255,255,255,0.35) 0%, rgba(255,255,255,0) 40%)`;

export function CardShell({
  kind,
  status = "proposed",
  width = "glance",
  children,
  noteOverride,
  serial,
  statusDate,
  lockReason,
  lockLabel,
  actions,
  headerExtra,
}: CardShellProps) {
  const token = TYPE_TOKENS[kind];
  const isNote = noteOverride ?? kind === "note";

  // Compact mode is a strip — no full type-label header, no status footer.
  // Compact shows the type icon inline with the body and relies on the corner
  // stamp + substrate weight to carry status.
  const isCompact = width === "compact";

  const { root, body } = cardShell({ width, status });

  // A status-footer band (approved/booked/confirmed) or an actions row already
  // caps the card's bottom edge — the band sits flush and carries its own mt-3
  // gap. When neither is present (an un-firmed proposed/idea/discarded card) the
  // body closes itself with bottom padding that mirrors its top/sides, so an
  // image-led card no longer bleeds flush against the bottom edge. Longhand
  // px/pt in the recipe keeps this a clean additive property (no p-3 override).
  const hasFooter =
    !isCompact &&
    (status === "approved" || status === "booked" || status === "confirmed");
  const bottomPad =
    isCompact || hasFooter || actions != null
      ? ""
      : width === "zoom"
        ? "pb-5"
        : "pb-3";

  return (
    <div
      role="group"
      aria-label={`${token.label} card, ${STATUS_TOKENS[status].label}`}
      className={root()}
      // Drives the .card-substrate CSS layer (paper colour / border / shadow).
      // Notes override bg+border via [data-note] while keeping the status shadow.
      data-status={status}
      data-note={isNote ? "true" : undefined}
      style={{ backgroundImage: SUBSTRATE_IMAGE } as CSSProperties}
    >
      {status !== "idea" && status !== "discarded" ? (
        <span
          aria-hidden
          className={`pointer-events-none absolute -top-0.5 ${
            isCompact ? "left-2 h-2 w-8" : "-top-1 left-3 h-3 w-12"
          } -rotate-3 opacity-80`}
          style={{
            backgroundColor: token.accent,
            boxShadow: "0 1px 2px rgba(0,0,0,0.2)",
            mixBlendMode: "multiply",
          }}
        />
      ) : null}

      <div className={bottomPad ? `${body()} ${bottomPad}` : body()}>
        {isCompact ? null : (
          <div className="flex items-center gap-2 text-[10px] uppercase tracking-[0.18em] text-ink/60">
            <token.Icon size={12} strokeWidth={1.6} aria-hidden />
            <span>{token.label}</span>
            {headerExtra ? <span className="ml-auto">{headerExtra}</span> : null}
          </div>
        )}
        {children}
      </div>

      {isCompact ? null : (
        <StatusFooter
          status={status}
          serial={serial}
          statusDate={statusDate}
          lockReason={lockReason}
          lockLabel={lockLabel}
        />
      )}

      {actions}
    </div>
  );
}

function StatusFooter({
  status,
  serial,
  statusDate,
  lockReason,
  lockLabel,
}: {
  status: StatusKind;
  serial: string | undefined;
  statusDate: string | undefined;
  lockReason: string | null | undefined;
  lockLabel: string | undefined;
}) {
  // A booked/confirmed node is status-locked: the crafted copy explains why an
  // edit would be refused, surfaced as the footer's tooltip + accessible label.
  const lockMsg =
    lockReason && (status === "booked" || status === "confirmed")
      ? lockCopy(status, lockLabel ?? "item")
      : undefined;
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
        aria-label={lockMsg ?? "Status: booked"}
        title={lockMsg}
        data-lock-reason={lockReason ?? undefined}
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
        aria-label={lockMsg ?? "Status: confirmed"}
        title={lockMsg}
        data-lock-reason={lockReason ?? undefined}
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
