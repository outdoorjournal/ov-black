"use client";

// Glance card that adapts a NodeResponse to the new card-design tokens
// (CardShell + TYPE_TOKENS) from /prototype/cards. Each node-type renders a
// type-specific body — its "signature detail" per the Cards_Style_Guide —
// while sharing the same shell, paper substrate, status badge, and
// noise-textured background.

import { ChevronRight } from "lucide-react";

import {
  CardShell,
  Chip,
  CompactBody,
  Sub,
  Title,
} from "../../shared/cards/CardShell";
import {
  TYPE_TOKENS,
  type CardKind,
  type StatusKind,
} from "../../shared/cards/tokens";

import {
  formatClock,
  formatDuration,
  offsetHoursOr,
} from "../../model/horizontalTime";
import type { HorizontalNodeMeta, NodeResponse } from "../../model/horizontalTypes";
import { getHMeta } from "../../model/horizontalTypes";

interface NodeCardProps {
  node: NodeResponse;
  tzOffsetHours: number;
  onClick?: () => void;
  flash?: boolean;
  // When the parent layout is below the compact zoom breakpoint, render
  // the strip variant (180px-wide, single-line) instead of the glance card.
  compact?: boolean;
  // Count of `note` nodes attached to this one (0014). When > 0 the card shows
  // a small badge; the notes themselves are read in the expanded detail sheet.
  attachedNoteCount?: number;
}

// The node graph collapses every ground transport leg into the single `transit`
// type, but the new card design has subway / train / drive / walk / boat. We
// infer from the mode/title — good enough for fixture data and lets each
// transit leg render with the right token color and icon.
export function inferCardKind(node: NodeResponse): CardKind {
  const meta = getHMeta(node);
  switch (node.type) {
    case "flight":
      return "flight";
    case "hotel":
      return "hotel";
    case "experience":
      return "experience";
    case "meal":
      return "meal";
    case "free_time":
      return "free_time";
    case "note":
      return "note";
    case "destination":
      return "destination";
    case "transit": {
      const txt = `${node.title} ${meta.mode ?? ""}`.toLowerCase();
      if (/ferry|boat|water/.test(txt)) return "boat";
      if (/shinkansen|jr|train|kintetsu|hiroden|tram|line/.test(txt))
        return "train";
      if (/metro|subway|tokyo metro|sanchome|marunouchi|ginza/.test(txt))
        return "subway";
      if (/taxi|car|drive|bus|highway/.test(txt)) return "drive";
      if (/walk|stroll|on foot/.test(txt)) return "walk";
      return "subway";
    }
    default:
      return "experience";
  }
}

function statusToKind(status: NodeResponse["status"]): StatusKind {
  switch (status) {
    case "idea":
    case "proposed":
    case "approved":
    case "booked":
    case "confirmed":
    case "discarded":
      return status;
    default:
      return "proposed";
  }
}

export function NodeCard({
  node,
  tzOffsetHours,
  onClick,
  flash,
  compact = false,
  attachedNoteCount = 0,
}: NodeCardProps) {
  const kind = inferCardKind(node);
  const status = statusToKind(node.status);

  // Make the whole shell a button so cards click-through to a detail sheet
  // and we keep the keyboard semantics the cards prototype already gives.
  const wrapperClass = [
    "relative block w-full text-left",
    flash ? "ring-2 ring-amber-400/70 rounded-lg" : "",
    "transition-shadow",
  ].join(" ");

  const width = compact ? "compact" : "glance";
  const meta = getHMeta(node);
  const start = meta.start_time
    ? formatClock(meta.start_time, offsetHoursOr(meta.start_time, tzOffsetHours))
    : null;
  const dur =
    typeof meta.duration_minutes === "number"
      ? formatDuration(meta.duration_minutes)
      : null;

  return (
    <button type="button" onClick={onClick} className={wrapperClass}>
      <CardShell
        kind={kind}
        status={status}
        width={width}
        lockReason={node.lock_reason ?? null}
        lockLabel={node.type}
      >
        {compact ? (
          <CompactBody
            kind={kind}
            title={node.title}
            time={start}
            duration={dur}
          />
        ) : (
          <CardBody node={node} kind={kind} tzOffsetHours={tzOffsetHours} />
        )}
      </CardShell>
      {attachedNoteCount > 0 ? (
        <span
          data-testid="attached-note-badge"
          aria-label={`${attachedNoteCount} note${attachedNoteCount === 1 ? "" : "s"}`}
          className="pointer-events-none absolute -right-1.5 -top-1.5 z-10 flex h-5 min-w-5 items-center justify-center rounded-full border border-amber-900/25 bg-[#fbf1c7] px-1 font-sans text-[10px] font-semibold leading-none text-amber-900 shadow-sm"
        >
          ✎ {attachedNoteCount}
        </span>
      ) : null}
    </button>
  );
}

