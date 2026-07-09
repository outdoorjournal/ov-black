"use client";

// The roster toolbar (Wave F): debounced search writing to the URL (the
// single source of table state) + enumerable status filters as links + the
// result count. `useTransition` keeps the SSR round-trip visible — the mono
// "searching…" hint — without any client-side data fetching.

import type { Route } from "next";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState, useTransition } from "react";

import { type TableParams, tableQuery } from "@/app/command-center/_lib/tableParams";
import { Input } from "@/components/ui/input";

const SEARCH_DEBOUNCE_MS = 300;

export type StatusOption = { value: string; label: string };

export function TableToolbar({
  base,
  params,
  total,
  noun,
  searchPlaceholder,
  statuses = [],
}: {
  base: Route;
  params: TableParams;
  total: number;
  /** "client" / "trip" / "invoice" — pluralized for the count. */
  noun: string;
  searchPlaceholder: string;
  statuses?: StatusOption[];
}) {
  const router = useRouter();
  const [isPending, startTransition] = useTransition();
  const [draft, setDraft] = useState(params.q);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // A back/forward navigation changes params.q under us — resync the input.
  useEffect(() => {
    setDraft(params.q);
  }, [params.q]);

  useEffect(() => {
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
  }, []);

  const search = (value: string) => {
    setDraft(value);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      startTransition(() => {
        router.replace(`${base}${tableQuery(params, { q: value })}` as Route, {
          scroll: false,
        });
      });
    }, SEARCH_DEBOUNCE_MS);
  };

  return (
    <div className="flex flex-wrap items-center gap-3">
      <div className="relative w-full max-w-xs">
        <Input
          type="search"
          value={draft}
          onChange={(e) => search(e.target.value)}
          placeholder={searchPlaceholder}
          aria-label={searchPlaceholder}
          className="h-9 border-paper/15 bg-paper/5 font-sans text-sm text-paper placeholder:text-paper/35"
        />
      </div>

      {statuses.length > 0 ? (
        <div className="flex items-center gap-1" role="group" aria-label="Filter by status">
          <FilterPill
            href={`${base}${tableQuery(params, { status: null })}` as Route}
            active={params.status === null}
          >
            All
          </FilterPill>
          {statuses.map((s) => (
            <FilterPill
              key={s.value}
              href={`${base}${tableQuery(params, { status: s.value })}` as Route}
              active={params.status === s.value}
            >
              {s.label}
            </FilterPill>
          ))}
        </div>
      ) : null}

      <span className="ml-auto font-mono text-[11px] uppercase tracking-[0.12em] text-paper/45">
        {isPending ? "searching…" : `${total} ${noun}${total === 1 ? "" : "s"}`}
      </span>
    </div>
  );
}

function FilterPill({
  href,
  active,
  children,
}: {
  href: Route;
  active: boolean;
  children: React.ReactNode;
}) {
  return (
    <Link
      href={href}
      replace
      scroll={false}
      aria-current={active ? "true" : undefined}
      className={
        "rounded-full border px-2.5 py-1 font-sans text-[10px] uppercase tracking-[0.2em] transition-colors " +
        (active
          ? "border-paper/50 bg-paper/10 text-paper"
          : "border-paper/15 text-paper/50 hover:border-paper/30 hover:text-paper")
      }
    >
      {children}
    </Link>
  );
}
