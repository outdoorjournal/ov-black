"use client";

// The Journal's ambient layer (traveler-journal design, phase 5) — behind the
// paper: the ACTIVE node's `ambient_image` as a very low-opacity watermark /
// watercolor wash, crossfading (framer-motion, within the design's 300–600ms
// band) as activation changes. A node without an image — and every diff-mode
// ghost, which is synthesized and usually carries none — falls back to the
// trip's mood tint (`MOOD_ACCENTS`), so the wash never goes dead.
//
// Discipline:
//   · a WHISPER — the watermark never competes with the paper; a paper-toned
//     veil keeps the reading column legible. Cinema mode flips the same layer
//     to full-bleed (higher presence, lighter veil) — no second DOM.
//   · LAZY at activation distance — only the active image is ever rendered;
//     neighbours (± a few scheduled nodes) are warmed with `new Image()` so
//     the next crossfade doesn't flash, and nothing else is fetched.
//   · `prefers-reduced-motion` → the crossfade collapses to an instant swap.

import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { useEffect, useMemo, useRef } from "react";

import { parseIso } from "../../model/time";
import { getVerticalMeta, MOOD_ACCENTS } from "../../model/types";
import { itineraryGraphStore } from "../../store/itineraryGraphStore";
import { useTimelineData } from "../../TimelineDataContext";

import { ambientFadeSeconds } from "./motion";

/** How many scheduled neighbours (each side of the active node) get their
 *  ambient image pre-warmed. */
export const AMBIENT_WARM_DISTANCE = 3;

const PAPER = "247, 244, 238"; // --color-paper, as an rgb triple for the veil

export function AmbientLayer() {
  const { timeline } = useTimelineData();
  const focusedNodeId = itineraryGraphStore.useStore((s) => s.focusedNodeId);
  const focusSource = itineraryGraphStore.useStore((s) => s.focusSource);
  const nodes = itineraryGraphStore.useStore((s) => s.nodes);
  const cinemaMode = itineraryGraphStore.useStore((s) => s.cinemaMode);
  const reduced = Boolean(useReducedMotion());

  // Only a real Journal interaction (scroll/click) drives the wash — the
  // seeded default focus keeps the resting mood tint (same rule as the rail).
  const activeNode =
    focusSource !== null && focusedNodeId
      ? (nodes.find((n) => n.id === focusedNodeId) ?? null)
      : null;
  const image = activeNode
    ? (getVerticalMeta(activeNode).ambient_image ?? null)
    : null;
  const tint = MOOD_ACCENTS[timeline.mood].tint;

  // The journey in time order — the "activation distance" neighbourhood the
  // pre-warm walks. Mirrors the Journal's visibility rule (scheduled only).
  const scheduled = useMemo(
    () =>
      nodes
        .filter((n) => {
          const meta = getVerticalMeta(n);
          return (
            typeof meta.start_time === "string" &&
            meta.start_time.length > 0 &&
            meta.start_synthesized !== true &&
            n.status !== "discarded"
          );
        })
        .sort(
          (a, b) =>
            parseIso(getVerticalMeta(a).start_time ?? "") -
            parseIso(getVerticalMeta(b).start_time ?? ""),
        ),
    [nodes],
  );

  // Lazy-load at activation distance: warm only the neighbourhood's images.
  const warmedRef = useRef(new Set<string>());
  useEffect(() => {
    if (typeof window === "undefined" || !focusedNodeId) return;
    const idx = scheduled.findIndex((n) => n.id === focusedNodeId);
    if (idx < 0) return;
    const from = Math.max(0, idx - AMBIENT_WARM_DISTANCE);
    const to = Math.min(scheduled.length - 1, idx + AMBIENT_WARM_DISTANCE);
    for (let i = from; i <= to; i += 1) {
      const neighbour = scheduled[i];
      const url = neighbour ? getVerticalMeta(neighbour).ambient_image : null;
      if (!url || warmedRef.current.has(url)) continue;
      warmedRef.current.add(url);
      const img = new Image();
      img.src = url;
    }
  }, [focusedNodeId, scheduled]);

  const fade = ambientFadeSeconds(reduced);
  // Watermark by default; presence in cinema (full-bleed, lighter veil).
  const washOpacity = cinemaMode ? 0.5 : 0.09;
  const key = image ?? `tint:${timeline.mood}`;

  return (
    <div
      aria-hidden
      data-testid="journal-ambient"
      data-cinema={cinemaMode ? "true" : undefined}
      // `absolute`, not `fixed`: the host (DashboardView) gives this a `relative`
      // parent so the wash is confined to the dashboard content region and held
      // still there while the story scrolls. A `fixed` backdrop escapes to the
      // whole viewport and paints its veil over the sibling rail + concierge
      // chrome, washing them grey.
      //
      // Confined to the RIGHT SIDE on desktop (lg+): the reading column (the
      // spine of cards) is left-anchored, so the wash lives in the free space to
      // its right — the whole right side, behind the rail (which carries no
      // background of its own, so the watermark reads through it). Below lg the
      // layout stacks (rail above the full-width Journal, no side channel), so
      // it spans the full width as before.
      className="pointer-events-none absolute inset-y-0 left-0 right-0 z-0 overflow-hidden lg:left-1/2"
    >
      {/* The resting wash — the trip's mood tint, always beneath the image. */}
      <div
        className="absolute inset-0 transition-opacity duration-500"
        style={{ backgroundColor: tint, opacity: cinemaMode ? 0.35 : 0.18 }}
      />
      <AnimatePresence initial={false}>
        <motion.div
          key={key}
          data-testid="journal-ambient-active"
          {...(image ? { "data-image": image } : {})}
          initial={{ opacity: 0 }}
          animate={{ opacity: washOpacity }}
          exit={{ opacity: 0 }}
          transition={{ duration: fade, ease: "easeInOut" }}
          className="absolute inset-0 bg-cover bg-center"
          style={
            image
              ? { backgroundImage: `url(${image})`, filter: "saturate(0.85)" }
              : { backgroundColor: tint }
          }
        />
      </AnimatePresence>
      {/* The paper veil — keeps the reading column legible; cinema lifts it. */}
      <div
        className="absolute inset-0 transition-opacity duration-500"
        style={{
          background: `linear-gradient(180deg, rgba(${PAPER}, 0.55), rgba(${PAPER}, 0.85))`,
          opacity: cinemaMode ? 0.45 : 1,
        }}
      />
    </div>
  );
}
