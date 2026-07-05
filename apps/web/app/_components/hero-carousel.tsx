"use client";

import Image from "next/image";
import { useEffect, useState } from "react";

// Full-bleed cross-fading hero. Deliberately dependency-free: each frame is a
// stacked <Image fill> toggled between opacity 0/1 with a CSS transition, so
// the fade is GPU-cheap and there's no animation library on the critical path.
// The cinematic darkening + rotation indicators live here too, so the parent
// page only has to overlay its content at a higher z-index.
const ROTATE_MS = 10_000;
const FADE_MS = 2_000;

export function HeroCarousel({ images }: { images: readonly string[] }) {
  const [active, setActive] = useState(0);

  useEffect(() => {
    if (images.length <= 1) return;
    const id = setInterval(() => {
      setActive((current) => (current + 1) % images.length);
    }, ROTATE_MS);
    return () => clearInterval(id);
  }, [images.length]);

  return (
    <div aria-hidden className="absolute inset-0 overflow-hidden bg-ink">
      {images.map((src, index) => (
        <div
          key={src}
          className="absolute inset-0 transition-opacity ease-in-out motion-reduce:transition-none"
          style={{
            opacity: index === active ? 1 : 0,
            transitionDuration: `${FADE_MS}ms`,
          }}
        >
          <Image
            src={src}
            alt=""
            fill
            priority={index === 0}
            sizes="100vw"
            className="object-cover"
          />
        </div>
      ))}

      {/* Cinematic darkening — heavier on the left and at the base so overlaid
          type stays legible while the photograph still reads through. */}
      <div className="absolute inset-0 bg-linear-to-r from-ink/85 via-ink/45 to-ink/70" />
      <div className="absolute inset-x-0 top-0 h-40 bg-linear-to-b from-ink/80 to-transparent" />
      <div className="absolute inset-x-0 bottom-0 h-56 bg-linear-to-t from-ink to-transparent" />

      {/* Rotation indicators — the active frame picks up the brand accent.
          z-20 so they sit above the page footer (which is z-10). */}
      <div className="absolute bottom-7 left-1/2 z-20 hidden -translate-x-1/2 items-center gap-2 sm:flex">
        {images.map((src, index) => (
          <span
            key={src}
            className={
              index === active
                ? "h-1.5 w-6 rounded-full bg-brand transition-all duration-500"
                : "h-1.5 w-1.5 rounded-full bg-paper/40 transition-all duration-500"
            }
          />
        ))}
      </div>
    </div>
  );
}
