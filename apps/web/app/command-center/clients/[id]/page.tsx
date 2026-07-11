import Link from "next/link";
import { notFound } from "next/navigation";

import {
  type AccessStatus,
  type AdvisorItinerarySummary,
  type ClientDetail,
  type ClientSessionSummary,
  type DocumentDetail,
  type PartyMemberDetail,
  getClient,
  getClientAwareness,
  listAdvisorItineraries,
  listClientDocuments,
  listClientPartyMembers,
  listClientSessions,
} from "@ov-black/api-client";

import { Button } from "@/components/ui/button";

import { AttentionStrip } from "@/app/command-center/_components/attention";
import { SetClientCrumb } from "@/app/command-center/_components/CommandCenterCrumb";
import { InviteActions } from "@/app/command-center/_components/invite-actions";
import {
  EmptyNote,
  Panel,
  SectionHeader,
  StatusPill,
  relativeDay,
} from "@/app/command-center/_components/panels";
import { advisorApi } from "@/app/command-center/_lib/api";

import { ClientContactsSection } from "./_components/ClientContactsSection";
import { ClientDocumentsSection } from "./_components/ClientDocumentsSection";
import { ClientFactColumns } from "./_components/ClientFactColumns";
import { ClientPartySection } from "./_components/ClientPartySection";
import { ClientSubNav, type SubNavSection } from "./_components/ClientSubNav";
import { NewItineraryButton } from "./_components/NewItineraryButton";

// Auth-gated per request. Wave F recomposition: cockpit header (identity +
// pills + mono quick-stats) → attention strip (Wave D placement, unchanged) →
// sticky section sub-nav with scroll-spy → the existing sections regrouped.
// The section components themselves are reused as-is.
export const dynamic = "force-dynamic";

export default async function ClientDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const api = await advisorApi();

  const [
    clientResult,
    itinerariesResult,
    sessionsResult,
    partyResult,
    documentsResult,
    awarenessResult,
  ] = await Promise.all([
    getClient(api, id),
    listAdvisorItineraries(api, { clientId: id }),
    listClientSessions(api, id),
    listClientPartyMembers(api, id),
    listClientDocuments(api, id),
    getClientAwareness(api, id),
  ]);

  if (!clientResult.ok) {
    if (clientResult.detail === "client_not_found") notFound();
    return (
      <main className="flex w-full flex-1 flex-col gap-6 px-6 py-12 sm:px-10 sm:py-16">
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
  const itineraries = itinerariesResult.ok ? itinerariesResult.itineraries : [];
  const sessions = sessionsResult.ok ? sessionsResult.sessions : [];
  const partyMembers: PartyMemberDetail[] = partyResult.ok
    ? partyResult.members
    : [];
  const documents: DocumentDetail[] = documentsResult.ok
    ? documentsResult.documents
    : [];
  // ADV-14 — best-effort: a failure just hides the strip, never breaks the page.
  const attention = awarenessResult.ok ? awarenessResult.attention : undefined;

  const factCount =
    (client.dossier_facts?.length ?? 0) +
    (client.profile_facts?.length ?? 0) +
    (client.osint_facts?.length ?? 0);

  const sections: SubNavSection[] = [
    ...(client.dossier ? [{ id: "basics", label: "Basics" }] : []),
    { id: "contacts", label: "Contacts" },
    { id: "party", label: "Party" },
    { id: "vault", label: "Vault" },
    { id: "trips", label: "Trips" },
    { id: "sessions", label: "Sessions" },
    { id: "facts", label: "Facts" },
  ];

  return (
    <main className="flex w-full flex-1 flex-col gap-8 px-6 py-10 sm:px-10 sm:py-12">
      <SetClientCrumb name={client.full_name} />

      <header className="flex flex-col gap-6 border-b border-paper/10 pb-8 lg:flex-row lg:items-end lg:justify-between">
        <div className="min-w-0">
          <p className="font-sans text-[10px] uppercase tracking-eyebrow text-paper/55">
            Client workspace
          </p>
          <h1 className="mt-3 font-serif text-4xl tracking-tight text-paper sm:text-5xl">
            {client.full_name}
          </h1>
          <p className="mt-2 font-sans text-sm text-paper/70">{client.email}</p>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <InvitePill
              status={client.access_status}
              acceptedAt={client.accepted_at}
            />
            {client.dossier ? (
              <Pill>Dossier on file</Pill>
            ) : (
              <Pill tone="quiet">No dossier</Pill>
            )}
            {client.access_status !== "active" ? (
              <InviteActions
                clientId={client.id}
                accessStatus={client.access_status}
                buttonStyle="brand"
              />
            ) : null}
          </div>
        </div>
        <dl className="flex shrink-0 gap-8">
          <QuickStat label="Trips" value={itineraries.length} />
          <QuickStat label="Sessions" value={sessions.length} />
          <QuickStat label="Party" value={partyMembers.length} />
          <QuickStat label="Facts" value={factCount} />
        </dl>
      </header>

      <AttentionStrip attention={attention} />

      <ClientSubNav sections={sections} />

      <div className="flex flex-col gap-12">
        {client.dossier ? (
          <Panel id="basics" className="scroll-mt-16" aria-labelledby="basics-heading">
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
                  <Field
                    label="Notes"
                    value={client.dossier.travel_party_notes}
                  />
                </div>
              ) : null}
            </dl>
          </Panel>
        ) : null}

        <Panel id="contacts" className="scroll-mt-16" aria-labelledby="contacts-heading">
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

        <Panel id="party" className="scroll-mt-16" aria-labelledby="party-heading">
          <SectionHeader
            id="party-heading"
            title="Travel party"
            eyebrow={`${partyMembers.length}`}
          />
          <ClientPartySection clientId={client.id} members={partyMembers} />
        </Panel>

        <Panel id="vault" className="scroll-mt-16" aria-labelledby="vault-heading">
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

        <Panel id="trips" className="scroll-mt-16" aria-labelledby="trips-heading">
          <SectionHeader
            id="trips-heading"
            title="Trips"
            eyebrow={`${itineraries.length}`}
            actions={<NewItineraryButton clientId={client.id} />}
          />
          {itineraries.length === 0 ? (
            <EmptyNote>No trips yet.</EmptyNote>
          ) : (
            <ul className="flex flex-col divide-y divide-paper/10 border-y border-paper/10">
              {itineraries.map((it) => (
                <ItineraryRow key={it.id} row={it} />
              ))}
            </ul>
          )}
        </Panel>

        <Panel id="sessions" className="scroll-mt-16" aria-labelledby="sessions-heading">
          <SectionHeader
            id="sessions-heading"
            title="Conversations"
            eyebrow={`${sessions.length}`}
          />
          {sessions.length === 0 ? (
            <EmptyNote>No agent conversations yet.</EmptyNote>
          ) : (
            <ul className="flex flex-col divide-y divide-paper/10 border-y border-paper/10">
              {sessions.map((s) => (
                <SessionRow key={s.id} row={s} clientId={client.id} />
              ))}
            </ul>
          )}
        </Panel>

        <Panel id="facts" className="scroll-mt-16" aria-labelledby="facts-heading">
          <SectionHeader id="facts-heading" title="Facts" />
          <ClientFactColumns
            clientId={client.id}
            dossierFacts={client.dossier_facts ?? []}
            profileFacts={client.profile_facts ?? []}
            osintFacts={client.osint_facts ?? []}
          />
        </Panel>
      </div>
    </main>
  );
}

