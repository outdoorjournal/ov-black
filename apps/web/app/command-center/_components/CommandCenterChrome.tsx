"use client";

// Advisor-section chrome: the shared black AppHeader (wordmark + breadcrumbs +
// avatar menu). The primary nav lives in the shared left rail
// (CommandCenterRail); Wave F adds the masthead actions — the ⌘K search
// trigger and the LIVE feed indicator — via AppHeader's actions slot.
//
// Crumbs are derived from the pathname here (a client component) so the server
// layout can render this once and every /command-center page lands in the right
// place without prop-drilling.

import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { AppHeader, type Crumb } from "@/app/_components/app-header/AppHeader";
import type { AppHeaderUser } from "@/lib/appHeader";

import { useCommandCenterCrumb } from "./CommandCenterCrumb";

/**
 * Location breadcrumbs for the advisor section, derived from the pathname.
 * `clientLabel` is the current client's name, fed up from the detail page — the
 * pathname alone only knows the id, so without it the trailing crumb would be a
 * meaningless "Client".
 */
function crumbsFor(pathname: string, clientLabel: string | null): Crumb[] {
  if (pathname === "/command-center") return [{ label: "Ops" }];
  if (pathname.startsWith("/command-center/trips")) return [{ label: "Trips" }];
  if (pathname.startsWith("/command-center/money")) return [{ label: "Money" }];

  if (
    pathname.startsWith("/command-center/clients") ||
    pathname.startsWith("/command-center/new-client")
  ) {
    const crumbs: Crumb[] = [
      { label: "Clients", href: "/command-center/clients" },
    ];
    if (pathname.startsWith("/command-center/new-client")) {
      crumbs.push({ label: "New client" });
    } else {
      const rest = pathname
        .replace("/command-center/clients", "")
        .split("/")
        .filter(Boolean);
      // On a specific client, show its name; until the page registers it, leave
      // the trailing crumb off rather than showing a generic placeholder.
      if (rest.length > 0 && clientLabel) {
        if (rest.includes("sessions")) {
          crumbs.push(
            { label: clientLabel, href: `/command-center/clients/${rest[0]}` },
            { label: "Session" },
          );
        } else {
          crumbs.push({ label: clientLabel });
        }
      }
    }
    return crumbs;
  }

  return [];
}

export function CommandCenterChrome({
  user,
  homeHref,
  actions,
}: {
  user: AppHeaderUser;
  homeHref: string;
  actions?: ReactNode;
}) {
  const pathname = usePathname() ?? "";
  const { clientLabel } = useCommandCenterCrumb();

  return (
    <AppHeader
      user={user}
      homeHref={homeHref}
      crumbs={crumbsFor(pathname, clientLabel)}
      {...(actions !== undefined ? { actions } : {})}
    />
  );
}
