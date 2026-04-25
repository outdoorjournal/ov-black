import Link from "next/link";
import { redirect } from "next/navigation";

import {
  type ClientSummary,
  createApiClient,
  type InviteStatus,
  listClients,
} from "@ov-black/api-client";

import { Button } from "@/components/ui/button";
import { publicEnv } from "@/lib/env";
import { createServerSupabase } from "@/lib/supabase/server";

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
  const result = await listClients(api);
  const clients = result.ok ? result.clients : [];

  const today = new Intl.DateTimeFormat("en-US", {
    weekday: "long",
    month: "long",
    day: "numeric",
    year: "numeric",
  }).format(new Date());

  const metrics = summarize(clients);
  const needsAttention = clients
    .filter((c) => c.invite_status === "pending")
    .slice(0, 5);
  const recent = [...clients]
    .sort((a, b) => b.created_at.localeCompare(a.created_at))
    .slice(0, 5);

  return (
    <main className="mx-auto flex w-full max-w-6xl flex-col gap-16 px-6 py-12 sm:px-10 sm:py-16">
      <header className="flex flex-col gap-6 border-b border-ink/10 pb-10 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="font-sans text-[10px] uppercase tracking-[0.4em] text-ink/55">
            Command Center · {today}
          </p>
          <h1 className="mt-4 font-serif text-5xl tracking-tight text-ink sm:text-6xl">
            Overview
          </h1>
          <p className="mt-4 max-w-xl font-sans text-sm leading-relaxed text-ink/70">
            The atelier at a glance — outstanding invites, latest
            acquaintances, and the shape of the roster. A feed, a map, and
            charts will settle in here as the season unfolds.
          </p>
        </div>
        <Button asChild>
          <Link href="/command-center/new-client">New Client</Link>
        </Button>
      </header>

      {!result.ok ? (
        <div className="border border-destructive/40 bg-destructive/5 p-6 text-sm text-destructive">
          Could not load roster — {errorCopy(result.detail)}
        </div>
      ) : null}

      <section aria-labelledby="metrics-heading">
        <h2
          id="metrics-heading"
          className="sr-only"
        >
          Roster snapshot
        </h2>
        <dl className="grid grid-cols-2 gap-px overflow-hidden border border-ink/10 bg-ink/10 sm:grid-cols-4">
          <Metric label="On the roster" value={metrics.total} />
          <Metric label="Active members" value={metrics.active} />
          <Metric label="Invites pending" value={metrics.pending} />
          <Metric label="Dossiers" value={metrics.dossiers} />
        </dl>
      </section>

      <section
        aria-labelledby="attention-heading"
        className="grid gap-10 lg:grid-cols-2 lg:gap-12"
      >
        <div>
          <div className="flex items-baseline justify-between gap-4 border-b border-ink/10 pb-3">
            <h2
              id="attention-heading"
              className="font-serif text-2xl tracking-tight text-ink"
            >
              Needs attention
            </h2>
            <Link
              href="/command-center/clients"
              className="font-sans text-[10px] uppercase tracking-[0.3em] text-ink/55 transition-colors hover:text-ink"
            >
              View all →
            </Link>
          </div>
          {needsAttention.length === 0 ? (
            <EmptyNote>Every invite has been answered — for now.</EmptyNote>
          ) : (
            <ul className="mt-6 flex flex-col divide-y divide-ink/10">
              {needsAttention.map((c) => (
                <ClientLine
                  key={c.id}
                  client={c}
                  eyebrow={inviteBadgeCopy(c.invite_status)}
                />
              ))}
            </ul>
          )}
        </div>

        <div>
          <div className="flex items-baseline justify-between gap-4 border-b border-ink/10 pb-3">
            <h2
              id="recent-heading"
              className="font-serif text-2xl tracking-tight text-ink"
            >
              Recently acquainted
            </h2>
            <Link
              href="/command-center/clients"
              className="font-sans text-[10px] uppercase tracking-[0.3em] text-ink/55 transition-colors hover:text-ink"
            >
              View all →
            </Link>
          </div>
          {recent.length === 0 ? (
            <EmptyNote>
              The atelier is quiet. Invite the first client to begin.
            </EmptyNote>
          ) : (
            <ul className="mt-6 flex flex-col divide-y divide-ink/10">
              {recent.map((c) => (
                <ClientLine
                  key={c.id}
                  client={c}
                  eyebrow={relativeDay(c.created_at)}
                />
              ))}
            </ul>
          )}
        </div>
      </section>
    </main>
  );
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div className="bg-paper px-6 py-8">
      <p className="font-serif text-5xl tracking-tight text-ink">{value}</p>
      <p className="mt-3 font-sans text-[10px] uppercase tracking-[0.3em] text-ink/55">
        {label}
      </p>
    </div>
  );
}

function ClientLine({
  client,
  eyebrow,
}: {
  client: ClientSummary;
  eyebrow: string;
}) {
  return (
    <li className="flex items-baseline justify-between gap-6 py-4">
      <div className="min-w-0">
        <p className="truncate font-serif text-lg tracking-tight text-ink">
          {client.full_name}
        </p>
        <p className="truncate font-sans text-xs text-ink/60">
          {client.email}
        </p>
      </div>
      <span className="whitespace-nowrap font-sans text-[10px] uppercase tracking-[0.3em] text-ink/55">
        {eyebrow}
      </span>
    </li>
  );
}

function EmptyNote({ children }: { children: React.ReactNode }) {
  return (
    <p className="mt-6 font-sans text-sm italic text-ink/55">{children}</p>
  );
}

function summarize(clients: ClientSummary[]): {
  total: number;
  active: number;
  pending: number;
  dossiers: number;
} {
  let active = 0;
  let pending = 0;
  let dossiers = 0;
  for (const c of clients) {
    if (c.invite_status === "consumed") active += 1;
    if (c.invite_status === "pending") pending += 1;
    if (c.has_dossier) dossiers += 1;
  }
  return { total: clients.length, active, pending, dossiers };
}

function inviteBadgeCopy(status: InviteStatus): string {
  switch (status) {
    case "consumed":
      return "Invite accepted";
    case "pending":
      return "Invite pending";
    case "cancelled":
      return "Invite cancelled";
    case "none":
      return "No invite";
  }
}

// Relative-day label with a one-week window; older rows fall back to an
// absolute date so the dashboard doesn't collapse into "a while ago".
function relativeDay(iso: string): string {
  const then = new Date(iso);
  const now = new Date();
  const days = Math.floor(
    (now.getTime() - then.getTime()) / (1000 * 60 * 60 * 24),
  );
  if (days <= 0) return "Today";
  if (days === 1) return "Yesterday";
  if (days < 7) return `${days} days ago`;
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
