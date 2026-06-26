// M003/V3 — advisor itinerary read-only VaultPanel. The wrappers are mocked so
// we assert it lists the household's documents and opens a presigned download.

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";

vi.mock("@ov-black/api-client", () => ({
  createApiClient: vi.fn(() => ({})),
  listItineraryDocuments: vi.fn(),
  getClientDocumentDownload: vi.fn(),
}));

import {
  getClientDocumentDownload,
  listItineraryDocuments,
  type DocumentDetail,
} from "@ov-black/api-client";

import { VaultPanel } from "@/app/_components/itinerary-graph/views/horizontal/VaultPanel";

function doc(over: Partial<DocumentDetail> = {}): DocumentDetail {
  return {
    id: "d-1",
    client_id: "c-1",
    party_member_id: null,
    party_member_name: "Kiddo",
    doc_type: "passport",
    label: "Kid passport",
    file_name: "kid.pdf",
    content_type: "application/pdf",
    size_bytes: 1024,
    expires_at: "2026-09-01",
    notes: null,
    expired: false,
    expires_soon: true,
    uploaded_at: "2026-01-02T00:00:00Z",
    created_by_actor: "traveler",
    archived_at: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...over,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(listItineraryDocuments).mockResolvedValue({
    ok: true,
    documents: [doc()],
  });
});

function renderPanel() {
  return render(
    <VaultPanel
      clientId="c-1"
      itineraryId="it-1"
      apiBaseUrl="http://api.test"
      accessToken="tok"
    />,
  );
}

test("lists the itinerary's household documents", async () => {
  renderPanel();
  await waitFor(() =>
    expect(listItineraryDocuments).toHaveBeenCalledWith({}, "it-1"),
  );
  await screen.findByText("Kid passport");
  expect(screen.getByText(/Kiddo · Expires 2026-09-01/)).toBeInTheDocument();
});

test("Open mints a presigned download via the client-scoped wrapper", async () => {
  vi.mocked(getClientDocumentDownload).mockResolvedValue({
    ok: true,
    url: "https://dl",
  });
  const open = vi.spyOn(window, "open").mockReturnValue(null);
  renderPanel();

  const btn = await screen.findByRole("button", { name: "Open" });
  fireEvent.click(btn);

  await waitFor(() =>
    expect(getClientDocumentDownload).toHaveBeenCalledWith({}, "c-1", "d-1"),
  );
  await waitFor(() =>
    expect(open).toHaveBeenCalledWith(
      "https://dl",
      "_blank",
      "noopener,noreferrer",
    ),
  );
});
