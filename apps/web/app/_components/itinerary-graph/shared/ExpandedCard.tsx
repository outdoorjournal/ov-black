"use client";

import { motion } from "framer-motion";
import type { ReactNode } from "react";

import {
  MOOD_ACCENTS,
  type MoodId,
  type NodeResponse,
  type NodeStatus,
  type NodeType,
  STATUS_LABELS,
  getMeta,
} from "../model/baseTypes";

const NOISE_URL =
  "url(\"data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='140' height='140'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='1' stitchTiles='stitch'/><feColorMatrix values='0 0 0 0 0.05 0 0 0 0 0.04 0 0 0 0 0.03 0 0 0 0.06 0'/></filter><rect width='140' height='140' filter='url(%23n)'/></svg>\")";

interface CardProps {
  node: NodeResponse;
  mood: MoodId;
  onClick?: () => void;
  isDragging?: boolean;
  flash?: boolean;
  ghost?: boolean;
  dim?: boolean;
  compact?: boolean;
}

export function Card({
  node,
  mood,
  onClick,
  isDragging = false,
  flash = false,
  ghost = false,
  dim = false,
  compact = false,
}: CardProps) {
  const accent = MOOD_ACCENTS[mood].accent;
  const tint = MOOD_ACCENTS[mood].tint;
  const statusClasses = statusShellClasses(node.status);

  const isNote = node.type === "note";
  const shellStyle = {
    backgroundImage: `${NOISE_URL}, linear-gradient(180deg, rgba(255,255,255,0.35) 0%, rgba(255,255,255,0) 40%)`,
    backgroundColor: isNote ? "#fbf1c7" : "#f7f4ee",
    borderColor: isNote
      ? "rgba(180, 140, 30, 0.22)"
      : "rgba(10, 10, 10, 0.10)",
    boxShadow: isDragging
      ? "0 1px 0 rgba(0,0,0,0.05), 0 24px 48px -14px rgba(0,0,0,0.35)"
      : "0 1px 0 rgba(0,0,0,0.04), 0 8px 24px -12px rgba(0,0,0,0.25), inset 0 1px 0 rgba(255,255,255,0.6)",
  };

  const motionProps = flash
    ? {
        animate: {
          boxShadow: [
            "0 1px 0 rgba(0,0,0,0.04), 0 8px 24px -12px rgba(0,0,0,0.25)",
            `0 0 0 3px ${tint}, 0 8px 24px -12px rgba(0,0,0,0.25)`,
            "0 1px 0 rgba(0,0,0,0.04), 0 8px 24px -12px rgba(0,0,0,0.25)",
          ],
        },
        transition: { duration: 1.2 },
      }
    : {};

  return (
    <motion.button
      type="button"
      onClick={onClick}
      className={[
        "relative w-full text-left rounded-lg border overflow-hidden",
        "font-sans",
        ghost ? "border-dashed" : "",
        dim ? "opacity-60" : "",
        compact ? "p-2.5" : "p-3",
        statusClasses,
      ].join(" ")}
      style={shellStyle}
      {...motionProps}
      whileHover={isDragging ? {} : { y: -1 }}
    >
      {node.status !== "idea" && node.status !== "discarded" ? (
        <span
          aria-hidden
          className="pointer-events-none absolute -top-1 left-3 h-3 w-12 rotate-[-3deg] opacity-70"
          style={{
            backgroundColor: accent,
            boxShadow: "0 1px 2px rgba(0,0,0,0.2)",
            mixBlendMode: "multiply",
          }}
        />
      ) : null}
      {node.type !== "note" && node.status === "approved" ? (
        <span className="absolute bottom-1.5 right-2 text-[9px] uppercase tracking-[0.2em] text-ink/40">
          Approved
        </span>
      ) : null}
      {node.type !== "note" && node.status === "proposed" ? (
        <span className="absolute bottom-1.5 right-2 text-[9px] uppercase tracking-[0.2em] text-ink/40">
          Proposed
        </span>
      ) : null}
      {node.type !== "note" && node.status === "discarded" ? (
        <span className="absolute bottom-1.5 right-2 text-[9px] uppercase tracking-[0.2em] text-ink/40">
          Dismissed
        </span>
      ) : null}

      <div className="flex items-center gap-2 text-[10px] uppercase tracking-[0.18em] text-ink/55">
        <TypeIcon type={node.type} />
        <span>{typeLabel(node.type)}</span>
        {node.parent_subgraph_id === null && typeof getMeta(node).nights === "number" ? (
          <span className="ml-auto text-ink/50">
            {getMeta(node).nights} night{getMeta(node).nights === 1 ? "" : "s"}
          </span>
        ) : null}
      </div>

      <CardFace node={node} mood={mood} compact={compact} />

      {ghost ? (
        <span
          className="pointer-events-none absolute inset-0 rounded-lg"
          style={{
            boxShadow: `0 0 0 1.5px ${accent}`,
            opacity: 0.6,
          }}
        />
      ) : null}

      <span className="sr-only">{STATUS_LABELS[node.status]}</span>
    </motion.button>
  );
}

