// Server-rendered sortable column header — a plain <Link> that toggles the
// sort params in the URL (no client JS; the page re-renders server-side).

import type { Route } from "next";
import Link from "next/link";

import {
  type TableParams,
  tableQuery,
  toggleSort,
} from "@/app/command-center/_lib/tableParams";

export function SortHeader({
  base,
  params,
  sortKey,
  defaultOrder = "asc",
  children,
}: {
  base: Route;
  params: TableParams;
  sortKey: string;
  defaultOrder?: "asc" | "desc";
  children: React.ReactNode;
}) {
  const active = params.sort === sortKey;
  const arrow = !active ? "" : (params.order ?? defaultOrder) === "asc" ? " ↑" : " ↓";
  const href = `${base}${tableQuery(params, toggleSort(params, sortKey, defaultOrder))}` as Route;
  return (
    <Link
      href={href}
      aria-label={`Sort by ${sortKey}`}
      className={`transition-colors hover:text-paper ${active ? "text-paper" : ""}`}
    >
      {children}
      <span aria-hidden>{arrow}</span>
    </Link>
  );
}
