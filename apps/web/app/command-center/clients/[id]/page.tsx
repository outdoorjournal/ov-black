import Link from "next/link";
import { notFound, redirect } from "next/navigation";

import {
  type AccessStatus,
  type AdvisorItinerarySummary,
  type ClientDetail,
  type ClientSessionSummary,
  type DocumentDetail,
  type ItineraryStatus,
  type PartyMemberDetail,
  createApiClient,
  getClient,
  listAdvisorItineraries,
  listClientDocuments,
  listClientPartyMembers,
  listClientSessions,
} from "@ov-black/api-client";

import { Button } from "@/components/ui/button";
import { publicEnv } from "@/lib/env";
import { createServerSupabase } from "@/lib/supabase/server";

import { ClientContactsSection } from "./_components/ClientContactsSection";
import { ClientDocumentsSection } from "./_components/ClientDocumentsSection";
import { ClientFactColumns } from "./_components/ClientFactColumns";
import { ClientPartySection } from "./_components/ClientPartySection";

// Auth-gated per request. Single-page workspace: header + dossier basics
// (typed core), itineraries roster filtered to this client, recent sessions,
// and the three-tier per-fact editing pane (Dossier / Profile / OSINT).
export const dynamic = "force-dynamic";

export default async function ClientDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;

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

  const [
    clientResult,
    allItinerariesResult,
    sessionsResult,
    partyResult,
    documentsResult,
  ] = await Promise.all([
    getClient(api, id),
    listAdvisorItineraries(api),
    listClientSessions(api, id),
    listClientPartyMembers(api, id),
    listClientDocuments(api, id),
  ]);

  if (!clientResult.ok) {
    if (clientResult.detail === "client_not_found") notFound();
    return (
      <main className="flex w-full flex-1 flex-col gap-6 bg-ink px-6 py-12 text-paper sm:px-10 sm:py-16">
        <p
          role="alert"
          className="font-sans text-sm font-medium text-destructive"
        >
          {detailCopy(clientResult.detail)}
        </p>
        <Button
          asChild
          variant="outline"
          className="self-start border-paper/20 bg-transparent text-paper hover:bg-paper/10 hover:text-paper"
        >
          <Link href="/command-center">Back</Link>
        </Button>
      </main>
    );
  }

  const client: ClientDetail = clientResult.client;
  const itineraries =
    allItinerariesResult.ok
      ? allItinerariesResult.itineraries.filter((i) => i.client.id === client.id)
      : [];
  const sessions = sessionsResult.ok ? sessionsResult.sessions : [];
  const partyMembers: PartyMemberDetail[] = partyResult.ok
    ? partyResult.members
    : [];
  const documents: DocumentDetail[] = documentsResult.ok
    ? documentsResult.documents
    : [];

  return (
    <main className="flex w-full flex-1 flex-col gap-12 bg-ink px-6 py-10 text-paper sm:px-10 sm:py-12">
      <header className="flex flex-col gap-6 border-b border-paper/10 pb-8 lg:flex-row lg:items-end lg:justify-between">
        <div className="min-w-0">
          <Link
            href="/command-center"
            className="font-sans text-[10px] uppercase tracking-eyebrow text-paper/55 transition-colors hover:text-paper"
          >
            ← Command Center
          </Link>
          <h1 className="mt-3 font-serif text-4xl tracking-tight text-paper sm:text-5xl">
            {client.full_name}
          </h1>
          <p className="mt-2 font-sans text-sm text-paper/70">{client.email}</p>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <InvitePill status={client.access_status} acceptedAt={client.accepted_at} />
            {client.dossier ? (
              <Pill>Dossier on file</Pill>
            ) : (
              <Pill tone="quiet">No dossier</Pill>
            )}
          </div>
        </div>
      </header>

      {client.dossier ? (
        <Panel aria-labelledby="basics-heading">
          <SectionHeader id="basics-heading" title="Basics" />
          <dl className="grid gap-x-8 gap-y-4 sm:grid-cols-2 lg:grid-cols-3">
            <Field
              label="Preferred contact"
              value={client.dossier.contact_preference}
            />
            <Field
              label="Children ages"
              value={
                client.dossier.children_ages.length
                  ? client.dossier.children_ages.join(", ")
                  : "—"
              }
            />
            <Field
              label="Estimated net worth (USD)"
              value={
                client.dossier.estimated_net_worth_usd != null
                  ? client.dossier.estimated_net_worth_usd.toLocaleString()
                  : "—"
              }
            />
            {client.dossier.travel_party_notes ? (
              <div className="sm:col-span-2 lg:col-span-3">
                <Field label="Notes" value={client.dossier.travel_party_notes} />
              </div>
            ) : null}
          </dl>
        </Panel>
      ) : null}

      <Panel aria-labelledby="contacts-heading">
        <SectionHeader
          id="contacts-heading"
          title="Contacts"
          eyebrow={`${client.contacts?.length ?? 0}`}
        />
        <ClientContactsSection
          clientId={client.id}
          contacts={client.contacts ?? []}
        />
      </Panel>

      <Panel aria-labelledby="party-heading">
        <SectionHeader
          id="party-heading"
          title="Travel party"
          eyebrow={`${partyMembers.length}`}
        />
        <ClientPartySection clientId={client.id} members={partyMembers} />
      </Panel>

      <Panel aria-labelledby="vault-heading">
        <SectionHeader
          id="vault-heading"
          title="Vault"
          eyebrow={`${documents.length}`}
        />
        <ClientDocumentsSection
          clientId={client.id}
          documents={documents}
          members={partyMembers}
        />
      </Panel>

      <Panel aria-labelledby="itineraries-heading">
        <SectionHeader
          id="itineraries-heading"
          title="Itineraries"
          eyebrow={`${itineraries.length}`}
        />
        {itineraries.length === 0 ? (
          <p className="font-sans text-sm italic text-paper/45">
            No itineraries yet.
          </p>
        ) : (
          <ul className="flex flex-col divide-y divide-paper/10 border-y border-paper/10">
            {itineraries.map((it) => (
              <ItineraryRow key={it.id} row={it} />
            ))}
          </ul>
        )}
      </Panel>

      <Panel aria-labelledby="sessions-heading">
        <SectionHeader
          id="sessions-heading"
          title="Conversations"
          eyebrow={`${sessions.length}`}
        />
        {sessions.length === 0 ? (
          <p className="font-sans text-sm italic text-paper/45">
            No agent conversations yet.
          </p>
        ) : (
          <ul className="flex flex-col divide-y divide-paper/10 border-y border-paper/10">
            {sessions.map((s) => (
              <SessionRow key={s.id} row={s} clientId={client.id} />
            ))}
          </ul>
        )}
      </Panel>

      <Panel aria-labelledby="facts-heading">
        <SectionHeader id="facts-heading" title="Facts" />
        <ClientFactColumns
          clientId={client.id}
          dossierFacts={client.dossier_facts ?? []}
          profileFacts={client.profile_facts ?? []}
          osintFacts={client.osint_facts ?? []}
        />
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
  eyebrow?: string;
}) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-b border-paper/10 pb-2">
      <h2 id={id} className="font-serif text-2xl tracking-tight text-paper">
        {title}
      </h2>
      {eyebrow ? (
        <span className="font-sans text-[10px] uppercase tracking-label text-paper/55">
          {eyebrow}
        </span>
      ) : null}
    </div>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="font-sans text-[10px] uppercase tracking-label text-paper/45">
        {label}
      </dt>
      <dd className="mt-1 font-sans text-sm text-paper/90">{value}</dd>
    </div>
  );
}

