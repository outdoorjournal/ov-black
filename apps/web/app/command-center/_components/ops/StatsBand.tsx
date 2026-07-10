// The glance band (Wave F): the portfolio's numbers in one strip, every cell
// a deep link into the surface that explains it. Mono numerals; the LIVE cell
// is the only place the band uses brand.

import type { Route } from "next";
import Link from "next/link";

import type { AdvisorOverviewResponse } from "@ov-black/api-client";

import { money } from "../panels";

export function StatsBand({ overview }: { overview: AdvisorOverviewResponse }) {
  const outstanding = overview.billing.reduce(
    (sum, row) => sum + Number(row.outstanding),
    0,
  );
  const outstandingLabel =
    overview.billing.length === 1 && overview.billing[0]
      ? money(overview.billing[0].outstanding, overview.billing[0].currency)
      : overview.billing.length === 0
        ? "—"
        : `${overview.billing.length} currencies`;

  return (
    <section
      aria-label="Portfolio"
      className="grid grid-cols-2 gap-px overflow-hidden rounded-md border border-paper/10 bg-paper/10 sm:grid-cols-3 lg:grid-cols-6"
    >
      <Cell
        href={"/command-center/clients" as Route}
        value={String(overview.clients.total)}
        label="Clients"
        sub={overview.clients.pending > 0 ? `${overview.clients.pending} pending` : undefined}
      />
      <Cell
        href={"/command-center/trips?status=in_studio" as Route}
        value={String(overview.itineraries.in_studio)}
        label="In the studio"
        sub="in studio"
      />
      <Cell
        href={"/command-center/trips?status=with_traveler" as Route}
        value={String(overview.itineraries.with_traveler)}
        label="With travelers"
        sub="awaiting review"
      />
      <Cell
        href={"/command-center/trips?status=approved" as Route}
        value={String(overview.itineraries.approved)}
        label="Approved"
        sub={
          overview.itineraries.reconcile_requested > 0
            ? `${overview.itineraries.reconcile_requested} reconcile`
            : undefined
        }
      />
      <Cell
        href={"/command-center/money?status=issued" as Route}
        value={outstandingLabel}
        label="Outstanding"
        hot={outstanding > 0}
      />
      <Cell
        value={String(overview.sessions.active)}
        label="Sessions open"
        sub={
          overview.sessions.avg_latency_ms_7d !== null &&
          overview.sessions.avg_latency_ms_7d !== undefined
            ? `${(overview.sessions.avg_latency_ms_7d / 1000).toFixed(1)}s avg`
            : undefined
        }
      />
    </section>
  );
}

function Cell({
  href,
  value,
  label,
  sub,
  hot = false,
}: {
  href?: Route;
  value: string;
  label: string;
  sub?: string | undefined;
  hot?: boolean;
}) {
  const body = (
    <>
      <p className={`font-mono text-3xl tracking-tight ${hot ? "text-brand" : "text-paper"}`}>
        {value}
      </p>
      <p className="mt-1.5 font-sans text-[10px] uppercase tracking-label text-paper/55">
        {label}
      </p>
      {sub ? (
        <p className="mt-0.5 font-mono text-[10px] text-paper/40">{sub}</p>
      ) : null}
    </>
  );
  if (href) {
    return (
      <Link href={href} className="bg-ink px-5 py-5 transition-colors hover:bg-paper/5">
        {body}
      </Link>
    );
  }
  return <div className="bg-ink px-5 py-5">{body}</div>;
}