function CardFace({
  node,
  mood,
  compact,
}: {
  node: NodeResponse;
  mood: MoodId;
  compact: boolean;
}) {
  switch (node.type) {
    case "flight":
      return <FlightFace node={node} />;
    case "hotel":
      return <HotelFace node={node} />;
    case "experience":
    case "destination":
      return <ExperienceFace node={node} mood={mood} compact={compact} />;
    case "meal":
      return <MealFace node={node} />;
    case "transit":
      return <TransitFace node={node} />;
    case "free_time":
      return <FreeTimeFace node={node} />;
    case "note":
      return <NoteFace node={node} />;
  }
}

function Title({ children }: { children: ReactNode }) {
  return (
    <h3 className="mt-1.5 font-serif text-[17px] leading-snug text-ink">
      {children}
    </h3>
  );
}

function Sub({ children }: { children: ReactNode }) {
  return <p className="mt-0.5 text-[11px] text-ink/60">{children}</p>;
}

function FlightFace({ node }: { node: NodeResponse }) {
  const meta = getMeta(node);
  return (
    <>
      <Title>{node.title}</Title>
      <div className="mt-2 flex items-center gap-2 font-mono text-[13px] tracking-widest text-ink/80">
        <span>{meta.iata_from ?? "— — —"}</span>
        <svg
          width="48"
          height="10"
          viewBox="0 0 48 10"
          className="text-ink/40"
          aria-hidden
        >
          <path
            d="M 2 5 C 12 -2, 24 12, 46 5"
            stroke="currentColor"
            strokeWidth="1"
            fill="none"
            strokeDasharray="2 2"
          />
        </svg>
        <span>{meta.iata_to ?? "— — —"}</span>
      </div>
      {meta.flight_code ? (
        <Sub>{meta.flight_code}</Sub>
      ) : (
        <Sub>{meta.snapshot?.price ?? "Private charter"}</Sub>
      )}
    </>
  );
}

function HotelFace({ node }: { node: NodeResponse }) {
  const meta = getMeta(node);
  const snap = meta.snapshot;
  return (
    <div className="mt-1.5 flex gap-3">
      {snap?.cover_image ? (
        <span
          className="h-14 w-14 shrink-0 rounded-md bg-ink/10"
          style={{
            backgroundImage: `url(${snap.cover_image})`,
            backgroundSize: "cover",
            backgroundPosition: "center",
          }}
          aria-hidden
        />
      ) : (
        <span className="h-14 w-14 shrink-0 rounded-md bg-ink/10" aria-hidden />
      )}
      <div className="min-w-0 flex-1">
        <h3 className="font-serif text-[16px] leading-snug text-ink truncate">
          {node.title}
        </h3>
        {snap?.location ? <Sub>{snap.location}</Sub> : null}
        {snap?.price ? (
          <p className="mt-1 text-[11px] text-ink/75">{snap.price}</p>
        ) : null}
      </div>
    </div>
  );
}

