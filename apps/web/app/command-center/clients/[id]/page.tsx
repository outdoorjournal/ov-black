import Link from "next/link";
import { notFound, redirect } from "next/navigation";

import {
  type ClientDetail,
  createApiClient,
  getClient,
} from "@ov-black/api-client";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { publicEnv } from "@/lib/env";
import { createServerSupabase } from "@/lib/supabase/server";

import { ClientDetailTabs } from "./_components/ClientDetailTabs";

// Auth-gated per request. Three tabs map 1:1 to the three private tiers
// described in CLAUDE.md → Traveler context: Dossier (private),
// Profile (traveler self-expressed, may be referenced), OSINT (external,
// never revealed). Each tab is its own list with add/edit/redact actions.
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

  const result = await getClient(api, id);
  if (!result.ok) {
    if (result.detail === "client_not_found") notFound();
    return (
      <main className="mx-auto flex w-full max-w-4xl flex-col gap-6 px-6 py-12 sm:px-10 sm:py-16">
        <p
          role="alert"
          className="font-sans text-sm font-medium text-destructive"
        >
          {detailCopy(result.detail)}
        </p>
        <Button asChild variant="outline">
          <Link href="/command-center/clients">Back to clients</Link>
        </Button>
      </main>
    );
  }

  const client: ClientDetail = result.client;

  return (
    <main className="mx-auto flex w-full max-w-4xl flex-col gap-10 px-6 py-12 sm:px-10 sm:py-16">
      <header className="flex flex-col gap-6 border-b border-ink/10 pb-8 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="font-sans text-[10px] uppercase tracking-[0.4em] text-ink/55">
            Client detail
          </p>
          <h1 className="mt-4 font-serif text-5xl tracking-tight text-ink sm:text-6xl">
            {client.full_name}
          </h1>
          <p className="mt-2 font-sans text-sm text-ink/70">{client.email}</p>
        </div>
        <Button asChild variant="outline">
          <Link href="/command-center/clients">Back</Link>
        </Button>
      </header>

      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Dossier basics</CardTitle>
          <CardDescription>
            Structured signals seeded by you. Private — never revealed to the
            traveler.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-3 font-sans text-sm text-ink/80 sm:grid-cols-2">
          {client.dossier ? (
            <>
              <Field label="Group type" value={client.dossier.group_type} />
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
                <Field
                  label="Party notes"
                  value={client.dossier.travel_party_notes}
                  span
                />
              ) : null}
            </>
          ) : (
            <p className="italic text-ink/55">No dossier on file.</p>
          )}
        </CardContent>
      </Card>

      <ClientDetailTabs
        clientId={client.id}
        dossierFacts={client.dossier_facts ?? []}
        profileFacts={client.profile_facts ?? []}
        osintFacts={client.osint_facts ?? []}
      />
    </main>
  );
}

function Field({
  label,
  value,
  span,
}: {
  label: string;
  value: string | number;
  span?: boolean;
}) {
  return (
    <div className={span ? "sm:col-span-2" : undefined}>
      <p className="font-sans text-[10px] uppercase tracking-[0.3em] text-ink/55">
        {label}
      </p>
      <p className="mt-1">{value}</p>
    </div>
  );
}

function detailCopy(detail: string): string {
  if (detail === "advisor_only")
    return "This workspace is advisor-only.";
  if (detail === "network_error")
    return "Could not reach the server. Try again in a moment.";
  return "Something went wrong. Try again in a moment.";
}