function CardBody({
  node,
  kind,
  tzOffsetHours,
}: {
  node: NodeResponse;
  kind: CardKind;
  tzOffsetHours: number;
}) {
  const meta = getHMeta(node);
  const start = meta.start_time
    ? formatClock(meta.start_time, offsetHoursOr(meta.start_time, tzOffsetHours))
    : null;
  const dur =
    typeof meta.duration_minutes === "number"
      ? formatDuration(meta.duration_minutes)
      : null;

  switch (kind) {
    case "flight":
      return (
        <FlightBody
          node={node}
          meta={meta}
          start={start}
          dur={dur}
          tzOffsetHours={tzOffsetHours}
        />
      );
    case "subway":
    case "train":
    case "boat":
    case "drive":
    case "walk":
      return (
        <TransitBody
          node={node}
          meta={meta}
          start={start}
          dur={dur}
          kind={kind}
        />
      );
    case "hotel":
      return <HotelBody node={node} meta={meta} kind={kind} />;
    case "experience":
      return (
        <ExperienceBody node={node} meta={meta} start={start} dur={dur} />
      );
    case "meal":
      return <MealBody node={node} meta={meta} start={start} dur={dur} />;
    case "free_time":
      return <FreeTimeBody node={node} meta={meta} start={start} dur={dur} />;
    case "note":
      return <NoteBody node={node} meta={meta} />;
    default:
      return <GenericBody node={node} meta={meta} start={start} dur={dur} />;
  }
}

// Strip a trailing " (IATA)" parenthetical from an airport label so the city
// reads cleanly under its code.
function cityOnly(label: string | undefined): string | null {
  if (!label) return null;
  return label.replace(/\s*\([^)]*\)\s*$/, "").trim() || null;
}

// "premium_economy" → "Premium economy"; "business" → "Business".
function cabinLabel(cabin: string | undefined): string | null {
  if (!cabin) return null;
  const words = cabin.replace(/_/g, " ").trim();
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : null;
}

function FlightBody({
  node,
  meta,
  start,
  dur,
  tzOffsetHours,
}: {
  node: NodeResponse;
  meta: HorizontalNodeMeta;
  start: string | null;
  dur: string | null;
  tzOffsetHours: number;
}) {
  const t = TYPE_TOKENS.flight;
  const from = meta.iata_from ?? "—";
  const to = meta.iata_to ?? "—";
  const fromCity = cityOnly(meta.from_location?.label);
  const toCity = cityOnly(meta.to_location?.label);
  // Prefer the flight's own depart/arrive wall-clock; fall back to the node's
  // scheduled start. Each end reads its OWN offset (a leg crosses zones).
  const depart = meta.depart_at
    ? formatClock(meta.depart_at, offsetHoursOr(meta.depart_at, tzOffsetHours))
    : start;
  const arrive = meta.arrive_at
    ? formatClock(meta.arrive_at, offsetHoursOr(meta.arrive_at, tzOffsetHours))
    : null;
  const cabin = cabinLabel(meta.cabin);

  return (
    <>
      <Title>{node.title}</Title>

      {/* Route — IATA codes anchored left/right with the great-circle arc and
          city names beneath, reading like a boarding pass. */}
      <div className="mt-2.5 flex items-start justify-between gap-2">
        <div className="flex min-w-0 flex-col">
          <span className="font-mono text-[15px] leading-none tracking-[0.18em] text-ink">
            {from}
          </span>
          {fromCity ? (
            <span className="mt-1 max-w-[88px] truncate text-[10px] text-ink/55">
              {fromCity}
            </span>
          ) : null}
        </div>
        <FlightArc accent={t.accent} />
        <div className="flex min-w-0 flex-col items-end">
          <span className="font-mono text-[15px] leading-none tracking-[0.18em] text-ink">
            {to}
          </span>
          {toCity ? (
            <span className="mt-1 max-w-[88px] truncate text-right text-[10px] text-ink/55">
              {toCity}
            </span>
          ) : null}
        </div>
      </div>

      {/* Depart → duration → arrive, the timing strip. */}
      {depart || arrive ? (
        <div className="mt-2.5 flex items-center justify-between font-mono text-[11px] text-ink/75">
          <span>{depart ?? "—"}</span>
          {dur ? (
            <span className="text-[10px] tracking-wide text-ink/40">{dur}</span>
          ) : null}
          <span>{arrive ?? "—"}</span>
        </div>
      ) : null}

      {/* Flight number + cabin/seat — the operating detail. */}
      <div className="mt-2 flex items-center justify-between gap-2">
        <Sub>{meta.flight_code ?? "Direct"}</Sub>
        <div className="flex items-center gap-1.5">
          {cabin ? <Chip tint={t.tint}>{cabin}</Chip> : null}
          {meta.seat ? (
            <span className="font-mono text-[10px] text-ink/65">{meta.seat}</span>
          ) : null}
        </div>
      </div>
    </>
  );
}

