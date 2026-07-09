import Link from "next/link";
import { redirect } from "next/navigation";

import {
  type AccessStatus,
  type AdvisorItinerarySummary,
  type ClientAttentionOut,
  type ClientSummary,
  createApiClient,
  getAwareness,
  listAdvisorItineraries,
  listClients,
} from "@ov-black/api-client";

import { Button } from "@/components/ui/button";
import { publicEnv } from "@/lib/env";
import { createServerSupabase } from "@/lib/supabase/server";

import { AttentionBadge } from "./_components/attention";

export const dynamic = "force-dynamic";

export default async function CommandCenterPage() {
  const supabase = await createServerSupabase();

  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    redirect("/");
  }

  const {
    data: { session },
  } = await supabase.auth.getSession();
  const accessToken = session?.access_token;

  const { apiBaseUrl } = publicEnv();
  const api = createApiClient(
    accessToken ? { baseUrl: apiBaseUrl, accessToken } : { baseUrl: apiBaseUrl },
  );

  // Three reads in parallel — all advisor-only, identical-key. Awareness
  // (ADV-14) is best-effort: a failure just means no badges, never a broken page.
  const [clientsResult, itinerariesResult, awarenessResult] = await Promise.all([
    listClients(api),
    listAdvisorItineraries(api),
    getAwareness(api),
  ]);

  const clients = clientsResult.ok ? clientsResult.clients : [];
  const itineraries = itinerariesResult.ok ? itinerariesResult.itineraries : [];

  // client_id → its attention rollup, plus the set of itineraries with an
  // actionable (open-state) signal so we can badge the itinerary roster too.
  const attentionByClient = new Map<string, ClientAttentionOut>();
  const attentionItineraries = new Set<string>();
  if (awarenessResult.ok) {
    for (const c of awarenessResult.clients) {
      attentionByClient.set(c.client_id, c);
      if (!c.needs_attention) continue;
      for (const item of c.items) {
        if (
          item.itinerary_id &&
          (item.kind === "changes_requested" || item.kind === "unread_messages")
        ) {
          attentionItineraries.add(item.itinerary_id);
        }
      }
    }
  }

  const today = new Intl.DateTimeFormat("en-US", {
    weekday: "long",
    month: "long",
    day: "numeric",
    year: "numeric",
  }).format(new Date());

  const metrics = summarize(clients, itineraries);

  return (
    <main className="flex w-full flex-1 flex-col gap-12 bg-ink px-6 py-10 text-paper sm:px-10 sm:py-12">
      <header className="flex flex-col gap-4 border-b border-paper/10 pb-8 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="font-sans text-[10px] uppercase tracking-eyebrow text-paper/55">
            Command Center · {today}
          </p>
          <h1 className="mt-3 font-serif text-4xl tracking-tight text-paper sm:text-5xl">
            The atelier
          </h1>
          <p className="mt-3 max-w-xl font-sans text-sm leading-relaxed text-paper/70">
            Active itineraries, the roster, and what wants attention — at a
            glance.
          </p>
        </div>
        <Button asChild variant="brand" className="self-start sm:self-auto">
          <Link href="/command-center/new-client">New Client</Link>
        </Button>
      </header>

      {!clientsResult.ok ? (
        <ErrorBanner>
          Could not load roster — {errorCopy(clientsResult.detail)}
        </ErrorBanner>
      ) : null}
      {!itinerariesResult.ok ? (
        <ErrorBanner>
          Could not load itineraries — {errorCopy(itinerariesResult.detail)}
        </ErrorBanner>
      ) : null}

      <section aria-labelledby="metrics-heading">
        <h2 id="metrics-heading" className="sr-only">
          Roster snapshot
        </h2>
        <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-md border border-paper/10 bg-paper/6 sm:grid-cols-5">
          <Metric label="Clients" value={metrics.total} />
          <Metric label="Active" value={metrics.active} />
          <Metric label="Awaiting sign-in" value={metrics.pending} />
          <Metric label="Itineraries" value={metrics.itineraries_total} />
          <Metric label="In draft" value={metrics.itineraries_draft} />
        </dl>
      </section>

      <Panel aria-labelledby="itineraries-heading">
        <SectionHeader
          id="itineraries-heading"
          title="Itineraries"
          eyebrow={`${itineraries.length} on the slate`}
        />
        {itineraries.length === 0 ? (
          <EmptyNote>No itineraries yet — they appear as soon as a client&rsquo;s first session is opened.</EmptyNote>
        ) : (
          <ItinerariesTable rows={itineraries} attentionItineraries={attentionItineraries} />
        )}
      </Panel>

      <Panel aria-labelledby="clients-heading">
        <SectionHeader
          id="clients-heading"
          title="Clients"
          eyebrow={`${clients.length} on the roster`}
        />
        {clients.length === 0 ? (
          <EmptyNote>
            The atelier is quiet. Add the first client to begin.
          </EmptyNote>
        ) : (
          <ClientsTable rows={clients} attentionByClient={attentionByClient} />
        )}
      </Panel>
    </main>
  );
}

