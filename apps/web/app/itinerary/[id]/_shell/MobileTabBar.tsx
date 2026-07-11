"use client";

// The places axis on a phone (M006/PS1) — a fixed bottom tab bar carrying the
// same routed destinations as the desktop Rail, plus a Chat tab that summons the
// concierge as a full-screen overlay (the people axis has no room to sit beside
// the plan on a phone). Home (the per-trip Dashboard, PS3) leads the bar.

import type { Route } from "next";
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { itineraryGraphStore } from "@/app/_components/itinerary-graph/store/itineraryGraphStore";

import {
  CollectionIcon,
  ConciergeIcon,
  DashboardIcon,
  PartyIcon,
  TimelineIcon,
} from "./icons";

export function MobileTabBar({
  onOpenConcierge,
}: {
  onOpenConcierge: () => void;
}) {
  const id = itineraryGraphStore.useStore((s) => s.itineraryId);
  const pathname = usePathname();
  const seg = pathname?.split("/").filter(Boolean).pop() ?? "";

  return (
    <nav
      data-testid="mobile-tab-bar"
      aria-label="Views"
      className="fixed inset-x-0 bottom-0 z-30 flex h-14 border-t border-ink/10 bg-paper/95 backdrop-blur-sm md:hidden"
    >
      <TabLink
        href={`/itinerary/${id}/dashboard`}
        label="Home"
        active={seg === "dashboard"}
        icon={<DashboardIcon />}
      />
      <TabLink
        href={`/itinerary/${id}/timeline`}
        label="Timeline"
        active={seg === "timeline"}
        icon={<TimelineIcon />}
      />
      <TabLink
        href={`/itinerary/${id}/collection`}
        label="Collection"
        active={seg === "collection"}
        icon={<CollectionIcon />}
      />
      <TabLink
        href={`/itinerary/${id}/party`}
        label="Party"
        active={seg === "party"}
        icon={<PartyIcon />}
      />
      <button
        type="button"
        onClick={onOpenConcierge}
        data-testid="mobile-tab-chat"
        className="flex flex-1 flex-col items-center justify-center gap-0.5 font-sans text-[9px] uppercase tracking-[0.14em] text-ink/50 transition-colors hover:text-ink"
      >
        <ConciergeIcon />
        Chat
      </button>
    </nav>
  );
}

function TabLink({
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
      data-testid={`mobile-tab-${label.toLowerCase()}`}
      className={
        "flex flex-1 flex-col items-center justify-center gap-0.5 font-sans text-[9px] uppercase tracking-[0.14em] transition-colors " +
        (active ? "text-ink" : "text-ink/50 hover:text-ink")
      }
    >
      {icon}
      {label}
    </Link>
  );
}
