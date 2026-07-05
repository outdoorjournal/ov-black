"use client";

import Link from "next/link";

import type { DocumentDetail, PartyMemberDetail } from "@ov-black/api-client";

import {
  archiveMyDocumentAction,
  completeMyDocumentAction,
  getMyDocumentDownloadAction,
  initMyDocumentUploadAction,
  updateMyDocumentAction,
} from "../actions";
import { DocumentList, type DocumentListActions } from "./DocumentList";

// Traveler self-service vault. Thin wrapper over the shared DocumentList, wiring
// the /me/* server actions; the list itself drives off the `documents` prop and
// revalidates on mutation.

export function VaultManager({
  documents,
  members,
}: {
  documents: DocumentDetail[];
  members: PartyMemberDetail[];
}) {
  const actions: DocumentListActions = {
    onInit: (meta) => initMyDocumentUploadAction(meta),
    onComplete: (id, size) => completeMyDocumentAction(id, size),
    onUpdate: (id, patch) => updateMyDocumentAction(id, patch),
    onArchive: (id) => archiveMyDocumentAction(id),
    onDownload: (id) => getMyDocumentDownloadAction(id),
  };

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-8 px-6 pb-16 pt-2 sm:px-10">
      <header className="flex flex-col gap-3 border-b border-paper/10 pb-6">
        <Link
          href="/basecamp"
          className="font-sans text-[10px] uppercase tracking-eyebrow text-paper/55 transition-colors hover:text-paper"
        >
          ← Basecamp
        </Link>
        <h1 className="font-serif text-4xl tracking-tight text-paper sm:text-5xl">
          Your vault
        </h1>
        <p className="max-w-xl font-sans text-sm leading-relaxed text-paper/70">
          Passports, visas, insurance — stored securely and remembered across
          every trip. Add a document once; your concierge has it whenever it&rsquo;s
          needed, and we&rsquo;ll flag anything close to expiring.
        </p>
      </header>

      <DocumentList
        documents={documents}
        members={members}
        actions={actions}
        emptyCopy="No documents yet. Add the first to begin."
      />
    </div>
  );
}
