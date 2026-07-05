"use client";

// The places axis (M006/PS1) — the itinerary's slice of the shared AppRail. One
// noun per destination; role changes affordances WITHIN a surface, not access,
// so the only role gate here is the advisor-only Studio below the divider.
//
// The rail is «back» · Home · Timeline · Collection · ─ · Studio (Q7). The top
// item is the return to the viewer's home (Basecamp for a traveler, the client
// list for an advisor), styled as a muted back link — so the masthead no longer
// needs a "Basecamp ›" breadcrumb (PS7 header cleanup). Below md the rail hides
// and the MobileTabBar carries the axis.

import type { Route } from "next";
import { usePathname } from "next/navigation";

import { AppRail, type RailItem } from "@/app/_components/shell/AppRail";
import { itineraryGraphStore } from "@/app/_components/itinerary-graph/store/itineraryGraphStore";
import { useTimelineData } from "@/app/_components/itinerary-graph/TimelineDataContext";

import {
  CollectionIcon,
  ConciergeIcon,
  DashboardIcon,
  StudioIcon,
  TimelineIcon,
} from "./icons";

export function Rail({ onOpenConcierge }: { onOpenConcierge: () => void }) {
  const id = itineraryGraphStore.useStore((s) => s.itineraryId);
  const role = itineraryGraphStore.useStore((s) => s.role);
  const { timeline } = useTimelineData();
  const pathname = usePathname();
  const activeSeg = lastSegment(pathname);

  // Studio is Diff-only now (M006) — the authoring tools moved to the Timeline
  // toolbar. So the advisor-only Studio noun only earns a slot when there's
  // something to reconcile: an alternative version (a fork with a baseline).
  const isAlternative = Boolean(timeline.itinerary.forked_from_id);

  const backItem =
    role === "advisor"
      ? { href: "/command-center/clients" as Route, label: "Clients" }
      : { href: "/basecamp" as Route, label: "Basecamp" };

  const items: RailItem[] = [
    {
      href: `/itinerary/${id}/dashboard` as Route,
      label: "Home",
      active: activeSeg === "dashboard",
      icon: <DashboardIcon />,
    },
    {
      href: `/itinerary/${id}/timeline` as Route,
      label: "Timeline",
      active: activeSeg === "timeline",
      icon: <TimelineIcon />,
    },
    {
      href: `/itinerary/${id}/collection` as Route,
      label: "Collection",
      active: activeSeg === "collection",
      icon: <CollectionIcon />,
    },
    ...(role === "advisor" && isAlternative
      ? [
          {
            href: `/itinerary/${id}/studio` as Route,
            label: "Studio",
            active: activeSeg === "studio",
            icon: <StudioIcon />,
            dividerBefore: true,
          },
        ]
      : []),
  ];

  return (
    <AppRail
      ariaLabel="Views"
      backItem={backItem}
      items={items}
      footer={
        // Concierge opener for the tablet band (md–1100px, where the column is
        // collapsed). Inert ≥1100px (the column is always in-flow there).
        <button
          type="button"
          onClick={onOpenConcierge}
          data-testid="rail-open-concierge"
          className="mt-auto flex flex-col items-center gap-1 py-2.5 font-sans text-[9px] uppercase tracking-[0.14em] text-ink/50 transition-colors hover:text-ink min-[1100px]:hidden"
        >
          <ConciergeIcon />
          Concierge
        </button>
      }
    />
  );
}

function lastSegment(pathname: string | null): string {
  if (!pathname) return "";
  const parts = pathname.split("/").filter(Boolean);
  return parts[parts.length - 1] ?? "";
}
