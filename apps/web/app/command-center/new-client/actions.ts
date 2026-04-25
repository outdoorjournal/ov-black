"use server";

import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";

import {
  type ClientCreatePayload,
  createApiClient,
  createClientEndpoint,
} from "@ov-black/api-client";

import { publicEnv } from "@/lib/env";
import { createServerSupabase } from "@/lib/supabase/server";

export type CreateClientActionResult = { error: string } | { ok: true };

// Copy for each collapsed `detail` string from createClientEndpoint.
// Mirrors the D015 pattern — one user-readable sentence per reason,
// rendered inline by the form rather than as a toast.
const ERROR_COPY = {
  advisor_only: "Only advisors can create clients in this workspace.",
  client_email_already_invited:
    "A client with this email has already been invited.",
  auth_upstream_unavailable:
    "The auth service is unreachable right now. Try again in a moment.",
  validation_error:
    "Some fields look off. Double-check the form and try again.",
  network_error: "Could not reach the server. Try again in a moment.",
  unknown: "Something went wrong. Try again in a moment.",
} as const;

export async function createClientAction(
  payload: ClientCreatePayload,
): Promise<CreateClientActionResult> {
  const supabase = await createServerSupabase();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    return { error: ERROR_COPY["advisor_only"] };
  }

  const {
    data: { session },
  } = await supabase.auth.getSession();
  const accessToken = session?.access_token;

  const { apiBaseUrl } = publicEnv();
  const api = createApiClient(
    accessToken ? { baseUrl: apiBaseUrl, accessToken } : { baseUrl: apiBaseUrl },
  );
  const result = await createClientEndpoint(api, payload);

  if (!result.ok) {
    const detail = result.detail as keyof typeof ERROR_COPY;
    return { error: ERROR_COPY[detail] ?? ERROR_COPY["unknown"] };
  }

  // New client row shows up on the /clients list and shifts the
  // dashboard's "Recent" and "Needs attention" panes. Bust both paths,
  // then push the advisor back to the list where the fresh row renders
  // alongside its invite state.
  revalidatePath("/command-center");
  revalidatePath("/command-center/clients");
  redirect("/command-center/clients");
}
