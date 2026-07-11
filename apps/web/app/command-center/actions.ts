"use server";

import { revalidatePath } from "next/cache";

import { createApiClient, resendWelcomeEmail } from "@ov-black/api-client";

import { publicEnv } from "@/lib/env";
import { createServerSupabase } from "@/lib/supabase/server";

export type InviteActionResult = { ok: true } | { ok: false; error: string };

const RESEND_COPY = {
  client_not_found:
    "That client is no longer available in this workspace.",
  advisor_only: "Only advisors can manage clients in this workspace.",
  client_already_accepted:
    "This client has already signed in — they can sign in directly.",
  auth_upstream_unavailable:
    "The auth service is unreachable right now. Try again in a moment.",
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

export async function resendWelcomeAction(
  clientId: string,
): Promise<InviteActionResult> {
  const api = await buildAuthedClient();
  if (api === null) {
    return { ok: false, error: RESEND_COPY["advisor_only"] };
  }
  const result = await resendWelcomeEmail(api, clientId);
  if (!result.ok) {
    const detail = result.detail as keyof typeof RESEND_COPY;
    return { ok: false, error: RESEND_COPY[detail] ?? RESEND_COPY["unknown"] };
  }
  revalidatePath("/command-center");
  revalidatePath("/command-center/clients");
  revalidatePath(`/command-center/clients/${clientId}`);
  return { ok: true };
}
