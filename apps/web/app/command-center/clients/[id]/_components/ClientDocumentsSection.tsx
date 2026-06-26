"use client";

import type { DocumentDetail, PartyMemberDetail } from "@ov-black/api-client";

import {
  DocumentList,
  type DocumentListActions,
} from "@/app/basecamp/vault/_components/DocumentList";

import {
  archiveClientDocumentAction,
  completeClientDocumentAction,
  getClientDocumentDownloadAction,
  initClientDocumentUploadAction,
  updateClientDocumentAction,
} from "../actions";

// The advisor's view of a client's secure vault — the "advisor views it"
// surface. Reuses the same DocumentList the traveler uses; only the actions are
// the client-scoped variants (closing over clientId).

export function ClientDocumentsSection({
  clientId,
  documents,
  members,
}: {
  clientId: string;
  documents: DocumentDetail[];
  members: PartyMemberDetail[];
}) {
  const actions: DocumentListActions = {
    onInit: (meta) => initClientDocumentUploadAction(clientId, meta),
    onComplete: (id, size) => completeClientDocumentAction(clientId, id, size),
    onUpdate: (id, patch) => updateClientDocumentAction(clientId, id, patch),
    onArchive: (id) => archiveClientDocumentAction(clientId, id),
    onDownload: (id) => getClientDocumentDownloadAction(clientId, id),
  };

  return (
    <DocumentList
      documents={documents}
      members={members}
      actions={actions}
      emptyCopy="No documents on file yet."
    />
  );
}
