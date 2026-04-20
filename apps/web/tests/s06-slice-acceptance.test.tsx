// S06 slice-acceptance suite — six bullets, one test() each.
//
// The slice plan's verification section defines six atmospheric-frame
// invariants for the client chat shell. This suite encodes each one as a
// single, independently failing assertion so verify-s06.sh can print
// PASS/FAIL per bullet and a future agent can localize a regression to
// exactly one invariant without reading the test body.
//
// Bullets (mirroring S05 shape):
//   (1) classifyMood maps Patagonia → glacial and Tuscany → amber
//   (2) ChatShell with 3-turn Patagonia fixture applies data-mood="glacial"
//   (3) phase-shift gate holds: 1-turn renders fallback, 3-turn classifies
//   (4) #conversation stays stable-color (bg-paper) across mood changes
//   (5) every mood palette satisfies WCAG AA contrast (≥ 4.5)
//   (6) image onError hides the image layer, palette layer stays visible
//
// The classifier and phase-shift hook already have unit coverage in
// tests/atmos/classifier.test.ts — here we pin the end-to-end DOM contract
// plus the WCAG and image-fallback guarantees that are slice-level demos.

import { fireEvent, render } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { AtmosFrame } from "@/app/chat/[client_id]/_components/AtmosFrame";
import { ChatShell } from "@/app/chat/[client_id]/_components/ChatShell";
import { classifyMood } from "@/lib/atmos/classifier";
import { MOODS, type MoodId } from "@/lib/atmos/moods";
import type { AgentTurnView } from "@/app/chat/[client_id]/_components/types";
import type { AgentTurnSummary } from "@ov-black/api-client";

// ── helpers ────────────────────────────────────────────────────────────────

function makeSummary(
  role: AgentTurnSummary["role"],
  content: string,
  index: number,
): AgentTurnSummary {
  return {
    id: `seed-${index}-${role}`,
    turn_index: index,
    role,
    content,
    model: null,
    latency_ms: null,
    first_token_ms: null,
    retried: 0,
    error_reason: null,
    created_at: new Date(0).toISOString(),
  };
}

function makeTurnView(
  role: AgentTurnView["role"],
  content: string,
  index: number,
): AgentTurnView {
  return { id: `t-${index}-${role}`, turn_index: index, role, content };
}

/**
 * Minimal fetch stub that returns an empty SSE stream — enough to keep
 * useAgentStream happy during the bootstrap fire-and-forget without
 * dispatching any frames that would mutate state.turns and disturb the
 * mood we're asserting on.
 */
function makeEmptyStreamFetch(): typeof fetch {
  return vi.fn(async () => {
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.close();
      },
    });
    return new Response(stream, {
      status: 200,
      headers: { "Content-Type": "text/event-stream" },
    });
  }) as unknown as typeof fetch;
}

function renderShell(initialTurns: AgentTurnSummary[]) {
  return render(
    <ChatShell
      sessionId="session-test"
      accessToken="test-token"
      apiBaseUrl="http://api.test"
      client={{ id: "client-test", full_name: "Test Client" }}
      initialTurns={initialTurns}
    />,
  );
}

// ── WCAG helper (hex-only, per T01: hex palettes) ──────────────────────────
//
// Colocated here (not imported) so bullet 5 stands on its own and a single
// regression lands in one file. 15-LOC WCAG 2.1 relative-luminance formula.

function parseHex(hex: string): [number, number, number] {
  const clean = hex.replace("#", "");
  const n = parseInt(clean, 16);
  return [(n >> 16) & 0xff, (n >> 8) & 0xff, n & 0xff];
}

function relativeLuminance(rgb: [number, number, number]): number {
  const srgb = rgb.map((v) => {
    const c = v / 255;
    return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
  });
  return 0.2126 * srgb[0]! + 0.7152 * srgb[1]! + 0.0722 * srgb[2]!;
}

function contrastRatio(fg: string, bg: string): number {
  const lf = relativeLuminance(parseHex(fg));
  const lb = relativeLuminance(parseHex(bg));
  const [lighter, darker] = lf > lb ? [lf, lb] : [lb, lf];
  return (lighter + 0.05) / (darker + 0.05);
}

// ── lifecycle ──────────────────────────────────────────────────────────────

const originalFetch = globalThis.fetch;

beforeEach(() => {
  vi.restoreAllMocks();
  globalThis.fetch = makeEmptyStreamFetch();
});

afterEach(() => {
  globalThis.fetch = originalFetch;
});

// ── bullet 1: classifyMood pure-function mapping ───────────────────────────

test("(1) classifyMood maps Patagonia to glacial and Tuscany to amber", () => {
  const patagoniaTurns: AgentTurnView[] = [
    makeTurnView("user", "I've always wanted to trek Patagonia.", 0),
  ];
  const tuscanyTurns: AgentTurnView[] = [
    makeTurnView("user", "A slow week in Tuscany sipping Chianti sounds perfect.", 0),
  ];

  expect(classifyMood(patagoniaTurns)).toBe("glacial");
  expect(classifyMood(tuscanyTurns)).toBe("amber");
});