function FlightArc({ accent }: { accent: string }) {
  return (
    <svg width="56" height="14" viewBox="0 0 56 14" aria-hidden>
      <path
        d="M 2 9 C 14 -2, 30 18, 54 9"
        stroke={accent}
        strokeWidth="1"
        fill="none"
        strokeDasharray="2 2"
        opacity="0.7"
      />
      <circle cx="2" cy="9" r="1.5" fill={accent} />
      <circle cx="54" cy="9" r="1.5" fill={accent} />
    </svg>
  );
}

function TransitBody({
  node,
  meta,
  start,
  dur,
  kind,
}: {
  node: NodeResponse;
  meta: HorizontalNodeMeta;
  start: string | null;
  dur: string | null;
  kind: CardKind;
}) {
  const t = TYPE_TOKENS[kind];
  const fromLabel = meta.from_location?.label;
  const toLabel = meta.to_location?.label ?? meta.location?.label;
  return (
    <>
      <Title>{node.title}</Title>
      {meta.mode ? <Sub>{meta.mode}</Sub> : null}
      {fromLabel || toLabel ? (
        <div className="mt-2 flex items-center gap-1 text-[11px] text-ink/75">
          <span className="truncate">{fromLabel ?? "—"}</span>
          <ChevronRight size={12} className="shrink-0 text-ink/45" aria-hidden />
          <span className="truncate">{toLabel ?? "—"}</span>
        </div>
      ) : null}
      <div className="mt-1.5 flex items-center justify-between text-[11px] text-ink/65">
        <span>{start ?? ""}</span>
        {dur ? (
          <Chip tint={t.tint} outlined>
            {dur}
          </Chip>
        ) : null}
      </div>
    </>
  );
}

function HotelBody({
  node,
  meta,
  kind,
}: {
  node: NodeResponse;
  meta: HorizontalNodeMeta;
  kind: CardKind;
}) {
  const t = TYPE_TOKENS[kind];
  const snap = meta.snapshot;
  const cover = snap?.cover_image ?? meta.ambient_image;
  const location = snap?.location ?? meta.location?.label;
  return (
    <div className="mt-1.5 flex gap-3">
      <ImageStub
        {...(cover ? { src: cover } : {})}
        fallbackTint="#5e6e5d"
        small
      />
      <div className="min-w-0 flex-1">
        <h3 className="truncate font-serif text-[15px] leading-snug text-ink">
          {snap?.title ?? node.title}
        </h3>
        {location ? <Sub>{location}</Sub> : null}
        {snap?.activities && snap.activities.length > 0 ? (
          <div className="mt-1.5 flex flex-wrap gap-1">
            {snap.activities.slice(0, 2).map((a) => (
              <Chip key={a} tint={t.tint}>
                {a}
              </Chip>
            ))}
          </div>
        ) : null}
      </div>
    </div>
  );
}

function ExperienceBody({
  node,
  meta,
  start,
  dur,
}: {
  node: NodeResponse;
  meta: HorizontalNodeMeta;
  start: string | null;
  dur: string | null;
}) {
  const t = TYPE_TOKENS.experience;
  const snap = meta.snapshot;
  const cover = snap?.cover_image ?? meta.ambient_image;
  return (
    <>
      <ImageStub {...(cover ? { src: cover } : {})} fallbackTint="#b58a3a" />
      <Title>{snap?.title ?? node.title}</Title>
      <Sub>
        {meta.location?.label ?? snap?.location ?? "—"}
        {dur ? ` · ${dur}` : ""}
      </Sub>
      {snap?.activities && snap.activities.length > 0 ? (
        <div className="mt-2 flex flex-wrap gap-1">
          {snap.activities.slice(0, 3).map((a) => (
            <Chip key={a} tint={t.tint}>
              {a}
            </Chip>
          ))}
        </div>
      ) : null}
      {start ? (
        <div className="mt-2 flex items-center justify-between text-[11px] text-ink/65">
          <span>Starts {start}</span>
        </div>
      ) : null}
    </>
  );
}

