"use client";

// The drag affordance for the desktop concierge docks. It renders as a thin
// flex sibling on the dock's RIGHT edge (both docks are left-attached), so it
// never fights the aside's position utilities the way an absolute overlay would.
// Visibility/order gating is left to the host via `className` — each shell has
// its own desktop breakpoint (itinerary min-[1100px], basecamp lg).

export function DockResizeHandle({
  onPointerDown,
  active,
  className,
}: {
  onPointerDown: (e: React.PointerEvent) => void;
  /** A drag is in flight — hold the line lit. */
  active: boolean;
  /** Host-supplied display/order/breakpoint classes (e.g. "hidden min-[1100px]:flex"). */
  className?: string;
}) {
  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label="Resize the concierge"
      onPointerDown={onPointerDown}
      data-testid="dock-resize-handle"
      className={[
        "group relative w-2 shrink-0 cursor-col-resize touch-none select-none",
        className ?? "",
      ].join(" ")}
    >
      {/* The visible 1px seam, centered in the wider grab target. */}
      <span
        aria-hidden
        className={[
          "pointer-events-none absolute inset-y-0 left-1/2 w-px -translate-x-1/2 transition-colors",
          active ? "bg-brand" : "bg-ink/10 group-hover:bg-brand/50",
        ].join(" ")}
      />
    </div>
  );
}
