"use client";

// The Journal's spine furniture: the node circle (a miniature of the card's
// identity — type accent + icon from the shared tokens, status worn as the
// ring) and the night segment (the spine itself darkening between days, per
// the `night_bar` treatment). The continuous line is drawn by the section
// container in JournalView; these pieces sit ON it.

import {
  BRAND_RGB,
  STATUS_TOKENS,
  TYPE_TOKENS,
  type CardKind,
  type StatusKind,
} from "../../shared/cards/tokens";

/** Width of the spine gutter column — JournalView's grid + line share it. */
export const SPINE_COL_PX = 44;

// Status → the circle's ring, mirroring the card-status vocabulary without
// relying on color alone (each non-pending status also wears its glyph badge):
//   pending    soft hairline ring
//   approved   solid accent ring + ✓ badge
//   booked     solid ink ring + ⚿ badge
//   confirmed  double ring + ◉ badge
//   discarded  grayscale, dashed feel via opacity
function ringShadow(status: StatusKind, accent: string, active: boolean): string {
  const activeGlow = active ? `, 0 0 0 5px rgba(${BRAND_RGB}, 0.28)` : "";
  switch (status) {
    case "approved":
      return `0 0 0 2px ${accent}${activeGlow}`;
    case "booked":
      return `0 0 0 2px #0a0a0a${activeGlow}`;
    case "confirmed":
      return `0 0 0 2px #0a0a0a, 0 0 0 4px rgba(10,10,10,0.35)${activeGlow}`;
    default:
      return `0 0 0 1px rgba(10,10,10,0.18)${activeGlow}`;
  }
}

const STATUS_GLYPH: Partial<Record<StatusKind, string>> = {
  approved: "✓",
  booked: "⚿",
  confirmed: "◉",
};

export function SpineCircle({
  kind,
  status,
  active,
}: {
  kind: CardKind;
  status: StatusKind;
  active: boolean;
}) {
  const token = TYPE_TOKENS[kind];
  return (
    <span
      role="img"
      aria-label={`${token.label} — ${STATUS_TOKENS[status].label}`}
      data-testid="journal-spine-circle"
      data-kind={kind}
      data-status={status}
      className={[
        "relative z-10 flex h-7 w-7 items-center justify-center rounded-full text-paper",
        "transition-transform duration-200",
        active ? "scale-110" : "",
        status === "discarded" ? "opacity-50 grayscale" : "",
      ].join(" ")}
      style={{
        backgroundColor: token.accent,
        boxShadow: ringShadow(status, token.accent, active),
      }}
    >
      <token.Icon size={13} strokeWidth={1.8} aria-hidden />
      {STATUS_GLYPH[status] ? (
        <span
          aria-hidden
          className="absolute -bottom-1 -right-1 flex h-3.5 w-3.5 items-center justify-center rounded-full border border-ink/20 bg-paper text-[8px] leading-none text-ink"
        >
          {STATUS_GLYPH[status]}
        </span>
      ) : null}
    </span>
  );
}

/** The small hollow circle a virtual (quiet) node sits on. */
export function QuietCircle() {
  return (
    <span
      aria-hidden
      className="relative z-10 block h-3 w-3 rounded-full border border-ink/30 bg-paper"
    />
  );
}

/**
 * The night treatment: the spine darkens between days — a slim moonlit bar in
 * the gutter with a whispered caption beside it. When the graph models the
 * night (a `night_bar` node, usually the hotel stay) its title names the stop.
 */
export function NightSegment({ title }: { title?: string | undefined }) {
  return (
    <div
      data-testid="journal-night"
      className="grid grid-cols-[var(--spine-col)_minmax(0,1fr)] items-center gap-x-4"
      style={{ "--spine-col": `${SPINE_COL_PX}px` } as React.CSSProperties}
    >
      <div className="flex justify-center py-1">
        <span
          aria-hidden
          className="relative z-10 flex h-16 w-2.5 items-end justify-center rounded-full pb-1"
          style={{
            backgroundImage:
              "linear-gradient(180deg, rgba(74,56,98,0.5), rgba(20,23,61,0.75))",
          }}
        >
          <span className="text-[9px] leading-none text-paper/90">☾</span>
        </span>
      </div>
      <p className="font-serif text-[12px] italic text-ink/40">
        {title ? `Night · ${title}` : "Night"}
      </p>
    </div>
  );
}
