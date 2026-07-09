import type { Route } from "next";
import Link from "next/link";

import { type MoneyRowOut, getAdvisorMoney } from "@ov-black/api-client";

import {
  EmptyNote,
  ErrorBanner,
  InvoiceStatusPill,
  Panel,
  money,
  relativeDay,
} from "../_components/panels";
import { CursorPager } from "../_components/table/CursorPager";
import { type ColumnDef, DataTable } from "../_components/table/DataTable";
import { EmptyState } from "../_components/table/EmptyState";
import { TableToolbar } from "../_components/table/TableToolbar";
import { advisorApi } from "../_lib/api";
import {
  type SearchParamsShape,
  parseTableParams,
} from "../_lib/tableParams";

// The Money screen (Wave F, closes the advisor-plan §6 cross-trip roster
// follow-up): every invoice across the roster with the client/trip identity
// it needs to be legible outside its itinerary, under a per-currency position
// band that always reflects the whole roster (not the page). Rows deep-link
// to the trip's invoicing cockpit.
export const dynamic = "force-dynamic";

const BASE = "/command-center/money" as Route;
const PARAMS_CONFIG = {
  statuses: ["draft", "issued", "paid", "void"],
  sorts: [],
} as const;

export default async function MoneyPage({
  searchParams,
}: {
  searchParams: Promise<SearchParamsShape>;
}) {
  const params = parseTableParams(await searchParams, PARAMS_CONFIG);
  const api = await advisorApi();

  const result = await getAdvisorMoney(api, {
    ...(params.status
      ? { status: params.status as "draft" | "issued" | "paid" | "void" }
      : {}),
    ...(params.cursor ? { cursor: params.cursor } : {}),
  });

  const invoices = result.ok ? result.invoices : [];
  const summary = result.ok ? result.summary : [];

  return (
    <main className="flex w-full flex-1 flex-col gap-10 px-6 py-10 sm:px-10 sm:py-12">
      <header className="border-b border-paper/10 pb-8">
        <p className="font-sans text-[10px] uppercase tracking-eyebrow text-paper/55">
          Command Center
        </p>
        <h1 className="mt-3 font-serif text-4xl tracking-tight text-paper sm:text-5xl">
          Money
        </h1>
      </header>

      {!result.ok ? (
        <ErrorBanner>Could not load the invoice roster — the API is unreachable or this account lacks advisor access.</ErrorBanner>
      ) : null}

      {summary.length > 0 ? (
        <section
          aria-label="Money position"
          className="grid grid-cols-1 gap-px overflow-hidden rounded-md border border-paper/10 bg-paper/10 sm:grid-cols-3"
        >
          {summary.map((row) => (
            <div key={row.currency} className="contents">
              <PositionCell label={`Invoiced · ${row.currency}`} value={money(row.invoiced, row.currency)} />
              <PositionCell label={`Paid · ${row.currency}`} value={money(row.paid, row.currency)} />
              <PositionCell
                label={`Outstanding · ${row.currency}`}
                value={money(row.outstanding, row.currency)}
                hot={Number(row.outstanding) > 0}
              />
            </div>
          ))}
        </section>
      ) : null}

      <Panel aria-label="Invoice roster">
        <TableToolbar
          base={BASE}
          params={params}
          total={invoices.length}
          noun="invoice"
          searchPlaceholder="Filter by status →"
          statuses={[
            { value: "issued", label: "Issued" },
            { value: "paid", label: "Paid" },
            { value: "draft", label: "Draft" },
            { value: "void", label: "Void" },
          ]}
        />
        {result.ok && invoices.length === 0 ? (
          <EmptyState
            base={BASE}
            params={params}
            emptyTitle="No invoices yet."
            emptyHint="Bill a trip from its invoicing cockpit and it appears here."
          />
        ) : !result.ok ? (
          <EmptyNote>Nothing to show.</EmptyNote>
        ) : (
          <DataTable columns={COLUMNS} rows={invoices} rowKey={(r) => r.id} />
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

function PositionCell({
  label,
  value,
  hot = false,
}: {
  label: string;
  value: string;
  hot?: boolean;
}) {
  return (
    <div className="bg-ink px-5 py-5">
      <p className={`font-mono text-2xl tracking-tight ${hot ? "text-brand" : "text-paper"}`}>
        {value}
      </p>
      <p className="mt-1.5 font-sans text-[10px] uppercase tracking-label text-paper/55">
        {label}
      </p>
    </div>
  );
}

const COLUMNS: ColumnDef<MoneyRowOut>[] = [
  {
    key: "client",
    header: "Client",
    cell: (r) => (
      <Link
        href={`/command-center/clients/${r.client_id}`}
        className="font-serif text-base tracking-tight text-paper underline-offset-4 focus-visible:underline group-hover:underline"
      >
        {r.client_name}
      </Link>
    ),
  },
  {
    key: "trip",
    header: "Trip",
    className: "text-paper/60",
    cell: (r) => (
      <Link
        href={`/itinerary/${r.itinerary_id}`}
        className="underline-offset-4 hover:text-paper hover:underline"
      >
        {r.itinerary_title || "Untitled draft"}
      </Link>
    ),
  },
  {
    key: "label",
    header: "Invoice",
    hideBelow: "md",
    className: "text-paper/60",
    cell: (r) => r.label || "—",
  },
  {
    key: "status",
    header: "Status",
    cell: (r) => <InvoiceStatusPill status={r.status} />,
  },
  {
    key: "total",
    header: "Total",
    align: "right",
    className: "whitespace-nowrap font-mono text-paper",
    cell: (r) => money(r.total, r.currency),
  },
  {
    key: "settled",
    header: "Settled",
    align: "right",
    hideBelow: "lg",
    className: "whitespace-nowrap font-mono text-paper/60",
    cell: (r) => money(r.settled, r.currency),
  },
  {
    key: "issued",
    header: "Issued",
    hideBelow: "lg",
    className: "whitespace-nowrap text-paper/60",
    cell: (r) => (r.issued_at ? relativeDay(r.issued_at) : "—"),
  },
];