function ExperienceFace({
  node,
  mood,
  compact,
}: {
  node: NodeResponse;
  mood: MoodId;
  compact: boolean;
}) {
  const meta = getMeta(node);
  const snap = meta.snapshot;
  const tint = MOOD_ACCENTS[mood].tint;
  return (
    <>
      {snap?.cover_image && !compact ? (
        <span
          className="mt-2 block h-16 w-full rounded-md bg-ink/10"
          style={{
            backgroundImage: `url(${snap.cover_image})`,
            backgroundSize: "cover",
            backgroundPosition: "center",
          }}
          aria-hidden
        />
      ) : null}
      <Title>{node.title}</Title>
      {snap?.location ? <Sub>{snap.location}</Sub> : null}
      {snap?.activities && snap.activities.length > 0 ? (
        <div className="mt-1.5 flex flex-wrap gap-1">
          {snap.activities.slice(0, 3).map((a) => (
            <span
              key={a}
              className="rounded-full px-2 py-0.5 text-[10px] text-ink/75"
              style={{ backgroundColor: tint }}
            >
              {a}
            </span>
          ))}
        </div>
      ) : null}
      {snap?.price ? (
        <p className="mt-1.5 text-[11px] text-ink/70">{snap.price}</p>
      ) : null}
    </>
  );
}

function MealFace({ node }: { node: NodeResponse }) {
  const meta = getMeta(node);
  const snap = meta.snapshot;
  const tod = meta.time_of_day ?? "";
  const todGlyph =
    tod === "morning" ? "☀" : tod === "evening" || tod === "night" ? "☾" : tod === "lunch" ? "◐" : "•";
  return (
    <>
      <Title>{node.title}</Title>
      <div className="mt-1 flex items-center gap-2 text-[11px] text-ink/70">
        <span aria-hidden>{todGlyph}</span>
        {tod ? <span className="capitalize">{tod}</span> : null}
        {snap?.location ? (
          <>
            <span className="text-ink/30">·</span>
            <span>{snap.location}</span>
          </>
        ) : null}
      </div>
      {snap?.price ? (
        <p className="mt-1 text-[11px] text-ink/65">{snap.price}</p>
      ) : null}
    </>
  );
}

function TransitFace({ node }: { node: NodeResponse }) {
  const meta = getMeta(node);
  return (
    <>
      <Title>{node.title}</Title>
      <Sub>{meta.mode ?? "Private transfer"}</Sub>
    </>
  );
}

function FreeTimeFace({ node }: { node: NodeResponse }) {
  const meta = getMeta(node);
  return (
    <div className="mt-1 rounded-md border border-dashed border-ink/20 px-2 py-1.5">
      <h3 className="font-serif italic text-[15px] leading-snug text-ink/85">
        {node.title}
      </h3>
      {meta.body ? <Sub>{meta.body}</Sub> : null}
    </div>
  );
}

function NoteFace({ node }: { node: NodeResponse }) {
  const meta = getMeta(node);
  return (
    <div className="mt-1">
      <h3 className="font-serif text-[15px] leading-snug text-ink">
        {node.title}
      </h3>
      {meta.body ? (
        <p className="mt-0.5 text-[11px] leading-snug text-ink/70">
          {meta.body}
        </p>
      ) : null}
    </div>
  );
}

function TypeIcon({ type }: { type: NodeType }) {
  const glyph =
    type === "flight"
      ? "✈"
      : type === "transit"
      ? "→"
      : type === "hotel"
      ? "◻"
      : type === "experience"
      ? "◉"
      : type === "destination"
      ? "⌂"
      : type === "meal"
      ? "◆"
      : type === "free_time"
      ? "◌"
      : "✎";
  return <span aria-hidden>{glyph}</span>;
}

function typeLabel(type: NodeType): string {
  switch (type) {
    case "free_time":
      return "Open";
    default:
      return type;
  }
}

function statusShellClasses(status: NodeStatus): string {
  switch (status) {
    case "idea":
      return "opacity-70";
    case "discarded":
      return "opacity-50 grayscale";
    default:
      return "";
  }
}
