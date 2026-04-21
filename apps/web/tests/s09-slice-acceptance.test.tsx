// S09 slice-acceptance suite — six bullets, one test() each.
//
// Mirrors the S08 pattern: each acceptance bullet is encoded as one
// independently failing assertion so verify-s09.sh can print PASS/FAIL
// per bullet and a future agent can localize a regression to exactly one
// invariant without reading the test body.
//
// Bullets:
//   (1) grouped day sections render in data-day-index order
//   (2) 'via Outdoor Voyage' attribution only on OV-sourced nodes
//   (3) typed sections — every node carries a non-empty data-node-type
//   (4) craft-feel invariants under data-testid='final-itinerary-view'
//   (5) SDK getItinerary maps 403 → { ok:false, detail:'forbidden' }
//   (6) mobile-first layout — max-w-2xl + flex-col, no md:grid-cols-* inside days
//
// Rendering the RSC at apps/web/app/itinerary/[id]/page.tsx is outside
// vitest's reach without a Next harness — these bullets therefore render
// FinalItineraryView directly with the fixture props, mirroring S08 bullet 6
// for the 403 path which asserts the SDK wrapper shape (the assertable
// proof-surface for notFound() collapse).

import { render } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import {
  createApiClient,
  getItinerary,
  type EdgeResponse,
  type ItineraryResponse,
  type NodeResponse,
} from "@ov-black/api-client";

import { FinalItineraryView } from "@/app/itinerary/[id]/_components/FinalItineraryView";

import approvedFixture from "./fixtures/s09_approved_itinerary.json";

// ── fixture typing ─────────────────────────────────────────────────────────

type ApprovedFixture = {
  itinerary: ItineraryResponse;
  nodes: NodeResponse[];
  edges: EdgeResponse[];
};

const fixture = approvedFixture as ApprovedFixture;
const ITINERARY_ID = fixture.itinerary.id;

function renderView() {
  return render(
    <FinalItineraryView
      status={fixture.itinerary.status ?? "approved"}
      nodes={fixture.nodes}
      edges={fixture.edges}
      title={fixture.itinerary.title}
    />,
  );
}

// ── fetch helpers ──────────────────────────────────────────────────────────

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
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

// ── bullet 1: grouped day sections render in data-day-index order ──────────

test("(1) Renders grouped day sections in data-day-index 0-then-1 order", () => {
  const { getByTestId, container } = renderView();

  const root = getByTestId("final-itinerary-view");
  const days = Array.from(
    root.querySelectorAll<HTMLElement>('[data-testid="final-itinerary-day"]'),
  );
  expect(days.length).toBeGreaterThanOrEqual(2);

  const dayIndexes = days.map((el) => el.getAttribute("data-day-index"));
  expect(dayIndexes[0]).toBe("0");
  expect(dayIndexes[1]).toBe("1");

  // Ensure the day sections are in document order matching the numeric order.
  // (container preserves DOM order; this doubles as a regression guard against
  // a future refactor that sorts by something other than emission order.)
  const allInContainer = Array.from(
    container.querySelectorAll<HTMLElement>(
      '[data-testid="final-itinerary-day"]',
    ),
  );
  expect(allInContainer).toEqual(days);
});

// ── bullet 2: attribution only on OV-sourced nodes ─────────────────────────

test("(2) 'via Outdoor Voyage' attribution renders only on OV-sourced nodes", () => {
  const { getByTestId } = renderView();
  const root = getByTestId("final-itinerary-view");

  const attributions = Array.from(
    root.querySelectorAll<HTMLElement>(
      '[data-testid="final-itinerary-attribution"]',
    ),
  );
  expect(attributions.length).toBeGreaterThan(0);
  for (const attr of attributions) {
    expect(attr.textContent?.trim()).toBe("via Outdoor Voyage");
  }

  // Every node carrying the attribution must sit inside a <li> whose
  // data-source is 'ov'.
  for (const attr of attributions) {
    const nodeLi = attr.closest<HTMLElement>(
      '[data-testid="final-itinerary-node"]',
    );
    expect(nodeLi).not.toBeNull();
    expect(nodeLi!.getAttribute("data-source")).toBe("ov");
  }

  // Conversely, no node with data-source='' (the non-inventory note) may
  // contain an attribution span.
  const nonOvLis = Array.from(
    root.querySelectorAll<HTMLElement>(
      '[data-testid="final-itinerary-node"][data-source=""]',
    ),
  );
  expect(nonOvLis.length).toBeGreaterThan(0);
  for (const li of nonOvLis) {
    expect(
      li.querySelector('[data-testid="final-itinerary-attribution"]'),
    ).toBeNull();
  }
});

