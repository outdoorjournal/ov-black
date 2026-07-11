"use client";

// The shared full-bleed, conversation-aware backdrop for the immersive agent
// surfaces (the trip intake and the basecamp onboarding first-touch). It is the
// landing page's dark cinematic imagery treatment, made mood-reactive: before
// the agent commits to a direction it slowly rotates the front-door hero set;
// the moment a `mood` frame arrives (the agent's set_mood) it locks to that
// mood's curated Unsplash frame and crossfades between subsequent moods. A
// layered dark veil keeps the floating chat card and serif headline legible
// over any frame.

import Image from "next/image";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { useEffect, useState } from "react";

import { ATMOSPHERIC_BACKDROPS } from "@/lib/atmos/backdrops";
import { MOODS, type MoodId } from "@/lib/atmos/moods";

// The big curated pool (lib/atmos/backdrops.ts) — front-door frames first,
// then peaks / water / coast / desert / forest. Rotation starts at a random
// frame per visit so returning to the room never replays the same reel.
const ROTATION_IMAGES = ATMOSPHERIC_BACKDROPS;

const ROTATE_MS = 11_000;

export function CinematicBackdrop({ mood }: { mood: MoodId | null }) {
  const reduced = useReducedMotion() ?? false;
  // Deterministic first frame for SSR/hydration parity; the reel jumps to a
  // random frame right after mount (a crossfade, so it reads as intentional)
  // and rotates from there.
  const [rotationIndex, setRotationIndex] = useState(0);
  useEffect(() => {
    setRotationIndex(Math.floor(Math.random() * ROTATION_IMAGES.length));
  }, []);

  // Idle rotation only while the conversation hasn't picked a direction.
  useEffect(() => {
    if (mood) return;
    const t = setInterval(
      () => setRotationIndex((i) => (i + 1) % ROTATION_IMAGES.length),
      ROTATE_MS,
    );
    return () => clearInterval(t);
  }, [mood]);

  const src = mood
    ? MOODS[mood].imageUrl
    : ROTATION_IMAGES[rotationIndex % ROTATION_IMAGES.length];

  return (
    <div aria-hidden className="absolute inset-0 overflow-hidden bg-ink">
      <AnimatePresence initial={false}>
        <motion.div
          key={src}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: reduced ? 0 : 1.6, ease: "easeInOut" }}
          className="absolute inset-0"
        >
          {src ? (
            <Image
              src={src}
              alt=""
              fill
              priority
              sizes="100vw"
              className="object-cover"
            />
          ) : null}
        </motion.div>
      </AnimatePresence>

      {/* Cinematic darkening — the landing page's veil discipline: a global
          dim plus a left-biased gradient and a bottom fade, so serif text and
          the paper chat card always sit on a quiet field. */}
      <div className="absolute inset-0 bg-ink/45" />
      <div className="absolute inset-0 bg-gradient-to-r from-ink/70 via-ink/25 to-ink/50" />
      <div className="absolute inset-x-0 bottom-0 h-1/3 bg-gradient-to-t from-ink/80 to-transparent" />
    </div>
  );
}
