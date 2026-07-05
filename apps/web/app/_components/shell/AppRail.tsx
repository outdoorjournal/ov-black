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

import type { Route } from "next";
import Link from "next/link";
import { Fragment, type ReactNode } from "react";

export type RailItem = {
  href: Route;
  label: string;
  icon: ReactNode;
  active: boolean;
  /** Render a divider above this item (e.g. the advisor-only Studio group). */
  dividerBefore?: boolean;
};

export type RailBackItem = {
  href: Route;
  label: string;
};

export function AppRail({
  backItem,
  items,
  footer,
  ariaLabel = "Navigation",
}: {
  backItem?: RailBackItem;
  items: RailItem[];
  /** Bottom-anchored extra (e.g. the itinerary's tablet concierge opener). */
  footer?: ReactNode;
  ariaLabel?: string;
}) {
  return (
    <nav
      data-testid="planner-rail"
      aria-label={ariaLabel}
      className="hidden w-[76px] shrink-0 flex-col items-stretch border-r border-ink/10 bg-paper/85 py-3 md:flex"
    >
      {backItem ? (
        <>
          <Link
            href={backItem.href}
            data-testid="rail-back"
            className="flex flex-col items-center gap-1 py-2.5 font-sans text-[9px] uppercase tracking-[0.14em] text-ink/40 transition-colors hover:text-ink"
          >
            <BackIcon />
            {backItem.label}
          </Link>
          <div className="mx-4 mb-1 mt-1 border-t border-ink/10" aria-hidden />
        </>
      ) : null}

      {items.map((item) => (
        <Fragment key={item.label}>
          {item.dividerBefore ? (
            <div className="mx-4 my-2 border-t border-ink/10" aria-hidden />
          ) : null}
          <RailLink {...item} />
        </Fragment>
      ))}

      {footer}
    </nav>
  );
}

function RailLink({ href, label, active, icon }: RailItem) {
  return (
    <Link
      href={href}
      aria-current={active ? "page" : undefined}
      data-testid={`rail-${label.toLowerCase()}`}
      className={
        "relative flex flex-col items-center gap-1 py-2.5 font-sans text-[9px] uppercase tracking-[0.14em] transition-colors " +
        (active ? "text-ink" : "text-ink/50 hover:text-ink")
      }
    >
      {active ? (
        <span
          className="absolute left-0 top-1/2 h-7 w-[3px] -translate-y-1/2 rounded-r bg-ink"
          aria-hidden
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
