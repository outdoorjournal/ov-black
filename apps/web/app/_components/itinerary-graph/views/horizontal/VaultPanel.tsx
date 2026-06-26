"use client";

import { useCallback, useEffect, useState } from "react";

import {
  type DocumentDetail,
  createApiClient,
  getClientDocumentDownload,
  listItineraryDocuments,
} from "@ov-black/api-client";

// Advisor "documents" surface — the itinerary-aside Vault tab (read-only).
//
// Documents are client-scoped (household assets), so they're inherently
// available on every trip; this tab just surfaces them for advisor convenience
// while building. Like ConciergeChat/PartyPanel it takes the staff credentials
// the store holds and calls the wrappers directly. Editing/uploading lives on
// the client-detail page + the traveler vault — here you can only view + open.

const ERROR_COPY: Record<string, string> = {
  client_not_found: "This client could not be found.",
  itinerary_not_found: "This itinerary could not be found.",
  document_not_found: "That document is no longer available.",
  network_error: "Could not reach the server. Try again in a moment.",
};

function copy(detail: string): string {
  return ERROR_COPY[detail] ?? "Something went wrong. Try again.";
}

const DOC_TYPE_LABELS: Record<string, string> = {
  passport: "Passport",
  visa: "Visa",
  drivers_license: "Driver's licence",
  national_id: "National ID",
  vaccination: "Vaccination",
  insurance: "Insurance",
  loyalty_card: "Loyalty card",
  other: "Document",
};

export function VaultPanel({
  clientId,
  itineraryId,
  apiBaseUrl,
  accessToken,
}: {
  clientId: string | null;
  itineraryId: string;
  apiBaseUrl: string | null;
  accessToken: string | null;
}) {
  const [documents, setDocuments] = useState<DocumentDetail[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  const api =
    apiBaseUrl && accessToken
      ? createApiClient({ baseUrl: apiBaseUrl, accessToken })
      : null;

  const refresh = useCallback(async () => {
    if (!api) return;
    const result = await listItineraryDocuments(api, itineraryId);
    if (result.ok) setDocuments(result.documents);
    else setError(copy(result.detail));
    setLoaded(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [itineraryId, apiBaseUrl, accessToken]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const download = (documentId: string) => {
    if (!api || !clientId) return;
    setError(null);
    setPending(true);
    void (async () => {
      const result = await getClientDocumentDownload(api, clientId, documentId);
      if (result.ok) window.open(result.url, "_blank", "noopener,noreferrer");
      else setError(copy(result.detail));
      setPending(false);
    })();
  };

  return (
    <div className="flex h-full flex-col gap-3 overflow-y-auto bg-paper px-4 py-4 text-ink">
      <h3 className="font-serif text-lg tracking-tight text-ink">
        Travel documents
      </h3>
      {!loaded ? (
        <p className="font-sans text-sm text-ink/50">Loading…</p>
      ) : documents.length === 0 ? (
        <p className="font-sans text-sm italic text-ink/50">
          No documents on file for this household yet.
        </p>
      ) : (
        <ul className="flex flex-col divide-y divide-ink/10 border-y border-ink/10">
          {documents.map((d) => (
            <li key={d.id} className="flex items-start gap-3 py-2.5">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-baseline gap-2">
                  <span className="truncate font-sans text-sm text-ink/90">
                    {d.label || d.file_name}
                  </span>
                  <span className="font-sans text-[10px] uppercase tracking-[0.2em] text-ink/45">
                    {DOC_TYPE_LABELS[d.doc_type] ?? "Document"}
                  </span>
                </div>
                <p className="mt-0.5 font-sans text-xs text-ink/55">
                  {d.party_member_name ? `${d.party_member_name} · ` : ""}
                  {d.expired
                    ? `Expired ${d.expires_at}`
                    : d.expires_soon
                      ? `Expires ${d.expires_at}`
                      : d.expires_at
                        ? `Expires ${d.expires_at}`
                        : "No expiry"}
                </p>
              </div>
              <button
                type="button"
                onClick={() => download(d.id)}
                disabled={pending}
                className="shrink-0 rounded-md border border-ink/20 bg-paper px-3 py-1 font-sans text-[10px] uppercase tracking-[0.2em] text-ink transition-colors hover:bg-ink/5 disabled:opacity-40"
              >
                Open
              </button>
            </li>
          ))}
        </ul>
      )}
      {error ? (
        <p role="alert" className="font-sans text-xs font-medium text-[#8b2a1d]">
          {error}
        </p>
      ) : null}
    </div>
  );
}
