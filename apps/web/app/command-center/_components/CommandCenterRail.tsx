"use client";

// The advisor's slice of the shared AppRail (M006/PS7) — the same left nav the
// itinerary shell and basecamp use, so every surface navigates identically.
// Command-center replaces its old bespoke horizontal masthead tabs with this
// rail. It is the advisor's home, so there is no back item; the destinations are
// the advisor surfaces (Overview · Clients).

import type { Route } from "next";
import { usePathname } from "next/navigation";
import { LayoutGrid, Users } from "lucide-react";

import { AppRail, type RailItem } from "@/app/_components/shell/AppRail";

export function CommandCenterRail() {
  const pathname = usePathname() ?? "";

  const items: RailItem[] = [
    {
      href: "/command-center" as Route,
      label: "Overview",
      active: pathname === "/command-center",
      icon: <LayoutGrid size={18} strokeWidth={1.6} aria-hidden />,
    },
    {
      href: "/command-center/clients" as Route,
      label: "Clients",
      active:
        pathname.startsWith("/command-center/clients") ||
        pathname.startsWith("/command-center/new-client"),
      icon: <Users size={18} strokeWidth={1.6} aria-hidden />,
    },
  ];

  return <AppRail ariaLabel="Command center" items={items} />;
}
