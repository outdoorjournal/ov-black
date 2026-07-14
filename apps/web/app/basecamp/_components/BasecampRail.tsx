"use client";

// Basecamp's slice of the shared AppRail (M006/PS7) — the same left nav the
// itinerary shell uses, so the two surfaces navigate identically. Basecamp is
// home, so there is no back item; the destinations are the account surfaces
// (Home · Party · Vault · Invoices) that used to be inline "Your …" links.

import type { Route } from "next";
import { usePathname } from "next/navigation";
import { BookOpen, Home, Receipt, Users, Vault } from "lucide-react";

import { AppRail, type RailItem } from "@/app/_components/shell/AppRail";

export function BasecampRail() {
  const pathname = usePathname() ?? "";

  const items: RailItem[] = [
    {
      href: "/basecamp" as Route,
      label: "Home",
      active: pathname === "/basecamp",
      icon: <Home size={18} strokeWidth={1.6} aria-hidden />,
    },
    {
      href: "/basecamp/party" as Route,
      label: "Party",
      active: pathname.startsWith("/basecamp/party"),
      icon: <Users size={18} strokeWidth={1.6} aria-hidden />,
    },
    {
      href: "/basecamp/reading" as Route,
      label: "Reading",
      active: pathname.startsWith("/basecamp/reading"),
      icon: <BookOpen size={18} strokeWidth={1.6} aria-hidden />,
    },
    {
      href: "/basecamp/vault" as Route,
      label: "Vault",
      active: pathname.startsWith("/basecamp/vault"),
      icon: <Vault size={18} strokeWidth={1.6} aria-hidden />,
    },
    {
      href: "/basecamp/invoices" as Route,
      label: "Invoices",
      active: pathname.startsWith("/basecamp/invoices"),
      icon: <Receipt size={18} strokeWidth={1.6} aria-hidden />,
    },
  ];

  // Basecamp scrolls the document (unlike the itinerary shell's pinned
  // viewport), so the rail pins itself below the sticky masthead — the same
  // top-14 convention as the concierge sidebar in BasecampShell.
  return (
    <AppRail
      ariaLabel="Basecamp"
      items={items}
      className="md:sticky md:top-14 md:h-[calc(100dvh-3.5rem)]"
    />
  );
}
