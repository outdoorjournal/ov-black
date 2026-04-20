// Full-bleed atmospheric frame behind the conversation column (S06).
//
// Two stacked absolute layers inside `#atmos-frame`:
//
//   1. palette layer — always visible; its backgroundColor comes from
//      MOODS[mood].palette.bg via inline style (keeps Tailwind JIT safe,
//      no dynamic class strings). transition-colors drives the 3s crossfade
//      when mood changes.
//
//   2. image layer — decorative next/image overlay at 55% opacity. If the
//      image errors, the wrapper flips to opacity-0 and data-image-status
//      stays observable for tests. The palette underneath keeps the frame
//      colored — no stark-default reversion.
//
// The root element is keyed on `mood` so React reconciles the stacked
// children cleanly on mood change (cleaner crossfade, no state leak from
// the prior mood's Image instance).

import Image from "next/image";
import { useEffect, useState } from "react";

import { MOODS, type MoodId } from "@/lib/atmos/moods";

type ImageStatus = "ok" | "error";

export type AtmosFrameProps = {
  mood: MoodId;
  phaseCounter: number;
};

export function AtmosFrame({ mood, phaseCounter }: AtmosFrameProps) {
  const [imageStatus, setImageStatus] = useState<ImageStatus>("ok");

  // Reset image-load state whenever the mood changes — the new mood deserves
  // a fresh load attempt, independent of whether the prior image errored.
  useEffect(() => {
    setImageStatus("ok");
  }, [mood]);

  const entry = MOODS[mood];

  return (
    <div
      key={mood}
      id="atmos-frame"
      className="absolute inset-0"
      aria-hidden
      data-mood={mood}
      data-phase-counter={phaseCounter}
    >
      <div
        data-atmos-layer="palette"
        className="absolute inset-0 transition-colors duration-[3000ms] ease-out"
        style={{ backgroundColor: entry.palette.bg }}
      />
      <div
        data-atmos-layer="image"
        data-image-status={imageStatus}
        className={
          imageStatus === "error"
            ? "absolute inset-0 opacity-0 transition-opacity duration-[3000ms] ease-out"
            : "absolute inset-0 opacity-[0.55] transition-opacity duration-[3000ms] ease-out"
        }
      >
        {imageStatus === "ok" ? (
          <Image
            src={entry.imageUrl}
            alt=""
            fill
            priority={false}
            sizes="100vw"
            className="object-cover"
            onError={() => setImageStatus("error")}
          />
        ) : null}
      </div>
    </div>
  );
}
