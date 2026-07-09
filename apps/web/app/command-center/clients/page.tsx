import type { Route } from "next";
import Link from "next/link";

import {
  type ClientAttentionOut,
  type ClientSummary,
  getAwareness,
  listClients,
} from "@ov-black/api-client";

import { Button } from "@/components/ui/button";

import { AttentionBadge } from "../_components/attention";
import {
  EmptyNote,
  ErrorBanner,
  InvitePill,
  Panel,
  relativeDay,
} from "../_components/panels";
import { CursorPager } from "../_components/table/CursorPager";
import { type ColumnDef, DataTable } from "../_components/table/DataTable";
import { EmptyState } from "../_components/table/EmptyState";
import { SortHeader } from "../_components/table/SortHeader";
import { TableToolbar } from "../_components/table/TableToolbar";
import { InviteActions } from "../_components/invite-actions";
import { advisorApi } from "../_lib/api";
import {
  type SearchParamsShape,
  type TableParams,
  parseTableParams,
} from "../_lib/tableParams";

// Always render per-request — the advisor's roster must never be cached
// across sessions.
export const dynamic = "force-dynamic";

const BASE = "/command-center/clients" as Route;
const PARAMS_CONFIG = {
  statuses: ["uninvited", "pending", "active"],
  sorts: ["created_at", "full_name"],
} as const;

export default async function ClientsPage({
  searchParams,
}: {
  searchParams: Promise<SearchParamsShape>;
}) {
  const params = parseTableParams(await searchParams, PARAMS_CONFIG);
  const api = await advisorApi();

  const [result, awarenessResult] = await Promise.all([
    listClients(api, {
      ...(params.q ? { q: params.q } : {}),
      ...(params.status ? { status: params.status as "uninvited" | "pending" | "active" } : {}),
      ...(params.sort ? { sort: params.sort as "created_at" | "full_name" } : {}),
      ...(params.order ? { order: params.order } : {}),
      ...(params.cursor ? { cursor: params.cursor } : {}),
    }),
    getAwareness(api), // best-effort: a failure just hides badges
  ]);

  const clients = result.ok ? result.clients : [];
  const attentionByClient = new Map<string, ClientAttentionOut>();
  if (awarenessResult.ok) {
    for (const c of awarenessResult.clients) attentionByClient.set(c.client_id, c);
  }

  return (
    <main className="flex w-full flex-1 flex-col gap-10 px-6 py-10 sm:px-10 sm:py-12">
      <header className="flex flex-col gap-4 border-b border-paper/10 pb-8 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="font-sans text-[10px] uppercase tracking-eyebrow text-paper/55">
            Command Center
          </p>
          <h1 className="mt-3 font-serif text-4xl tracking-tight text-paper sm:text-5xl">
            Clients
          </h1>
        </div>
        <Button asChild variant="brand" className="self-start sm:self-auto">
          <Link href="/command-center/new-client">New Client</Link>
        </Button>
      </header>

      {!result.ok ? (
        <ErrorBanner>Could not load clients — {errorCopy(result.detail)}</ErrorBanner>
      ) : null}

      <Panel aria-label="Client roster">
        <TableToolbar
          base={BASE}
          params={params}
          total={result.ok ? result.total : 0}
          noun="client"
          searchPlaceholder="Search name or email…"
          statuses={[
            { value: "active", label: "Active" },
            { value: "pending", label: "Pending" },
            { value: "uninvited", label: "Uninvited" },
          ]}
        />
        {result.ok && clients.length === 0 ? (
          <EmptyState
            base={BASE}
            params={params}
            emptyTitle="The atelier is quiet."
            emptyHint="Add the first client to begin."
          />
        ) : !result.ok ? (
          <EmptyNote>Nothing to show.</EmptyNote>
        ) : (
          <DataTable
            columns={columns(params, attentionByClient)}
            rows={clients}
            rowKey={(c) => c.id}
          />
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

function columns(
  params: TableParams,
  attentionByClient: Map<string, ClientAttentionOut>,
): ColumnDef<ClientSummary>[] {
  return [
    {
      key: "name",
      header: "Name",
      headerCell: (
        <SortHeader base={BASE} params={params} sortKey="full_name">
          Name
        </SortHeader>
      ),
      cell: (c) => (
        <span className="flex flex-wrap items-center gap-2">
          <Link
            href={`/command-center/clients/${c.id}`}
            className="font-serif text-base tracking-tight text-paper underline-offset-4 focus-visible:underline group-hover:underline"
          >
            {c.full_name}
          </Link>
          <AttentionBadge attention={attentionByClient.get(c.id)} />
        </span>
      ),
    },
    {
      key: "email",
      header: "Email",
      hideBelow: "md",
      className: "truncate text-paper/60",
      cell: (c) => c.email,
    },
    {
      key: "status",
      header: "Status",
      cell: (c) => <InvitePill status={c.access_status} />,
    },
    {
      key: "dossier",
      header: "Dossier",
      hideBelow: "lg",
      className: "text-paper/60",
      cell: (c) => (c.has_dossier ? "On file" : "—"),
    },
    {
      key: "added",
      header: "Added",
      headerCell: (
        <SortHeader base={BASE} params={params} sortKey="created_at" defaultOrder="desc">
          Added
        </SortHeader>
      ),
      className: "whitespace-nowrap text-paper/60",
      cell: (c) => relativeDay(c.created_at),
    },
    {
      key: "signed_in",
      header: "Signed in",
      hideBelow: "lg",
      className: "whitespace-nowrap text-paper/60",
      cell: (c) => (c.accepted_at ? relativeDay(c.accepted_at) : "—"),
    },
    {
      key: "actions",
      header: "",
      align: "right",
      className: "pr-5 sm:pr-7",
      cell: (c) => <InviteActions clientId={c.id} accessStatus={c.access_status} />,
    },
  ];
}

function errorCopy(detail: string): string {
  if (detail === "advisor_only") {
    return "this account does not have advisor access.";
  }
  if (detail === "network_error") {
    return "the API is unreachable. Is it running?";
  }
  return "an unexpected error occurred.";
}
