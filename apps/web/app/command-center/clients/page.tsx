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

import { InviteActions } from "../_components/invite-actions";

// Always render per-request — the advisor's roster must never be cached
// across sessions.
export const dynamic = "force-dynamic";

export default async function ClientsPage() {
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

  return (
    <main className="flex w-full flex-1 flex-col gap-10 bg-ink px-6 py-10 text-paper sm:px-10 sm:py-12">
      <header className="flex flex-col gap-4 border-b border-paper/10 pb-8 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="font-sans text-[10px] uppercase tracking-[0.4em] text-paper/55">
            Command Center
          </p>
          <h1 className="mt-3 font-serif text-4xl tracking-tight text-paper sm:text-5xl">
            Clients
          </h1>
        </div>
        <Button asChild className="self-start sm:self-auto">
          <Link href="/command-center/new-client">New Client</Link>
        </Button>
      </header>

      {!result.ok ? (
        <div className="border border-destructive/40 bg-destructive/10 p-4 font-sans text-sm text-destructive-foreground">
          Could not load clients — {errorCopy(result.detail)}
        </div>
      ) : null}

      <section className="flex flex-col gap-4 rounded-md border border-paper/10 bg-paper/[0.05] p-5 sm:p-7">
        {clients.length === 0 ? (
          <p className="font-sans text-sm italic text-paper/55">
            No clients yet — click <em>New Client</em> to issue the first
            invite.
          </p>
        ) : (
          <ClientList clients={clients} />
        )}
      </section>
    </main>
  );
}

function ClientList({ clients }: { clients: ClientSummary[] }) {
  return (
    <div className="-mx-5 overflow-x-auto sm:-mx-7">
      <table className="w-full border-y border-paper/10 text-left font-sans text-sm">
        <thead className="bg-paper/[0.06] text-[10px] uppercase tracking-[0.3em] text-paper/55">
          <tr>
            <Th className="pl-5 sm:pl-7">Name</Th>
            <Th className="hidden md:table-cell">Email</Th>
            <Th>Invite</Th>
            <Th>Dossier</Th>
            <Th>Joined</Th>
            <Th className="pr-5 text-right sm:pr-7" />
          </tr>
        </thead>
        <tbody className="divide-y divide-paper/10">
          {clients.map((c) => (
            <tr key={c.id} className="group transition-colors hover:bg-paper/[0.08]">
              <Td className="pl-5 sm:pl-7">
                <Link
                  href={`/command-center/clients/${c.id}`}
                  className="font-serif text-base tracking-tight text-paper underline-offset-4 group-hover:underline"
                >
                  {c.full_name}
                </Link>
              </Td>
              <Td className="hidden truncate text-paper/60 md:table-cell">
                {c.email}
              </Td>
              <Td>
                <InvitePill status={c.invite_status} />
              </Td>
              <Td className="text-paper/60">
                {c.has_dossier ? "On file" : "—"}
              </Td>
              <Td className="whitespace-nowrap text-paper/60">
                {relativeDay(c.created_at)}
              </Td>
              <Td className="pr-5 text-right sm:pr-7">
                <InviteActions
                  clientId={c.id}
                  inviteStatus={c.invite_status}
                />
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

function InvitePill({ status }: { status: InviteStatus }) {
  const copy =
    status === "consumed"
      ? "Accepted"
      : status === "pending"
        ? "Pending"
        : status === "cancelled"
          ? "Cancelled"
          : "—";
  const tone =
    status === "consumed"
      ? "border-paper/40 text-paper"
      : status === "pending"
        ? "border-amber-300/40 text-amber-200/90"
        : "border-paper/15 text-paper/55";
  return (
    <span
      className={`inline-block rounded-full border px-2 py-0.5 font-sans text-[10px] uppercase tracking-[0.25em] ${tone}`}
    >
      {copy}
    </span>
  );
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
