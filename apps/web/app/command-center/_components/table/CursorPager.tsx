// Keyset pager (Wave F) — server-rendered links. Keyset paging is forward-
// only; "back" is the browser's history (or the first-page link, which just
// clears the cursor).

import type { Route } from "next";
import Link from "next/link";

import { type TableParams, tableQuery } from "@/app/command-center/_lib/tableParams";

export function CursorPager({
  base,
  params,
  nextCursor,
}: {
  base: Route;
  params: TableParams;
  nextCursor: string | null;
}) {
  if (!nextCursor && !params.cursor) return null;
  return (
    <nav aria-label="Pagination" className="flex items-center justify-between pt-1">
      {params.cursor ? (
        <Link
          href={`${base}${tableQuery(params, { cursor: null })}` as Route}
          className="font-sans text-[11px] uppercase tracking-[0.2em] text-paper/50 transition-colors hover:text-paper"
        >
          ‹ First page
        </Link>
      ) : (
        <span />
      )}
      {nextCursor ? (
        <Link
          href={`${base}${tableQuery(params, { cursor: nextCursor })}` as Route}
          className="font-sans text-[11px] uppercase tracking-[0.2em] text-paper/70 transition-colors hover:text-paper"
        >
          Older ›
        </Link>
      ) : null}
    </nav>
  );
}
