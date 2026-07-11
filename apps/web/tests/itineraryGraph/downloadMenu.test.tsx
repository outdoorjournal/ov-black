// The hero's Download affordance (PDF / Excel). Pins: both formats render;
// clicking calls downloadItineraryExport with the store's itineraryId + format;
// a success object-URLs the blob and clicks a synthetic <a download>; a failure
// shows the inline error. A credential-less viewer sees nothing.

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

const downloadExportMock = vi.fn();
vi.mock("@ov-black/api-client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@ov-black/api-client")>();
  return {
    ...actual,
    createApiClient: vi.fn(() => ({})),
    downloadItineraryExport: (...args: unknown[]) => downloadExportMock(...args),
  };
});

import {
  itineraryGraphStore,
  type ItineraryGraphInit,
} from "@/app/_components/itinerary-graph/store/itineraryGraphStore";
import type { ItineraryTimeline } from "@/app/_components/itinerary-graph/model/types";
import { DownloadMenu } from "@/app/itinerary/[id]/_shell/DownloadMenu";

function timeline(): ItineraryTimeline {
  return {
    id: "it-1",
    label: "Trip",
    subtitle: "",
    mood: "tidal",
    timezoneOffsetHours: 0,
    windowStart: "2026-06-01T00:00:00Z",
    windowEnd: "2026-06-02T00:00:00Z",
    days: [],
    itinerary: {
      id: "it-1",
      title: "Trip",
      client_id: "c-1",
      created_by: "u-1",
      display_status: "in_studio",
    },
    nodes: [],
    edges: [],
  };
}

function renderMenu(partial: Partial<ItineraryGraphInit> = {}) {
  const init: ItineraryGraphInit = {
    timeline: timeline(),
    itineraryId: "it-1",
    status: "in_studio",
    role: "client",
    apiBaseUrl: "http://api.test",
    accessToken: "tok",
    ...partial,
  };
  return render(
    <itineraryGraphStore.Provider initial={init}>
      <DownloadMenu />
    </itineraryGraphStore.Provider>,
  );
}

const clickMock = vi.fn();

beforeEach(() => {
  vi.clearAllMocks();
  // jsdom lacks object-URL + anchor-click download plumbing; stub them.
  globalThis.URL.createObjectURL = vi.fn(() => "blob:mock");
  globalThis.URL.revokeObjectURL = vi.fn();
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(clickMock);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("DownloadMenu", () => {
  test("opens a menu with both formats", () => {
    renderMenu();
    fireEvent.click(screen.getByTestId("hero-download"));
    expect(screen.getByTestId("hero-download-pdf")).toBeInTheDocument();
    expect(screen.getByTestId("hero-download-xlsx")).toBeInTheDocument();
  });

  test("clicking PDF downloads via the wrapper and triggers a file download", async () => {
    downloadExportMock.mockResolvedValue({
      ok: true,
      blob: new Blob(["%PDF"], { type: "application/pdf" }),
      filename: "Trip-2026-06-01.pdf",
    });
    renderMenu();
    fireEvent.click(screen.getByTestId("hero-download"));
    fireEvent.click(screen.getByTestId("hero-download-pdf"));

    await waitFor(() =>
      expect(downloadExportMock).toHaveBeenCalledWith(
        expect.anything(),
        "it-1",
        "pdf",
      ),
    );
    await waitFor(() => expect(clickMock).toHaveBeenCalled());
    expect(globalThis.URL.createObjectURL).toHaveBeenCalled();
    expect(globalThis.URL.revokeObjectURL).toHaveBeenCalled();
  });

  test("clicking Excel requests the xlsx format", async () => {
    downloadExportMock.mockResolvedValue({
      ok: true,
      blob: new Blob(["PK"]),
      filename: "Trip.xlsx",
    });
    renderMenu();
    fireEvent.click(screen.getByTestId("hero-download"));
    fireEvent.click(screen.getByTestId("hero-download-xlsx"));
    await waitFor(() =>
      expect(downloadExportMock).toHaveBeenCalledWith(
        expect.anything(),
        "it-1",
        "xlsx",
      ),
    );
  });

  test("a failed export shows the inline error and downloads nothing", async () => {
    downloadExportMock.mockResolvedValue({ ok: false, status: 500 });
    renderMenu();
    fireEvent.click(screen.getByTestId("hero-download"));
    fireEvent.click(screen.getByTestId("hero-download-pdf"));
    await waitFor(() =>
      expect(screen.getByTestId("hero-download-error")).toBeInTheDocument(),
    );
    expect(clickMock).not.toHaveBeenCalled();
  });

  test("a credential-less viewer sees no download control", () => {
    renderMenu({ apiBaseUrl: null, accessToken: null });
    expect(screen.queryByTestId("hero-download")).not.toBeInTheDocument();
  });
});
