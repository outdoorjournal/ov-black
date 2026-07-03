"use client";

// The one masthead shared across every app-chrome surface (command-center,
// itinerary builder, correspondence). Black (`bg-ink`) with paper text — the
// treatment the product owner standardized on — carrying:
//   • the Outdoor Voyage · Black wordmark (links to the viewer's home),
//   • breadcrumbs marking where you are, and
//   • the viewer's avatar as a dropdown (identity + sign out) in the corner.
//
// Presentational + dumb: it takes an explicit `crumbs` list and a resolved
// `user`. Surfaces that know their location (the itinerary page knows the trip
// title; command-center derives from the pathname) build the crumbs and pass
// them in. A `secondary` slot renders an optional sub-row on the same ink
// masthead (command-center uses it for its Overview/Clients tabs).

import Link from "next/link";
import { LogOut } from "lucide-react";
import { Fragment, type ReactNode } from "react";

import { signOutAction } from "@/app/_actions/sign-out";
import type { AppHeaderUser } from "@/lib/appHeader";
import {
  Avatar,
  AvatarFallback,
  AvatarImage,
} from "@/components/ui/avatar";
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

export type Crumb = { label: string; href?: string };

export type AppHeaderProps = {
  user: AppHeaderUser;
  /** Wordmark link target (advisor → /command-center, client → /basecamp). */
  homeHref: string;
  crumbs?: Crumb[];
  /** Optional sub-row (e.g. command-center nav tabs) on the same ink masthead. */
  secondary?: ReactNode;
};

function initialsFor(user: AppHeaderUser): string {
  const source = user.name ?? user.email;
  const parts = source.trim().split(/[\s@._-]+/).filter(Boolean);
  if (parts.length === 0) return "OV";
  if (parts.length === 1) return (parts[0]?.slice(0, 2) ?? "OV").toUpperCase();
  return `${parts[0]?.[0] ?? ""}${parts[1]?.[0] ?? ""}`.toUpperCase();
}

export function AppHeader({ user, homeHref, crumbs = [], secondary }: AppHeaderProps) {
  const displayName = user.name ?? user.email;

  return (
    <header className="sticky top-0 z-40 border-b border-paper/10 bg-ink text-paper">
      <div className="flex items-center justify-between gap-4 px-6 py-3 sm:px-10">
        <div className="flex min-w-0 items-center gap-4">
          <Link
            href={homeHref}
            className="flex shrink-0 items-baseline gap-2.5 transition-opacity hover:opacity-80"
          >
            <span className="font-serif text-xl tracking-tight">
              Outdoor Voyage
            </span>
            <span className="text-[10px] uppercase tracking-[0.35em] text-paper/60">
              Black
            </span>
          </Link>

          {crumbs.length > 0 ? (
            <>
              <span aria-hidden className="hidden h-4 w-px bg-paper/20 sm:block" />
              <Breadcrumb className="hidden min-w-0 sm:block">
                <BreadcrumbList className="text-paper/55">
                  {crumbs.map((crumb, i) => {
                    const isLast = i === crumbs.length - 1;
                    return (
                      <Fragment key={`${crumb.label}-${i}`}>
                        <BreadcrumbItem className="min-w-0">
                          {isLast || !crumb.href ? (
                            <BreadcrumbPage className="truncate text-paper">
                              {crumb.label}
                            </BreadcrumbPage>
                          ) : (
                            <BreadcrumbLink
                              asChild
                              className="truncate text-paper/55 hover:text-paper"
                            >
                              <Link href={crumb.href}>{crumb.label}</Link>
                            </BreadcrumbLink>
                          )}
                        </BreadcrumbItem>
                        {!isLast ? (
                          <BreadcrumbSeparator className="text-paper/30" />
                        ) : null}
                      </Fragment>
                    );
                  })}
                </BreadcrumbList>
              </Breadcrumb>
            </>
          ) : null}
        </div>

        <DropdownMenu>
          <DropdownMenuTrigger
            className="flex items-center gap-2 rounded-full outline-none ring-offset-2 ring-offset-ink transition focus-visible:ring-2 focus-visible:ring-brand"
            aria-label="Account menu"
          >
            <Avatar className="h-8 w-8 border border-paper/20">
              {user.avatarUrl ? (
                <AvatarImage src={user.avatarUrl} alt={displayName} />
              ) : null}
              <AvatarFallback className="bg-paper/15 text-[11px] font-medium text-paper">
                {initialsFor(user)}
              </AvatarFallback>
            </Avatar>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-60">
            <DropdownMenuLabel className="font-normal">
              <div className="flex flex-col gap-0.5">
                <span className="truncate font-serif text-base leading-tight">
                  {displayName}
                </span>
                {user.name ? (
                  <span className="truncate text-xs text-muted-foreground">
                    {user.email}
                  </span>
                ) : null}
              </div>
            </DropdownMenuLabel>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              className="cursor-pointer"
              onSelect={(e) => {
                e.preventDefault();
                void signOutAction();
              }}
            >
              <LogOut />
              Sign out
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>

      {secondary}
    </header>
  );
}