/** Cockpit quick-stat: mono numeral over a label — figures are data. */
function QuickStat({ label, value }: { label: string; value: number }) {
  return (
    <div className="text-right">
      <dd className="font-mono text-2xl tabular-nums text-paper">{value}</dd>
      <dt className="font-sans text-[10px] uppercase tracking-label text-paper/45">
        {label}
      </dt>
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
  // The row opens the read-only replay (transcript + telemetry); the "Live"
  // link beside it jumps into the same /chat surface the traveler sees.
  return (
    <li className="flex items-center gap-4 px-1 py-3 transition-colors hover:bg-paper/4">
      <Link
        href={`/command-center/clients/${clientId}/sessions/${row.id}`}
        className="group min-w-0 flex-1"
      >
        <p className="truncate font-sans text-sm text-paper/90 underline-offset-4 group-hover:underline">
          {row.seeded_opener || "Concierge conversation"}
        </p>
        <p className="font-sans text-xs text-paper/55">
          {row.turn_count} turn{row.turn_count === 1 ? "" : "s"}
          {row.last_turn_at ? ` · last ${relativeDay(row.last_turn_at)}` : ""}
          {row.itinerary_id ? " · pinned" : ""}
        </p>
      </Link>
      <Link
        href={`/chat/${clientId}`}
        className="font-sans text-[10px] uppercase tracking-[0.25em] text-paper/55 transition-colors hover:text-paper"
      >
        Live
      </Link>
      <Link
        aria-label="Open session replay"
        href={`/command-center/clients/${clientId}/sessions/${row.id}`}
        className="text-paper/30 transition-colors hover:text-paper"
      >
        →
      </Link>
    </li>
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
      : status === "pending"
        ? "Invite pending"
        : "Not invited";
  const tone =
    status === "active"
      ? "border-paper/40 text-paper"
      : status === "pending"
        ? "border-amber-300/40 text-amber-200/90"
        : "border-paper/20 text-paper/50";
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

function detailCopy(detail: string): string {
  if (detail === "advisor_only") return "This workspace is advisor-only.";
  if (detail === "network_error")
    return "Could not reach the server. Try again in a moment.";
  return "Something went wrong. Try again in a moment.";
}
