"use client";

// Advisor-section chrome: the shared black AppHeader (wordmark + breadcrumbs +
// avatar menu) plus the command-center's primary nav tabs on the same ink
// masthead. Replaces the old bespoke Navbar so command-center matches the
// itinerary builder and correspondence exactly.
//
// Crumbs + the active tab are derived from the pathname here (a client
// component) so the server layout can render this once and every /command-center
// page lands in the right place without prop-drilling.

import Link from "next/link";
import { usePathname } from "next/navigation";

import { AppHeader, type Crumb } from "@/app/_components/app-header/AppHeader";
import type { AppHeaderUser } from "@/lib/appHeader";

type NavItem = {
  label: string;
  href: string;
  isActive: (pathname: string) => boolean;
};

const NAV: readonly NavItem[] = [
  {
    label: "Overview",
    href: "/command-center",
    isActive: (p) => p === "/command-center",
  },
  {
    label: "Clients",
    href: "/command-center/clients",
    isActive: (p) =>
      p.startsWith("/command-center/clients") ||
      p.startsWith("/command-center/new-client"),
  },
];

/** Location breadcrumbs for the advisor section, derived from the pathname. */
function crumbsFor(pathname: string): Crumb[] {
  if (pathname === "/command-center") return [{ label: "Overview" }];

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
      if (rest.length > 0) crumbs.push({ label: "Client" });
    }
    return crumbs;
  }

  return [];
}

export function CommandCenterChrome({
  user,
  homeHref,
}: {
  user: AppHeaderUser;
  homeHref: string;
}) {
  const pathname = usePathname() ?? "";

  const tabs = (
    <div className="border-t border-paper/10">
      <div className="flex items-center gap-8 px-6 sm:px-10">
        {NAV.map((item) => {
          const active = item.isActive(pathname);
          return (
            <Link
              key={item.href}
              href={item.href}
              aria-current={active ? "page" : undefined}
              className={
                "relative py-3 font-sans text-[10px] uppercase tracking-[0.3em] transition-colors " +
                (active ? "text-paper" : "text-paper/55 hover:text-paper")
              }
            >
              {item.label}
              {active ? (
                <span
                  aria-hidden
                  className="absolute inset-x-0 bottom-0 h-0.5 bg-brand"
                />
              ) : null}
            </Link>
          );
        })}
      </div>
    </div>
  );

  return (
    <AppHeader
      user={user}
      homeHref={homeHref}
      crumbs={crumbsFor(pathname)}
      secondary={tabs}
    />
  );
}
