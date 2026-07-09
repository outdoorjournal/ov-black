"use client";

// The advisor's slice of the shared AppRail (M006/PS7) — the same left nav the
// itinerary shell and basecamp use, so every surface navigates identically.
// Wave F: the rail goes dark (the ops-room shell) and grows to the four
// advisor jobs — Ops (triage home), Clients (dossier/invite lifecycle), Trips
// (the pipeline roster), Money (the cross-client invoice roster).

import type { Route } from "next";
import { usePathname } from "next/navigation";
import { Activity, Landmark, Map, PackageSearch, Users } from "lucide-react";

import { AppRail, type RailItem } from "@/app/_components/shell/AppRail";

export function CommandCenterRail() {
  const pathname = usePathname() ?? "";

  const items: RailItem[] = [
    {
      href: "/command-center" as Route,
      label: "Ops",
      active: pathname === "/command-center",
      icon: <Activity size={18} strokeWidth={1.6} aria-hidden />,
    },
    {
      href: "/command-center/clients" as Route,
      label: "Clients",
      active:
        pathname.startsWith("/command-center/clients") ||
        pathname.startsWith("/command-center/new-client"),
      icon: <Users size={18} strokeWidth={1.6} aria-hidden />,
    },
    {
      href: "/command-center/trips" as Route,
      label: "Trips",
      active: pathname.startsWith("/command-center/trips"),
      icon: <Map size={18} strokeWidth={1.6} aria-hidden />,
    },
    {
      href: "/command-center/money" as Route,
      label: "Money",
      active: pathname.startsWith("/command-center/money"),
      icon: <Landmark size={18} strokeWidth={1.6} aria-hidden />,
    },
    {
      href: "/command-center/inventory" as Route,
      label: "Inventory",
      active: pathname.startsWith("/command-center/inventory"),
      icon: <PackageSearch size={18} strokeWidth={1.6} aria-hidden />,
    },
  ];

  return <AppRail ariaLabel="Command center" items={items} tone="dark" />;
}
