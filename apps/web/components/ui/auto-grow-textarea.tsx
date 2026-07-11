"use client";

// The one chat composer input. Every concierge/human message box (the /chat
// Composer, the shared ConversationPanel, the itinerary HumanThread) renders
// this so they behave identically: the field rests at a single line, grows with
// its content up to `maxHeightPx`, then scrolls internally — the Claude Code
// composer feel. Enter submits (via `onSubmit`); Shift+Enter inserts a newline.
//
// It is styling-agnostic: callers pass their own visual className (border, font,
// colours, padding) so each surface keeps its look. What's shared — and what
// used to drift between three hand-rolled copies — is the behaviour: auto-grow,
// Enter-to-send semantics, and ref merging for focus management.

import * as React from "react";

import { cn } from "@/lib/utils";

export interface AutoGrowTextareaProps extends Omit<
  React.ComponentProps<"textarea">,
  "onChange" | "value"
> {
  value: string;
  onValueChange: (value: string) => void;
  // Enter (without Shift) fires this; Shift+Enter inserts a newline. Omit to
  // keep plain textarea behaviour (Enter inserts a newline). A caller-supplied
  // `onKeyDown` still runs after this.
  onSubmit?: () => void;
  // Optional resting-height floor. Omit to rest at a single row (the field grows
  // from one line). Set it when a surface wants more presence at rest.
  minHeightPx?: number;
  // Grows up to this height, then scrolls. Defaults to a roomy composer ceiling.
  maxHeightPx?: number;
}

export const AutoGrowTextarea = React.forwardRef<
  HTMLTextAreaElement,
  AutoGrowTextareaProps
>(function AutoGrowTextarea(
  {
    value,
    onValueChange,
    onSubmit,
    onKeyDown,
    minHeightPx,
    maxHeightPx = 200,
    className,
    style,
    rows = 1,
    ...props
  },
  forwardedRef,
) {
  const innerRef = React.useRef<HTMLTextAreaElement>(null);

  // Merge the caller's ref (used for focus management) with our own measuring
  // ref, so both point at the same element.
  const setRefs = React.useCallback(
    (node: HTMLTextAreaElement | null) => {
      innerRef.current = node;
      if (typeof forwardedRef === "function") forwardedRef(node);
      else if (forwardedRef) forwardedRef.current = node;
    },
    [forwardedRef],
  );

  // Auto-grow: reset to auto so scrollHeight reflects the true content height,
  // then clamp to the ceiling. Re-runs on every value change (including the
  // reset to "" after a send, which snaps the field back to one line).
  React.useLayoutEffect(() => {
    const el = innerRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, maxHeightPx)}px`;
  }, [value, maxHeightPx]);

  return (
    <textarea
      ref={setRefs}
      rows={rows}
      value={value}
      onChange={(e) => onValueChange(e.target.value)}
      onKeyDown={(e) => {
        if (onSubmit && e.key === "Enter" && !e.shiftKey) {
          e.preventDefault();
          onSubmit();
        }
        onKeyDown?.(e);
      }}
      style={{
        ...(minHeightPx === undefined ? {} : { minHeight: minHeightPx }),
        maxHeight: maxHeightPx,
        ...style,
      }}
      className={cn("resize-none overflow-y-auto", className)}
      {...props}
    />
  );
});
