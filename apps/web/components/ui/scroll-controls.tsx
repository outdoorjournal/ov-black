"use client";

// Floating up/down jump buttons for a scrollable message stream. Shared by every
// conversation surface so the affordance looks and behaves the same. Given a ref
// to the scroll element, it watches scroll position + content growth and shows
// the "jump to top" button only when there's room above, the "jump to bottom"
// button only when there's room below — so a stream that fits its viewport shows
// nothing at all. Both scrolls are smooth.
//
// Render it as a sibling of the scroll element inside a `relative` wrapper that
// matches the scroll viewport (not inside the scroller itself — an absolutely
// positioned child of a scroller scrolls away with the content).

import { ChevronDown, ChevronUp } from "lucide-react";
import * as React from "react";

import { cn } from "@/lib/utils";

// Ignore sub-pixel/rubber-band slack so a stream pinned to an edge doesn't
// flicker the button on and off.
const EDGE_SLACK_PX = 24;

export interface ScrollControlsProps {
  targetRef: React.RefObject<HTMLElement | null>;
  // Position override for the button cluster (defaults to bottom-right).
  className?: string;
}

export function ScrollControls({ targetRef, className }: ScrollControlsProps) {
  const [canUp, setCanUp] = React.useState(false);
  const [canDown, setCanDown] = React.useState(false);

  React.useEffect(() => {
    const el = targetRef.current;
    if (!el) return;

    const update = () => {
      const { scrollTop, scrollHeight, clientHeight } = el;
      setCanUp(scrollTop > EDGE_SLACK_PX);
      setCanDown(scrollHeight - scrollTop - clientHeight > EDGE_SLACK_PX);
    };

    update();
    el.addEventListener("scroll", update, { passive: true });
    window.addEventListener("resize", update);
    // Recompute as the viewport resizes and as content grows (streaming tokens,
    // new turns) — the content wrapper's height change is what we're catching.
    // Guarded for environments without ResizeObserver (jsdom under test); the
    // scroll + resize listeners still keep the buttons broadly in sync there.
    const observer =
      typeof ResizeObserver === "undefined" ? null : new ResizeObserver(update);
    if (observer) {
      observer.observe(el);
      if (el.firstElementChild) observer.observe(el.firstElementChild);
    }

    return () => {
      el.removeEventListener("scroll", update);
      window.removeEventListener("resize", update);
      observer?.disconnect();
    };
  }, [targetRef]);

  const jump = (top: number) => {
    targetRef.current?.scrollTo({ top, behavior: "smooth" });
  };

  if (!canUp && !canDown) return null;

  return (
    <div
      className={cn(
        "pointer-events-none absolute bottom-3 right-3 z-10 flex flex-col gap-1.5",
        className,
      )}
      data-testid="scroll-controls"
    >
      {canUp ? (
        <button
          type="button"
          onClick={() => jump(0)}
          aria-label="Scroll to top"
          data-testid="scroll-to-top"
          className="pointer-events-auto flex h-8 w-8 items-center justify-center rounded-full border border-ink/15 bg-paper/90 text-ink/70 shadow-sm backdrop-blur-xs transition-colors hover:border-ink/40 hover:text-ink"
        >
          <ChevronUp className="h-4 w-4" />
        </button>
      ) : null}
      {canDown ? (
        <button
          type="button"
          onClick={() => jump(targetRef.current?.scrollHeight ?? 0)}
          aria-label="Scroll to bottom"
          data-testid="scroll-to-bottom"
          className="pointer-events-auto flex h-8 w-8 items-center justify-center rounded-full border border-ink/15 bg-paper/90 text-ink/70 shadow-sm backdrop-blur-xs transition-colors hover:border-ink/40 hover:text-ink"
        >
          <ChevronDown className="h-4 w-4" />
        </button>
      ) : null}
    </div>
  );
}
