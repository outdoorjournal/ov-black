// S08 slice-acceptance suite — six bullets, one test() each.
//
// Mirrors the S07 pattern: each acceptance bullet is encoded as one
// independently failing assertion so verify-s08.sh can print PASS/FAIL
// per bullet and a future agent can localize a regression to exactly one
// invariant without reading the test body.
//
// Bullets:
//   (1) draft editor renders assembled nodes from getItinerary fixture
//   (2) Edit button acquires lock and enables inline editors
//   (3) Approve transitions status optimistically and disables on approved
//   (4) craft-feel invariants under data-testid='draft-itinerary-editor'
//   (5) Release dispatches releaseItineraryLock and clears lock indicator
//   (6) Non-advisor GET /itinerary/{id} on draft returns 403 mapped to
//       detail='forbidden' through the SDK wrapper

import { act, fireEvent, render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import {
  createApiClient,
  getItinerary,
  type EdgeResponse,
  type ItineraryResponse,
  type NodeResponse,
} from "@ov-black/api-client";

import { DraftItineraryEditor } from "@/app/command-center/itineraries/[id]/_components/DraftItineraryEditor";

import draftFixture from "./fixtures/s08_draft_itinerary.json";

// ── fixture typing ─────────────────────────────────────────────────────────

type DraftFixture = {
  itinerary: ItineraryResponse;
  nodes: NodeResponse[];
  edges: EdgeResponse[];
};

const fixture = draftFixture as DraftFixture;
const ITINERARY_ID = fixture.itinerary.id;

// ── fetch helpers ──────────────────────────────────────────────────────────

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
      method = input.method.toUpperCase();
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

// ── bullet 1: draft editor renders assembled nodes from fixture ────────────

test("(1) draft editor renders assembled nodes from getItinerary fixture", () => {
  // No fetch needed — the editor takes initialNodes directly. Bullet 1 is the
  // hydrated-render contract: given the assembled graph, three nodes show up
  // and the itinerary status data-attribute is `draft`.
  globalThis.fetch = vi.fn().mockResolvedValue(
    jsonResponse({ detail: "unexpected" }, 500),
  ) as unknown as typeof fetch;

  const { getByTestId } = render(
    <DraftItineraryEditor
      itineraryId={ITINERARY_ID}
      apiBaseUrl="http://api.test"
      accessToken="test-token"
      initialNodes={fixture.nodes}
      initialEdges={fixture.edges}
      initialStatus={fixture.itinerary.status ?? "draft"}
    />,
  );

  const editor = getByTestId("draft-itinerary-editor");
  expect(editor.getAttribute("data-itinerary-status")).toBe("draft");

  const titleInputs = editor.querySelectorAll<HTMLInputElement>(
    '[data-testid="draft-itinerary-node-title"]',
  );
  expect(titleInputs.length).toBe(3);
  const renderedTitles = Array.from(titleInputs).map((el) => el.defaultValue);
  for (const node of fixture.nodes) {
    expect(renderedTitles).toContain(node.title);
  }
});

// ── bullet 2: Edit button acquires lock and enables inline editors ─────────

test("(2) Edit button acquires lock and enables inline editors", async () => {
  const seen: CapturedRequest[] = [];
  globalThis.fetch = captureFetch(seen, (req) => {
    if (req.method === "POST" && req.url.endsWith(`/itinerary/${ITINERARY_ID}/lock`)) {
      return jsonResponse(
        {
          ...fixture.itinerary,
          // Ensure the response carries a real locked_by — even though the
          // editor doesn't read it back today, this matches the contract.
          locked_by: "advisor-uuid",
        },
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
      initialNodes={fixture.nodes}
      initialEdges={fixture.edges}
      initialStatus="draft"
    />,
  );

  const editor = getByTestId("draft-itinerary-editor");
  expect(editor.getAttribute("data-lock-status")).toBe("unlocked");

  await act(async () => {
    fireEvent.click(getByTestId("draft-itinerary-edit"));
  });

  await waitFor(() => {
    expect(editor.getAttribute("data-lock-status")).toBe("locked-by-me");
  });

  const titleInputs = editor.querySelectorAll<HTMLInputElement>(
    '[data-testid="draft-itinerary-node-title"]',
  );
  expect(titleInputs.length).toBeGreaterThan(0);
  for (const input of Array.from(titleInputs)) {
    expect(input.readOnly).toBe(false);
  }
});

// ── bullet 3: Approve transitions status optimistically + disables on approved

test("(3) Approve transitions status optimistically and disables the button on approved", async () => {
  const seen: CapturedRequest[] = [];
  globalThis.fetch = captureFetch(seen, (req) => {
    if (req.method === "POST" && req.url.endsWith(`/itinerary/${ITINERARY_ID}/approve`)) {
      return jsonResponse(
        { ...fixture.itinerary, status: "approved" },
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
      initialNodes={fixture.nodes}
      initialEdges={fixture.edges}
      initialStatus="draft"
    />,
  );

  const approveButton = getByTestId(
    "draft-itinerary-approve",
  ) as HTMLButtonElement;
  expect(approveButton.disabled).toBe(false);

  await act(async () => {
    fireEvent.click(approveButton);
  });

  await waitFor(() => {
    expect(
      getByTestId("draft-itinerary-editor").getAttribute(
        "data-itinerary-status",
      ),
    ).toBe("approved");
  });

  const approveCalls = seen.filter(
    (r) =>
      r.method === "POST" &&
      r.url.endsWith(`/itinerary/${ITINERARY_ID}/approve`),
  );
  expect(approveCalls).toHaveLength(1);
  expect(approveButton.disabled).toBe(true);
});

// ── bullet 4: craft-feel invariants under draft-itinerary-editor ───────────

test("(4) craft-feel invariants under data-testid='draft-itinerary-editor'", () => {
  globalThis.fetch = vi
    .fn()
    .mockResolvedValue(jsonResponse({ detail: "unexpected" }, 500)) as unknown as typeof fetch;

  const { getByTestId } = render(
    <DraftItineraryEditor
      itineraryId={ITINERARY_ID}
      apiBaseUrl="http://api.test"
      accessToken="test-token"
      initialNodes={fixture.nodes}
      initialEdges={fixture.edges}
      initialStatus="draft"
    />,
  );

  const editor = getByTestId("draft-itinerary-editor");

  // Mirror S07's regex: any Extended_Pictographic codepoint is a fail.
  const emojiRe = /\p{Extended_Pictographic}/u;
  expect(emojiRe.test(editor.innerHTML)).toBe(false);
  expect(emojiRe.test(editor.textContent ?? "")).toBe(false);

  expect(editor.querySelector('[role="progressbar"]')).toBeNull();
  expect(editor.querySelector('[aria-busy="true"]')).toBeNull();
  expect(
    editor.querySelector(".Skeleton, [class*='Skeleton']"),
  ).toBeNull();
  expect(editor.querySelector(".spinner, [class*='spinner']")).toBeNull();
});

// ── bullet 5: Release dispatches releaseItineraryLock + clears indicator ───

test("(5) Release dispatches releaseItineraryLock and clears lock indicator optimistically", async () => {
  const seen: CapturedRequest[] = [];
  globalThis.fetch = captureFetch(seen, (req) => {
    if (req.method === "POST" && req.url.endsWith(`/itinerary/${ITINERARY_ID}/lock`)) {
      return jsonResponse(fixture.itinerary, 200);
    }
    if (req.method === "POST" && req.url.endsWith(`/itinerary/${ITINERARY_ID}/release`)) {
      return jsonResponse(
        { itinerary: fixture.itinerary, replayed_count: 0 },
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
      initialNodes={fixture.nodes}
      initialEdges={fixture.edges}
      initialStatus="draft"
    />,
  );

  // Acquire the lock first so Release becomes enabled.
  await act(async () => {
    fireEvent.click(getByTestId("draft-itinerary-edit"));
  });
  await waitFor(() => {
    expect(
      getByTestId("draft-itinerary-editor").getAttribute("data-lock-status"),
    ).toBe("locked-by-me");
  });

  await act(async () => {
    fireEvent.click(getByTestId("draft-itinerary-release"));
  });

  await waitFor(() => {
    const releaseCalls = seen.filter(
      (r) =>
        r.method === "POST" &&
        r.url.endsWith(`/itinerary/${ITINERARY_ID}/release`),
    );
    expect(releaseCalls).toHaveLength(1);
  });

  expect(
    getByTestId("draft-itinerary-editor").getAttribute("data-lock-status"),
  ).toBe("unlocked");
});

// ── bullet 6: SDK getItinerary maps 403 → { ok:false, detail:'forbidden' } ─

test("(6) Non-advisor GET /itinerary/{id} on draft returns 403 mapped to detail='forbidden'", async () => {
  globalThis.fetch = vi
    .fn()
    .mockResolvedValue(
      jsonResponse({ detail: "forbidden" }, 403),
    ) as unknown as typeof fetch;

  const client = createApiClient({
    baseUrl: "http://api.test",
    accessToken: "client-token",
  });
  const result = await getItinerary(client, ITINERARY_ID);

  expect(result.ok).toBe(false);
  if (result.ok) throw new Error("expected forbidden result");
  expect(result.status).toBe(403);
  expect(result.detail).toBe("forbidden");
});
