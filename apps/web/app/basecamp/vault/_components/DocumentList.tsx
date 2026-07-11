"use client";

import { useState, useTransition } from "react";

import type {
  DocumentDetail,
  DocumentInitRequest,
  DocumentUpdate,
  PartyMemberDetail,
} from "@ov-black/api-client";

import { Button } from "@/components/ui/button";

import { DocumentMetaForm } from "./DocumentMetaForm";
import { DocumentUploadForm } from "./DocumentUploadForm";

// The shared dark-surface document list + upload, driven by server actions.
// Both the traveler vault and the advisor client-detail panel render this; only
// the wired actions differ. The itinerary read-only panel is separate (it talks
// to the API directly, like the party panel).

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

export type DocumentListActions = {
  onInit: (
    meta: DocumentInitRequest,
  ) => Promise<
    { ok: true; uploadUrl: string; documentId: string } | { error: string }
  >;
  onComplete: (
    documentId: string,
    sizeBytes: number | null,
  ) => Promise<{ ok: true } | { error: string }>;
  onUpdate: (
    documentId: string,
    patch: DocumentUpdate,
  ) => Promise<{ ok: true } | { error: string }>;
  onArchive: (documentId: string) => Promise<{ ok: true } | { error: string }>;
  onDownload: (
    documentId: string,
  ) => Promise<{ ok: true; url: string } | { error: string }>;
};

export function DocumentList({
  documents,
  members,
  actions,
  emptyCopy = "No documents yet.",
}: {
  documents: DocumentDetail[];
  members: PartyMemberDetail[];
  actions: DocumentListActions;
  emptyCopy?: string;
}) {
  const [adding, setAdding] = useState(false);

  return (
    <div className="flex flex-col gap-3">
      {adding ? (
        <DocumentUploadForm
          members={members}
          onInit={actions.onInit}
          onComplete={actions.onComplete}
          onDone={() => setAdding(false)}
          onCancel={() => setAdding(false)}
        />
      ) : (
        <Button
          type="button"
          variant="brand"
          size="sm"
          onClick={() => setAdding(true)}
          className="self-start"
        >
          Add a document
        </Button>
      )}

      {documents.length === 0 ? (
        <p className="font-sans text-sm italic text-paper/45">{emptyCopy}</p>
      ) : (
        <ul className="flex flex-col gap-3">
          {documents.map((d) => (
            <li key={d.id}>
              <DocumentRow document={d} members={members} actions={actions} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function ExpiryBadge({ document }: { document: DocumentDetail }) {
  if (!document.expires_at) return null;
  if (document.expired) {
    return (
      <span className="rounded-full border border-destructive/50 px-2 py-0.5 font-sans text-[10px] uppercase tracking-[0.2em] text-destructive">
        Expired {document.expires_at}
      </span>
    );
  }
  if (document.expires_soon) {
    return (
      <span className="rounded-full border border-amber-300/40 px-2 py-0.5 font-sans text-[10px] uppercase tracking-[0.2em] text-amber-200/90">
        Expires {document.expires_at}
      </span>
    );
  }
  return (
    <span className="font-sans text-xs text-paper/55">
      Expires {document.expires_at}
    </span>
  );
}

function DocumentRow({
  document,
  members,
  actions,
}: {
  document: DocumentDetail;
  members: PartyMemberDetail[];
  actions: DocumentListActions;
}) {
  const [editing, setEditing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  const download = () => {
    setError(null);
    startTransition(async () => {
      const result = await actions.onDownload(document.id);
      if ("error" in result) setError(result.error);
      else window.open(result.url, "_blank", "noopener,noreferrer");
    });
  };

  const archive = () => {
    if (!window.confirm(`Remove ${document.label || document.file_name}?`)) return;
    setError(null);
    startTransition(async () => {
      const result = await actions.onArchive(document.id);
      if ("error" in result) setError(result.error);
    });
  };

  if (editing) {
    return (
      <DocumentMetaForm
        document={document}
        members={members}
        onSave={(patch) => actions.onUpdate(document.id, patch)}
        onCancel={() => setEditing(false)}
      />
    );
  }

  const typeLabel = DOC_TYPE_LABELS[document.doc_type] ?? "Document";

  return (
    <div className="group flex items-start gap-4 rounded-sm border border-paper/10 bg-paper/4 px-4 py-3">
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline gap-2">
          <span className="font-serif text-lg tracking-tight text-paper">
            {document.label || document.file_name}
          </span>
          <span className="font-sans text-[10px] uppercase tracking-[0.25em] text-paper/45">
            {typeLabel}
          </span>
          {document.party_member_name ? (
            <span className="font-sans text-xs text-paper/55">
              {document.party_member_name}
            </span>
          ) : null}
          <ExpiryBadge document={document} />
          {!document.uploaded_at ? (
            <span className="font-sans text-[10px] uppercase tracking-[0.2em] text-paper/40">
              uploading…
            </span>
          ) : null}
        </div>
        {document.notes ? (
          <p className="mt-1 font-sans text-xs text-paper/55">{document.notes}</p>
        ) : null}
        {error ? (
          <p role="alert" className="mt-1 font-sans text-xs text-destructive">
            {error}
          </p>
        ) : null}
      </div>
      <div className="flex shrink-0 gap-2 opacity-0 transition-opacity group-hover:opacity-100 md:opacity-100">
        <button
          type="button"
          onClick={download}
          disabled={isPending}
          className="font-sans text-[10px] uppercase tracking-[0.2em] text-paper/55 transition-colors hover:text-paper"
        >
          Download
        </button>
        <span className="text-paper/20">·</span>
        <button
          type="button"
          onClick={() => setEditing(true)}
          disabled={isPending}
          className="font-sans text-[10px] uppercase tracking-[0.2em] text-paper/55 transition-colors hover:text-paper"
        >
          Edit
        </button>
        <span className="text-paper/20">·</span>
        <button
          type="button"
          onClick={archive}
          disabled={isPending}
          className="font-sans text-[10px] uppercase tracking-[0.2em] text-paper/55 transition-colors hover:text-destructive"
        >
          Remove
        </button>
      </div>
    </div>
  );
}
