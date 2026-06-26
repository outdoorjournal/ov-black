"use server";

import { revalidatePath } from "next/cache";

import {
  type PartyMemberCreate,
  type PartyMemberUpdate,
  archiveMyPartyMember,
  createApiClient,
  createMyPartyMember,
  updateMyPartyMember,
} from "@ov-black/api-client";

import { publicEnv } from "@/lib/env";
import { createServerSupabase } from "@/lib/supabase/server";

// Traveler self-service party-member mutations. The traveler is resolved from
// the Supabase JWT on the server (the `/me/*` routes need no client_id), so
// these actions only forward a token — never an identity. Mirrors the
// command-center fact actions: a discriminated `{ ok } | { error }` result and
// a revalidate so the RSC re-reads the roster.

export type PartyActionResult = { ok: true } | { error: string };

const ERROR_COPY: Record<string, string> = {
  client_not_found: "We couldn't find your account. Reach your concierge.",
  party_member_not_found: "That traveler has already been removed.",
  validation_error: "Some fields look off. Double-check and try again.",
  network_error: "Could not reach the server. Try again in a moment.",
};

async function _api() {
  const supabase = await createServerSupabase();
  const {
    data: { session },
  } = await supabase.auth.getSession();
  const accessToken = session?.access_token;
  const { apiBaseUrl } = publicEnv();
  return createApiClient(
    accessToken ? { baseUrl: apiBaseUrl, accessToken } : { baseUrl: apiBaseUrl },
  );
}

function _shape(detail: string | undefined): PartyActionResult {
  return {
    error:
      ERROR_COPY[detail ?? "unknown"] ?? "Something went wrong. Try again.",
  };
}

function _bust() {
  revalidatePath("/basecamp/party");
}

export async function createMyPartyMemberAction(
  payload: PartyMemberCreate,
): Promise<PartyActionResult> {
  const api = await _api();
  const result = await createMyPartyMember(api, payload);
  if (!result.ok) return _shape(result.detail);
  _bust();
  return { ok: true };
}

export async function updateMyPartyMemberAction(
  memberId: string,
  payload: PartyMemberUpdate,
): Promise<PartyActionResult> {
  const api = await _api();
  const result = await updateMyPartyMember(api, memberId, payload);
  if (!result.ok) return _shape(result.detail);
  _bust();
  return { ok: true };
}

export async function archiveMyPartyMemberAction(
  memberId: string,
): Promise<PartyActionResult> {
  const api = await _api();
  const result = await archiveMyPartyMember(api, memberId);
  if (!result.ok) return _shape(result.detail);
  _bust();
  return { ok: true };
}
