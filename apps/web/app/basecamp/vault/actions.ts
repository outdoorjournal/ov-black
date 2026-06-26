"use server";

import { revalidatePath } from "next/cache";

import {
  type DocumentInitRequest,
  type DocumentUpdate,
  archiveMyDocument,
  completeMyDocument,
  createApiClient,
  getMyDocumentDownload,
  initMyDocumentUpload,
  updateMyDocument,
} from "@ov-black/api-client";

import { publicEnv } from "@/lib/env";
import { createServerSupabase } from "@/lib/supabase/server";

// Traveler self-service vault mutations. The upload is a two-step presigned
// flow: the browser asks the API to begin (init → presigned PUT), uploads the
// bytes straight to S3, then confirms (complete). Only the init + complete +
// metadata edits touch the API; the bytes never pass through here.

export type VaultActionResult = { ok: true } | { error: string };
export type InitActionResult =
  | { ok: true; uploadUrl: string; documentId: string }
  | { error: string };
export type DownloadActionResult = { ok: true; url: string } | { error: string };

const ERROR_COPY: Record<string, string> = {
  client_not_found: "We couldn't find your account. Reach your concierge.",
  document_not_found: "That document has already been removed.",
  party_member_not_found: "That traveler is no longer in your party.",
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

function _copy(detail: string | undefined): string {
  return ERROR_COPY[detail ?? "unknown"] ?? "Something went wrong. Try again.";
}

function _bust() {
  revalidatePath("/basecamp/vault");
}

export async function initMyDocumentUploadAction(
  meta: DocumentInitRequest,
): Promise<InitActionResult> {
  const api = await _api();
  const result = await initMyDocumentUpload(api, meta);
  if (!result.ok) return { error: _copy(result.detail) };
  // No revalidate yet — the row is pending until the browser confirms.
  return { ok: true, uploadUrl: result.uploadUrl, documentId: result.document.id };
}

export async function completeMyDocumentAction(
  documentId: string,
  sizeBytes: number | null,
): Promise<VaultActionResult> {
  const api = await _api();
  const result = await completeMyDocument(api, documentId, {
    size_bytes: sizeBytes,
  });
  if (!result.ok) return { error: _copy(result.detail) };
  _bust();
  return { ok: true };
}

export async function updateMyDocumentAction(
  documentId: string,
  patch: DocumentUpdate,
): Promise<VaultActionResult> {
  const api = await _api();
  const result = await updateMyDocument(api, documentId, patch);
  if (!result.ok) return { error: _copy(result.detail) };
  _bust();
  return { ok: true };
}

export async function archiveMyDocumentAction(
  documentId: string,
): Promise<VaultActionResult> {
  const api = await _api();
  const result = await archiveMyDocument(api, documentId);
  if (!result.ok) return { error: _copy(result.detail) };
  _bust();
  return { ok: true };
}

export async function getMyDocumentDownloadAction(
  documentId: string,
): Promise<DownloadActionResult> {
  const api = await _api();
  const result = await getMyDocumentDownload(api, documentId);
  if (!result.ok) return { error: _copy(result.detail) };
  return { ok: true, url: result.url };
}