function ItineraryRow({ row }: { row: AdvisorItinerarySummary }) {
  return (
    <li>
      <Link
        href={`/itinerary/${row.id}`}
        className="group flex items-center gap-4 px-1 py-3 transition-colors hover:bg-paper/4"
      >
        <div className="min-w-0 flex-1">
          <p className="truncate font-serif text-base tracking-tight text-paper underline-offset-4 group-hover:underline">
            {row.title || "Untitled draft"}
          </p>
          <p className="font-sans text-xs text-paper/55">
            Updated {relativeDay(row.last_activity_at)}
          </p>
        </div>
        <StatusPill status={row.status} />
        <span aria-hidden className="text-paper/30">
          →
        </span>
      </Link>
    </li>
  );
}

function SessionRow({
  row,
  clientId,
}: {
  row: ClientSessionSummary;
  clientId: string;
}) {
  // For now sessions don't have a dedicated advisor read-only view; clicking
  // takes the advisor to the same /chat surface the traveler sees so they can
  // observe the live thread. A read-only replay page can replace this href
  // when /sessions/{id}/turns gets a UI.
  return (
    <li>
      <Link
        href={`/chat/${clientId}`}
        className="group flex items-center gap-4 px-1 py-3 transition-colors hover:bg-paper/4"
      >
        <div className="min-w-0 flex-1">
          <p className="truncate font-sans text-sm text-paper/90">
            {row.seeded_opener || "Concierge conversation"}
          </p>
          <p className="font-sans text-xs text-paper/55">
            {row.turn_count} turn{row.turn_count === 1 ? "" : "s"}
            {row.last_turn_at ? ` · last ${relativeDay(row.last_turn_at)}` : ""}
            {row.itinerary_id ? " · pinned" : ""}
          </p>
        </div>
        <span
          className="font-sans text-[10px] uppercase tracking-[0.25em] text-paper/55"
        >
          Open
        </span>
        <span aria-hidden className="text-paper/30">
          →
        </span>
      </Link>
    </li>
  );
}

