// Traveler secure document vault (/basecamp/vault).
//
// Self-scoped like the rest of basecamp — the document roster + party members
// come from the /me/* endpoints, resolved from the Supabase JWT. Documents are
// household assets (M003/V3): stored once under SSE-KMS, available on every
// trip. Advisors manage the same vault from the command-center client page; the
// itinerary view shows them read-only.

import { notFound, redirect } from "next/navigation";

import {
  createApiClient,
  listMyDocuments,
  listMyPartyMembers,
  type DocumentDetail,
  type PartyMemberDetail,
} from "@ov-black/api-client";

import { publicEnv } from "@/lib/env";
import { headerUserFromSupabase } from "@/lib/appHeader";
import { resolveClientIdForUser } from "@/lib/role";
import { createServerSupabase } from "@/lib/supabase/server";

import { BasecampChrome } from "../_components/BasecampChrome";
import { VaultManager } from "./_components/VaultManager";

export const dynamic = "force-dynamic";

export default async function VaultPage() {
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

  const clientId = await resolveClientIdForUser(supabase);
  if (!clientId) {
    notFound();
  }

  const { apiBaseUrl } = publicEnv();
  const api = createApiClient({ baseUrl: apiBaseUrl, accessToken });

  const [docsResult, membersResult] = await Promise.all([
    listMyDocuments(api),
    listMyPartyMembers(api),
  ]);
  const documents: DocumentDetail[] = docsResult.ok ? docsResult.documents : [];
  const members: PartyMemberDetail[] = membersResult.ok
    ? membersResult.members
    : [];

  return (
    <BasecampChrome user={headerUserFromSupabase(user)}>
      {/* The paper-on-ink manager owns its dark mood surface — the shell around
          it stays light (see BasecampChrome). Without this, near-white text on
          the light shell renders invisible. */}
      <div className="min-h-full bg-ink text-paper">
        <VaultManager documents={documents} members={members} />
      </div>
    </BasecampChrome>
  );
}
