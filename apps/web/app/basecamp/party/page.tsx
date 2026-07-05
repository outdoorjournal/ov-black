// Traveler self-service party form (/basecamp/party).
//
// Self-scoped like the rest of basecamp — the member roster comes from the
// /me/party-members endpoints, resolved from the Supabase JWT, so no client_id
// is in the URL. The durable members persist across every trip (M003/V1); this
// is where the traveler keeps them current. Advisors edit the same roster from
// the command-center client detail page; the agent records it mid-conversation.

import { notFound, redirect } from "next/navigation";

import {
  createApiClient,
  listMyPartyMembers,
  type PartyMemberDetail,
} from "@ov-black/api-client";

import { publicEnv } from "@/lib/env";
import { headerUserFromSupabase } from "@/lib/appHeader";
import { resolveClientIdForUser } from "@/lib/role";
import { createServerSupabase } from "@/lib/supabase/server";

import { BasecampChrome } from "../_components/BasecampChrome";
import { PartyManager } from "./_components/PartyManager";

export const dynamic = "force-dynamic";

export default async function PartyPage() {
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
  if (!accessToken) {
    redirect("/");
  }

  // Confirm the caller resolves to a client (a linked traveler); otherwise the
  // /me roster has no home and we hide the surface rather than 500.
  const clientId = await resolveClientIdForUser(supabase);
  if (!clientId) {
    notFound();
  }

  const { apiBaseUrl } = publicEnv();
  const api = createApiClient({ baseUrl: apiBaseUrl, accessToken });

  const result = await listMyPartyMembers(api);
  const members: PartyMemberDetail[] = result.ok ? result.members : [];

  return (
    <BasecampChrome user={headerUserFromSupabase(user)}>
      <PartyManager members={members} />
    </BasecampChrome>
  );
}
