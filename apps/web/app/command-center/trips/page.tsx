import type { Route } from "next";
import Link from "next/link";

import {
  type AdvisorItinerarySummary,
  type DisplayStatus,
  listAdvisorItineraries,
} from "@ov-black/api-client";

import {
  EmptyNote,
  ErrorBanner,
  Panel,
  StatusPill,
  relativeDay,
} from "../_components/panels";
import { CursorPager } from "../_components/table/CursorPager";
import { type ColumnDef, DataTable } from "../_components/table/DataTable";
import { EmptyState } from "../_components/table/EmptyState";
import { SortHeader } from "../_components/table/SortHeader";
import { TableToolbar } from "../_components/table/TableToolbar";
import { advisorApi } from "../_lib/api";
import {
  type SearchParamsShape,
  type TableParams,
  parseTableParams,
} from "../_lib/tableParams";

// The pipeline roster (Wave F): every trip across the advisor's clients as a
// first-class searchable surface — until now trips only existed as an
// unpaginated table on the dashboard. Rows deep-link into the itinerary
// studio; the brand dot marks trips carrying an open-state awareness signal.
export const dynamic = "force-dynamic";

const BASE = "/command-center/trips" as Route;
const PARAMS_CONFIG = {
  statuses: ["in_studio", "with_traveler", "approved"],
  sorts: ["updated_at", "created_at", "title"],
} as const;

export default async function TripsPage({
  searchParams,
}: {
  searchParams: Promise<SearchParamsShape>;
}) {
  const params = parseTableParams(await searchParams, PARAMS_CONFIG);
  const api = await advisorApi();

  const result = await listAdvisorItineraries(api, {
    ...(params.q ? { q: params.q } : {}),
    ...(params.status ? { status: params.status as DisplayStatus } : {}),
    ...(params.sort
      ? { sort: params.sort as "updated_at" | "created_at" | "title" }
      : {}),
    ...(params.order ? { order: params.order } : {}),
    ...(params.cursor ? { cursor: params.cursor } : {}),
  });

  const trips = result.ok ? result.itineraries : [];

  return (
    <main className="flex w-full flex-1 flex-col gap-10 px-6 py-10 sm:px-10 sm:py-12">
      <header className="border-b border-paper/10 pb-8">
        <p className="font-sans text-[10px] uppercase tracking-eyebrow text-paper/55">
          Command Center
        </p>
        <h1 className="mt-3 font-serif text-4xl tracking-tight text-paper sm:text-5xl">
          Trips
        </h1>
      </header>

      {!result.ok ? (
        <ErrorBanner>Could not load trips — the API is unreachable or this account lacks advisor access.</ErrorBanner>
      ) : null}

      <Panel aria-label="Trip roster">
        <TableToolbar
          base={BASE}
          params={params}
          total={result.ok ? result.total : 0}
          noun="trip"
          searchPlaceholder="Search title or client…"
          statuses={[
            { value: "in_studio", label: "In studio" },
            { value: "with_traveler", label: "With traveler" },
            { value: "approved", label: "Approved" },
          ]}
        />
        {result.ok && trips.length === 0 ? (
          <EmptyState
            base={BASE}
            params={params}
            emptyTitle="No itineraries yet."
            emptyHint="They appear as soon as a client's first session is opened."
          />
        ) : !result.ok ? (
          <EmptyNote>Nothing to show.</EmptyNote>
        ) : (
          <DataTable columns={columns(params)} rows={trips} rowKey={(t) => t.id} />
        )}
        <CursorPager
          base={BASE}
          params={params}
          nextCursor={result.ok ? result.nextCursor : null}
        />
      </Panel>
    </main>
  );
}

function columns(params: TableParams): ColumnDef<AdvisorItinerarySummary>[] {
  return [
    {
      key: "title",
      header: "Title",
      headerCell: (
        <SortHeader base={BASE} params={params} sortKey="title">
          Title
        </SortHeader>
      ),
      cell: (t) => (
        <span className="flex items-center gap-2">
          {t.needs_attention ? (
            <span
              aria-label="Needs attention"
              title="Needs attention"
              className="inline-block h-1.5 w-1.5 shrink-0 rounded-full bg-brand"
            />
          ) : null}
          <Link
            href={`/itinerary/${t.id}`}
            className="font-serif text-base tracking-tight text-paper underline-offset-4 focus-visible:underline group-hover:underline"
          >
            {t.title || "Untitled draft"}
          </Link>
        </span>
      ),
    },
    {
      key: "client",
      header: "Client",
      className: "text-paper/60",
      cell: (t) => (
        <Link
          href={`/command-center/clients/${t.client.id}`}
          className="underline-offset-4 hover:text-paper hover:underline"
        >
          {t.client.full_name}
        </Link>
      ),
    },
    {
      key: "status",
      header: "Status",
      cell: (t) => <StatusPill status={t.status} />,
    },
    {
      key: "activity",
      header: "Activity",
      headerCell: (
        <SortHeader base={BASE} params={params} sortKey="updated_at" defaultOrder="desc">
          Activity
        </SortHeader>
      ),
      className: "whitespace-nowrap text-paper/60",
      cell: (t) => relativeDay(t.last_activity_at),
    },
    {
      key: "open",
      header: "",
      align: "right",
      className: "pr-5 sm:pr-7 text-paper/35",
      cell: () => <span aria-hidden>→</span>,
    },
  ];
}