// ── bullet 2: ChatShell with Patagonia-seeded turns → data-mood="glacial" ──

test("(2) ChatShell with Patagonia-seeded initialTurns applies data-mood glacial", () => {
  const patagoniaTurns: AgentTurnSummary[] = [
    makeSummary("user", "I want to see Patagonia's fjords.", 0),
    makeSummary("assistant", "The glacier treks there are extraordinary.", 1),
    makeSummary("user", "And arctic Norway too — norway fjord glacier.", 2),
  ];

  renderShell(patagoniaTurns);

  const frame = document.getElementById("atmos-frame");
  expect(frame).not.toBeNull();
  expect(frame?.getAttribute("data-mood")).toBe("glacial");
});

// ── bullet 3: phase-shift gate holds (1-turn fallback, 3-turn classified) ──

test("(3) phase-shift gate: 1-turn renders fallback alpine, 3-turn renders amber", () => {
  const oneTuscanyTurn: AgentTurnSummary[] = [
    makeSummary("user", "Tuscany vineyards at dusk.", 0),
  ];

  const { unmount } = renderShell(oneTuscanyTurn);
  const frameOne = document.getElementById("atmos-frame");
  expect(frameOne?.getAttribute("data-mood")).toBe("alpine");
  unmount();

  const threeTuscanyTurns: AgentTurnSummary[] = [
    makeSummary("user", "Tuscany vineyards at dusk.", 0),
    makeSummary("assistant", "Florence and Siena in the same week?", 1),
    makeSummary("user", "Yes — chianti and umbria too.", 2),
  ];

  renderShell(threeTuscanyTurns);
  const frameThree = document.getElementById("atmos-frame");
  expect(frameThree?.getAttribute("data-mood")).toBe("amber");
});

// ── bullet 4: #conversation stays stable-color across mood changes ─────────

test("(4) conversation surface carries bg-paper across mood changes", () => {
  const glacialTurns: AgentTurnSummary[] = [
    makeSummary("user", "Patagonia fjord.", 0),
    makeSummary("assistant", "Iceland glacier arctic.", 1),
    makeSummary("user", "antarctica norway.", 2),
  ];

  const { unmount } = renderShell(glacialTurns);
  const glacialFrame = document.getElementById("atmos-frame");
  expect(glacialFrame?.getAttribute("data-mood")).toBe("glacial");
  const conversationGlacial = document.getElementById("conversation");
  expect(conversationGlacial).not.toBeNull();
  expect(conversationGlacial?.className ?? "").toMatch(/\bbg-paper\b/);
  unmount();

  const amberTurns: AgentTurnSummary[] = [
    makeSummary("user", "Tuscany chianti.", 0),
    makeSummary("assistant", "Florence and Siena.", 1),
    makeSummary("user", "Umbria and provence.", 2),
  ];

  renderShell(amberTurns);
  const amberFrame = document.getElementById("atmos-frame");
  expect(amberFrame?.getAttribute("data-mood")).toBe("amber");
  const conversationAmber = document.getElementById("conversation");
  expect(conversationAmber).not.toBeNull();
  expect(conversationAmber?.className ?? "").toMatch(/\bbg-paper\b/);
});

// ── bullet 5: every mood satisfies WCAG AA (≥ 4.5:1) fg/bg contrast ────────

test("(5) every MOODS entry satisfies WCAG AA contrast between palette fg and bg", () => {
  const moodIds = Object.keys(MOODS) as MoodId[];
  expect(moodIds.length).toBeGreaterThan(0);
  for (const id of moodIds) {
    const { fg, bg } = MOODS[id].palette;
    const ratio = contrastRatio(fg, bg);
    expect(
      ratio,
      `mood '${id}' palette fg=${fg} bg=${bg} has contrast ${ratio.toFixed(2)} (< 4.5)`,
    ).toBeGreaterThanOrEqual(4.5);
  }
});

// ── bullet 6: image onError hides image layer, palette layer stays visible ─

test("(6) AtmosFrame image onError hides image layer but keeps palette visible", () => {
  render(<AtmosFrame mood="glacial" phaseCounter={1} />);

  const paletteBefore = document.querySelector('[data-atmos-layer="palette"]');
  expect(paletteBefore).not.toBeNull();

  const imageLayer = document.querySelector('[data-atmos-layer="image"]');
  expect(imageLayer).not.toBeNull();

  // next/image renders an underlying <img>; find it inside the image layer.
  const img = imageLayer!.querySelector("img");
  expect(img).not.toBeNull();

  fireEvent.error(img!);

  const paletteAfter = document.querySelector('[data-atmos-layer="palette"]');
  expect(paletteAfter).not.toBeNull();

  const imageLayerAfter = document.querySelector(
    '[data-atmos-layer="image"][data-image-status="error"]',
  );
  expect(imageLayerAfter).not.toBeNull();
});
