// S08 T05 — vitest for the advisor draft-itinerary editor surface.
//
// Covers the S08 plan bullets for this task:
//   (a) Edit click → acquireItineraryLock POST fires
//   (b) Release click → releaseItineraryLock POST fires
//   (d) locked-by-other (409 on lock) disables Edit and renders the
//       advisory-notice copy
//
// The old (c) approve-button flow was deleted with the whole-itinerary
// approve endpoint (trunk + forks model); the editor is rebuilt next wave.
//
// The component is rendered directly (not through the RSC) because the
// server-side branch is trivial typecheck-territory — these bullets are
// strictly client-side reducer + fetch interactions.

import { act, fireEvent, render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import type {
  EdgeResponse,
  ItineraryResponse,
  NodeResponse,
} from "@ov-black/api-client";

import { DraftItineraryEditor } from "@/app/command-center/itineraries/[id]/_components/DraftItineraryEditor";

// ── fixtures ────────────────────────────────────────────────────────────────

const ITINERARY_ID = "itin-s08-1";
const NODE_A = "11111111-1111-1111-1111-111111111111";
const NODE_B = "22222222-2222-2222-2222-222222222222";

function buildNodes(): NodeResponse[] {
  return [
    {
      id: NODE_A,
      itinerary_id: ITINERARY_ID,
      parent_subgraph_id: null,
      type: "experience",
      status: "pending",
      title: "Heli-ski Chugach",
      source: "ov",
      source_id: "ov-123",
      metadata: {},
    },
    {
      id: NODE_B,
      itinerary_id: ITINERARY_ID,
      parent_subgraph_id: null,
      type: "experience",
      status: "pending",
      title: "Sahara glamping",
      source: "ov",
      source_id: "ov-42",
      metadata: {},
    },
  ];
}

function buildItineraryBody(overrides: Partial<ItineraryResponse> = {}): ItineraryResponse {
  return {
    id: ITINERARY_ID,
    title: "Concierge draft",
    client_id: "client-s08",
    created_by: "advisor-s08",
    display_status: "in_studio",
    ...overrides,
  };
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

type CapturedRequest = { method: string; url: string; body: string | null };

function captureFetch(
  seen: CapturedRequest[],
  handler: (req: CapturedRequest) => Response,
) {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    let url: string;
    let method: string;
    let bodyText: string | null = null;
    if (input instanceof Request) {
      url = input.url;
      method = input.method;
      try {
        bodyText = await input.clone().text();
      } catch {
        bodyText = null;
      }
    } else {
      url = typeof input === "string" ? input : input.toString();
      method = (init?.method ?? "GET").toUpperCase();
      bodyText =
        typeof init?.body === "string"
          ? init.body
          : init?.body == null
          ? null
          : String(init.body);
    }
    const captured: CapturedRequest = { method, url, body: bodyText };
    seen.push(captured);
    return handler(captured);
  });
}

// ── lifecycle ──────────────────────────────────────────────────────────────

const originalFetch = globalThis.fetch;

beforeEach(() => {
  vi.restoreAllMocks();
});

afterEach(() => {
  globalThis.fetch = originalFetch;
});

// ── (a) Edit → acquireItineraryLock fires ──────────────────────────────────

