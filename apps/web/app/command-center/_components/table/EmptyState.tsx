// Roster empty states (Wave F): "nothing exists" and "nothing matches" are
// different sentences — the second offers a way out (clear the search).

import type { Route } from "next";
import Link from "next/link";

import { type TableParams, tableQuery } from "@/app/command-center/_lib/tableParams";

export function EmptyState({
  base,
  params,
  emptyTitle,
  emptyHint,
}: {
  base: Route;
  params: TableParams;
  emptyTitle: string;
  emptyHint?: string;
}) {
  const filtered = params.q !== "" || params.status !== null;
  if (filtered) {
    return (
      <div className="flex flex-col items-start gap-2 py-8">
        <p className="font-serif text-xl text-paper/85">
          Nothing matches{params.q ? ` “${params.q}”` : " that filter"}.
        </p>
        <Link
          href={`${base}${tableQuery(params, { q: "", status: null })}` as Route}
          className="font-sans text-[11px] uppercase tracking-[0.2em] text-brand transition-opacity hover:opacity-80"
        >
          Clear search
        </Link>
      </div>
    );
  }
  return (
    <div className="flex flex-col items-start gap-2 py-8">
      <p className="font-serif text-xl text-paper/85">{emptyTitle}</p>
      {emptyHint ? <p className="font-sans text-sm text-paper/50">{emptyHint}</p> : null}
    </div>
  );
}

export function TableSkeleton({ rows = 8 }: { rows?: number }) {
  return (
    <div aria-hidden className="flex animate-pulse flex-col gap-0 pt-2">
      <div className="mb-3 flex items-center gap-3">
        <div className="h-9 w-64 rounded-md bg-paper/6" />
        <div className="ml-auto h-4 w-20 rounded bg-paper/6" />
      </div>
      <div className="border-y border-paper/10">
        {Array.from({ length: rows }, (_, i) => (
          <div key={i} className="flex items-center gap-6 border-b border-paper/8 px-2 py-3.5">
            <div className="h-4 w-48 rounded bg-paper/8" />
            <div className="hidden h-3 w-40 rounded bg-paper/6 md:block" />
            <div className="ml-auto h-4 w-16 rounded-full bg-paper/6" />
          </div>
        ))}
      </div>
    </div>
  );
}