function MealBody({
  node,
  meta,
  start,
  dur,
}: {
  node: NodeResponse;
  meta: HorizontalNodeMeta;
  start: string | null;
  dur: string | null;
}) {
  const t = TYPE_TOKENS.meal;
  return (
    <>
      <Title>{node.title}</Title>
      <Sub>
        {meta.location?.label ?? "—"}
        {start ? ` · ${start}` : ""}
        {dur ? ` · ${dur}` : ""}
      </Sub>
      {meta.time_of_day ? (
        <div className="mt-2 flex flex-wrap gap-1">
          <Chip tint={t.tint}>{capitalize(meta.time_of_day)}</Chip>
          {meta.snapshot?.price ? (
            <Chip tint={t.tint}>{meta.snapshot.price}</Chip>
          ) : null}
        </div>
      ) : null}
    </>
  );
}

function FreeTimeBody({
  node,
  meta,
  start,
  dur,
}: {
  node: NodeResponse;
  meta: HorizontalNodeMeta;
  start: string | null;
  dur: string | null;
}) {
  return (
    <>
      <div className="mt-1 rounded-md border border-dashed border-ink/20 px-2.5 py-2">
        <h3 className="font-serif text-[15px] italic leading-snug text-ink/85">
          {node.title}
        </h3>
        <Sub>
          {start ?? "open"}
          {dur ? ` · ${dur}` : ""}
        </Sub>
      </div>
      {meta.body ? (
        <p className="mt-2 line-clamp-3 text-[11px] leading-relaxed text-ink/75">
          {meta.body}
        </p>
      ) : null}
    </>
  );
}

function NoteBody({
  node,
  meta,
}: {
  node: NodeResponse;
  meta: HorizontalNodeMeta;
}) {
  return (
    <>
      <Title>{node.title}</Title>
      {meta.body ? (
        <p className="mt-1.5 line-clamp-4 text-[11px] leading-relaxed text-ink/80">
          {meta.body}
        </p>
      ) : null}
    </>
  );
}

function GenericBody({
  node,
  meta,
  start,
  dur,
}: {
  node: NodeResponse;
  meta: HorizontalNodeMeta;
  start: string | null;
  dur: string | null;
}) {
  return (
    <>
      <Title>{node.title}</Title>
      {meta.location?.label ? <Sub>{meta.location.label}</Sub> : null}
      {start || dur ? (
        <div className="mt-1 text-[11px] text-ink/65">
          {start ?? ""}
          {dur ? ` · ${dur}` : ""}
        </div>
      ) : null}
    </>
  );
}

function ImageStub({
  src,
  fallbackTint,
  small = false,
}: {
  src?: string;
  fallbackTint: string;
  small?: boolean;
}) {
  // Use next/image without configuring remote loaders is overkill for fixtures;
  // a plain <img> degrades cleanly when /japan/* assets are missing. The
  // gradient fallback keeps the card readable in either case.
  const className = small
    ? "h-14 w-14 shrink-0"
    : "mt-2 h-24 w-full";
  return (
    <div
      className={`relative overflow-hidden rounded-md border border-ink/10 ${className}`}
      role="img"
      aria-label="Card image"
      style={{
        backgroundImage: src
          ? `url(${JSON.stringify(src)})`
          : `linear-gradient(135deg, ${fallbackTint} 0%, ${mix(fallbackTint, "#f7f4ee", 0.4)} 60%, #f7f4ee 100%)`,
        backgroundSize: "cover",
        backgroundPosition: "center",
      }}
    >
      {!src ? (
        <span className="absolute bottom-1 right-1.5 text-[8px] uppercase tracking-[0.18em] text-paper/85">
          photo
        </span>
      ) : null}
    </div>
  );
}

function capitalize(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

// Cheap hex mix for image-fallback gradients. Inputs assumed in #rrggbb form.
function mix(a: string, b: string, t: number): string {
  const pa = parseHex(a);
  const pb = parseHex(b);
  const r = Math.round(pa[0] + (pb[0] - pa[0]) * t);
  const g = Math.round(pa[1] + (pb[1] - pa[1]) * t);
  const bl = Math.round(pa[2] + (pb[2] - pa[2]) * t);
  return `rgb(${r}, ${g}, ${bl})`;
}

function parseHex(hex: string): [number, number, number] {
  const v = hex.replace("#", "");
  return [
    parseInt(v.slice(0, 2), 16) || 0,
    parseInt(v.slice(2, 4), 16) || 0,
    parseInt(v.slice(4, 6), 16) || 0,
  ];
}