// ── bullet 3: typed sections visible in DOM ────────────────────────────────

test("(3) Typed sections — every node carries a non-empty data-node-type", () => {
  const { getByTestId } = renderView();
  const root = getByTestId("final-itinerary-view");

  const nodeLis = Array.from(
    root.querySelectorAll<HTMLElement>(
      '[data-testid="final-itinerary-node"]',
    ),
  );
  expect(nodeLis.length).toBe(fixture.nodes.length);

  const seenTypes = new Set<string>();
  for (const li of nodeLis) {
    const t = li.getAttribute("data-node-type");
    expect(t).not.toBeNull();
    expect(t!.length).toBeGreaterThan(0);
    seenTypes.add(t!);
  }
  expect(seenTypes.size).toBeGreaterThanOrEqual(2);
});

// ── bullet 4: craft-feel invariants under final-itinerary-view ─────────────

test("(4) craft-feel invariants under data-testid='final-itinerary-view'", () => {
  globalThis.fetch = vi
    .fn()
    .mockResolvedValue(jsonResponse({ detail: "unexpected" }, 500)) as unknown as typeof fetch;

  const { getByTestId } = renderView();

  const view = getByTestId("final-itinerary-view");

  // Mirror S08's regex: any Extended_Pictographic codepoint is a fail.
  const emojiRe = /\p{Extended_Pictographic}/u;
  expect(emojiRe.test(view.innerHTML)).toBe(false);
  expect(emojiRe.test(view.textContent ?? "")).toBe(false);

  expect(view.querySelector('[role="progressbar"]')).toBeNull();
  expect(view.querySelector('[aria-busy="true"]')).toBeNull();
  expect(
    view.querySelector(".Skeleton, [class*='Skeleton']"),
  ).toBeNull();
  expect(view.querySelector(".spinner, [class*='spinner']")).toBeNull();
});

// ── bullet 5: SDK getItinerary maps 403 → { ok:false, detail:'forbidden' } ─

test("(5) Non-advisor GET /itinerary/{id} on draft returns 403 mapped to detail='forbidden'", async () => {
  globalThis.fetch = vi
    .fn()
    .mockResolvedValue(
      jsonResponse({ detail: "forbidden" }, 403),
    ) as unknown as typeof fetch;

  const client = createApiClient({
    baseUrl: "http://api.test",
    accessToken: "tok",
  });
  const result = await getItinerary(client, ITINERARY_ID);

  expect(result.ok).toBe(false);
  if (result.ok) throw new Error("expected forbidden result");
  expect(result.status).toBe(403);
  expect(result.detail).toBe("forbidden");
});

// ── bullet 6: mobile-friendly layout ───────────────────────────────────────

test("(6) Mobile-friendly layout — max-w-2xl, flex-col, no md:grid-cols-* inside days", () => {
  const { getByTestId } = renderView();

  const view = getByTestId("final-itinerary-view");
  const cls = view.className;
  expect(cls).toContain("max-w-2xl");
  expect(cls).toContain("flex-col");

  const days = Array.from(
    view.querySelectorAll<HTMLElement>('[data-testid="final-itinerary-day"]'),
  );
  expect(days.length).toBeGreaterThan(0);
  for (const day of days) {
    expect(day.querySelector('[class*="md:grid-cols-"]')).toBeNull();
  }
});
