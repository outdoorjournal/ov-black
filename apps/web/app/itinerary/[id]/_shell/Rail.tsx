"use client";

// The places axis (M006/PS1) — a slim left rail of routed destinations. One
// noun per destination; role changes affordances WITHIN a surface, not access,
// so the only role gate here is the advisor-only Studio below the divider.
//
// PS1 ships Timeline · Collection · ─ · Studio. Home/Dashboard joins at the top
// in PS3 (the per-trip home). Party + notifications live in the Dashboard, not
// the rail (Q7). Below md the rail hides and the MobileTabBar carries the axis.

import type { Route } from "next";
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { itineraryGraphStore } from "@/app/_components/itinerary-graph/store/itineraryGraphStore";

import {
  CollectionIcon,
  ConciergeIcon,
  StudioIcon,
  TimelineIcon,
} from "./icons";

export function Rail({ onOpenConcierge }: { onOpenConcierge: () => void }) {
  const id = itineraryGraphStore.useStore((s) => s.itineraryId);
  const role = itineraryGraphStore.useStore((s) => s.role);
  const pathname = usePathname();
  const activeSeg = lastSegment(pathname);

  return (
    <nav
      data-testid="planner-rail"
      aria-label="Views"
      className="hidden w-[76px] shrink-0 flex-col items-stretch border-r border-ink/10 bg-paper/85 py-3 md:flex"
    >
      <RailLink
        href={`/itinerary/${id}/timeline`}
        label="Timeline"
        active={activeSeg === "timeline"}
        icon={<TimelineIcon />}
      />
      <RailLink
        href={`/itinerary/${id}/collection`}
        label="Collection"
        active={activeSeg === "collection"}
        icon={<CollectionIcon />}
      />

      {role === "advisor" ? (
        <>
          <div className="mx-4 my-2 border-t border-ink/10" aria-hidden />
          <RailLink
            href={`/itinerary/${id}/studio`}
            label="Studio"
            active={activeSeg === "studio"}
            icon={<StudioIcon />}
          />
        </>
      ) : null}

      {/* Concierge opener for the tablet band (md–1100px, where the column is
          collapsed). Inert ≥1100px (the column is always in-flow there). */}
      <button
        type="button"
        onClick={onOpenConcierge}
        data-testid="rail-open-concierge"
        className="mt-auto flex flex-col items-center gap-1 py-2.5 font-sans text-[9px] uppercase tracking-[0.14em] text-ink/50 transition-colors hover:text-ink min-[1100px]:hidden"
      >
        <ConciergeIcon />
        Concierge
      </button>
    </nav>
  );
}

function RailLink({
  href,
  label,
  active,
  icon,
}: {
  href: Route;
  label: string;
  active: boolean;
  icon: ReactNode;
}) {
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

function lastSegment(pathname: string | null): string {
  if (!pathname) return "";
  const parts = pathname.split("/").filter(Boolean);
  return parts[parts.length - 1] ?? "";
}
