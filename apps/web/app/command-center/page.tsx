import Link from "next/link";
import { redirect } from "next/navigation";

import {
  createApiClient,
  type InviteStatus,
  listClients,
} from "@ov-black/api-client";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { publicEnv } from "@/lib/env";
import { createServerSupabase } from "@/lib/supabase";

import { InviteActions } from "./_components/invite-actions";

// Always render per-request — this page gates on the current user session
// and reads the advisor's client list, which must never be cached.
export const dynamic = "force-dynamic";

export default async function CommandCenterPage() {
  const supabase = await createServerSupabase();

  // getUser() revalidates the JWT against the Supabase server; getSession()
  // would trust the cookie contents. Always use getUser() for auth gates.
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    redirect("/");
  }

  // Safe to read the session token AFTER the getUser() validation: the
  // token we forward to our API is the same JWT the server just accepted.
  const {
    data: { session },
  } = await supabase.auth.getSession();
  const accessToken = session?.access_token;

  const { apiBaseUrl } = publicEnv();
  const api = createApiClient(
    accessToken ? { baseUrl: apiBaseUrl, accessToken } : { baseUrl: apiBaseUrl },
  );
  const result = await listClients(api);

  return (
    <main className="mx-auto flex min-h-screen max-w-4xl flex-col gap-12 px-6 py-16">
      <header className="flex items-end justify-between gap-6">
        <div>
          <h1 className="font-serif text-5xl tracking-tight text-ink">
            Command Center
          </h1>
          <p className="mt-3 font-sans text-xs uppercase tracking-[0.3em] text-ink/60">
            Your clients
          </p>
        </div>
        <Button asChild>
          <Link href="/command-center/new-client">New Client</Link>
        </Button>
      </header>

      {result.ok ? (
        <ClientList clients={result.clients} />
      ) : (
        <Card className="border-destructive/40">
          <CardHeader>
            <CardTitle className="text-lg">Could not load clients</CardTitle>
            <CardDescription>{errorCopy(result.detail)}</CardDescription>
          </CardHeader>
        </Card>
      )}
    </main>
  );
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

function ClientList({
  clients,
}: {
  clients: Array<{
    id: string;
    full_name: string;
    email: string;
    has_voodoo_doll: boolean;
    invite_status: InviteStatus;
    created_at: string;
  }>;
}) {
  if (clients.length === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-lg">No clients yet</CardTitle>
          <CardDescription>
            Click New Client to create the first Voodoo Doll and issue an
            invite.
          </CardDescription>
        </CardHeader>
      </Card>
    );
  }

  return (
    <ul className="flex flex-col gap-4">
      {clients.map((c) => (
        <li key={c.id}>
          <Card>
            <CardHeader>
              <div className="flex items-start justify-between gap-6">
                <div>
                  <CardTitle className="font-serif text-2xl">
                    {c.full_name}
                  </CardTitle>
                  <CardDescription className="font-sans text-sm text-ink/70">
                    {c.email}
                  </CardDescription>
                </div>
                <div className="flex flex-col items-end gap-3">
                  <span className="whitespace-nowrap font-sans text-[11px] uppercase tracking-[0.2em] text-ink/60">
                    {inviteBadgeCopy(c.invite_status)}
                  </span>
                  <InviteActions
                    clientId={c.id}
                    inviteStatus={c.invite_status}
                  />
                </div>
              </div>
            </CardHeader>
            <CardContent className="font-sans text-sm text-ink/70">
              {c.has_voodoo_doll
                ? "Voodoo Doll on file."
                : "No Voodoo Doll yet."}
            </CardContent>
          </Card>
        </li>
      ))}
    </ul>
  );
}

function errorCopy(detail: string): string {
  switch (detail) {
    case "advisor_only":
      return "This workspace is advisor-only.";
    case "network_error":
      return "Could not reach the server. Try again in a moment.";
    default:
      return "Something went wrong. Try again in a moment.";
  }
}
