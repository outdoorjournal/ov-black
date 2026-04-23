"use server";

import { revalidatePath } from "next/cache";

import {
  cancelClientInvite,
  createApiClient,
  reissueClientInvite,
} from "@ov-black/api-client";

import { publicEnv } from "@/lib/env";
import { createServerSupabase } from "@/lib/supabase";

export type InviteActionResult = { ok: true } | { ok: false; error: string };

const REISSUE_COPY = {
  client_not_found:
    "That client is no longer available in this workspace.",
  advisor_only: "Only advisors can manage invites in this workspace.",
  invite_already_redeemed:
    "This client has already accepted an invite — they can sign in directly.",
  auth_upstream_unavailable:
    "The auth service is unreachable right now. Try again in a moment.",
  network_error: "Could not reach the server. Try again in a moment.",
  unknown: "Something went wrong. Try again in a moment.",
} as const;

const CANCEL_COPY = {
  client_not_found:
    "That client is no longer available in this workspace.",
  advisor_only: "Only advisors can manage invites in this workspace.",
  no_active_invite: "There is no active invite to cancel.",
  network_error: "Could not reach the server. Try again in a moment.",
  unknown: "Something went wrong. Try again in a moment.",
} as const;

async function buildAuthedClient() {
  const supabase = await createServerSupabase();
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    return null;
  }
  const {
    data: { session },
  } = await supabase.auth.getSession();
  const accessToken = session?.access_token;
  const { apiBaseUrl } = publicEnv();
  return createApiClient(
    accessToken ? { baseUrl: apiBaseUrl, accessToken } : { baseUrl: apiBaseUrl },
  );
}

export async function reissueInviteAction(
  clientId: string,
): Promise<InviteActionResult> {
  const api = await buildAuthedClient();
  if (api === null) {
    return { ok: false, error: REISSUE_COPY["advisor_only"] };
  }
  const result = await reissueClientInvite(api, clientId);
  if (!result.ok) {
    const detail = result.detail as keyof typeof REISSUE_COPY;
    return { ok: false, error: REISSUE_COPY[detail] ?? REISSUE_COPY["unknown"] };
  }
  revalidatePath("/command-center");
  return { ok: true };
}

export async function cancelInviteAction(
  clientId: string,
): Promise<InviteActionResult> {
  const api = await buildAuthedClient();
  if (api === null) {
    return { ok: false, error: CANCEL_COPY["advisor_only"] };
  }
  const result = await cancelClientInvite(api, clientId);
  if (!result.ok) {
    const detail = result.detail as keyof typeof CANCEL_COPY;
    return { ok: false, error: CANCEL_COPY[detail] ?? CANCEL_COPY["unknown"] };
  }
  revalidatePath("/command-center");
  return { ok: true };
}