test("Edit click calls acquireItineraryLock and flips lock status", async () => {
  const seen: CapturedRequest[] = [];
  globalThis.fetch = captureFetch(seen, (req) => {
    if (req.url.includes("/lock")) {
      return jsonResponse(buildItineraryBody(), 200);
    }
    return jsonResponse({ detail: "unexpected" }, 500);
  }) as unknown as typeof fetch;

  const edges: EdgeResponse[] = [];
  const { getByTestId } = render(
    <DraftItineraryEditor
      itineraryId={ITINERARY_ID}
      apiBaseUrl="http://api.test"
      accessToken="test-token"
      initialNodes={buildNodes()}
      initialEdges={edges}
      initialStatus="in_studio"
    />,
  );

  const editor = getByTestId("draft-itinerary-editor");
  expect(editor.getAttribute("data-lock-status")).toBe("unlocked");

  await act(async () => {
    fireEvent.click(getByTestId("draft-itinerary-edit"));
  });

  await waitFor(() => {
    const lockCalls = seen.filter(
      (r) => r.method === "POST" && r.url.endsWith(`/itinerary/${ITINERARY_ID}/lock`),
    );
    expect(lockCalls).toHaveLength(1);
  });

  expect(editor.getAttribute("data-lock-status")).toBe("locked-by-me");
  // Inputs become editable once the lock is held. Two nodes render two
  // title inputs — check the first; both share the same readOnly state.
  const titleInputs = editor.querySelectorAll<HTMLInputElement>(
    '[data-testid="draft-itinerary-node-title"]',
  );
  expect(titleInputs.length).toBeGreaterThan(0);
  const firstTitleInput = titleInputs[0];
  if (!firstTitleInput) throw new Error("expected at least one title input");
  expect(firstTitleInput.readOnly).toBe(false);
});

// ── (b) Release → releaseItineraryLock fires ───────────────────────────────

test("Release click calls releaseItineraryLock and clears lock status", async () => {
  const seen: CapturedRequest[] = [];
  globalThis.fetch = captureFetch(seen, (req) => {
    if (req.url.endsWith("/lock")) {
      return jsonResponse(buildItineraryBody(), 200);
    }
    if (req.url.endsWith("/release")) {
      return jsonResponse(
        { itinerary: buildItineraryBody(), replayed_count: 0 },
        200,
      );
    }
    return jsonResponse({ detail: "unexpected" }, 500);
  }) as unknown as typeof fetch;

  const { getByTestId } = render(
    <DraftItineraryEditor
      itineraryId={ITINERARY_ID}
      apiBaseUrl="http://api.test"
      accessToken="test-token"
      initialNodes={buildNodes()}
      initialEdges={[]}
      initialStatus="in_studio"
    />,
  );

  // Acquire the lock first so Release is enabled.
  await act(async () => {
    fireEvent.click(getByTestId("draft-itinerary-edit"));
  });
  await waitFor(() => {
    expect(getByTestId("draft-itinerary-editor").getAttribute("data-lock-status"))
      .toBe("locked-by-me");
  });

  await act(async () => {
    fireEvent.click(getByTestId("draft-itinerary-release"));
  });

  await waitFor(() => {
    const releaseCalls = seen.filter(
      (r) =>
        r.method === "POST" && r.url.endsWith(`/itinerary/${ITINERARY_ID}/release`),
    );
    expect(releaseCalls).toHaveLength(1);
  });
  expect(getByTestId("draft-itinerary-editor").getAttribute("data-lock-status"))
    .toBe("unlocked");
});

// ── (d) locked-by-other → Edit disabled + notice rendered ──────────────────

test("locked-by-other collapses Edit to disabled + shows advisory notice", async () => {
  const seen: CapturedRequest[] = [];
  globalThis.fetch = captureFetch(seen, (req) => {
    if (req.url.endsWith("/lock")) {
      return jsonResponse({ detail: "already_locked" }, 409);
    }
    return jsonResponse({ detail: "unexpected" }, 500);
  }) as unknown as typeof fetch;

  const { getByTestId, queryByTestId } = render(
    <DraftItineraryEditor
      itineraryId={ITINERARY_ID}
      apiBaseUrl="http://api.test"
      accessToken="test-token"
      initialNodes={buildNodes()}
      initialEdges={[]}
      initialStatus="in_studio"
    />,
  );

  await act(async () => {
    fireEvent.click(getByTestId("draft-itinerary-edit"));
  });

  await waitFor(() => {
    expect(getByTestId("draft-itinerary-editor").getAttribute("data-lock-status"))
      .toBe("locked-by-other");
  });
  const editButton = getByTestId("draft-itinerary-edit") as HTMLButtonElement;
  expect(editButton.disabled).toBe(true);
  expect(queryByTestId("draft-itinerary-locked-notice")).not.toBeNull();
});
