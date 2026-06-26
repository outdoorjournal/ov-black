// M003/V3 — DocumentList: the shared dark-surface vault list (traveler +
// advisor). Actions are mocked so we assert rendering + wiring:
//   - documents render with label/type/linked-member,
//   - expiry derivation drives the badge copy (expired vs expires-soon),
//   - Download calls onDownload then opens the presigned URL,
//   - Remove (confirmed) calls onArchive.

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";

import type { DocumentDetail } from "@ov-black/api-client";

import {
  DocumentList,
  type DocumentListActions,
} from "@/app/basecamp/vault/_components/DocumentList";

function doc(over: Partial<DocumentDetail> = {}): DocumentDetail {
  return {
    id: "d-1",
    client_id: "c-1",
    party_member_id: null,
    party_member_name: null,
    doc_type: "passport",
    label: "My passport",
    file_name: "passport.pdf",
    content_type: "application/pdf",
    size_bytes: 2048,
    expires_at: null,
    notes: null,
    expired: false,
    expires_soon: false,
    uploaded_at: "2026-01-02T00:00:00Z",
    created_by_actor: "traveler",
    archived_at: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...over,
  };
}

function actions(over: Partial<DocumentListActions> = {}): DocumentListActions {
  return {
    onInit: vi.fn(async () => ({
      ok: true as const,
      uploadUrl: "u",
      documentId: "d",
    })),
    onComplete: vi.fn(async () => ({ ok: true as const })),
    onUpdate: vi.fn(async () => ({ ok: true as const })),
    onArchive: vi.fn(async () => ({ ok: true as const })),
    onDownload: vi.fn(async () => ({ ok: true as const, url: "https://dl" })),
    ...over,
  };
}

beforeEach(() => {
  vi.restoreAllMocks();
});

test("renders documents with label, type and linked member", () => {
  render(
    <DocumentList
      documents={[doc({ party_member_name: "Kiddo" })]}
      members={[]}
      actions={actions()}
    />,
  );
  expect(screen.getByText("My passport")).toBeInTheDocument();
  expect(screen.getByText("Passport")).toBeInTheDocument();
  expect(screen.getByText("Kiddo")).toBeInTheDocument();
});

test("expiry derivation drives the badge", () => {
  const { rerender } = render(
    <DocumentList
      documents={[doc({ expires_at: "2026-01-01", expired: true })]}
      members={[]}
      actions={actions()}
    />,
  );
  expect(screen.getByText(/expired 2026-01-01/i)).toBeInTheDocument();

  rerender(
    <DocumentList
      documents={[doc({ expires_at: "2026-09-01", expires_soon: true })]}
      members={[]}
      actions={actions()}
    />,
  );
  expect(screen.getByText(/expires 2026-09-01/i)).toBeInTheDocument();
});

test("Download opens the presigned URL", async () => {
  const open = vi.spyOn(window, "open").mockReturnValue(null);
  const a = actions();
  render(<DocumentList documents={[doc()]} members={[]} actions={a} />);

  fireEvent.click(screen.getByRole("button", { name: "Download" }));
  await waitFor(() => expect(a.onDownload).toHaveBeenCalledWith("d-1"));
  await waitFor(() =>
    expect(open).toHaveBeenCalledWith(
      "https://dl",
      "_blank",
      "noopener,noreferrer",
    ),
  );
});

test("Remove (confirmed) archives", async () => {
  vi.spyOn(window, "confirm").mockReturnValue(true);
  const a = actions();
  render(<DocumentList documents={[doc()]} members={[]} actions={a} />);

  fireEvent.click(screen.getByRole("button", { name: "Remove" }));
  await waitFor(() => expect(a.onArchive).toHaveBeenCalledWith("d-1"));
});