function Panel({
  children,
  ...rest
}: {
  children: React.ReactNode;
} & React.HTMLAttributes<HTMLElement>) {
  return (
    <section
      {...rest}
      className="flex flex-col gap-4 rounded-md border border-paper/10 bg-paper/5 p-5 sm:p-7"
    >
      {children}
    </section>
  );
}

function SectionHeader({
  id,
  title,
  eyebrow,
}: {
  id: string;
  title: string;
  eyebrow: string;
}) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-b border-paper/10 pb-3">
      <h2
        id={id}
        className="font-serif text-2xl tracking-tight text-paper"
      >
        {title}
      </h2>
      <span className="font-sans text-[10px] uppercase tracking-label text-paper/55">
        {eyebrow}
      </span>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div className="bg-ink px-5 py-6">
      <p className="font-serif text-4xl tracking-tight text-paper">{value}</p>
      <p className="mt-2 font-sans text-[10px] uppercase tracking-label text-paper/55">
        {label}
      </p>
    </div>
  );
}

function ItinerariesTable({
  rows,
  attentionItineraries,
}: {
  rows: AdvisorItinerarySummary[];
  attentionItineraries: Set<string>;
}) {
  return (
    <div className="-mx-5 overflow-x-auto sm:-mx-7">
      <table className="w-full border-y border-paper/10 text-left font-sans text-sm">
        <thead className="bg-paper/6 text-[10px] uppercase tracking-label text-paper/55">
          <tr>
            <Th className="pl-5 sm:pl-7">Title</Th>
            <Th>Client</Th>
            <Th>Status</Th>
            <Th>Activity</Th>
            <Th className="pr-5 text-right sm:pr-7" />
          </tr>
        </thead>
        <tbody className="divide-y divide-paper/10">
          {rows.map((row) => (
            <tr
              key={row.id}
              className="group transition-colors hover:bg-paper/8"
            >
              <Td className="pl-5 sm:pl-7">
                <span className="flex items-center gap-2">
                  {attentionItineraries.has(row.id) ? (
                    <span
                      aria-label="Needs attention"
                      title="Needs attention"
                      className="inline-block h-1.5 w-1.5 shrink-0 rounded-full bg-brand"
                    />
                  ) : null}
                  <Link
                    href={`/itinerary/${row.id}`}
                    className="font-serif text-base tracking-tight text-paper underline-offset-4 group-hover:underline"
                  >
                    {row.title || "Untitled draft"}
                  </Link>
                </span>
              </Td>
              <Td>
                <Link
                  href={`/command-center/clients/${row.client.id}`}
                  className="text-paper/80 underline-offset-4 hover:text-paper hover:underline"
                >
                  {row.client.full_name}
                </Link>
              </Td>
              <Td>
                <StatusPill status={row.status} />
              </Td>
              <Td className="whitespace-nowrap text-paper/60">
                {relativeDay(row.last_activity_at)}
              </Td>
              <Td className="pr-5 text-right text-paper/40 sm:pr-7">
                <span aria-hidden>→</span>
              </Td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ClientsTable({
  rows,
  attentionByClient,
}: {
  rows: ClientSummary[];
  attentionByClient: Map<string, ClientAttentionOut>;
}) {
  return (
    <div className="-mx-5 overflow-x-auto sm:-mx-7">
      <table className="w-full border-y border-paper/10 text-left font-sans text-sm">
        <thead className="bg-paper/6 text-[10px] uppercase tracking-label text-paper/55">
          <tr>
            <Th className="pl-6 sm:pl-10">Name</Th>
            <Th className="hidden md:table-cell">Email</Th>
            <Th>Status</Th>
            <Th>Dossier</Th>
            <Th>Joined</Th>
            <Th className="pr-5 text-right sm:pr-7" />
          </tr>
        </thead>
        <tbody className="divide-y divide-paper/10">
          {rows.map((c) => (
            <tr
              key={c.id}
              className="group transition-colors hover:bg-paper/8"
            >
              <Td className="pl-5 sm:pl-7">
                <span className="flex flex-wrap items-center gap-2">
                  <Link
                    href={`/command-center/clients/${c.id}`}
                    className="font-serif text-base tracking-tight text-paper underline-offset-4 group-hover:underline"
                  >
                    {c.full_name}
                  </Link>
                  <AttentionBadge attention={attentionByClient.get(c.id)} />
                </span>
              </Td>
              <Td className="hidden truncate text-paper/60 md:table-cell">
                {c.email}
              </Td>
              <Td>
                <InvitePill status={c.access_status} />
              </Td>
              <Td className="text-paper/60">{c.has_dossier ? "On file" : "—"}</Td>
              <Td className="whitespace-nowrap text-paper/60">
                {relativeDay(c.created_at)}
              </Td>
              <Td className="pr-5 text-right text-paper/40 sm:pr-7">
                <span aria-hidden>→</span>
              </Td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Th({
  children,
  className = "",
}: {
  children?: React.ReactNode;
  className?: string;
}) {
  return (
    <th
      scope="col"
      className={`whitespace-nowrap px-3 py-3 font-sans font-normal ${className}`}
    >
      {children}
    </th>
  );
}

function Td({
  children,
  className = "",
}: {
  children?: React.ReactNode;
  className?: string;
}) {
  return <td className={`px-3 py-3 align-middle ${className}`}>{children}</td>;
}

function StatusPill({ status }: { status: AdvisorItinerarySummary["status"] }) {
  const tone =
    status === "approved"
      ? "border-paper/40 text-paper"
      : "border-paper/15 text-paper/65";
  return (
    <span
      className={`inline-block rounded-full border px-2 py-0.5 font-sans text-[10px] uppercase tracking-[0.25em] ${tone}`}
    >
      {status}
    </span>
  );
}

function InvitePill({ status }: { status: AccessStatus }) {
  const copy =
    status === "active"
      ? "Active"
      : status === "pending"
        ? "Pending"
        : "Uninvited";
  const tone =
    status === "active"
      ? "border-paper/40 text-paper"
      : status === "pending"
        ? "border-brand/40 text-brand"
        : "border-paper/20 text-paper/50";
  return (
    <span
      className={`inline-block rounded-full border px-2 py-0.5 font-sans text-[10px] uppercase tracking-[0.25em] ${tone}`}
    >
      {copy}
    </span>
  );
}

function EmptyNote({ children }: { children: React.ReactNode }) {
  return (
    <p className="font-sans text-sm italic text-paper/55">{children}</p>
  );
}

function ErrorBanner({ children }: { children: React.ReactNode }) {
  return (
    <div className="border border-destructive/40 bg-destructive/10 p-4 font-sans text-sm text-destructive-foreground">
      {children}
    </div>
  );
}

function summarize(
  clients: ClientSummary[],
  itineraries: AdvisorItinerarySummary[],
): {
  total: number;
  active: number;
  pending: number;
  itineraries_total: number;
  itineraries_draft: number;
} {
  let active = 0;
  let pending = 0;
  for (const c of clients) {
    if (c.access_status === "active") active += 1;
    if (c.access_status === "pending") pending += 1;
  }
  let drafts = 0;
  for (const i of itineraries) {
    if (i.status === "draft") drafts += 1;
  }
  return {
    total: clients.length,
    active,
    pending,
    itineraries_total: itineraries.length,
    itineraries_draft: drafts,
  };
}

function relativeDay(iso: string): string {
  const then = new Date(iso);
  const now = new Date();
  const days = Math.floor(
    (now.getTime() - then.getTime()) / (1000 * 60 * 60 * 24),
  );
  if (days <= 0) return "Today";
  if (days === 1) return "Yesterday";
  if (days < 7) return `${days}d ago`;
  if (days < 30) return `${Math.floor(days / 7)}w ago`;
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
  }).format(then);
}

function errorCopy(detail: string): string {
  switch (detail) {
    case "advisor_only":
      return "this workspace is advisor-only.";
    case "network_error":
      return "could not reach the server.";
    default:
      return "try again in a moment.";
  }
}