function StatusPill({ status }: { status: ItineraryStatus }) {
  const tone =
    status === "approved"
      ? "border-paper/40 text-paper"
      : "border-paper/15 text-paper/65";
  return (
    <span
      className={`whitespace-nowrap rounded-full border px-2 py-0.5 font-sans text-[10px] uppercase tracking-[0.25em] ${tone}`}
    >
      {status}
    </span>
  );
}

function InvitePill({
  status,
  acceptedAt,
}: {
  status: AccessStatus;
  acceptedAt: string | null;
}) {
  const signedInOn =
    status === "active" && acceptedAt
      ? new Intl.DateTimeFormat("en-US", {
          month: "short",
          day: "numeric",
          year: "numeric",
        }).format(new Date(acceptedAt))
      : null;
  const copy =
    status === "active"
      ? signedInOn
        ? `Signed in · ${signedInOn}`
        : "Signed in"
      : "Invite pending";
  const tone =
    status === "active"
      ? "border-paper/40 text-paper"
      : "border-amber-300/40 text-amber-200/90";
  return (
    <span
      className={`inline-block rounded-full border px-2 py-0.5 font-sans text-[10px] uppercase tracking-[0.25em] ${tone}`}
    >
      {copy}
    </span>
  );
}

function Pill({
  children,
  tone = "default",
}: {
  children: React.ReactNode;
  tone?: "default" | "quiet";
}) {
  const cls =
    tone === "quiet"
      ? "border-paper/15 text-paper/55"
      : "border-paper/40 text-paper";
  return (
    <span
      className={`inline-block rounded-full border px-2 py-0.5 font-sans text-[10px] uppercase tracking-[0.25em] ${cls}`}
    >
      {children}
    </span>
  );
}

function relativeDay(iso: string): string {
  const then = new Date(iso);
  const now = new Date();
  const days = Math.floor(
    (now.getTime() - then.getTime()) / (1000 * 60 * 60 * 24),
  );
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  if (days < 7) return `${days}d ago`;
  if (days < 30) return `${Math.floor(days / 7)}w ago`;
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
  }).format(then);
}

function detailCopy(detail: string): string {
  if (detail === "advisor_only") return "This workspace is advisor-only.";
  if (detail === "network_error")
    return "Could not reach the server. Try again in a moment.";
  return "Something went wrong. Try again in a moment.";
}
