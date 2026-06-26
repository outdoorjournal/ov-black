// M003/V3 — DocumentUploadForm: the two-step presigned upload flow.
//
// onInit/onComplete + the global fetch (the S3 PUT) are mocked so we assert the
// component's orchestration without a backend or S3:
//   - a file is required before submit,
//   - submit maps the metadata (incl. party_member_id + notes) into onInit,
//   - on init success the browser PUTs the file to the presigned URL, then
//     calls onComplete with the byte size.

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import type { DocumentInitRequest, PartyMemberDetail } from "@ov-black/api-client";

import { DocumentUploadForm } from "@/app/basecamp/vault/_components/DocumentUploadForm";

function member(id: string, name: string): PartyMemberDetail {
  return {
    id,
    client_id: "c-1",
    full_name: name,
    date_of_birth: null,
    nationality: null,
    dietary: null,
    medical: null,
    mobility: null,
    loyalty_programs: [],
    emergency_contact: {},
    relationship_to_primary: null,
    is_primary: false,
    notes: null,
    created_by_actor: "traveler",
    updated_by_actor: "traveler",
    archived_at: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  };
}

const MEMBERS = [member("m-kid", "Kiddo")];

beforeEach(() => {
  vi.restoreAllMocks();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function setFile(name = "passport.pdf", type = "application/pdf") {
  const input = document.querySelector(
    'input[type="file"]',
  ) as HTMLInputElement;
  const file = new File(["bytes"], name, { type });
  fireEvent.change(input, { target: { files: [file] } });
  return file;
}

test("requires a file before submitting", async () => {
  const onInit = vi.fn();
  const onComplete = vi.fn();
  render(
    <DocumentUploadForm
      members={MEMBERS}
      onInit={onInit}
      onComplete={onComplete}
    />,
  );

  fireEvent.click(screen.getByRole("button", { name: "Upload document" }));
  expect(await screen.findByText(/choose a file to upload/i)).toBeInTheDocument();
  expect(onInit).not.toHaveBeenCalled();
});

test("maps metadata, PUTs to the presigned URL, then completes", async () => {
  const onInit = vi.fn(async (_meta: DocumentInitRequest) => ({
    ok: true as const,
    uploadUrl: "https://mock-s3.local/vault/c-1/d-1/passport.pdf?op=put",
    documentId: "d-1",
  }));
  const onComplete = vi.fn(async (_id: string, _size: number | null) => ({
    ok: true as const,
  }));
  const fetchMock = vi.fn(
    async (_url: string, _opts?: RequestInit) => ({ ok: true }) as Response,
  );
  vi.stubGlobal("fetch", fetchMock);

  render(
    <DocumentUploadForm
      members={MEMBERS}
      onInit={onInit}
      onComplete={onComplete}
    />,
  );

  // Choose the linked member + add notes, then attach a file and submit.
  fireEvent.change(screen.getByDisplayValue("— whole household —"), {
    target: { value: "m-kid" },
  });
  fireEvent.change(screen.getByPlaceholderText(/anything the concierge/i), {
    target: { value: "renew before Japan" },
  });
  const file = setFile();
  fireEvent.click(screen.getByRole("button", { name: "Upload document" }));

  await waitFor(() => expect(onInit).toHaveBeenCalledTimes(1));
  const meta = onInit.mock.calls[0]![0];
  expect(meta).toMatchObject({
    doc_type: "passport",
    file_name: "passport.pdf",
    content_type: "application/pdf",
    party_member_id: "m-kid",
    notes: "renew before Japan",
  });

  // The browser PUTs the file straight to S3.
  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
  expect(fetchMock.mock.calls[0]![0]).toContain("mock-s3.local");
  expect(fetchMock.mock.calls[0]![1]).toMatchObject({ method: "PUT" });

  // Then it confirms with the byte size.
  await waitFor(() =>
    expect(onComplete).toHaveBeenCalledWith("d-1", file.size),
  );
});

test("surfaces an init error and never PUTs", async () => {
  const onInit = vi.fn(async () => ({ error: "Could not reach the server." }));
  const onComplete = vi.fn();
  const fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);

  render(
    <DocumentUploadForm
      members={MEMBERS}
      onInit={onInit}
      onComplete={onComplete}
    />,
  );
  setFile();
  fireEvent.click(screen.getByRole("button", { name: "Upload document" }));

  expect(
    await screen.findByText(/could not reach the server/i),
  ).toBeInTheDocument();
  expect(fetchMock).not.toHaveBeenCalled();
  expect(onComplete).not.toHaveBeenCalled();
});
