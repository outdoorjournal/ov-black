"use client";

// The common left navigation rail (M006/PS7) — shared by the itinerary planner
// shell and basecamp so the two surfaces navigate identically. A slim column of
// one-noun destinations; an optional `backItem` renders at the top, styled
// differently (a muted return link above a divider) — on the itinerary that is
// "‹ Basecamp", which is why the masthead no longer carries a back breadcrumb.
//
// Presentational: callers resolve the active item + supply their own icons, so
// the rail carries no store or route knowledge of its own. Hidden below md (the
// surface's mobile affordance carries the axis there).
//
// Wave F: an additive `tone` prop — "light" (default, unchanged) for the
// traveler-facing surfaces, "dark" for the Command Center's ink ops-room
// shell. Same geometry and testids either way.

import type { Route } from "next";
import Link from "next/link";
import { Fragment, type ReactNode } from "react";

export type RailTone = "light" | "dark";

export type RailItem = {
  href: Route;
  label: string;
  icon: ReactNode;
  active: boolean;
  /** Render a divider above this item (e.g. the advisor-only Studio group). */
  dividerBefore?: boolean;
  /** Wave F: a brand attention dot on the destination (e.g. Ops with items waiting). */
  attention?: boolean;
};

export type RailBackItem = {
  href: Route;
  label: string;
};

const TONE = {
  light: {
    nav: "border-ink/10 bg-paper/85",
    divider: "border-ink/10",
    back: "text-ink/40 hover:text-ink",
    active: "bg-ink text-paper",
    idle: "text-ink/50 hover:bg-ink/5 hover:text-ink",
  },
  dark: {
    nav: "border-paper/10 bg-ink",
    divider: "border-paper/10",
    back: "text-paper/40 hover:text-paper",
    active: "bg-paper text-ink",
    idle: "text-paper/50 hover:bg-paper/10 hover:text-paper",
  },
} as const;

export function AppRail({
  backItem,
  items,
  footer,
  ariaLabel = "Navigation",
  tone = "light",
}: {
  backItem?: RailBackItem;
  items: RailItem[];
  /** Bottom-anchored extra (e.g. the itinerary's tablet concierge opener). */
  footer?: ReactNode;
  ariaLabel?: string;
  tone?: RailTone;
}) {
  const t = TONE[tone];
  return (
    <nav
      data-testid="planner-rail"
      aria-label={ariaLabel}
      className={`hidden w-[76px] shrink-0 flex-col items-stretch border-r py-3 md:flex ${t.nav}`}
    >
      {backItem ? (
        <>
          <Link
            href={backItem.href}
            data-testid="rail-back"
            className={`flex flex-col items-center gap-1 py-2.5 font-sans text-[9px] uppercase tracking-[0.14em] transition-colors ${t.back}`}
          >
            <BackIcon />
            {backItem.label}
          </Link>
          <div className={`mx-4 mb-1 mt-1 border-t ${t.divider}`} aria-hidden />
        </>
      ) : null}

      {items.map((item) => (
        <Fragment key={item.label}>
          {item.dividerBefore ? (
            <div className={`mx-4 my-2 border-t ${t.divider}`} aria-hidden />
          ) : null}
          <RailLink {...item} tone={tone} />
        </Fragment>
      ))}

      {footer}
    </nav>
  );
}

function RailLink({
  href,
  label,
  active,
  icon,
  attention,
  tone,
}: RailItem & { tone: RailTone }) {
  const t = TONE[tone];
  // Selected destination reads as an inverse fill — paper type on an ink chip
  // (or the reverse on the dark rail) — rather than a thin edge indicator, so
  // the active surface is unmistakable.
  return (
    <Link
      href={href}
      aria-current={active ? "page" : undefined}
      data-testid={`rail-${label.toLowerCase()}`}
      className={
        "relative flex flex-col items-center gap-1 py-2.5 font-sans text-[9px] uppercase tracking-[0.14em] transition-colors " +
        (active ? t.active : t.idle)
      }
    >
      {attention ? (
        <span
          aria-hidden
          className="absolute right-4 top-2 inline-block h-1.5 w-1.5 rounded-full bg-brand"
        />
      ) : null}
      {icon}
      {label}
    </Link>
  );
}

function BackIcon() {
  return (
    <svg
      width="18"
      height="18"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <path d="M15 18l-6-6 6-6" />
    </svg>
  );
}
