"use server";

import { revalidatePath } from "next/cache";

import {
  type ClientContactCreate,
  type ClientContactUpdate,
  type DossierFactCreate,
  type DossierFactUpdate,
  type OsintFactCreate,
  type OsintFactUpdate,
  type ProfileFactCreate,
  type ProfileFactUpdate,
  type RedactRequest,
  createApiClient,
  createClientContact,
  createDossierFact,
  createOsintFact,
  createProfileFact,
  deleteClientContact,
  redactDossierFact,
  redactOsintFact,
  redactProfileFact,
  updateClientContact,
  updateDossierFact,
  updateOsintFact,
  updateProfileFact,
} from "@ov-black/api-client";

import { publicEnv } from "@/lib/env";
import { createServerSupabase } from "@/lib/supabase/server";

export type FactActionResult = { ok: true } | { error: string };

const ERROR_COPY: Record<string, string> = {
  advisor_only: "This workspace is advisor-only.",
  client_not_found: "This client could not be found.",
  fact_not_found: "This fact has already been removed.",
  contact_not_found: "This contact has already been removed.",
  invalid_source_kind: "That source kind is not allowed for this tier.",
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

function _shape(detail: string | undefined): FactActionResult {
  return {
    error:
      ERROR_COPY[detail ?? "unknown"] ?? "Something went wrong. Try again.",
  };
}

function _bust(clientId: string) {
  revalidatePath(`/command-center/clients/${clientId}`);
}

// ── Dossier ──────────────────────────────────────────────────────────────

export async function createDossierFactAction(
  clientId: string,
  payload: DossierFactCreate,
): Promise<FactActionResult> {
  const api = await _api();
  const result = await createDossierFact(api, clientId, payload);
  if (!result.ok) return _shape(result.detail);
  _bust(clientId);
  return { ok: true };
}

export async function updateDossierFactAction(
  clientId: string,
  factId: string,
  payload: DossierFactUpdate,
): Promise<FactActionResult> {
  const api = await _api();
  const result = await updateDossierFact(api, clientId, factId, payload);
  if (!result.ok) return _shape(result.detail);
  _bust(clientId);
  return { ok: true };
}

export async function redactDossierFactAction(
  clientId: string,
  factId: string,
  body: RedactRequest,
): Promise<FactActionResult> {
  const api = await _api();
  const result = await redactDossierFact(api, clientId, factId, body);
  if (!result.ok) return _shape(result.detail);
  _bust(clientId);
  return { ok: true };
}

// ── Profile ──────────────────────────────────────────────────────────────

export async function createProfileFactAction(
  clientId: string,
  payload: ProfileFactCreate,
): Promise<FactActionResult> {
  const api = await _api();
  const result = await createProfileFact(api, clientId, payload);
  if (!result.ok) return _shape(result.detail);
  _bust(clientId);
  return { ok: true };
}

export async function updateProfileFactAction(
  clientId: string,
  factId: string,
  payload: ProfileFactUpdate,
): Promise<FactActionResult> {
  const api = await _api();
  const result = await updateProfileFact(api, clientId, factId, payload);
  if (!result.ok) return _shape(result.detail);
  _bust(clientId);
  return { ok: true };
}

export async function redactProfileFactAction(
  clientId: string,
  factId: string,
  body: RedactRequest,
): Promise<FactActionResult> {
  const api = await _api();
  const result = await redactProfileFact(api, clientId, factId, body);
  if (!result.ok) return _shape(result.detail);
  _bust(clientId);
  return { ok: true };
}

// ── OSINT ────────────────────────────────────────────────────────────────

export async function createOsintFactAction(
  clientId: string,
  payload: OsintFactCreate,
): Promise<FactActionResult> {
  const api = await _api();
  const result = await createOsintFact(api, clientId, payload);
  if (!result.ok) return _shape(result.detail);
  _bust(clientId);
  return { ok: true };
}

export async function updateOsintFactAction(
  clientId: string,
  factId: string,
  payload: OsintFactUpdate,
): Promise<FactActionResult> {
  const api = await _api();
  const result = await updateOsintFact(api, clientId, factId, payload);
  if (!result.ok) return _shape(result.detail);
  _bust(clientId);
  return { ok: true };
}

export async function redactOsintFactAction(
  clientId: string,
  factId: string,
  body: RedactRequest,
): Promise<FactActionResult> {
  const api = await _api();
  const result = await redactOsintFact(api, clientId, factId, body);
  if (!result.ok) return _shape(result.detail);
  _bust(clientId);
  return { ok: true };
}

// ── Contacts ──────────────────────────────────────────────────────────────

export async function createClientContactAction(
  clientId: string,
  payload: ClientContactCreate,
): Promise<FactActionResult> {
  const api = await _api();
  const result = await createClientContact(api, clientId, payload);
  if (!result.ok) return _shape(result.detail);
  _bust(clientId);
  return { ok: true };
}

export async function updateClientContactAction(
  clientId: string,
  contactId: string,
  payload: ClientContactUpdate,
): Promise<FactActionResult> {
  const api = await _api();
  const result = await updateClientContact(api, clientId, contactId, payload);
  if (!result.ok) return _shape(result.detail);
  _bust(clientId);
  return { ok: true };
}

export async function deleteClientContactAction(
  clientId: string,
  contactId: string,
): Promise<FactActionResult> {
  const api = await _api();
  const result = await deleteClientContact(api, clientId, contactId);
  if (!result.ok) return _shape(result.detail);
  _bust(clientId);
  return { ok: true };
}
